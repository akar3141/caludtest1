"""Orchestrates the full pipeline for each report type.

This is the only layer that knows the *order* of operations. Every
individual step (fetch data, compute stats, ask Gemini, render chart,
send Telegram) lives in its own single-responsibility module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime

from .chart_generator import build_price_chart
from .config import ASSET_DISPLAY_NAMES, ASSET_SYMBOLS, AssetName, Settings
from .exceptions import NewsFetchError
from .gemini_analyst import GeminiAnalyst
from .logger import get_logger
from .market_calendar import MarketCalendar
from .market_data import MarketDataClient
from .message_formatter import format_daily_caption, format_short_caption, format_weekly_caption
from .news_filter import NewsEvent, NewsFilter
from .state_store import StateStore
from .statistical_analyzer import daily_session_stats, weekly_stats
from .telegram_sender import TelegramSender
from .time_manager import TimeManager

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScheduleTarget:
    """Describes when a given (asset, mode) job is supposed to run.

    Note: there is deliberately no "requires_news_gate" here. News never
    gates whether a report is sent — every due report goes out every day,
    for all three assets, without exception. The news filter only affects
    report *content* (see run_daily_job), not whether run_daily_job runs
    at all.
    """

    target_time: datetime
    requires_trading_day: bool


def compute_schedule_target(
    asset: AssetName, mode: str, tm: TimeManager, today: date | None = None
) -> ScheduleTarget:
    if mode == "daily":
        if asset == "gold":
            return ScheduleTarget(tm.target_before_ny_open(30, today), True)
        if asset == "dow":
            return ScheduleTarget(tm.target_before_ny_open(15, today), True)
        if asset == "bitcoin":
            return ScheduleTarget(tm.target_tehran_time(21, 0, today), False)
    elif mode == "weekly":
        if asset == "gold":
            return ScheduleTarget(tm.target_tehran_time(17, 0, today), False)
        if asset == "dow":
            return ScheduleTarget(tm.target_tehran_time(18, 0, today), False)
        if asset == "bitcoin":
            return ScheduleTarget(tm.target_tehran_time(19, 0, today), False)
    raise ValueError(f"Unknown asset/mode combination: {asset}/{mode}")


def is_job_due(
    asset: AssetName,
    mode: str,
    settings: Settings,
    tm: TimeManager,
    calendar: MarketCalendar,
) -> bool:
    if mode == "weekly" and not tm.is_saturday_tehran():
        logger.info("Skip: weekly reports only run on Saturday (Asia/Tehran).")
        return False

    target = compute_schedule_target(asset, mode, tm)

    if target.requires_trading_day and not calendar.is_trading_day(tm.now_ny().date()):
        logger.info("Skip: %s is not an NYSE trading day.", tm.now_ny().date())
        return False

    if not tm.is_due(
        target.target_time, settings.schedule_tolerance_minutes, settings.catch_up_minutes
    ):
        logger.info(
            "Skip: not within due window. target=%s now=%s window=[-%dm, +%dm]",
            target.target_time, tm.now_utc(),
            settings.schedule_tolerance_minutes, settings.catch_up_minutes,
        )
        return False

    return True


async def run_daily_job(
    asset: AssetName,
    settings: Settings,
    tm: TimeManager,
    news_filter: NewsFilter,
    market_data: MarketDataClient,
    analyst: GeminiAnalyst,
    sender: TelegramSender,
    state: StateStore,
    dry_run: bool = False,
) -> None:
    job_id = f"daily:{asset}:{tm.now_tehran().date().isoformat()}"
    if state.is_done(job_id):
        logger.info("Skip: %s already sent today.", job_id)
        return

    # News is editorial content only — it never blocks sending. Every due
    # daily report is sent every day for all three assets, without
    # exception. For Gold/Dow, if there IS high-impact USD news today, the
    # report's AI summary and caption include an analysis of it; if not,
    # the report still goes out, just without that section. Bitcoin never
    # calls the news filter at all — its reports never reference USD news.
    today_news: list[NewsEvent] = []
    if asset in ("gold", "dow"):
        try:
            today_news = news_filter.today_high_impact_usd_events()
        except NewsFetchError as exc:
            # A news-fetch failure must not affect report delivery — log
            # it and simply send the report without a news section today.
            logger.error(
                "News fetch/parse failed for %s — sending report without a news section. %s",
                asset, exc,
            )
            today_news = []

    symbol = ASSET_SYMBOLS[asset]
    display_name = ASSET_DISPLAY_NAMES[asset]

    df = market_data.fetch_daily(symbol, interval=settings.yfinance_interval)
    stats = daily_session_stats(df)

    if today_news:
        titles = "; ".join(e.title for e in today_news[:5])
        news_context = (
            f"{len(today_news)} high-impact USD event(s) released today: {titles}. "
            "Analyze how this news is likely relevant to today's price action."
        )
    elif asset in ("gold", "dow"):
        news_context = "No high-impact USD news today — do not mention news in the summary."
    else:
        news_context = "N/A (Bitcoin reports are independent of the news filter)."

    summary = analyst.summarize_daily(
        asset_name=display_name,
        date_str=tm.format_tehran(tm.now_utc()),
        stats=stats,
        news_context=news_context,
    )

    chart = build_price_chart(
        df, title=f"{display_name} — Daily", subtitle=tm.format_tehran(tm.now_utc())
    )
    caption = format_daily_caption(
        display_name, tm.now_utc(), stats, summary, today_news
    )
    short_caption = format_short_caption(
        display_name, tm.format_tehran(tm.now_utc()), "Full report below ⬇️"
    )

    if dry_run:
        logger.info(
            "[DRY RUN] Would send %s daily report (%d chars caption, %d byte chart). "
            "State NOT marked done.", asset, len(caption), len(chart.getvalue()),
        )
        return

    await sender.send_report(chart, caption, short_caption)
    state.mark_done(job_id, tm.now_utc().isoformat())


async def run_weekly_job(
    asset: AssetName,
    settings: Settings,
    tm: TimeManager,
    news_filter: NewsFilter,
    market_data: MarketDataClient,
    analyst: GeminiAnalyst,
    sender: TelegramSender,
    state: StateStore,
    dry_run: bool = False,
) -> None:
    # ISO week number keeps this stable regardless of which weekday the job runs on.
    week_key = tm.now_tehran().isocalendar()
    job_id = f"weekly:{asset}:{week_key[0]}-W{week_key[1]}"
    if state.is_done(job_id):
        logger.info("Skip: %s already sent this week.", job_id)
        return

    symbol = ASSET_SYMBOLS[asset]
    display_name = ASSET_DISPLAY_NAMES[asset]

    df = market_data.fetch_weekly(symbol, interval=settings.yfinance_interval)
    stats = weekly_stats(df)

    # Weekly reports always include the important USD news of the week,
    # for all three assets. A news-fetch failure here must NOT take down
    # the whole weekly report — OHLC, the chart, and the AI summary are
    # all independently valuable and don't depend on this endpoint being
    # up, so we degrade gracefully instead.
    try:
        news_events = news_filter.important_events_this_week()
        news_context = (
            f"{len(news_events)} high-impact USD event(s) this week."
            if news_events
            else "No high-impact USD events this week."
        )
    except NewsFetchError as exc:
        logger.error("News fetch/parse failed for weekly report — continuing without it. %s", exc)
        news_events = []
        news_context = "News data unavailable this week (fetch error)."

    summary = analyst.summarize_weekly(
        asset_name=display_name,
        date_str=tm.format_tehran(tm.now_utc()),
        stats=stats,
        news_context=news_context,
    )

    chart = build_price_chart(
        df, title=f"{display_name} — Weekly", subtitle=tm.format_tehran(tm.now_utc())
    )
    caption = format_weekly_caption(
        display_name, tm.format_tehran(tm.now_utc()), stats, news_events, summary
    )
    short_caption = format_short_caption(
        display_name, tm.format_tehran(tm.now_utc()), "Full weekly report below ⬇️"
    )

    if dry_run:
        logger.info(
            "[DRY RUN] Would send %s weekly report (%d chars caption, %d byte chart). "
            "State NOT marked done.", asset, len(caption), len(chart.getvalue()),
        )
        return

    await sender.send_report(chart, caption, short_caption)
    state.mark_done(job_id, tm.now_utc().isoformat())
