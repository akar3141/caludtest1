"""Gemini AI Analyst module for generating structured Persian market reports."""

from __future__ import annotations

import google.generativeai as genai
from google.generativeai.types import RequestOptions

from .logger import get_logger

logger = get_logger(__name__)


SYSTEM_INSTRUCTION = """
شما یک تحلیل‌گر و معامله‌گر حرفه‌ای و فوق‌العاده باسابقه در بازار Forex و پرایس اکشن هستید.
وظیفه شما ارائه تحلیل‌های دقیق، علمی و پرایس‌اکشنی برای معامله‌گران قبل از اوپن نیویورک است.

قوانین سخت‌گیرانه:
1. تمام پاسخ‌ها باید کاملاً به زبان فارسی روان و تخصصی باشد.
2. از ایموجی‌ها و آیکون‌ها به تعداد بسیار محدود استفاده کنید تا متن حالت علمی و رسمی داشته باشد.
3. از هرگونه ارائه سیگنال مستقیم (نظیر Buy/Sell یا نقطه ورود دقیق) خودداری کنید. تمرکز اصلی باید روی «سناریوهای آینده بازار»، «سطوح حمایت/مقاومت کلیدی» و «چشم‌انداز حرکت بعدی قیمت» باشد.
4. لحن گزارش باید کاملاً حرفه‌ای، تحلیلی و معطوف به آینده باشد.
"""


class GeminiAnalyst:
    def __init__(self, api_key: str, model_chain: list[str]) -> None:
        genai.configure(api_key=api_key)
        self._model_chain = model_chain

    def _generate_with_fallback(self, prompt: str) -> str:
        last_exception = None
        for model_name in self._model_chain:
            try:
                logger.info("Requesting Gemini summary using model=%s", model_name)
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=SYSTEM_INSTRUCTION,
                )
                response = model.generate_content(
                    prompt,
                    request_options=RequestOptions(timeout=30),
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as exc:
                logger.warning("Gemini generation failed with model %s: %s", model_name, exc)
                last_exception = exc

        raise RuntimeError(f"All Gemini models in chain failed. Last error: {last_exception}")

    def summarize_daily(
        self, asset_name: str, date_str: str, stats: dict, news_context: str
    ) -> str:
        prompt = f"""
تحلیل پرایس اکشن و پیش‌بینی آینده برای {asset_name} - تاریخ: {date_str}

آمارهای بازار:
- قیمت کلوز: {stats.get('close', 'N/A')}
- سقف (High): {stats.get('high', 'N/A')}
- کف (Low): {stats.get('low', 'N/A')}
- تغییرات: {stats.get('change', 'N/A')} ({stats.get('pct_change', 'N/A')}%)

وضعیت رویدادهای اقتصادی:
{news_context}

لطفاً تحلیلی شامل بخش‌های زیر ارائه دهید (با تعداد بسیار کم ایموجی):

1. بررسی ساختار حرکت اخیر: تحلیل کوتاه رفتار قیمت و ساختار بازار.
2. سناریوهای صعودی و نزولی آینده:
   - سناریوی صعودی: در صورت حفظ/شکست چه سطوحی پیشروی ادامه می‌یابد؟
   - سناریوی نزولی: در صورت از دست رفتن چه سطوحی احتمال اصلاح وجود دارد؟
3. سطوح کلیدی معامله: مهم‌ترین حمایت‌ها و مقاومت‌های پیش‌رو برای سیشن نیویورک.
4. جمع‌بندی تحلیلی: خلاصه‌ کوتاه از وضعیت کلی جهت تصمیم‌گیری معامله‌گران.

در انتهای متن حتماً دو عبارت زیر را قرار دهید:

این گزارش سیگنال معاملاتی نیست و صرفاً تحلیل علمی و آماری بر پایه تیک چارت است.

دریافت گزارشات روزانه و هفتگی قبل از اوپن نیویورک هر روز در کانال:
https://t.me/test5tts
"""
        return self._generate_with_fallback(prompt)

    def summarize_weekly(
        self, asset_name: str, date_str: str, stats: dict, news_context: str
    ) -> str:
        prompt = f"""
تحلیل ساختاری هفتگی و چشم‌انداز هفته آینده برای {asset_name} - تاریخ: {date_str}

آمار کندل هفتگی:
- کلوز هفته: {stats.get('close', 'N/A')}
- سقف هفته: {stats.get('high', 'N/A')}
- کف هفته: {stats.get('low', 'N/A')}
- تغییرات هفتگی: {stats.get('pct_change', 'N/A')}%

اخبار کلیدی هفته:
{news_context}

لطفاً یک گزارش جامع و علمی (با تعداد بسیار کم ایموجی) شامل موارد زیر بنویسید:
1. جمع‌بندی ساختار هفتگی: پیام اصلی کندل هفتگی.
2. چشم‌انداز و سناریوهای اصلی هفته آینده: احتمال ادامه روند یا اصلاح ساختاری.
3. زون‌های کلیدی (Key Zones): سطوح حمایت و مقاومت اصلی هفته.

در انتهای متن حتماً دو عبارت زیر را قرار دهید:

این گزارش سیگنال معاملاتی نیست و صرفاً تحلیل علمی و آماری بر پایه تیک چارت است.

دریافت گزارشات روزانه و هفتگی قبل از اوپن نیویورک هر روز در کانال:
https://t.me/test5tts
"""
        return self._generate_with_fallback(prompt)
