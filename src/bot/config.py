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
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(..., alias="TELEGRAM_CHAT_ID")
    gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")
    gemini_model: str | None = Field(default=None, alias="GEMINI_MODEL")

    news_calendar_url: str = Field(
        default="https://nodedata.forexfactory.com/forex-calendar/weekly.json",
        alias="NEWS_CALENDAR_URL",
    )
    schedule_tolerance_minutes: int = Field(default=7, alias="SCHEDULE_TOLERANCE_MINUTES")
    catch_up_minutes: int = Field(default=20, alias="CATCH_UP_MINUTES")
    yfinance_interval: str = Field(default="1m", alias="YFINANCE_INTERVAL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    state_file_path: str = Field(default="data/state.json", alias="STATE_FILE_PATH")

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

    def gemini_model_chain(self) -> list[str]:
        chain = ([self.gemini_model] if self.gemini_model else []) + DEFAULT_GEMINI_MODEL_CHAIN
        seen: set[str] = set()
        ordered: list[str] = []
        for m in chain:
            if m not in seen:
                seen.add(m)
                ordered.append(m)
        return ordered


def load_settings() -> Settings:
    from pydantic import ValidationError
    from .exceptions import ConfigError

    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(f"Invalid or missing configuration: {exc}") from exc
