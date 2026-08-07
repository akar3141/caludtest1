"""Single source of truth for all time calculations.

Everything routes through ``zoneinfo``, so America/New_York DST
transitions (EDT/EST) are handled automatically by the IANA tz database —
nothing here is hardcoded to a fixed UTC offset for NY. Asia/Tehran has
used a fixed UTC+03:30 offset (no DST) since Iran abolished daylight
saving in 2022, so it needs no special handling either, but we still
route it through zoneinfo for consistency and future-proofing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
TEHRAN_TZ = ZoneInfo("Asia/Tehran")
UTC_TZ = ZoneInfo("UTC")

NY_OPEN_LOCAL_TIME = time(9, 30)  # NYSE regular session open, local NY time


@dataclass(frozen=True)
class TargetTime:
    """A scheduling target, always timezone-aware."""

    when: datetime
    label: str


class TimeManager:
    """DST-safe time utilities used across the whole project."""

    def now_utc(self) -> datetime:
        return datetime.now(UTC_TZ)

    def now_ny(self) -> datetime:
        return self.now_utc().astimezone(NY_TZ)

    def now_tehran(self) -> datetime:
        return self.now_utc().astimezone(TEHRAN_TZ)

    def to_tehran(self, dt: datetime) -> datetime:
        """Converts any aware datetime to Asia/Tehran for display purposes."""
        if dt.tzinfo is None:
            raise ValueError("to_tehran() requires a timezone-aware datetime")
        return dt.astimezone(TEHRAN_TZ)

    def format_tehran(self, dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
        return self.to_tehran(dt).strftime(fmt) + " (Asia/Tehran)"

    def ny_open_for(self, day: date) -> datetime:
        """NYSE open (09:30) on the given date, in America/New_York local time.

        zoneinfo resolves the correct UTC offset for that specific date
        (EDT in summer, EST in winter) — no manual DST bookkeeping needed.
        """
        return datetime.combine(day, NY_OPEN_LOCAL_TIME, tzinfo=NY_TZ)

    def target_before_ny_open(self, minutes_before: int, day: date | None = None) -> datetime:
        """Returns the datetime `minutes_before` NYSE open on `day` (default: today, NY-local)."""
        day = day or self.now_ny().date()
        return self.ny_open_for(day) - timedelta(minutes=minutes_before)

    def target_tehran_time(self, hour: int, minute: int, day: date | None = None) -> datetime:
        """Returns a specific hour:minute today (or `day`) in Asia/Tehran, tz-aware."""
        day = day or self.now_tehran().date()
        return datetime.combine(day, time(hour, minute), tzinfo=TEHRAN_TZ)

    def is_due(
        self,
        target: datetime,
        tolerance_before_minutes: int,
        catch_up_after_minutes: int = 0,
    ) -> bool:
        """True if `now` falls in the window [target - before, target + after].

        Deliberately **asymmetric**. Two things this needs to satisfy at
        once:

        1. Reject the "wrong" DST cron line. Gold/Dow workflows carry two
           static cron lines (one per DST state), exactly one hour apart.
           As long as ``tolerance_before_minutes + catch_up_after_minutes``
           stays well under 60, the non-matching line's fixed UTC time
           always falls outside this window and is safely skipped.
        2. Tolerate GitHub Actions' well-documented scheduling drift.
           Scheduled workflows are a *best-effort* feature — GitHub's own
           docs note runs can be delayed, especially at the top of the
           hour under high load. A purely symmetric +-7 minute window is
           too narrow in practice and can silently swallow a whole day's
           report if the runner is late. `catch_up_after_minutes` (paired
           with a second, later cron trigger in the workflow YAML — see
           README) gives a wide "still due" window after the ideal time,
           while state_store still prevents double-sending if the
           primary trigger already succeeded.
        """
        now = self.now_utc()
        window_start = target - timedelta(minutes=tolerance_before_minutes)
        window_end = target + timedelta(minutes=catch_up_after_minutes)
        return window_start <= now <= window_end

    def is_saturday_tehran(self) -> bool:
        # Python weekday(): Monday=0 ... Sunday=6, so Saturday=5
        return self.now_tehran().weekday() == 5


def get_time_manager() -> TimeManager:
    return TimeManager()
