from __future__ import annotations

import numpy as np
import pandas as pd

from bot.statistical_analyzer import daily_session_stats, weekly_stats


def _make_ohlcv(periods: int, start: str = "2026-08-03", freq: str = "1min", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    close = 2000 + np.cumsum(rng.normal(0, 0.5, periods))
    return pd.DataFrame(
        {
            "Open": close + rng.normal(0, 0.1, periods),
            "High": close + np.abs(rng.normal(0, 0.3, periods)),
            "Low": close - np.abs(rng.normal(0, 0.3, periods)),
            "Close": close,
            "Volume": rng.integers(1, 100, periods),
        },
        index=idx,
    )


def test_daily_session_stats_basic_invariants() -> None:
    df = _make_ohlcv(1440)  # one day of 1-minute bars
    stats = daily_session_stats(df)

    assert stats.high >= stats.low
    assert stats.open == df["Open"].iloc[0]
    assert stats.close == df["Close"].iloc[-1]
    assert len(stats.sessions) == 3
    assert {s.name for s in stats.sessions} == {"Asia", "London", "New York"}


def test_weekly_stats_basic_invariants() -> None:
    df = _make_ohlcv(1440 * 6)  # ~6 days of 1-minute bars
    stats = weekly_stats(df)

    assert stats.week_high >= stats.week_low
    assert stats.weekly_range == stats.week_high - stats.week_low
    assert stats.volatility_pct >= 0
    assert stats.average_daily_range > 0
    assert stats.highest_volume_day.volume == max(d.volume for d in stats.daily_breakdown)
    assert 0 <= stats.most_active_hour_utc <= 23
    assert "bullish" in stats.trend_summary or "bearish" in stats.trend_summary or "neutral" in stats.trend_summary


def test_weekly_stats_strongest_and_weakest_day_are_consistent() -> None:
    df = _make_ohlcv(1440 * 6)
    stats = weekly_stats(df)

    changes = {d.date: d.close - d.open for d in stats.daily_breakdown}
    assert stats.strongest_day.date == max(changes, key=changes.get)  # type: ignore[arg-type]
    assert stats.weakest_day.date == min(changes, key=changes.get)  # type: ignore[arg-type]
