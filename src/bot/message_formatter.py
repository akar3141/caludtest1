"""Builds Telegram MarkdownV2-safe captions.

Kept separate from chart_generator so that changing the message layout
never touches chart rendering. It does depend on `gemini_analyst` for one
constant (`SECTION_SPLIT_MARKER`): `summarize_daily`/`summarize_weekly`
return a single string containing two AI-written blocks (a statistical
recap and a scenario outlook) joined by that marker, and this module
splits on it to place each block in its own numbered report section —
without needing a second model call or a second return value (jobs.py's
call sites are unchanged).

The daily/weekly reports are built entirely from `DailyStats` /
`WeeklyStats` (no numbers are invented here — everything comes from
`statistical_analyzer.py`); the only free-text pieces are the two
Gemini-written blocks passed in as `ai_summary`, the second of which
already ends with its own deterministic disclaimer + Telegram
channel-link footer (see `gemini_analyst.py`).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

import jdatetime

from .gemini_analyst import SECTION_SPLIT_MARKER
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

# English (not transliterated) Gregorian month abbreviations — deliberately
# hardcoded rather than using datetime.strftime("%b") so the header format
# never depends on the host's locale being English.
_GREGORIAN_MONTHS_EN_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

SEP = "━━━━━━━━━━"
_TZ_LINE = "🕐 GMT+3 | ایران GMT+3:30"

# Emoji + Persian display name for each session, in the fixed display
# order used by both the compact session line and the facts fed to
# Gemini. Must stay in sync with statistical_analyzer.SESSIONS_UTC.
_SESSION_DISPLAY: dict[str, dict[str, str]] = {
    "Asia": {"emoji": "🔵", "fa_name": "توکیو"},
    "London": {"emoji": "🟠", "fa_name": "لندن"},
    "New York": {"emoji": "🔴", "fa_name": "نیویورک"},
}


def escape_mdv2(text: str) -> str:
    return re.sub(f"([{re.escape(_MDV2_SPECIAL)}])", r"\\\1", text)


def _fa_digits(s: str) -> str:
    return s.translate(_PERSIAN_DIGITS)


def _server_hm(ts) -> str:
    return ts.astimezone(SERVER_TZ).strftime("%H:%M")


def _header_dates(report_time: datetime) -> tuple[str, str]:
    """Returns (persian_jalali_date, gregorian_date) strings, both in
    Asia/Tehran local date — e.g. ("۱۷ مرداد ۱۴۰۵", "8 Aug 2026")."""
    tehran_dt = report_time.astimezone(TEHRAN_TZ)
    jdatetime.set_locale(jdatetime.FA_LOCALE)
    jd = jdatetime.date.fromgregorian(date=tehran_dt.date())
    persian = f"{_fa_digits(str(jd.day))} {jd.strftime('%B')} {_fa_digits(str(jd.year))}"
    gregorian = f"{tehran_dt.day} {_GREGORIAN_MONTHS_EN_ABBR[tehran_dt.month]} {tehran_dt.year}"
    return persian, gregorian


def _parse_tehran_time_str(tehran_time_str: str) -> datetime:
    """Parses the fixed 'YYYY-MM-DD HH:MM (Asia/Tehran)' string produced by
    TimeManager.format_tehran() back into a tz-aware Asia/Tehran datetime,
    so the weekly header can be built from the same date logic as the
    daily header without needing a raw datetime object passed in."""
    naive_part = tehran_time_str.split(" (")[0]
    naive_dt = datetime.strptime(naive_part, "%Y-%m-%d %H:%M")
    return naive_dt.replace(tzinfo=TEHRAN_TZ)


def _split_ai_blocks(ai_summary: str) -> tuple[str, str]:
    """Splits the `analyst.summarize_*()` output into (analysis_block,
    outlook_block_with_footer) on the shared marker. Falls back to putting
    everything in the analysis block if the marker is somehow missing —
    a degraded section 4 is better than a crashed report."""
    if SECTION_SPLIT_MARKER in ai_summary:
        analysis, outlook = ai_summary.split(SECTION_SPLIT_MARKER, 1)
        return analysis.strip(), outlook.strip()
    return ai_summary.strip(), ""


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
    persian_date, gregorian_date = _header_dates(report_time)
    analysis_block, outlook_block = _split_ai_blocks(ai_summary)

    day_change = stats.close - stats.open

    lines: list[str] = [
        L(f"📊 {asset_display_name} | {persian_date} | {gregorian_date}"),
        L(_TZ_LINE),
        SEP,
    ]

    lines.append(L(f"📈 باز: {stats.open:.2f} → بسته: {stats.close:.2f}"))
    range_part = f" | دامنه: {stats.total_range:.2f}$" if stats.total_range is not None else ""
    lines.append(L(f"📊 تغییر: {day_change:+.2f}${range_part} | حجم: {stats.volume:,.0f}"))
    if stats.up_candles is not None and stats.total_candles:
        neutral_candles = stats.total_candles - stats.up_candles - stats.down_candles
        lines.append(
            L(f"🟢 {stats.up_candles} | 🔴 {stats.down_candles} | ⚪ {neutral_candles}")
        )

    # --- Section 1: one compact line per session ---
    lines += [SEP, L("1️⃣ سشن‌ها"), SEP]

    for s in stats.sessions:
        disp = _SESSION_DISPLAY.get(s.name, {"emoji": "⚪", "fa_name": s.name})
        if s.high is None or s.low is None or s.net_move is None:
            lines.append(L(f"{disp['emoji']} {disp['fa_name']}: داده‌ای موجود نیست"))
            continue
        s_range = s.high - s.low
        lines.append(L(f"{disp['emoji']} {disp['fa_name']}: {s.net_move:+.2f}$ | Range {s_range:.2f}$"))

    if stats.overlap is not None:
        lines.append(L(f"🟣 لندن–نیویورک: Avg 1m = {stats.overlap.avg_candle_range:.2f}$"))

    # --- Section 2: key points ---
    lines += [SEP, L("2️⃣ نقاط کلیدی"), SEP]

    if stats.busiest_hour is not None:
        h = stats.busiest_hour.hour_start_utc.astimezone(SERVER_TZ).hour
        lines.append(L(f"🔥 پرنوسان‌ترین: {h:02d}:{(h + 1) % 24:02d} → {stats.busiest_hour.range:.2f}$"))
    if stats.quietest_hour is not None:
        h = stats.quietest_hour.hour_start_utc.astimezone(SERVER_TZ).hour
        lines.append(L(f"😴 کم‌نوسان‌ترین: {h:02d}:{(h + 1) % 24:02d} → {stats.quietest_hour.range:.2f}$"))
    if stats.biggest_up_candle is not None:
        t = _server_hm(stats.biggest_up_candle.time_utc)
        lines.append(L(f"⬆️ بزرگ‌ترین حرکت: {t} → {stats.biggest_up_candle.value:+.2f}$"))
    if stats.highest_volume_1m is not None:
        t = _server_hm(stats.highest_volume_1m.time_utc)
        lines.append(L(f"♦️ بیشترین حجم: {t} → {stats.highest_volume_1m.value:,.0f}"))
    if stats.max_runup is not None:
        lines.append(L(f"🔺 Max Runup: {stats.max_runup.value:+.2f}$"))
    if stats.max_drawdown is not None:
        lines.append(L(f"🔻 Max DD: {-stats.max_drawdown.value:+.2f}$"))

    # Editorial-only section: present only on days with confirmed high-impact
    # USD news. Its absence never affects whether the report itself is sent.
    if news_events:
        lines += [SEP, L("📰 اخبار مهم دلاری امروز"), SEP]
        for e in news_events[:5]:
            lines.append(L(f"• {_server_hm(e.when)} — {e.title}"))

    # --- Section 3: AI statistical recap ---
    lines += [SEP, L("3️⃣ تحلیل آماری"), SEP, L(analysis_block)]

    # --- Section 4: AI scenario outlook (already ends with the
    # deterministic disclaimer + channel footer appended in gemini_analyst.py) ---
    lines += [SEP, L("4️⃣ چشم‌انداز احتمالی"), SEP, L(outlook_block)]

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
    L = escape_mdv2  # noqa: N806
    tehran_dt = _parse_tehran_time_str(tehran_time_str)
    persian_date, gregorian_date = _header_dates(tehran_dt)
    analysis_block, outlook_block = _split_ai_blocks(ai_summary)

    change = stats.week_close - stats.week_open

    lines: list[str] = [
        L(f"📊 {asset_display_name} | گزارش هفتگی | {persian_date} | {gregorian_date}"),
        L(_TZ_LINE),
        SEP,
    ]

    lines.append(L(f"📈 باز هفته: {stats.week_open:.2f} → بسته هفته: {stats.week_close:.2f}"))
    lines.append(
        L(
            f"📊 تغییر: {change:+.2f}$ | دامنه هفتگی: {stats.weekly_range:.2f}$ | "
            f"میانگین دامنه‌ی روزانه: {stats.average_daily_range:.2f}$"
        )
    )
    lines.append(L(f"⚡ نوسان‌پذیری: {stats.volatility_pct:.4f}٪"))

    # --- Section 1: one compact line per trading day (the weekly analogue
    # of the daily report's per-session lines — a week has no sessions). ---
    lines += [SEP, L("1️⃣ روزهای هفته"), SEP]
    for d in stats.daily_breakdown:
        d_change = d.close - d.open
        lines.append(L(f"📅 {d.date}: {d_change:+.2f}$ | Range {d.range:.2f}$"))

    # --- Section 2: key weekly points ---
    lines += [SEP, L("2️⃣ نقاط کلیدی هفته"), SEP]

    strongest_change = stats.strongest_day.close - stats.strongest_day.open
    weakest_change = stats.weakest_day.close - stats.weakest_day.open
    lines.append(L(f"🏆 قوی‌ترین روز: {stats.strongest_day.date} → {strongest_change:+.2f}$"))
    lines.append(L(f"🥶 ضعیف‌ترین روز: {stats.weakest_day.date} → {weakest_change:+.2f}$"))
    lines.append(
        L(f"♦️ پرحجم‌ترین روز: {stats.highest_volume_day.date} → {stats.highest_volume_day.volume:,.0f}")
    )
    lines.append(L(f"🔥 پرفعالیت‌ترین ساعت (UTC): {stats.most_active_hour_utc:02d}:00"))

    if news_events:
        lines += [SEP, L("📰 اخبار مهم دلاری این هفته"), SEP]
        for e in news_events[:8]:
            when_str = e.when.astimezone(SERVER_TZ).strftime("%a %H:%M")
            lines.append(L(f"• {when_str} — {e.title}"))

    # --- Section 3: AI statistical recap ---
    lines += [SEP, L("3️⃣ تحلیل آماری"), SEP, L(analysis_block)]

    # --- Section 4: AI scenario outlook (already ends with the
    # deterministic disclaimer + channel footer appended in gemini_analyst.py) ---
    lines += [SEP, L("4️⃣ چشم‌انداز احتمالی"), SEP, L(outlook_block)]

    return "\n".join(lines)
