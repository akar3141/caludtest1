"""Gemini AI Analyst module for generating structured Persian market reports."""

from __future__ import annotations

import google.generativeai as genai
from google.generativeai.types import RequestOptions

from .logger import get_logger

logger = get_logger(__name__)


SYSTEM_INSTRUCTION = """
شما یک تحلیل‌گر و معامله‌گر حرفه‌ای و فوق‌العاده باسابقه در بازار Forex و پرایس اکشن هستید.
وظیفه شما ارائه تحلیل‌های بسیار دقیق، علمی و پرایس‌اکشنی برای معامله‌گران قبل از اوپن نیویورک است.

قوانین سخت‌گیرانه:
1. تمام پاسخ‌ها باید کاملاً به زبان فارسی روان و تخصصی باشد.
2. از ایموجی‌ها و آیکون‌ها به تعداد بسیار محدود استفاده کنید.
3. از کاراکترهای خاص مارک‌داون پیچیده استفاده نکنید تا متن در تلگرام بدون خطا ارسال شود.
4. از هرگونه ارائه سیگنال مستقیم (نظیر Buy/Sell یا نقطه ورود دقیق) خودداری کنید. تمرکز اصلی باید روی «سناریوهای آینده بازار»، «سطوح حمایت/مقاومت کلیدی» و «چشم‌انداز حرکت بعدی قیمت» باشد.
5. متن تحلیل باید خلاصه، مفید و روان باشد.
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
- کلوز: {stats.get('close', 'N/A')}
- سقف: {stats.get('high', 'N/A')}
- کف: {stats.get('low', 'N/A')}
- تغییرات: {stats.get('pct_change', 'N/A')}%

وضعیت اخبار:
{news_context}

لطفاً تحلیلی خلاصه و روان در ۴ بخش زیر بنویسید (حداکثر ۱۵۰ کلمه):

۱. بررسی ساختار قیمت: تحلیل کوتاه رفتار اخیر.
۲. سناریوهای صعودی و نزولی آینده:
- سناریوی صعودی: در صورت حفظ سطوح حمایتی.
- سناریوی نزولی: در صورت از دست رفتن سطوح.
۳. سطوح کلیدی معامله: حمایت‌ها و مقاومت‌های مهم نیویورک.
۴. جمع‌بندی کوتاه.

در انتهای متن حتما دقیقاً دو خط زیر را بنویسید:

این گزارش سیگنال معاملاتی نیست و صرفاً تحلیل علمی و آماری بر پایه تیک چارت است.
دریافت گزارشات روزانه و هفتگی قبل اوپن نیویرک هروزه در کانال:
https://t.me/test5tts
"""
        return self._generate_with_fallback(prompt)

    def summarize_weekly(
        self, asset_name: str, date_str: str, stats: dict, news_context: str
    ) -> str:
        prompt = f"""
تحلیل هفتگی {asset_name} - تاریخ: {date_str}

آمارهای هفته:
- کلوز: {stats.get('close', 'N/A')}
- سقف: {stats.get('high', 'N/A')}
- کف: {stats.get('low', 'N/A')}

لطفاً گزارش هفتگی مختصر در ۳ بخش زیر بنویسید (حداکثر ۱۵۰ کلمه):
۱. جمع‌بندی ساختار هفتگی
۲. سناریوی هفته آینده
۳. زون‌های کلیدی حمایت و مقاومت

در انتهای متن حتما دقیقاً دو خط زیر را بنویسید:

این گزارش سیگنال معاملاتی نیست و صرفاً تحلیل علمی و آماری بر پایه تیک چارت است.
دریافت گزارشات روزانه و هفتگی قبل اوپن نیویرک هروزه در کانال:
https://t.me/test5tts
"""
        return self._generate_with_fallback(prompt)
