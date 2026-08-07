"""Gemini AI Analyst module for generating structured Persian market reports."""

from __future__ import annotations

from typing import List

import google.generativeai as genai
from google.generativeai.types import RequestOptions

from .logger import get_logger


logger = get_logger(__name__)


SYSTEM_INSTRUCTION = """
You are a professional financial market analyst specialized in Forex,
Gold Futures, Dow Jones, Bitcoin, and price action analysis.

Your job is to create short, high-quality, data-driven market reports
for traders before the New York session.

Strict rules:

- Output language must be Persian only.
- The report must be professional, clear, and suitable for Telegram.
- Never provide direct trading signals.
- Never say Buy, Sell, Enter, Exit, or give exact entry points.
- Do not predict with certainty.
- Analyze probabilities and possible market scenarios.
- Focus on:
  * Market Structure
  * Price Action
  * Trend condition
  * Volatility
  * Key Support and Resistance zones
  * Bullish and Bearish scenarios
  * Important risks

Formatting rules:

- Use simple Persian text.
- Avoid complex Markdown.
- Avoid tables.
- Avoid excessive emojis.
- Keep the report concise.
- Maximum length: 150 Persian words.
"""


class GeminiAnalyst:
    """
    Gemini based financial report generator.
    """

    def __init__(
        self,
        api_key: str,
        model_chain: List[str],
    ) -> None:

        if not api_key:
            raise ValueError("Gemini API key is missing")

        if not model_chain:
            raise ValueError("Gemini model chain is empty")

        genai.configure(api_key=api_key)

        self._model_chain = model_chain


    def _generate_with_fallback(
        self,
        prompt: str
    ) -> str:

        last_exception = None

        for model_name in self._model_chain:

            try:

                logger.info(
                    "Requesting Gemini model=%s",
                    model_name
                )


                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=SYSTEM_INSTRUCTION,
                )


                response = model.generate_content(
                    prompt,
                    request_options=RequestOptions(
                        timeout=30
                    ),
                )


                if response and response.text:
                    return response.text.strip()


            except Exception as exc:

                logger.warning(
                    "Gemini failed model=%s error=%s",
                    model_name,
                    exc
                )

                last_exception = exc


        raise RuntimeError(
            f"All Gemini models failed. Last error: {last_exception}"
        )



    def summarize_daily(
        self,
        asset_name: str,
        date_str: str,
        stats: dict,
        news_context: str,
    ) -> str:


        prompt = f"""

Create a daily market analysis report.

Asset:
{asset_name}

Date:
{date_str}


Market statistics:

Close:
{stats.get("close", "N/A")}

High:
{stats.get("high", "N/A")}

Low:
{stats.get("low", "N/A")}

Daily change:
{stats.get("pct_change", "N/A")}%


Important news context:

{news_context}


Write a Persian professional analysis.

Structure:

1. ساختار قیمت (Market Structure)

Explain recent price behavior,
trend condition, and market context.


2. سناریوهای احتمالی (Market Scenarios)

Explain:

- Bullish scenario:
Conditions that could support upward movement.

- Bearish scenario:
Conditions that could create downward pressure.


3. سطوح کلیدی (Key Levels)

Mention important support and resistance areas.


4. جمع‌بندی (Summary)

Give a short professional conclusion.


At the end write exactly:

این گزارش سیگنال معاملاتی نیست و صرفاً تحلیل علمی و آماری بر پایه داده‌های بازار است.

دریافت گزارشات روزانه و هفتگی قبل از اوپن نیویورک در کانال:
https://t.me/test5tts

"""


        return self._generate_with_fallback(prompt)



    def summarize_weekly(
        self,
        asset_name: str,
        date_str: str,
        stats: dict,
        news_context: str,
    ) -> str:


        prompt = f"""

Create a weekly market analysis report.

Asset:
{asset_name}

Date:
{date_str}


Weekly statistics:

Close:
{stats.get("close", "N/A")}

High:
{stats.get("high", "N/A")}

Low:
{stats.get("low", "N/A")}


News context:

{news_context}


Write a Persian professional weekly analysis.

Structure:

1. ساختار هفتگی بازار (Weekly Market Structure)

Analyze the weekly trend and price behavior.


2. سناریوهای هفته آینده (Next Week Scenarios)

Explain possible bullish and bearish scenarios.


3. مناطق مهم (Key Zones)

Mention important support and resistance zones.


4. جمع‌بندی کوتاه


At the end write exactly:

این گزارش سیگنال معاملاتی نیست و صرفاً تحلیل علمی و آماری بر پایه داده‌های بازار است.

دریافت گزارشات روزانه و هفتگی قبل از اوپن نیویورک در کانال:
https://t.me/test5tts

"""


        return self._generate_with_fallback(prompt)
