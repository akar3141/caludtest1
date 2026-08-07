"""AI-generated narrative summaries via Gemini (google-genai SDK).

Reads the model name from the GEMINI_MODEL environment variable
(preferring "gemini-3.1-pro-preview" when available). Since preview
models can be pulled or renamed without notice, this module tries a
configurable fallback chain rather than failing the whole report if the
preferred model is temporarily unavailable.

Only receives pre-computed, processed statistics (never raw OHLCV) —
Gemini interprets numbers the analytics layer already produced, so the
narrative is grounded in a fixed, auditable set of facts.
"""

from __future__ import annotations

import time

from google import genai

from .exceptions import AIGenerationError
from .logger import get_logger
from .statistical_analyzer import DailyStats, WeeklyStats

logger = get_logger(__name__)

# Short, same-model retries before falling through to the next model in the
# chain. Without this, a single transient network blip on the *preferred*
# model burns it for the whole run and silently downgrades every report to
# a fallback model — which defeats the purpose of preferring it in the
# first place. The google-genai SDK's exception hierarchy for transient vs.
# terminal (e.g. "model not found") errors isn't reliably distinguishable
# from here, so this stays a short, cheap retry rather than a long one.
SAME_MODEL_RETRY_ATTEMPTS = 2
SAME_MODEL_RETRY_DELAY_SECONDS = 2.0

DAILY_PROMPT_TEMPLATE = """You are a professional market analyst writing a concise daily briefing.

Asset: {asset_name}
Date (Asia/Tehran): {date_str}

Session statistics:
{session_lines}

Daily OHLCV:
- Open: {open:.2f}
- High: {high:.2f}
- Low: {low:.2f}
- Close: {close:.2f}
- Volume: {volume:,.0f}

News context: {news_context}

Write a 3-4 sentence professional summary in English covering price action,
which session drove the move, and the overall tone for the day. No
disclaimers, no headers, plain prose only.
"""

WEEKLY_PROMPT_TEMPLATE = """You are a professional market analyst writing a concise weekly report.

Asset: {asset_name}
Week ending (Asia/Tehran): {date_str}

Weekly statistics:
- Open: {week_open:.2f}
- High: {week_high:.2f}
- Low: {week_low:.2f}
- Close: {week_close:.2f}
- Weekly range: {weekly_range:.2f}
- Volatility (stddev of 1m log returns): {volatility_pct:.4f}%
- Average daily range: {average_daily_range:.2f}
- Strongest day: {strongest_day_date} (close-open change)
- Weakest day: {weakest_day_date} (close-open change)
- Highest volume day: {highest_volume_day_date}
- Most active hour (UTC): {most_active_hour_utc}:00
- Trend: {trend_summary}

Important USD news this week: {news_context}

Write a 5-6 sentence professional weekly briefing in English summarizing
the price action, volatility, the trend, and what to watch next week. No
disclaimers, no headers, plain prose only.
"""


class GeminiAnalyst:
    def __init__(self, api_key: str, model_chain: list[str]) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_chain = model_chain

    def _generate_with_model(self, model_name: str, prompt: str) -> str:
        """Tries a single model, with a couple of short retries for transient errors."""
        last_error: Exception | None = None
        for attempt in range(1, SAME_MODEL_RETRY_ATTEMPTS + 1):
            try:
                response = self._client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                text = (response.text or "").strip()
                if text:
                    return text
                raise AIGenerationError(f"Empty response from model {model_name}")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < SAME_MODEL_RETRY_ATTEMPTS:
                    logger.warning(
                        "Gemini model %s failed (attempt %d/%d): %s — retrying shortly.",
                        model_name, attempt, SAME_MODEL_RETRY_ATTEMPTS, exc,
                    )
                    time.sleep(SAME_MODEL_RETRY_DELAY_SECONDS)
        assert last_error is not None
        raise last_error

    def _generate(self, prompt: str) -> str:
        last_error: Exception | None = None
        for model_name in self._model_chain:
            try:
                logger.info("Requesting Gemini summary using model=%s", model_name)
                return self._generate_with_model(model_name, prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini model %s exhausted its retries: %s", model_name, exc)
                last_error = exc
                continue
        raise AIGenerationError(
            f"All Gemini models in the fallback chain failed. Last error: {last_error}"
        )

    def summarize_daily(
        self,
        asset_name: str,
        date_str: str,
        stats: DailyStats,
        news_context: str,
    ) -> str:
        session_lines = "\n".join(
            f"- {s.name}: high={s.high}, low={s.low}, volume={s.volume}" for s in stats.sessions
        )
        prompt = DAILY_PROMPT_TEMPLATE.format(
            asset_name=asset_name,
            date_str=date_str,
            session_lines=session_lines,
            open=stats.open,
            high=stats.high,
            low=stats.low,
            close=stats.close,
            volume=stats.volume,
            news_context=news_context,
        )
        return self._generate(prompt)

    def summarize_weekly(
        self,
        asset_name: str,
        date_str: str,
        stats: WeeklyStats,
        news_context: str,
    ) -> str:
        prompt = WEEKLY_PROMPT_TEMPLATE.format(
            asset_name=asset_name,
            date_str=date_str,
            week_open=stats.week_open,
            week_high=stats.week_high,
            week_low=stats.week_low,
            week_close=stats.week_close,
            weekly_range=stats.weekly_range,
            volatility_pct=stats.volatility_pct,
            average_daily_range=stats.average_daily_range,
            strongest_day_date=stats.strongest_day.date,
            weakest_day_date=stats.weakest_day.date,
            highest_volume_day_date=stats.highest_volume_day.date,
            most_active_hour_utc=stats.most_active_hour_utc,
            trend_summary=stats.trend_summary,
            news_context=news_context,
        )
        return self._generate(prompt)


def get_gemini_analyst(api_key: str, model_chain: list[str]) -> GeminiAnalyst:
    return GeminiAnalyst(api_key=api_key, model_chain=model_chain)
