"""Builds Telegram MarkdownV2-safe captions.

Kept separate from chart_generator/gemini_analyst so that changing the
message layout never touches chart rendering or AI-generation logic.

The daily report renders a compact, emoji-led Persian statistical
breakdown built entirely from `DailyStats` (no numbers are invented
here — everything comes from `statistical_analyzer.py`); the only
free-text piece is the Gemini-written wrap-up passed in as `ai_summary`,
which already ends with its own deterministic disclaimer + Telegram
channel-link footer (see `gemini_analyst.py`).

The weekly report mirrors the same visual language (header, separators,
numbered sections, emoji-led lines) but is built entirely from weekly
concepts — week open/close, weekly range, volatility, average daily
range, per-day breakdown, strongest/weakest/highest-volume day, weekly
trend — never daily/session vocabulary, since a week has no sessions.
"""

from __future__ import annotations

import re
from datetime import datetime
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

# English (not transliterated) Gregorian month abbreviations — deliberately
# hardcoded rather than using datetime.strftime("%b") so the header format
# never depends on the host's locale being English.
_GREGORIAN_MONTHS_EN_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

# Numbered-section keycap headers used by both report types.
_SEC1, _SEC2, _SEC3, _SEC4, _SEC5 = "۱️⃣", "۲️⃣", "۳️⃣", "۴️⃣", "۵️⃣"

SEP = "━━━━━━━━━━"
_TZ_LINE = "🕐 سرور GMT+3 | ایران GMT+3:30"

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
    "emoji": "🟣", "fa_name": "همپوشانی لندن–نیویورک",
    "server": "15:00–19:00", "tehran": "15:30–19:30",
}


def escape_mdv2(text: str) -> str:
    return re.sub(f"([{re.escape(_MDV2_SPECIAL)}])", r"\\\1", text)


def _fa_digits(s: str) -> str:
    return s.translate(_PERSIAN_DIGITS)


def _server_hm(ts) -> str:
    return ts.astimezone(SERVER_TZ).strftime("%H:%M")


def _header_dates(report_time: datetime) -> tuple[str, str]:
    """Returns (persian_jalali_date, gregorian_date) strings, both in
    Asia/Tehran local date — e.g. ("۱۴ مرداد ۱۴۰۵", "5 Aug 2026")."""
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

    lines: list[str] = [
        L(f"📊 {asset_display_name} | {persian_date} | {gregorian_date}"),
        L(_TZ_LINE),
        SEP, L(f"{_SEC1} خلاصه روز"), SEP,
    ]

    day_change = stats.close - stats.open
    lines.append(L(f"🔓 باز: {stats.open:.2f} → 🔒 بسته: {stats.close:.2f}"))
    range_part = f" | دامنه: {stats.total_range:.2f}$" if stats.total_range is not None else ""
    lines.append(L(f"📈 تغییر: {day_change:+.2f}${range_part}"))
    if stats.avg_candle_range is not None:
        lines.append(L(f"📊 میانگین کندل 1m: {stats.avg_candle_range:.2f}$"))
    if stats.up_candles is not None and stats.total_candles:
        lines.append(
            L(
                f"🟢 صعودی: {stats.up_candles} ({stats.up_pct:.2f}٪) | "
                f"🔴 نزولی: {stats.down_candles} ({stats.down_pct:.2f}٪)"
            )
        )
    lines.append(L(f"♦️ حجم کل: {stats.volume:,.0f}"))

    # --- Section 2: session breakdown ---
    lines += [SEP, L(f"{_SEC2} عملکرد سشن‌ها"), SEP]

    for s in stats.sessions:
        disp = _SESSION_DISPLAY.get(s.name, {"emoji": "⚪", "fa_name": s.name, "server": "?", "tehran": "?"})
        lines.append(L(f"{disp['emoji']} {disp['fa_name']} | {disp['server']}"))
        lines.append(L(f"🇮🇷 ایران: {disp['tehran']}"))

        if s.high is None or s.low is None:
            lines.append(L("داده‌ای موجود نیست"))
            continue

        lines.append(L(f"↕️ دامنه: {s.high - s.low:.2f}$"))
        if s.net_move is not None:
            lines.append(L(f"📈 حرکت خالص: {s.net_move:+.2f}$"))
        if s.up_candles is not None and s.down_candles is not None:
            lines.append(L(f"🟢/🔴 کندل: {s.up_candles} / {s.down_candles}"))
            lines.append(L(f"📊 درصد صعودی: {s.up_pct:.2f}٪"))
        if s.biggest_up_candle is not None:
            lines.append(L(f"⬆️ بزرگ‌ترین صعود 1m: {s.biggest_up_candle.value:+.2f}$"))
        if s.biggest_down_candle is not None:
            lines.append(L(f"⬇️ بزرگ‌ترین نزول 1m: {s.biggest_down_candle.value:.2f}$"))
        if s.volume is not None:
            lines.append(L(f"♦️ حجم: {s.volume:,.0f}"))
        if s.highest_5m_volume is not None:
            t = _server_hm(s.highest_5m_volume.start_time_utc)
            lines.append(L(f"5m: {t} → {s.highest_5m_volume.volume:,.0f}"))

    if stats.overlap is not None:
        o = stats.overlap
        d = _OVERLAP_DISPLAY
        lines.append(L(f"{d['emoji']} {d['fa_name']} | {d['server']}"))
        lines.append(L(f"🇮🇷 ایران: {d['tehran']}"))
        lines.append(L(f"↕️ دامنه: {o.range:.2f}$"))
        lines.append(L(f"📊 میانگین کندل: {o.avg_candle_range:.2f}$/1m"))
        pct_word = "بیشتر" if o.pct_above_daily_avg >= 0 else "کمتر"
        lines.append(L(f"⚡ حدود {abs(o.pct_above_daily_avg):.0f}٪ {pct_word} از میانگین کل روز"))

    # --- Section 3: key points ---
    lines += [SEP, L(f"{_SEC3} نقاط کلیدی"), SEP]

    if stats.biggest_range_candle is not None:
        t = _server_hm(stats.biggest_range_candle.time_utc)
        lines.append(L(f"📏 بیشترین دامنه: {t} → {stats.biggest_range_candle.value:.2f}$"))
    if stats.second_biggest_range_candle is not None:
        t = _server_hm(stats.second_biggest_range_candle.time_utc)
        lines.append(L(f"📏 دومین: {t} → {stats.second_biggest_range_candle.value:.2f}$"))
    if stats.highest_volume_1m is not None:
        t = _server_hm(stats.highest_volume_1m.time_utc)
        lines.append(L(f"♦️ بیشترین حجم 1m: {t} → {stats.highest_volume_1m.value:,.0f}"))
    if stats.biggest_up_candle is not None:
        t = _server_hm(stats.biggest_up_candle.time_utc)
        lines.append(L(f"⬆️ بزرگ‌ترین صعود: {t} → {stats.biggest_up_candle.value:+.2f}$"))
    if stats.biggest_down_candle is not None:
        t = _server_hm(stats.biggest_down_candle.time_utc)
        lines.append(L(f"⬇️ بزرگ‌ترین نزول: {t} → {stats.biggest_down_candle.value:.2f}$"))
    if stats.busiest_hour is not None:
        h = stats.busiest_hour.hour_start_utc.astimezone(SERVER_TZ).hour
        lines.append(
            L(f"🔥 پرنوسان‌ترین ساعت: {h:02d}–{(h + 1) % 24:02d} → {stats.busiest_hour.range:.2f}$")
        )
    if stats.quietest_hour is not None:
        h = stats.quietest_hour.hour_start_utc.astimezone(SERVER_TZ).hour
        lines.append(
            L(f"😴 کم‌نوسان‌ترین: {h:02d}–{(h + 1) % 24:02d} → {stats.quietest_hour.range:.2f}$")
        )

    # --- Section 4: intraday drawdown / runup ---
    lines += [SEP, L(f"{_SEC4} افت / رشد"), SEP]

    if stats.max_drawdown is not None:
        dd = stats.max_drawdown
        lines.append(
            L(f"🔻 Max DD: {dd.value:.2f}$ | {_server_hm(dd.start_time_utc)}–{_server_hm(dd.end_time_utc)}")
        )
    if stats.max_runup is not None:
        ru = stats.max_runup
        lines.append(
            L(f"🔺 Max Runup: {ru.value:.2f}$ | {_server_hm(ru.start_time_utc)}–{_server_hm(ru.end_time_utc)}")
        )

    # Editorial-only section: present only on days with confirmed high-impact
    # USD news. Its absence never affects whether the report itself is sent.
    if news_events:
        lines += [SEP, L("📰 اخبار مهم دلاری امروز"), SEP]
        for e in news_events[:5]:
            when_str = _server_hm(e.when)
            lines.append(L(f"• {when_str} — {e.title}"))

    # --- Section 5: AI-written wrap-up. `ai_summary` already ends with the
    # deterministic disclaimer + Telegram channel footer appended in
    # gemini_analyst.py — never generated by the model itself.
    lines += [SEP, L(f"{_SEC5} جمع‌بندی"), SEP, L(ai_summary)]

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

    change = stats.week_close - stats.week_open

    lines: list[str] = [
        L(f"📊 {asset_display_name} | گزارش هفتگی | {persian_date} | {gregorian_date}"),
        L(_TZ_LINE),
        SEP, L(f"{_SEC1} خلاصه هفته"), SEP,
    ]
    lines.append(L(f"🔓 باز: {stats.week_open:.2f} → 🔒 بسته: {stats.week_close:.2f}"))
    lines.append(L(f"📈 تغییر: {change:+.2f}$ | دامنه هفتگی: {stats.weekly_range:.2f}$"))
    lines.append(L(f"📊 میانگین دامنه‌ی روزانه: {stats.average_daily_range:.2f}$"))
    lines.append(L(f"⚡ نوسان‌پذیری: {stats.volatility_pct:.4f}٪"))
    lines.append(L(f"🔝 بیشینه هفته: {stats.week_high:.2f}$ | 🔻 کمینه هفته: {stats.week_low:.2f}$"))

    # --- Section 2: day-by-day breakdown (the weekly analogue of session
    # breakdown — a week has no trading sessions, so this walks each
    # trading day of the week instead). ---
    lines += [SEP, L(f"{_SEC2} عملکرد روزهای هفته"), SEP]

    max_range_day = max(stats.daily_breakdown, key=lambda d: d.range) if stats.daily_breakdown else None
    for d in stats.daily_breakdown:
        d_change = d.close - d.open
        lines.append(L(f"📅 {d.date} | باز {d.open:.2f} → بسته {d.close:.2f}"))
        range_note = (
            " (پرنوسان‌ترین روز هفته)" if max_range_day is not None and d.date == max_range_day.date else ""
        )
        lines.append(L(f"↕️ دامنه: {d.range:.2f}${range_note}"))
        lines.append(L(f"📈 حرکت خالص: {d_change:+.2f}$"))
        vol_note = " (پرحجم‌ترین روز هفته)" if d.date == stats.highest_volume_day.date else ""
        lines.append(L(f"♦️ حجم: {d.volume:,.0f}{vol_note}"))

    # --- Section 3: key weekly points ---
    lines += [SEP, L(f"{_SEC3} نقاط کلیدی هفته"), SEP]

    strongest_change = stats.strongest_day.close - stats.strongest_day.open
    weakest_change = stats.weakest_day.close - stats.weakest_day.open
    lines.append(L(f"🏆 قوی‌ترین روز: {stats.strongest_day.date} → {strongest_change:+.2f}$"))
    lines.append(L(f"🥶 ضعیف‌ترین روز: {stats.weakest_day.date} → {weakest_change:+.2f}$"))
    lines.append(
        L(f"♦️ پرحجم‌ترین روز: {stats.highest_volume_day.date} → {stats.highest_volume_day.volume:,.0f}")
    )
    lines.append(L(f"🔥 پرفعالیت‌ترین ساعت (UTC): {stats.most_active_hour_utc:02d}:00"))

    # --- Section 4: weekly trend ---
    lines += [SEP, L(f"{_SEC4} روند هفته"), SEP]

    net_change_pct = (change / stats.week_open * 100) if stats.week_open else 0.0
    if net_change_pct > 0.15:
        direction_fa = "صعودی"
    elif net_change_pct < -0.15:
        direction_fa = "نزولی"
    else:
        direction_fa = "خنثی / رنج"
    lines.append(L(f"📊 تغییر هفتگی: {net_change_pct:+.2f}٪ | جهت کلی: {direction_fa}"))

    if news_events:
        lines += [SEP, L("📰 اخبار مهم دلاری این هفته"), SEP]
        for e in news_events[:8]:
            when_str = e.when.astimezone(SERVER_TZ).strftime("%a %H:%M")
            lines.append(L(f"• {when_str} — {e.title}"))

    # --- Section 5: AI-written wrap-up (weekly-specific prompt/footer —
    # see gemini_analyst.py). ---
    lines += [SEP, L(f"{_SEC5} جمع‌بندی"), SEP, L(ai_summary)]

    return "\n".join(lines)
