"""Pure computation over OHLCV data — no I/O, fully unit-testable.

Two entry points:
  - `daily_session_stats`: session-based breakdown (Asia/London/NY) for
     Gold & Dow's daily reports.
  - `weekly_stats`: full weekly analytics required by the spec (OHLC,
     range, volatility, ADR, strongest/weakest day, highest-volume day,
     trend summary, most active hours).
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


@dataclass(frozen=True)
class SessionStat:
    name: str
    high: float | None
    low: float | None
    volume: float | None


@dataclass(frozen=True)
class DailyStats:
    open: float
    high: float
    low: float
    close: float
    volume: float
    sessions: list[SessionStat] = field(default_factory=list)


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


def daily_session_stats(df: pd.DataFrame) -> DailyStats:
    df = _ensure_utc_index(df)
    sessions: list[SessionStat] = []
    for name, (start, end) in SESSIONS_UTC.items():
        mask = (df.index.time >= start) & (df.index.time < end)
        window = df.loc[mask]
        if window.empty:
            sessions.append(SessionStat(name=name, high=None, low=None, volume=None))
        else:
            sessions.append(
                SessionStat(
                    name=name,
                    high=float(window["High"].max()),
                    low=float(window["Low"].min()),
                    volume=float(window["Volume"].sum()),
                )
            )

    return DailyStats(
        open=float(df["Open"].iloc[0]),
        high=float(df["High"].max()),
        low=float(df["Low"].min()),
        close=float(df["Close"].iloc[-1]),
        volume=float(df["Volume"].sum()),
        sessions=sessions,
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
