"""Builds Telegram MarkdownV2-safe captions.

Kept separate from chart_generator/gemini_analyst so that changing the
message layout never touches chart rendering or AI-generation logic.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .statistical_analyzer import DailyStats, WeeklyStats

if TYPE_CHECKING:
    # Import only for type checking — avoids pulling in news_filter's httpx
    # dependency at runtime just to annotate a parameter type.
    from .news_filter import NewsEvent

_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!"
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096
# Leave headroom below Telegram's hard limits: MarkdownV2 escaping inflates
# length (every literal '.', '-', '(' etc. becomes 2 chars), and Telegram
# counts length in UTF-16 code units, so surrogate-pair emoji count as 2.
_CAPTION_SAFETY_MARGIN = 80


def escape_mdv2(text: str) -> str:
    return re.sub(f"([{re.escape(_MDV2_SPECIAL)}])", r"\\\1", text)


def format_short_caption(asset_display_name: str, tehran_time_str: str, note: str) -> str:
    """A minimal caption used when the full report doesn't fit Telegram's
    1024-char photo caption limit; the full report is sent as a follow-up
    text message instead (see telegram_sender + jobs)."""
    lines = [
        f"*{escape_mdv2(asset_display_name)}*",
        f"🕒 {escape_mdv2(tehran_time_str)}",
        escape_mdv2(note),
    ]
    return "\n".join(lines)


def format_daily_caption(
    asset_display_name: str,
    tehran_time_str: str,
    stats: DailyStats,
    ai_summary: str,
    news_events: "list[NewsEvent] | None" = None,
) -> str:
    lines = [
        f"*{escape_mdv2(asset_display_name)} — Daily Report*",
        f"🕒 {escape_mdv2(tehran_time_str)}",
        "",
        "*Session Stats*",
    ]
    for s in stats.sessions:
        if s.high is None:
            lines.append(f"• {escape_mdv2(s.name)}: no data")
        else:
            lines.append(
                f"• {escape_mdv2(s.name)}: H {escape_mdv2(f'{s.high:.2f}')} "
                f"/ L {escape_mdv2(f'{s.low:.2f}')} "
                f"/ Vol {escape_mdv2(f'{s.volume:,.0f}')}"
            )

    lines += [
        "",
        "*Daily OHLCV*",
        f"O: {escape_mdv2(f'{stats.open:.2f}')}  H: {escape_mdv2(f'{stats.high:.2f}')}  "
        f"L: {escape_mdv2(f'{stats.low:.2f}')}  C: {escape_mdv2(f'{stats.close:.2f}')}",
        f"Volume: {escape_mdv2(f'{stats.volume:,.0f}')}",
    ]

    # Editorial-only section: present only on days with confirmed high-impact
    # USD news. Its absence never affects whether the report itself is sent.
    if news_events:
        lines += ["", "*🔴 High-Impact USD News Today*"]
        for e in news_events[:5]:
            when_str = e.when.strftime("%H:%M UTC")
            lines.append(f"• {escape_mdv2(when_str)} — {escape_mdv2(e.title)}")

    lines += ["", "*AI Summary*", escape_mdv2(ai_summary)]
    return "\n".join(lines)


def fits_caption(text: str) -> bool:
    """True if `text` safely fits Telegram's photo-caption limit (1024 chars)."""
    return len(text) <= (TELEGRAM_CAPTION_LIMIT - _CAPTION_SAFETY_MARGIN)


def chunk_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Splits `text` into Telegram-message-sized chunks, breaking on line boundaries
    where possible so MarkdownV2 formatting isn't split mid-entity."""
    limit -= 50  # safety margin
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if current_len + line_len > limit and current:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def format_weekly_caption(
    asset_display_name: str,
    tehran_time_str: str,
    stats: WeeklyStats,
    news_events: "list[NewsEvent]",
    ai_summary: str,
) -> str:
    lines = [
        f"*{escape_mdv2(asset_display_name)} — Weekly Report*",
        f"🕒 {escape_mdv2(tehran_time_str)}",
        "",
        "*Weekly OHLC*",
        f"O: {escape_mdv2(f'{stats.week_open:.2f}')}  H: {escape_mdv2(f'{stats.week_high:.2f}')}  "
        f"L: {escape_mdv2(f'{stats.week_low:.2f}')}  C: {escape_mdv2(f'{stats.week_close:.2f}')}",
        f"Range: {escape_mdv2(f'{stats.weekly_range:.2f}')}  "
        f"Volatility: {escape_mdv2(f'{stats.volatility_pct:.4f}')}%",
        f"Avg Daily Range: {escape_mdv2(f'{stats.average_daily_range:.2f}')}",
        "",
        f"💪 Strongest day: {escape_mdv2(stats.strongest_day.date)}",
        f"📉 Weakest day: {escape_mdv2(stats.weakest_day.date)}",
        f"📊 Highest volume day: {escape_mdv2(stats.highest_volume_day.date)}",
        f"⏱ Most active hour \\(UTC\\): {escape_mdv2(f'{stats.most_active_hour_utc}:00')}",
        "",
        f"*Trend*: {escape_mdv2(stats.trend_summary)}",
    ]

    lines.append("")
    if news_events:
        lines.append("*Important USD News This Week*")
        for e in news_events[:8]:
            when_str = e.when.strftime("%a %H:%M UTC")
            lines.append(f"• {escape_mdv2(when_str)} — {escape_mdv2(e.title)}")
    else:
        lines.append("*Important USD News This Week*: none")

    lines += ["", "*AI Summary*", escape_mdv2(ai_summary)]
    return "\n".join(lines)
