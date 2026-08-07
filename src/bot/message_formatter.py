"""Builds Telegram MarkdownV2-safe captions.

Kept separate from chart_generator/gemini_analyst so that changing the
message layout never touches chart rendering or AI-generation logic.

The daily report renders a full Persian statistical breakdown built
entirely from `DailyStats` (no numbers are invented here — everything
comes from `statistical_analyzer.py`); the only free-text piece is the
Gemini-written outlook/summary passed in as `ai_summary`, which already
carries its own deterministic disclaimer + channel-link footer (see
`gemini_analyst.py`).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import jdatetime

from .statistical_analyzer import DailyStats, WeeklyStats
from .time_manager import SERVER_TZ, TEHRAN_TZ

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

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

_GREGORIAN_MONTHS_FA = {
    1: "ژانویه", 2: "فوریه", 3: "مارس", 4: "آوریل", 5: "می",
    6: "ژوئن", 7: "ژوئیه", 8: "آگوست", 9: "سپتامبر", 10: "اکتبر",
    11: "نوامبر", 12: "دسامبر",
}

# Emoji + Persian display name + fixed server/Tehran window labels for each
# session. Window strings are precomputed (not derived via generic datetime
# math) because SESSIONS_UTC only ever has these three fixed entries — see
# statistical_analyzer.SESSIONS_UTC, which these must stay in sync with.
_SESSION_DISPLAY: dict[str, dict[str, str]] = {
    "Asia": {"emoji": "🔵", "fa_name": "توکیو", "server": "03:00–11:00", "tehran": "03:30–11:30"},
    "London": {"emoji": "🟠", "fa_name": "لندن", "server": "10:00–19:00", "tehran": "10:30–19:30"},
    "New York": {
        "emoji": "🔴", "fa_name": "نیویورک", "server": "15:00–24:00", "tehran": "15:30–00:30",
    },
}
_OVERLAP_DISPLAY = {
    "emoji": "🟣", "fa_name": "همپوشانی لندن-نیویورک",
    "server": "15:00–19:00", "tehran": "15:30–19:30",
}


def escape_mdv2(text: str) -> str:
    return re.sub(f"([{re.escape(_MDV2_SPECIAL)}])", r"\\\1", text)


def _fa_digits(s: str) -> str:
    return s.translate(_PERSIAN_DIGITS)


def _dual_time(dt: datetime) -> str:
    """'سرور HH:MM (ایران HH:MM)' — server is fixed UTC+3, Tehran UTC+3:30."""
    server_str = dt.astimezone(SERVER_TZ).strftime("%H:%M")
    tehran_str = dt.astimezone(TEHRAN_TZ).strftime("%H:%M")
    return f"سرور {server_str} (ایران {tehran_str})"


def _dual_hour_range(hour_start_utc: datetime) -> str:
    """Same as `_dual_time` but for a full clock-hour window, e.g. used for
    busiest/quietest hour where the hour boundary itself is the fact."""
    hour_end_utc = hour_start_utc + timedelta(hours=1)
    server_start = hour_start_utc.astimezone(SERVER_TZ).strftime("%H:%M")
    server_end = hour_end_utc.astimezone(SERVER_TZ).strftime("%H:%M")
    tehran_start = hour_start_utc.astimezone(TEHRAN_TZ).strftime("%H:%M")
    tehran_end = hour_end_utc.astimezone(TEHRAN_TZ).strftime("%H:%M")
    return f"سرور {server_start}–{server_end} (ایران {tehran_start}–{tehran_end})"


def _header_dates(report_time: datetime) -> tuple[str, str]:
    """Returns (persian_jalali_date, gregorian_date) strings, both in
    Asia/Tehran local date, matching the report header format."""
    tehran_dt = report_time.astimezone(TEHRAN_TZ)
    jdatetime.set_locale(jdatetime.FA_LOCALE)
    jd = jdatetime.date.fromgregorian(date=tehran_dt.date())
    persian = _fa_digits(jd.strftime("%A %d %B %Y"))
    gregorian = f"{tehran_dt.day} {_GREGORIAN_MONTHS_FA[tehran_dt.month]} {tehran_dt.year}"
    return persian, gregorian


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
    report_time: datetime,
    stats: DailyStats,
    ai_summary: str,
    news_events: "list[NewsEvent] | None" = None,
) -> str:
    L = escape_mdv2  # noqa: N806 — short alias, used on nearly every line below
    SEP = "━━━━━━━━━━━━━━━━━━━━"
    persian_date, gregorian_date = _header_dates(report_time)

    lines: list[str] = [
        L(f"📊 گزارش آماری جامع {asset_display_name} | {persian_date} ({gregorian_date})"),
        L("🕐 ساعت سرور بروکر: GMT+3 | ساعت ایران: UTC+3:30 (۳۰ دقیقه جلوتر از سرور)"),
        SEP,
        f"*{L('۱) خلاصه‌ی کلی روز')}*",
        SEP,
    ]

    day_change = stats.close - stats.open
    direction_fa = "صعودی" if day_change >= 0 else "نزولی"
    lines.append(
        L(
            f"باز شدن: {stats.open:.2f} → بسته شدن: {stats.close:.2f} → "
            f"روز {direction_fa}، {day_change:+.2f} دلار"
        )
    )
    if stats.total_range is not None:
        lines.append(L(f"دامنه‌ی نوسان کل روز: {stats.total_range:.2f} دلار"))
    if stats.avg_candle_range is not None:
        lines.append(L(f"میانگین دامنه‌ی هر کندل ۱ دقیقه‌ای: {stats.avg_candle_range:.2f} دلار"))
    if stats.up_candles is not None and stats.total_candles:
        lines.append(
            L(f"کندل صعودی: {stats.up_candles} از {stats.total_candles} ({stats.up_pct:.2f}٪)")
        )
        lines.append(
            L(f"کندل نزولی: {stats.down_candles} از {stats.total_candles} ({stats.down_pct:.2f}٪)")
        )
    lines.append(L(f"♦️حجم تیک کل روز: {stats.volume:,.0f}"))

    # --- Section 2: session breakdown ---
    lines += [SEP, f"*{L('۲) عملکرد سشن‌ها')}*", SEP, ""]

    session_ranges = {
        s.name: (s.high - s.low) for s in stats.sessions if s.high is not None and s.low is not None
    }
    max_range_session = max(session_ranges, key=lambda k: session_ranges[k]) if session_ranges else None
    session_net_moves = {s.name: s.net_move for s in stats.sessions if s.net_move is not None}
    max_move_session = (
        max(session_net_moves, key=lambda k: abs(session_net_moves[k])) if session_net_moves else None
    )
    session_5m_vols = {
        s.name: s.highest_5m_volume.volume
        for s in stats.sessions
        if s.highest_5m_volume is not None
    }
    max_5m_session = max(session_5m_vols, key=lambda k: session_5m_vols[k]) if session_5m_vols else None

    for s in stats.sessions:
        disp = _SESSION_DISPLAY.get(s.name, {"emoji": "⚪", "fa_name": s.name})
        lines.append(
            L(
                f"{disp['emoji']} {disp['fa_name']} | سرور {disp.get('server', '?')} "
                f"→ ایران {disp.get('tehran', '?')}"
            )
        )
        if s.high is None or s.low is None:
            lines.append(L("داده‌ای موجود نیست"))
            lines.append("")
            continue

        rng = s.high - s.low
        rng_note = " (پرنوسان‌ترین سشن روز)" if s.name == max_range_session else ""
        lines.append(L(f"دامنه نوسان: {rng:.2f}${rng_note}"))

        if s.net_move is not None:
            move_note = " (قوی‌ترین حرکت جهت‌دار روز)" if s.name == max_move_session else ""
            lines.append(L(f"حرکت خالص: {s.net_move:+.2f}${move_note}"))

        if s.up_candles is not None and s.down_candles is not None:
            total = s.up_candles + s.down_candles
            up_pct = (s.up_candles / total * 100) if total else 0.0
            lines.append(L(f"کندل صعودی/نزولی: {s.up_candles} / {s.down_candles} ({up_pct:.2f}٪ صعودی)"))

        if s.biggest_up_candle is not None:
            lines.append(L(f"بزرگ‌ترین کندل صعودی ۱دقیقه‌ای: {s.biggest_up_candle.value:+.2f}$"))
        if s.biggest_down_candle is not None:
            lines.append(L(f"بزرگ‌ترین کندل نزولی ۱دقیقه‌ای: {s.biggest_down_candle.value:.2f}$"))

        vol_note = " (بیشترین حجم روز)" if s.name == stats.highest_volume_session_name else ""
        lines.append(L(f"🔸حجم: {s.volume:,.0f}{vol_note}"))

        if s.highest_5m_volume is not None:
            fivem_note = " (بیشترین 5m روز)" if s.name == max_5m_session else ""
            lines.append(
                L(
                    f"🔹بزرگترین حجم کندل 5m: در {_dual_time(s.highest_5m_volume.start_time_utc)} "
                    f"= {s.highest_5m_volume.volume:,.0f}{fivem_note}"
                )
            )
        lines.append("")

    if stats.overlap is not None:
        d = _OVERLAP_DISPLAY
        lines.append(L(f"{d['emoji']} {d['fa_name']} | سرور {d['server']} → ایران {d['tehran']}"))
        lines.append(L(f"دامنه نوسان: {stats.overlap.range:.2f}$ در فقط ۴ ساعت"))
        pct = stats.overlap.pct_above_daily_avg
        pct_note = "بیشتر" if pct >= 0 else "کمتر"
        lines.append(
            L(
                f"میانگین دامنه‌ی هر کندل در این بازه: {stats.overlap.avg_candle_range:.2f}$ "
                f"(حدود {abs(pct):.0f}٪ {pct_note} از میانگین کل روز)"
            )
        )
        if pct >= 0:
            lines.append(L("فشرده‌ترین بازه‌ی نوسان روز از نظر تراکم در دقیقه"))
        lines.append("")

    # --- Section 3: key points ---
    lines += [SEP, f"*{L('۳) نقاط کلیدی روز')}*", SEP]

    if stats.biggest_range_candle is not None:
        lines.append(
            L(
                f"بزرگ‌ترین دامنه‌ی یک کندل: {_dual_time(stats.biggest_range_candle.time_utc)} "
                f"- مقدار {stats.biggest_range_candle.value:.2f}$"
            )
        )
    if stats.second_biggest_range_candle is not None:
        lines.append(
            L(
                f"دومین دامنه‌ی بزرگ: {_dual_time(stats.second_biggest_range_candle.time_utc)} "
                f"- مقدار {stats.second_biggest_range_candle.value:.2f}$"
            )
        )
    if stats.highest_volume_1m is not None:
        lines.append(
            L(
                f"بیشترین حجم یک دقیقه: {_dual_time(stats.highest_volume_1m.time_utc)} - "
                f"{stats.highest_volume_1m.value:,.0f} تیک"
            )
        )
    if stats.biggest_up_candle is not None:
        lines.append(
            L(
                f"بزرگ‌ترین کندل صعودی: {_dual_time(stats.biggest_up_candle.time_utc)} - "
                f"{stats.biggest_up_candle.value:+.2f}$"
            )
        )
    if stats.biggest_down_candle is not None:
        lines.append(
            L(
                f"بزرگ‌ترین کندل نزولی: {_dual_time(stats.biggest_down_candle.time_utc)} - "
                f"{stats.biggest_down_candle.value:.2f}$"
            )
        )
    if stats.busiest_hour is not None:
        lines.append(
            L(
                f"پرنوسان‌ترین ساعت روز: {_dual_hour_range(stats.busiest_hour.hour_start_utc)} - "
                f"{stats.busiest_hour.range:.2f}$"
            )
        )
    if stats.quietest_hour is not None:
        lines.append(
            L(
                f"کم‌نوسان‌ترین ساعت روز: {_dual_hour_range(stats.quietest_hour.hour_start_utc)} - "
                f"{stats.quietest_hour.range:.2f}$"
            )
        )

    # --- Section 4: intraday drawdown / runup ---
    lines += [SEP, f"*{L('۴) بیشینه‌ی افت و رشد درون‌روزی')}*", SEP]

    if stats.max_drawdown is not None:
        dd = stats.max_drawdown
        lines.append(L(f"بزرگ‌ترین اصلاح (Max Drawdown): {dd.value:.2f} دلار"))
        lines.append(L(f"از {_dual_time(dd.start_time_utc)} تا {_dual_time(dd.end_time_utc)}"))
    if stats.max_runup is not None:
        ru = stats.max_runup
        lines.append(L(f"بزرگ‌ترین رشد پیوسته (Max Runup): {ru.value:.2f} دلار"))
        lines.append(L(f"از {_dual_time(ru.start_time_utc)} تا {_dual_time(ru.end_time_utc)}"))

    # Editorial-only section: present only on days with confirmed high-impact
    # USD news. Its absence never affects whether the report itself is sent.
    if news_events:
        lines += [SEP, f"*{L('اخبار مهم دلاری امروز')}*", SEP]
        for e in news_events[:5]:
            when_str = e.when.strftime("%H:%M UTC")
            lines.append(L(f"• {when_str} — {e.title}"))

    # --- Section 5: AI-written wrap-up + outlook. `ai_summary` already
    # ends with the deterministic disclaimer + Telegram channel footer
    # appended in gemini_analyst.py — never generated by the model itself.
    lines += [SEP, f"*{L('۵) جمع‌بندی')}*", SEP, L(ai_summary)]

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
