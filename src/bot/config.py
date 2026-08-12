"""Application configuration loaded from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AssetName = Literal["gold", "dow", "bitcoin"]
ReportMode = Literal["daily", "weekly"]


ASSET_SYMBOLS: dict[AssetName, str] = {
    "gold": "GC=F",
    "dow": "^DJI",
    "bitcoin": "BTC-USD",
}


ASSET_DISPLAY_NAMES: dict[AssetName, str] = {
    "gold": "Gold Futures (GC=F)",
    "dow": "Dow Jones (^DJI)",
    "bitcoin": "Bitcoin (BTC-USD)",
}


DEFAULT_GEMINI_MODEL_CHAIN = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemma-4-31b-it",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(..., alias="TELEGRAM_CHAT_ID")

    gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")
    gemini_model: str | None = Field(default=None, alias="GEMINI_MODEL")

    # Override this in GitHub Variables/Secrets if the provider changes.
    news_calendar_url: str = Field(
        default="https://nodedata.forexfactory.com/forex-calendar/weekly.json",
        alias="NEWS_CALENDAR_URL",
    )

    # The workflow fires at target, +15, +30 and +45 minutes.
    # Python remains the final authority on whether a report is due.
    schedule_tolerance_minutes: int = Field(
        default=7,
        alias="SCHEDULE_TOLERANCE_MINUTES",
    )
    catch_up_minutes: int = Field(
        default=45,
        alias="CATCH_UP_MINUTES",
    )

    yfinance_interval: str = Field(
        default="1m",
        alias="YFINANCE_INTERVAL",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Each workflow supplies its own state file.
    state_file_path: str = Field(
        default="data/state.json",
        alias="STATE_FILE_PATH",
    )

    @field_validator("telegram_bot_token", "gemini_api_key")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("news_calendar_url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("NEWS_CALENDAR_URL must use https://")
        return v

    @field_validator("schedule_tolerance_minutes", "catch_up_minutes")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    def gemini_model_chain(self) -> list[str]:
        """Return ordered Gemini model fallback chain."""
        chain = (
            [self.gemini_model] if self.gemini_model else []
        ) + DEFAULT_GEMINI_MODEL_CHAIN

        seen: set[str] = set()
        ordered: list[str] = []

        for model in chain:
            if model not in seen:
                seen.add(model)
                ordered.append(model)

        return ordered


def load_settings() -> Settings:
    """Load and validate settings."""
    from pydantic import ValidationError
    from .exceptions import ConfigError

    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        raise ConfigError(f"Invalid or missing configuration: {exc}") from exc
