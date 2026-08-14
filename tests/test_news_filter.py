from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.exceptions import NewsFetchError
from bot.news_filter import NewsFilter
from bot.time_manager import TimeManager


def _filter() -> NewsFilter:
    return NewsFilter(calendar_url="https://example.invalid/weekly.json", time_manager=TimeManager())


def test_parses_standard_dateline_field() -> None:
    nf = _filter()
    ts = int(datetime(2026, 8, 5, 12, 30, tzinfo=timezone.utc).timestamp())
    raw = [{"title": "CPI m/m", "country": "USD", "impact": "High", "dateline": ts}]
    events = nf._parse(raw)
    assert len(events) == 1
    assert events[0].is_high_impact_usd


def test_impact_matching_is_case_insensitive_substring() -> None:
    nf = _filter()
    ts = int(datetime(2026, 8, 5, 12, 30, tzinfo=timezone.utc).timestamp())
    raw = [{"title": "NFP", "country": "usd", "impact": "High Impact Expected", "dateline": ts}]
    events = nf._parse(raw)
    assert events[0].is_high_impact_usd


def test_non_usd_or_low_impact_excluded() -> None:
    nf = _filter()
    ts = int(datetime(2026, 8, 5, 12, 30, tzinfo=timezone.utc).timestamp())
    raw = [
        {"title": "ECB Rate", "country": "EUR", "impact": "High", "dateline": ts},
        {"title": "Minor release", "country": "USD", "impact": "Low", "dateline": ts},
    ]
    events = nf._parse(raw)
    assert all(not e.is_high_impact_usd for e in events)


def test_schema_drift_raises_when_all_items_unparseable() -> None:
    nf = _filter()
    # Every item is missing any recognizable date key -> _parse_one returns None for all.
    raw = [{"foo": "bar"} for _ in range(10)]
    with pytest.raises(NewsFetchError):
        nf._parse(raw)


def test_partial_parse_failures_are_skipped_not_fatal() -> None:
    nf = _filter()
    ts = int(datetime(2026, 8, 5, 12, 30, tzinfo=timezone.utc).timestamp())
    raw = [
        {"title": "Good event", "country": "USD", "impact": "High", "dateline": ts},
        {"unparseable": True},
    ]
    events = nf._parse(raw)
    assert len(events) == 1
