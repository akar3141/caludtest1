"""Pure computation over OHLCV data — no I/O, fully unit-testable.

Two entry points:
  - `daily_session_stats`: full session-based breakdown (Asia/London/NY +
     London-NY overlap) plus day-level extremes, hourly volatility, and
     intraday drawdown/runup, for Gold/Dow/Bitcoin daily reports.
  - `weekly_stats`: full weekly analytics required by the spec (OHLC,
     range, volatility, ADR, strongest/weakest day, highest-volume day,
     trend summary, most active hours).

All timestamps stored on the returned dataclasses are UTC-aware
`pandas.Timestamp` objects — this module never renders text or picks a
display timezone (see `message_formatter.py` / `time_manager.py` for
that), keeping this module a pure, unit-testable numeric layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

from .exceptions import NoMarketDataError

UTC = ZoneInfo("UTC")

# Trading-session windows expressed in UTC hours (approximate, standard
# convention). Used to slice intraday data for session-level stats.
SESSIONS_UTC: dict[str, tuple[time, time]] = {
    "Asia": (time(0, 0), time(8, 0)),
    "London": (time(7, 0), time(16, 0)),
    "New York": (time(12, 0), time(21, 0)),
}

# London-New York overlap: the intersection of the two windows above.
# Kept as a separate, explicit constant rather than computed from
# SESSIONS_UTC so a future change to either session's hours doesn't
# silently change the overlap window without a deliberate edit here too.
OVERLAP_UTC: tuple[str, time, time] = ("London-New York Overlap", time(12, 0), time(16, 0))


@dataclass(frozen=True)
class CandleEvent:
    """A single notable 1-minute candle: when it happened and its value
    (interpretation of `value` depends on context — a price move, a
    range, or a volume figure)."""

    time_utc: pd.Timestamp
    value: float


@dataclass(frozen=True)
class VolumeWindow:
    """A rolling window (e.g. 5 minutes) with the highest summed volume."""

    start_time_utc: pd.Timestamp
    volume: float


@dataclass(frozen=True)
class HourStat:
    hour_start_utc: pd.Timestamp
    range: float


@dataclass(frozen=True)
class DrawdownRunup:
    value: float
    start_time_utc: pd.Timestamp
    end_time_utc: pd.Timestamp


@dataclass(frozen=True)
class SessionStat:
    name: str
    high: float | None
    low: float | None
    volume: float | None
    net_move: float | None = None
    up_candles: int | None = None
    down_candles: int | None = None
    up_pct: float | None = None
    biggest_up_candle: CandleEvent | None = None
    biggest_down_candle: CandleEvent | None = None
    highest_5m_volume: VolumeWindow | None = None


@dataclass(frozen=True)
class OverlapStat:
    name: str
    range: float
    avg_candle_range: float
    pct_above_daily_avg: float


@dataclass(frozen=True)
class DailyStats:
    open: float
    high: float
    low: float
    close: float
    volume: float
    sessions: list[SessionStat] = field(default_factory=list)

    # --- Extended day-level analytics (all optional so any construction
    # site with only the original five fields still works) ---
    total_range: float | None = None
    avg_candle_range: float | None = None
    up_candles: int | None = None
    down_candles: int | None = None
    total_candles: int | None = None
    up_pct: float | None = None
    down_pct: float | None = None
    biggest_range_candle: CandleEvent | None = None
    second_biggest_range_candle: CandleEvent | None = None
    highest_volume_1m: CandleEvent | None = None
    biggest_up_candle: CandleEvent | None = None
    biggest_down_candle: CandleEvent | None = None
    busiest_hour: HourStat | None = None
    quietest_hour: HourStat | None = None
    max_drawdown: DrawdownRunup | None = None
    max_runup: DrawdownRunup | None = None
    highest_volume_session_name: str | None = None
    overlap: OverlapStat | None = None


@dataclass(frozen=True)
class DayBreakdown:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    range: float


@dataclass(frozen=True)
class WeeklyStats:
    week_open: float
    week_high: float
    week_low: float
    week_close: float
    weekly_range: float
    volatility_pct: float
    average_daily_range: float
    strongest_day: DayBreakdown
    weakest_day: DayBreakdown
    highest_volume_day: DayBreakdown
    most_active_hour_utc: int
    trend_summary: str
    daily_breakdown: list[DayBreakdown]


def _ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tz is None:
        return df.tz_localize("UTC")
    return df.tz_convert("UTC")


def _session_window_stats(window: pd.DataFrame) -> dict:
    """Extra per-session analytics shared by session and overlap slicing."""
    diffs = window["Close"] - window["Open"]
    up_candles = int((diffs > 0).sum())
    down_candles = int((diffs < 0).sum())
    total = len(window)
    up_pct = (up_candles / total * 100) if total else None

    biggest_up_idx = diffs.idxmax()
    biggest_down_idx = diffs.idxmin()
    biggest_up = CandleEvent(time_utc=biggest_up_idx, value=float(diffs.loc[biggest_up_idx]))
    biggest_down = CandleEvent(time_utc=biggest_down_idx, value=float(diffs.loc[biggest_down_idx]))

    highest_5m: VolumeWindow | None = None
    vol_5m = window["Volume"].resample("5min").sum()
    vol_5m = vol_5m[vol_5m > 0]
    if not vol_5m.empty:
        idx = vol_5m.idxmax()
        highest_5m = VolumeWindow(start_time_utc=idx, volume=float(vol_5m.loc[idx]))

    return {
        "net_move": float(window["Close"].iloc[-1] - window["Open"].iloc[0]),
        "up_candles": up_candles,
        "down_candles": down_candles,
        "up_pct": up_pct,
        "biggest_up_candle": biggest_up,
        "biggest_down_candle": biggest_down,
        "highest_5m_volume": highest_5m,
    }


def daily_session_stats(df: pd.DataFrame) -> DailyStats:
    df = _ensure_utc_index(df)

    sessions: list[SessionStat] = []
    session_volumes: dict[str, float] = {}
    for name, (start, end) in SESSIONS_UTC.items():
        mask = (df.index.time >= start) & (df.index.time < end)
        window = df.loc[mask]
        if window.empty:
            sessions.append(SessionStat(name=name, high=None, low=None, volume=None))
            continue

        extra = _session_window_stats(window)
        volume = float(window["Volume"].sum())
        session_volumes[name] = volume
        sessions.append(
            SessionStat(
                name=name,
                high=float(window["High"].max()),
                low=float(window["Low"].min()),
                volume=volume,
                **extra,
            )
        )

    highest_volume_session_name = (
        max(session_volumes, key=lambda k: session_volumes[k]) if session_volumes else None
    )

    # Day-level candle stats.
    diffs = df["Close"] - df["Open"]
    ranges = df["High"] - df["Low"]
    total_candles = len(df)
    up_candles = int((diffs > 0).sum())
    down_candles = int((diffs < 0).sum())
    avg_candle_range = float(ranges.mean()) if total_candles else 0.0

    biggest_range_idx = ranges.idxmax()
    biggest_range_candle = CandleEvent(
        time_utc=biggest_range_idx, value=float(ranges.loc[biggest_range_idx])
    )
    second_biggest_range_candle: CandleEvent | None = None
    top_two = ranges.nlargest(2)
    if len(top_two) >= 2:
        second_idx = top_two.index[1]
        second_biggest_range_candle = CandleEvent(
            time_utc=second_idx, value=float(top_two.iloc[1])
        )

    highest_volume_idx = df["Volume"].idxmax()
    highest_volume_1m = CandleEvent(
        time_utc=highest_volume_idx, value=float(df["Volume"].loc[highest_volume_idx])
    )

    biggest_up_idx = diffs.idxmax()
    biggest_up_candle = CandleEvent(time_utc=biggest_up_idx, value=float(diffs.loc[biggest_up_idx]))
    biggest_down_idx = diffs.idxmin()
    biggest_down_candle = CandleEvent(
        time_utc=biggest_down_idx, value=float(diffs.loc[biggest_down_idx])
    )

    # Busiest / quietest hour by intra-hour range (high-low across all
    # candles in that hour), not by volume — matches "پرنوسان‌ترین ساعت".
    hourly = df.groupby(df.index.floor("h"))
    hourly_range = hourly["High"].max() - hourly["Low"].min()
    busiest_idx = hourly_range.idxmax()
    quietest_idx = hourly_range.idxmin()
    busiest_hour = HourStat(hour_start_utc=busiest_idx, range=float(hourly_range.loc[busiest_idx]))
    quietest_hour = HourStat(
        hour_start_utc=quietest_idx, range=float(hourly_range.loc[quietest_idx])
    )

    # Intraday max drawdown (largest peak-to-trough decline) and max runup
    # (largest trough-to-peak rise), computed on the Close series.
    close = df["Close"]
    running_max = close.cummax()
    drawdown_series = close - running_max
    dd_end_idx = drawdown_series.idxmin()
    dd_start_idx = close.loc[:dd_end_idx].idxmax()
    max_drawdown = DrawdownRunup(
        value=float(-drawdown_series.loc[dd_end_idx]),
        start_time_utc=dd_start_idx,
        end_time_utc=dd_end_idx,
    )

    running_min = close.cummin()
    runup_series = close - running_min
    ru_end_idx = runup_series.idxmax()
    ru_start_idx = close.loc[:ru_end_idx].idxmin()
    max_runup = DrawdownRunup(
        value=float(runup_series.loc[ru_end_idx]),
        start_time_utc=ru_start_idx,
        end_time_utc=ru_end_idx,
    )

    # London-New York overlap window.
    overlap_name, overlap_start, overlap_end = OVERLAP_UTC
    overlap_mask = (df.index.time >= overlap_start) & (df.index.time < overlap_end)
    overlap_window = df.loc[overlap_mask]
    overlap: OverlapStat | None = None
    if not overlap_window.empty:
        overlap_range = float(overlap_window["High"].max() - overlap_window["Low"].min())
        overlap_avg_range = float((overlap_window["High"] - overlap_window["Low"]).mean())
        pct_above = (
            ((overlap_avg_range / avg_candle_range) - 1) * 100 if avg_candle_range else 0.0
        )
        overlap = OverlapStat(
            name=overlap_name,
            range=overlap_range,
            avg_candle_range=overlap_avg_range,
            pct_above_daily_avg=pct_above,
        )

    return DailyStats(
        open=float(df["Open"].iloc[0]),
        high=float(df["High"].max()),
        low=float(df["Low"].min()),
        close=float(df["Close"].iloc[-1]),
        volume=float(df["Volume"].sum()),
        sessions=sessions,
        total_range=float(df["High"].max() - df["Low"].min()),
        avg_candle_range=avg_candle_range,
        up_candles=up_candles,
        down_candles=down_candles,
        total_candles=total_candles,
        up_pct=(up_candles / total_candles * 100) if total_candles else None,
        down_pct=(down_candles / total_candles * 100) if total_candles else None,
        biggest_range_candle=biggest_range_candle,
        second_biggest_range_candle=second_biggest_range_candle,
        highest_volume_1m=highest_volume_1m,
        biggest_up_candle=biggest_up_candle,
        biggest_down_candle=biggest_down_candle,
        busiest_hour=busiest_hour,
        quietest_hour=quietest_hour,
        max_drawdown=max_drawdown,
        max_runup=max_runup,
        highest_volume_session_name=highest_volume_session_name,
        overlap=overlap,
    )


def weekly_stats(df: pd.DataFrame) -> WeeklyStats:
    df = _ensure_utc_index(df)

    daily = df.resample("1D").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna(subset=["Open", "High", "Low", "Close"])

    if daily.empty:
        # Can happen if yfinance returns a very sparse/degenerate window
        # (e.g. a holiday-only week for an asset with limited trading hours).
        raise NoMarketDataError(
            "No complete trading days found in the fetched weekly window; "
            "cannot compute weekly statistics."
        )

    breakdown: list[DayBreakdown] = []
    for idx, row in daily.iterrows():
        breakdown.append(
            DayBreakdown(
                date=idx.strftime("%Y-%m-%d"),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
                range=float(row["High"] - row["Low"]),
            )
        )

    week_open = breakdown[0].open
    week_close = breakdown[-1].close
    week_high = max(d.high for d in breakdown)
    week_low = min(d.low for d in breakdown)
    weekly_range = week_high - week_low
    average_daily_range = sum(d.range for d in breakdown) / len(breakdown)

    # Volatility: stddev of 1-minute log returns over the week, expressed as %.
    import math

    close = df["Close"].astype(float)
    log_returns = (close.div(close.shift(1))).dropna().apply(math.log)
    # std() needs at least 2 points (ddof=1); fewer yields NaN, not 0.
    volatility_pct = float(log_returns.std() * 100) if len(log_returns) >= 2 else 0.0

    strongest_day = max(breakdown, key=lambda d: d.close - d.open)
    weakest_day = min(breakdown, key=lambda d: d.close - d.open)
    highest_volume_day = max(breakdown, key=lambda d: d.volume)

    hourly_volume = df.groupby(df.index.hour)["Volume"].sum()
    most_active_hour_utc = int(hourly_volume.idxmax()) if not hourly_volume.empty else 0

    net_change_pct = ((week_close - week_open) / week_open) * 100 if week_open else 0.0
    if net_change_pct > 0.15:
        direction = "bullish"
    elif net_change_pct < -0.15:
        direction = "bearish"
    else:
        direction = "range-bound / neutral"
    trend_summary = (
        f"Net change over the week: {net_change_pct:+.2f}% — overall bias: {direction}."
    )

    return WeeklyStats(
        week_open=week_open,
        week_high=week_high,
        week_low=week_low,
        week_close=week_close,
        weekly_range=weekly_range,
        volatility_pct=volatility_pct,
        average_daily_range=average_daily_range,
        strongest_day=strongest_day,
        weakest_day=weakest_day,
        highest_volume_day=highest_volume_day,
        most_active_hour_utc=most_active_hour_utc,
        trend_summary=trend_summary,
        daily_breakdown=breakdown,
    )
