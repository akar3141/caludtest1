"""USD High-Impact news filter (ForexFactory weekly calendar).

Editorial content only — it does NOT gate whether a report is sent.
Gold, Dow and Bitcoin daily reports are sent every day without
exception; this module only determines whether that day's report
includes a "today's high-impact USD news" section with AI analysis of
it. Bitcoin still never calls this module (its reports never mention
USD news), but that's an editorial choice, not an execution dependency.

IMPORTANT — production risk this module cannot fully eliminate:
`nodedata.forexfactory.com/forex-calendar/weekly.json` is an undocumented,
unofficial endpoint. Its exact field names/shapes are not guaranteed and
can change without notice. Two defenses are built in:

  1. The parser accepts several plausible key-name variants for each
     field (see `_first_present`) instead of a single hardcoded name.
  2. Schema-drift detection: if the endpoint returns a non-empty payload
     but *every single item* fails to parse, that's a strong signal the
     schema changed — not "no news this week" — so we raise NewsFetchError
     instead of silently returning an empty list. Since this no longer
     gates report delivery, a schema-drift failure can no longer silence
     Gold/Dow reports — worst case is a report goes out without its news
     section, which is why it's still worth fixing (see README) but no
     longer a "reports stop forever" risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from .exceptions import NewsFetchError
from .logger import get_logger
from .retry import retry_sync
from .time_manager import NY_TZ, TimeManager

logger = get_logger(__name__)

# Matched as a case-insensitive substring against the impact field, since
# the real endpoint may return "High", "high", or a descriptive label like
# "High Impact Expected" rather than a clean enum value.
HIGH_IMPACT_MARKER = "high"

# Plausible key-name variants per field, most-likely-first. Defends against
# minor schema drift without needing a code change for every rename.
DATE_KEYS = ("dateline", "date", "timestamp", "time")
TITLE_KEYS = ("title", "name", "event")
COUNTRY_KEYS = ("country", "currency", "code")
IMPACT_KEYS = ("impact", "impact_title", "impactTitle", "impact_class")


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


@dataclass(frozen=True)
class NewsEvent:
    title: str
    country: str
    impact: str
    when: datetime  # tz-aware, UTC

    @property
    def is_high_impact_usd(self) -> bool:
        return self.country.upper() == "USD" and HIGH_IMPACT_MARKER in self.impact.lower()


class NewsFilter:
    """Fetches the weekly calendar once per run and answers filter queries against it."""

    def __init__(self, calendar_url: str, time_manager: TimeManager) -> None:
        self._url = calendar_url
        self._tm = time_manager
        self._events: list[NewsEvent] | None = None

    @retry_sync(exceptions=(httpx.HTTPError, ValueError), attempts=3)
    def _fetch_raw(self) -> list[dict[str, Any]]:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(
                self._url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; market-report-bot/1.0; "
                        "+https://github.com/) "
                    ),
                    "Accept": "application/json",
                    "Referer": "https://www.forexfactory.com/calendar",
                },
            )
            resp.raise_for_status()
            data = resp.json()  # raises ValueError/json.JSONDecodeError on non-JSON body
            if not isinstance(data, list):
                raise NewsFetchError(
                    f"Unexpected calendar payload shape: expected a list, got {type(data).__name__}"
                )
            return data

    def _parse_one(self, item: dict[str, Any]) -> NewsEvent | None:
        raw_when = _first_present(item, DATE_KEYS)
        if raw_when is None:
            return None

        if isinstance(raw_when, (int, float)):
            when = datetime.fromtimestamp(int(raw_when), tz=self._tm.now_utc().tzinfo)
        else:
            text = str(raw_when).strip()
            if text.isdigit():
                when = datetime.fromtimestamp(int(text), tz=self._tm.now_utc().tzinfo)
            else:
                when = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=self._tm.now_utc().tzinfo)

        return NewsEvent(
            title=str(_first_present(item, TITLE_KEYS) or "").strip(),
            country=str(_first_present(item, COUNTRY_KEYS) or "").strip(),
            impact=str(_first_present(item, IMPACT_KEYS) or "").strip(),
            when=when,
        )

    def _parse(self, raw: list[dict[str, Any]]) -> list[NewsEvent]:
        events: list[NewsEvent] = []
        failures = 0
        sample_keys: set[str] = set()
        for item in raw:
            try:
                if isinstance(item, dict):
                    sample_keys.update(item.keys())
                event = self._parse_one(item)
                if event is not None:
                    events.append(event)
                else:
                    failures += 1
            except (ValueError, TypeError, KeyError) as exc:
                failures += 1
                logger.debug("Skipping malformed news item %r: %s", item, exc)

        if raw and not events:
            # Schema-drift safety net — see module docstring.
            raise NewsFetchError(
                f"Parsed 0 usable events out of {len(raw)} raw items; the ForexFactory "
                f"calendar schema may have changed. Observed keys in payload: "
                f"{sorted(sample_keys)}. Update news_filter.py's key-name lists."
            )
        if failures:
            logger.warning(
                "%d of %d news items could not be parsed and were skipped.",
                failures, len(raw),
            )
        return events

    def load(self) -> None:
        if self._events is not None:
            return
        try:
            raw = self._fetch_raw()
        except httpx.HTTPError as exc:
            raise NewsFetchError(f"Failed to fetch news calendar: {exc}") from exc
        self._events = self._parse(raw)
        logger.info("Loaded %d news events (weekly calendar).", len(self._events))

    def today_high_impact_usd_events(self, today: date | None = None) -> list[NewsEvent]:
        """Returns today's (NY calendar day) high-impact USD news events, if any.

        Used purely as editorial content for the daily report — an empty
        list means "no red-folder USD news today", in which case the
        report is still sent, just without a news-analysis section.
        Deliberately uses America/New_York's date, not UTC's — Gold/Dow
        daily reports run right before NY open and the news that matters
        for that session is defined by the NY calendar day.
        """
        self.load()
        assert self._events is not None
        today = today or self._tm.now_ny().date()
        matches = [
            e for e in self._events
            if e.is_high_impact_usd and e.when.astimezone(NY_TZ).date() == today
        ]
        if matches:
            logger.info("Found %d high-impact USD event(s) today.", len(matches))
        else:
            logger.info("No high-impact USD news today.")
        return sorted(matches, key=lambda e: e.when)

    def has_high_impact_usd_today(self, today: date | None = None) -> bool:
        """Convenience boolean wrapper around `today_high_impact_usd_events`."""
        return bool(self.today_high_impact_usd_events(today))

    def important_events_this_week(self) -> list[NewsEvent]:
        self.load()
        assert self._events is not None
        events = [e for e in self._events if e.is_high_impact_usd]
        return sorted(events, key=lambda e: e.when)


def get_news_filter(calendar_url: str, time_manager: TimeManager) -> NewsFilter:
    return NewsFilter(calendar_url, time_manager)
