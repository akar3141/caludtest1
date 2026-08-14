"""yfinance wrapper for fetching OHLCV data.

Always uses interval="1m" per spec. Yahoo Finance limits 1-minute data to
roughly the trailing 7 days, which conveniently covers both the daily
session view and the full weekly-report lookback window.

Known production risk: Yahoo Finance has, at various times, rate-limited
or blocked requests from shared/datacenter IP ranges — which is exactly
what GitHub-hosted runners use. This shows up as empty DataFrames or
HTTP errors that look identical to a transient network blip. There is no
way to fully eliminate this risk from the client side; the mitigations
here are (1) a longer, more patient retry chain than other I/O in this
project, and (2) documentation in the README recommending a self-hosted
runner or a proxy if throttling becomes a persistent, not transient, problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from .exceptions import NoMarketDataError
from .logger import get_logger
from .retry import retry_sync

logger = get_logger(__name__)


@dataclass(frozen=True)
class MarketDataRequest:
    symbol: str
    interval: str = "1m"
    period: str | None = None  # e.g. "1d" — mutually exclusive with start/end
    start: datetime | None = None
    end: datetime | None = None


class MarketDataClient:
    # More attempts + longer backoff than other I/O in this project: Yahoo's
    # throttling is often transient (a few tens of seconds), and unlike
    # Telegram/Gemini there's no paid fallback provider configured, so it's
    # worth waiting longer before giving up on a report entirely.
    @retry_sync(exceptions=(Exception,), attempts=5, base_delay=3.0, max_delay=45.0)
    def fetch(self, request: MarketDataRequest) -> pd.DataFrame:
        logger.info(
            "Fetching %s data: period=%s start=%s end=%s interval=%s",
            request.symbol, request.period, request.start, request.end, request.interval,
        )
        kwargs: dict = {"interval": request.interval, "auto_adjust": False, "timeout": 30}
        if request.period is not None:
            kwargs["period"] = request.period
        else:
            kwargs["start"] = request.start
            kwargs["end"] = request.end

        df = yf.Ticker(request.symbol).history(**kwargs)
        if df is None or df.empty:
            raise NoMarketDataError(
                f"yfinance returned no data for {request.symbol} "
                f"(period={request.period}, start={request.start}, end={request.end}, "
                f"interval={request.interval})"
            )
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if df.empty:
            raise NoMarketDataError(f"All rows for {request.symbol} were NaN after cleaning.")
        return df

    def fetch_daily(self, symbol: str, interval: str = "1m") -> pd.DataFrame:
        # "1d" is well inside Yahoo's 1m-interval window and not near any
        # documented boundary, so the simple period keyword is fine here.
        return self.fetch(MarketDataRequest(symbol=symbol, period="1d", interval=interval))

    def fetch_weekly(self, symbol: str, interval: str = "1m") -> pd.DataFrame:
        """Fetches ~7 days of 1-minute data using explicit start/end.

        Yahoo Finance caps 1-minute granularity at 7 days of history. Using
        the `period="7d"` keyword sits exactly on that boundary and has
        been observed to intermittently raise "1m data not available for
        the requested range" depending on the exact current timestamp
        (e.g. mid-way through the 8th day in UTC vs. exchange time). Using
        an explicit start/end window that stays a safety margin *inside*
        the 7-day cap (6 days 22 hours) avoids that edge case entirely.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=6, hours=22)
        return self.fetch(
            MarketDataRequest(symbol=symbol, interval=interval, start=start, end=end)
        )


def get_market_data_client() -> MarketDataClient:
    return MarketDataClient()
