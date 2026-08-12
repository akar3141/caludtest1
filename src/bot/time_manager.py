"""Single source of truth for all time calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


NY_TZ = ZoneInfo("America/New_York")
TEHRAN_TZ = ZoneInfo("Asia/Tehran")
UTC_TZ = ZoneInfo("UTC")

# Broker / MT5 server time.
SERVER_TZ = timezone(timedelta(hours=3))

# NYSE regular session open.
NY_OPEN_LOCAL_TIME = time(9, 30)


@dataclass(frozen=True)
class TargetTime:
    """A scheduling target, always timezone-aware."""

    when: datetime
    label: str


class TimeManager:

    def now_utc(self) -> datetime:
        return datetime.now(UTC_TZ)

    def now_ny(self) -> datetime:
        return self.now_utc().astimezone(NY_TZ)

    def now_tehran(self) -> datetime:
        return self.now_utc().astimezone(TEHRAN_TZ)

    def to_tehran(self, dt: datetime) -> datetime:

        if dt.tzinfo is None:
            raise ValueError(
                "to_tehran() requires a timezone-aware datetime"
            )

        return dt.astimezone(TEHRAN_TZ)

    def to_server(self, dt: datetime) -> datetime:

        if dt.tzinfo is None:
            raise ValueError(
                "to_server() requires a timezone-aware datetime"
            )

        return dt.astimezone(SERVER_TZ)

    def format_tehran(
        self,
        dt: datetime,
        fmt: str = "%Y-%m-%d %H:%M",
    ) -> str:

        return (
            self.to_tehran(dt).strftime(fmt)
            + " (Asia/Tehran)"
        )

    def format_dual_time(
        self,
        dt: datetime,
        fmt: str = "%H:%M",
    ) -> str:

        server_str = self.to_server(dt).strftime(fmt)
        tehran_str = self.to_tehran(dt).strftime(fmt)

        return (
            f"سرور {server_str} "
            f"(ایران {tehran_str})"
        )

    def ny_open_for(self, day: date) -> datetime:

        return datetime.combine(
            day,
            NY_OPEN_LOCAL_TIME,
            tzinfo=NY_TZ,
        )

    def target_before_ny_open(
        self,
        minutes_before: int,
        day: date | None = None,
    ) -> datetime:

        day = day or self.now_ny().date()

        return (
            self.ny_open_for(day)
            - timedelta(minutes=minutes_before)
        )

    def target_tehran_time(
        self,
        hour: int,
        minute: int,
        day: date | None = None,
    ) -> datetime:

        day = day or self.now_tehran().date()

        return datetime.combine(
            day,
            time(hour, minute),
            tzinfo=TEHRAN_TZ,
        )

    def is_due(
        self,
        target: datetime,
        tolerance_before_minutes: int,
        catch_up_after_minutes: int = 0,
    ) -> bool:
        """Check whether the current time is inside the due window.

        Window:

            target - tolerance_before
                <= now <=
            target + catch_up_after

        The early tolerance remains small.
        The late catch-up window is intentionally larger because
        GitHub Actions cron execution is not guaranteed to happen
        exactly at the requested minute.
        """

        if target.tzinfo is None:
            raise ValueError(
                "is_due() requires a timezone-aware target"
            )

        now = self.now_utc()

        target_utc = target.astimezone(UTC_TZ)

        window_start = (
            target_utc
            - timedelta(
                minutes=tolerance_before_minutes
            )
        )

        window_end = (
            target_utc
            + timedelta(
                minutes=catch_up_after_minutes
            )
        )

        return window_start <= now <= window_end

    def is_saturday_tehran(self) -> bool:

        # Monday=0 ... Saturday=5 ... Sunday=6
        return self.now_tehran().weekday() == 5


def get_time_manager() -> TimeManager:
    return TimeManager()
