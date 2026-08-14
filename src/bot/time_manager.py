"""Single source of truth for timezone-aware scheduling."""

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
    when: datetime
    label: str


class TimeManager:
    """Timezone/DST-aware clock and scheduling helper."""

    def now_utc(self) -> datetime:
        return datetime.now(UTC_TZ)

    def now_ny(self) -> datetime:
        return self.now_utc().astimezone(NY_TZ)

    def now_tehran(self) -> datetime:
        return self.now_utc().astimezone(TEHRAN_TZ)

    @staticmethod
    def _require_aware(dt: datetime, method: str) -> None:
        if dt.tzinfo is None:
            raise ValueError(f"{method}() requires a timezone-aware datetime")

    def to_tehran(self, dt: datetime) -> datetime:
        self._require_aware(dt, "to_tehran")
        return dt.astimezone(TEHRAN_TZ)

    def to_server(self, dt: datetime) -> datetime:
        self._require_aware(dt, "to_server")
        return dt.astimezone(SERVER_TZ)

    def format_tehran(
        self,
        dt: datetime,
        fmt: str = "%Y-%m-%d %H:%M",
    ) -> str:
        return self.to_tehran(dt).strftime(fmt) + " (Asia/Tehran)"

    def format_dual_time(
        self,
        dt: datetime,
        fmt: str = "%H:%M",
    ) -> str:
        return (
            f"سرور {self.to_server(dt).strftime(fmt)} "
            f"(ایران {self.to_tehran(dt).strftime(fmt)})"
        )

    def ny_open_for(self, day: date) -> datetime:
        # ZoneInfo applies the correct EST/EDT offset for the supplied date.
        return datetime.combine(day, NY_OPEN_LOCAL_TIME, tzinfo=NY_TZ)

    def target_before_ny_open(
        self,
        minutes_before: int,
        day: date | None = None,
    ) -> datetime:
        day = day or self.now_ny().date()
        return self.ny_open_for(day) - timedelta(minutes=minutes_before)

    def target_tehran_time(
        self,
        hour: int,
        minute: int,
        day: date | None = None,
    ) -> datetime:
        day = day or self.now_tehran().date()
        return datetime.combine(day, time(hour, minute), tzinfo=TEHRAN_TZ)

    def is_due(
        self,
        target: datetime,
        tolerance_before_minutes: int,
        catch_up_after_minutes: int = 0,
        now: datetime | None = None,
    ) -> bool:
        """Return True only when now is inside the target's due window.

        target - tolerance <= now <= target + catch_up.

        The default application catch-up window is intentionally generous
        because GitHub Actions scheduled workflows are best-effort and can
        start well after their nominal cron minute. Target creation remains
        IANA-timezone based, so New York DST is handled automatically.
        """
        self._require_aware(target, "is_due")

        if tolerance_before_minutes < 0 or catch_up_after_minutes < 0:
            raise ValueError("due-window values must be >= 0")

        current = now if now is not None else self.now_utc()
        self._require_aware(current, "is_due(now)")

        target_utc = target.astimezone(UTC_TZ)
        now_utc = current.astimezone(UTC_TZ)

        start = target_utc - timedelta(minutes=tolerance_before_minutes)
        end = target_utc + timedelta(minutes=catch_up_after_minutes)

        return start <= now_utc <= end

    def is_saturday_tehran(self) -> bool:
        return self.now_tehran().weekday() == 5

    def schedule_debug(
        self,
        target: datetime,
        tolerance_before_minutes: int,
        catch_up_after_minutes: int,
        now: datetime | None = None,
    ) -> str:
        current = now if now is not None else self.now_utc()
        start = target - timedelta(minutes=tolerance_before_minutes)
        end = target + timedelta(minutes=catch_up_after_minutes)
        return (
            f"target_utc={target.astimezone(UTC_TZ).isoformat()} "
            f"target_ny={target.astimezone(NY_TZ).isoformat()} "
            f"target_tehran={target.astimezone(TEHRAN_TZ).isoformat()} "
            f"window_start_utc={start.astimezone(UTC_TZ).isoformat()} "
            f"window_end_utc={end.astimezone(UTC_TZ).isoformat()} "
            f"now_utc={current.astimezone(UTC_TZ).isoformat()}"
        )


def get_time_manager() -> TimeManager:
    return TimeManager()
