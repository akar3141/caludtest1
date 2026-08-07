"""NYSE trading-day detection.

Gold (GC=F) and Dow (^DJI) daily reports only make sense on days the NYSE
is actually open — not just "not Saturday/Sunday", but also official
holidays (e.g. Thanksgiving, Christmas). This was not addressed in the
original spec, so as an architectural improvement we skip execution
entirely (same as a "no high-impact news" skip) on non-trading days.

Uses `pandas_market_calendars` when available for full accuracy (correct
holiday list, early-close days, etc.). If the dependency is unavailable
at runtime for any reason, falls back to a weekday-only check and logs a
warning, so the bot degrades gracefully instead of crashing.
"""

from __future__ import annotations

from datetime import date

from .logger import get_logger

logger = get_logger(__name__)


class MarketCalendar:
    def __init__(self) -> None:
        self._nyse = None
        try:
            import pandas_market_calendars as mcal  # type: ignore

            self._nyse = mcal.get_calendar("NYSE")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "pandas_market_calendars unavailable (%s); "
                "falling back to weekday-only trading-day check.",
                exc,
            )

    def is_trading_day(self, day: date) -> bool:
        if self._nyse is not None:
            schedule = self._nyse.schedule(start_date=day.isoformat(), end_date=day.isoformat())
            return not schedule.empty
        # Fallback: Monday=0 .. Sunday=6
        return day.weekday() < 5


def get_market_calendar() -> MarketCalendar:
    return MarketCalendar()
