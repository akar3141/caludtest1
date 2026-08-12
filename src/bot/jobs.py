"""Orchestrates scheduling and the full report pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .chart_generator import build_price_chart
from .config import ASSET_DISPLAY_NAMES, ASSET_SYMBOLS, AssetName, Settings
from .exceptions import NewsFetchError
from .gemini_analyst import GeminiAnalyst
from .logger import get_logger
from .market_calendar import MarketCalendar
from .market_data import MarketDataClient
from .message_formatter import (
    format_daily_caption,
    format_short_caption,
    format_weekly_caption,
)
from .news_filter import NewsEvent, NewsFilter
from .state_store import StateStore
from .statistical_analyzer import daily_session_stats, weekly_stats
from .telegram_sender import TelegramSender
from .time_manager import NY_TZ, TEHRAN_TZ, UTC_TZ, TimeManager


logger = get_logger(__name__)


@dataclass(frozen=True)
class ScheduleTarget:
    target_time: datetime
    requires_trading_day: bool


def compute_schedule_target(
    asset: AssetName,
    mode: str,
    tm: TimeManager,
    today: date | None = None,
) -> ScheduleTarget:
    """Return the real local-time target. Never use a fixed UTC offset here."""

    if mode == "daily":
        if asset == "gold":
            # 09:00 America/New_York = 13:00 UTC in EDT / 14:00 UTC in EST.
            return ScheduleTarget(
                tm.target_before_ny_open(30, today),
                True,
            )

        if asset == "dow":
            # 09:15 America/New_York = 13:15 UTC in EDT / 14:15 UTC in EST.
            return ScheduleTarget(
                tm.target_before_ny_open(15, today),
                True,
            )

        if asset == "bitcoin":
            # 21:00 Asia/Tehran.
            return ScheduleTarget(
                tm.target_tehran_time(21, 0, today),
                False,
            )

    if mode == "weekly":
        if asset == "gold":
            # Saturday 17:00 Asia/Tehran.
            return ScheduleTarget(
                tm.target_tehran_time(17, 0, today),
                False,
            )

        if asset == "dow":
            # Saturday 18:00 Asia/Tehran.
            return ScheduleTarget(
                tm.target_tehran_time(18, 0, today),
                False,
            )

        if asset == "bitcoin":
            # Saturday 19:00 Asia/Tehran.
            return ScheduleTarget(
                tm.target_tehran_time(19, 0, today),
                False,
            )

    raise ValueError(f"Unknown asset/mode combination: {asset}/{mode}")


def is_job_due(
    asset: AssetName,
    mode: str,
    settings: Settings,
    tm: TimeManager,
    calendar: MarketCalendar,
) -> bool:
    """Final server-side gate. A cron trigger alone can never send a report."""

    if mode == "weekly" and not tm.is_saturday_tehran():
        logger.info(
            "TIME_GATE_SKIP reason=not_saturday "
            "asset=%s mode=%s tehran_now=%s",
            asset,
            mode,
            tm.now_tehran().isoformat(),
        )
        return False

    target = compute_schedule_target(asset, mode, tm)

    if target.requires_trading_day:
        trading_day = tm.now_ny().date()
        if not calendar.is_trading_day(trading_day):
            logger.info(
                "TIME_GATE_SKIP reason=not_trading_day "
                "asset=%s mode=%s ny_date=%s",
                asset,
                mode,
                trading_day,
            )
            return False

    now = tm.now_utc()
    due = tm.is_due(
        target.target_time,
        settings.schedule_tolerance_minutes,
        settings.catch_up_minutes,
        now=now,
    )

    logger.info(
        "TIME_GATE_CHECK asset=%s mode=%s due=%s "
        "target=%s target_utc=%s target_ny=%s target_tehran=%s "
        "now_utc=%s tolerance_before=%dm catch_up=%dm",
        asset,
        mode,
        due,
        target.target_time.isoformat(),
        target.target_time.astimezone(UTC_TZ).isoformat(),
        target.target_time.astimezone(NY_TZ).isoformat(),
        target.target_time.astimezone(TEHRAN_TZ).isoformat(),
        now.isoformat(),
        settings.schedule_tolerance_minutes,
        settings.catch_up_minutes,
    )

    if not due:
        logger.info(
            "TIME_GATE_SKIP reason=outside_due_window "
            "asset=%s mode=%s",
            asset,
            mode,
        )
        return False

    logger.info(
        "JOB_IS_DUE asset=%s mode=%s target=%s now=%s",
        asset,
        mode,
        target.target_time.isoformat(),
        now.isoformat(),
    )
    return True


def _daily_job_id(asset: AssetName, tm: TimeManager) -> str:
    # Gold/Dow are NY-session reports; Bitcoin is a Tehran-time report.
    if asset in ("gold", "dow"):
        key_date = tm.now_ny().date()
    else:
        key_date = tm.now_tehran().date()
    return f"daily:{asset}:{key_date.isoformat()}"


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
    job_id = _daily_job_id(asset, tm)

    if state.is_done(job_id):
        logger.info("STATE_SKIP job_id=%s already_sent=true", job_id)
        return

    today_news: list[NewsEvent] = []

    if asset in ("gold", "dow"):
        try:
            today_news = news_filter.today_high_impact_usd_events()
        except NewsFetchError as exc:
            logger.error(
                "News fetch/parse failed for %s — "
                "sending report without a news section. %s",
                asset,
                exc,
            )

    symbol = ASSET_SYMBOLS[asset]
    display_name = ASSET_DISPLAY_NAMES[asset]

    df = market_data.fetch_daily(
        symbol,
        interval=settings.yfinance_interval,
    )
    stats = daily_session_stats(df)

    if today_news:
        titles = "; ".join(event.title for event in today_news[:5])
        news_context = (
            f"{len(today_news)} high-impact USD event(s) released today: "
            f"{titles}. Analyze how this news is likely relevant to today's price action."
        )
    elif asset in ("gold", "dow"):
        news_context = (
            "No high-impact USD news today — do not mention news in the summary."
        )
    else:
        news_context = "N/A (Bitcoin reports are independent of the news filter)."

    summary = analyst.summarize_daily(
        asset_name=display_name,
        date_str=tm.format_tehran(tm.now_utc()),
        stats=stats,
        news_context=news_context,
    )

    chart = build_price_chart(
        df,
        title=f"{display_name} — Daily",
        subtitle=tm.format_tehran(tm.now_utc()),
    )

    caption = format_daily_caption(
        display_name,
        tm.now_utc(),
        stats,
        summary,
        today_news,
    )

    short_caption = format_short_caption(
        display_name,
        tm.format_tehran(tm.now_utc()),
        "Full report below ⬇️",
    )

    if dry_run:
        logger.info(
            "[DRY RUN] Would send %s daily report "
            "(%d chars caption, %d byte chart). State NOT marked done.",
            asset,
            len(caption),
            len(chart.getvalue()),
        )
        return

    await sender.send_report(chart, caption, short_caption)
    state.mark_done(job_id, tm.now_utc().isoformat())
    logger.info("STATE_MARKED_DONE job_id=%s", job_id)


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
    week_key = tm.now_tehran().isocalendar()
    job_id = f"weekly:{asset}:{week_key[0]}-W{week_key[1]}"

    if state.is_done(job_id):
        logger.info("STATE_SKIP job_id=%s already_sent=true", job_id)
        return

    symbol = ASSET_SYMBOLS[asset]
    display_name = ASSET_DISPLAY_NAMES[asset]

    df = market_data.fetch_weekly(
        symbol,
        interval=settings.yfinance_interval,
    )
    stats = weekly_stats(df)

    try:
        news_events = news_filter.important_events_this_week()
        news_context = (
            f"{len(news_events)} high-impact USD event(s) this week."
            if news_events
            else "No high-impact USD events this week."
        )
    except NewsFetchError as exc:
        logger.error(
            "News fetch/parse failed for weekly report — continuing without it. %s",
            exc,
        )
        news_events = []
        news_context = "News data unavailable this week (fetch error)."

    summary = analyst.summarize_weekly(
        asset_name=display_name,
        date_str=tm.format_tehran(tm.now_utc()),
        stats=stats,
        news_context=news_context,
    )

    chart = build_price_chart(
        df,
        title=f"{display_name} — Weekly",
        subtitle=tm.format_tehran(tm.now_utc()),
    )

    caption = format_weekly_caption(
        display_name,
        tm.format_tehran(tm.now_utc()),
        stats,
        news_events,
        summary,
    )

    short_caption = format_short_caption(
        display_name,
        tm.format_tehran(tm.now_utc()),
        "Full weekly report below ⬇️",
    )

    if dry_run:
        logger.info(
            "[DRY RUN] Would send %s weekly report "
            "(%d chars caption, %d byte chart). State NOT marked done.",
            asset,
            len(caption),
            len(chart.getvalue()),
        )
        return

    await sender.send_report(chart, caption, short_caption)
    state.mark_done(job_id, tm.now_utc().isoformat())
    logger.info("STATE_MARKED_DONE job_id=%s", job_id)
