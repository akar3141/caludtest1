from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from bot.time_manager import TimeManager


def test_ny_open_uses_correct_offset_winter_and_summer() -> None:
    tm = TimeManager()

    winter_open = tm.ny_open_for(date(2026, 1, 15))  # EST, UTC-5
    summer_open = tm.ny_open_for(date(2026, 7, 15))  # EDT, UTC-4

    assert winter_open.utcoffset() == timedelta(hours=-5)
    assert summer_open.utcoffset() == timedelta(hours=-4)
    assert winter_open.hour == 9 and winter_open.minute == 30
    assert summer_open.hour == 9 and summer_open.minute == 30


def test_target_before_ny_open_matches_expected_utc_time() -> None:
    tm = TimeManager()
    target = tm.target_before_ny_open(30, date(2026, 1, 15))
    assert target.astimezone(timezone.utc).hour == 14  # 09:00 EST == 14:00 UTC
    assert target.astimezone(timezone.utc).minute == 0


def test_is_due_accepts_within_symmetric_window() -> None:
    tm = TimeManager()
    target = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)

    class FrozenTM(TimeManager):
        def now_utc(self) -> datetime:
            return datetime(2026, 1, 15, 14, 3, tzinfo=timezone.utc)

    frozen = FrozenTM()
    assert frozen.is_due(target, tolerance_before_minutes=7, catch_up_after_minutes=20)


def test_is_due_rejects_wrong_dst_line() -> None:
    """The EDT-line target (13:00 UTC) must NOT be considered due when
    now is actually near the EST-line target (14:00 UTC) — this is what
    keeps the two static cron lines from ever double-firing."""
    edt_target = datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)

    class FrozenTM(TimeManager):
        def now_utc(self) -> datetime:
            return datetime(2026, 1, 15, 14, 3, tzinfo=timezone.utc)

    frozen = FrozenTM()
    assert not frozen.is_due(edt_target, tolerance_before_minutes=7, catch_up_after_minutes=20)


def test_is_due_catch_up_window_covers_delayed_trigger() -> None:
    """A GitHub Actions trigger delayed by up to catch_up_after_minutes
    past the ideal target should still be considered due."""
    target = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)

    class FrozenTM(TimeManager):
        def now_utc(self) -> datetime:
            return datetime(2026, 1, 15, 14, 18, tzinfo=timezone.utc)  # 18 min late

    frozen = FrozenTM()
    assert frozen.is_due(target, tolerance_before_minutes=7, catch_up_after_minutes=20)


def test_is_due_rejects_too_early() -> None:
    target = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)

    class FrozenTM(TimeManager):
        def now_utc(self) -> datetime:
            return datetime(2026, 1, 15, 13, 45, tzinfo=timezone.utc)  # 15 min early

    frozen = FrozenTM()
    assert not frozen.is_due(target, tolerance_before_minutes=7, catch_up_after_minutes=20)


def test_is_due_accepts_realistic_github_delay() -> None:
    target = datetime(2026, 8, 14, 13, 15, tzinfo=timezone.utc)

    class FrozenTM(TimeManager):
        def now_utc(self) -> datetime:
            return datetime(2026, 8, 14, 15, 52, tzinfo=timezone.utc)

    frozen = FrozenTM()
    assert frozen.is_due(target, tolerance_before_minutes=7, catch_up_after_minutes=720)
