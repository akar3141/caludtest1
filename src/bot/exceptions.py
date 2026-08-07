"""Domain-specific exceptions.

Using dedicated exception types (instead of bare Exception) lets main.py
and jobs.py handle failures precisely — e.g. a NoMarketDataError should
abort the current job, while a TelegramSendError might be worth a retry
at a higher level.
"""

from __future__ import annotations


class MarketReportError(Exception):
    """Base class for all application-specific errors."""


class ConfigError(MarketReportError):
    """Raised when required configuration is missing or invalid."""


class NoMarketDataError(MarketReportError):
    """Raised when yfinance returns empty or malformed data."""


class NewsFetchError(MarketReportError):
    """Raised when the ForexFactory calendar cannot be fetched or parsed."""


class AIGenerationError(MarketReportError):
    """Raised when the Gemini API fails to produce a summary."""


class TelegramSendError(MarketReportError):
    """Raised when a Telegram message/photo fails to send."""


class ChartGenerationError(MarketReportError):
    """Raised when matplotlib fails to render a chart."""
