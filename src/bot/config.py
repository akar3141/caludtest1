"""Async Telegram delivery via python-telegram-bot.

Handles three real-world Telegram API constraints that the original
implementation missed:

1. Photo captions are capped at 1024 chars (vs. 4096 for text messages).
   Weekly reports routinely exceed this once news events + AI summary are
   included, so `send_report()` falls back to a short caption + a
   full-detail follow-up text message when needed.
2. `RetryAfter` (HTTP 429 flood control) carries the server-mandated wait
   time in `.retry_after` — retrying with a fixed/backoff delay instead of
   honoring that value just re-triggers the same rate limit.
3. `Bot` is used as an async context manager per the python-telegram-bot
   docs, so its underlying HTTPX client is properly initialized and torn
   down instead of relying on lazy/implicit initialization.
"""

from __future__ import annotations

import asyncio
from io import BytesIO

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.request import HTTPXRequest

from .exceptions import TelegramSendError
from .logger import get_logger
from .message_formatter import chunk_message, fits_caption
from .retry import retry_async

logger = get_logger(__name__)

MAX_RETRY_AFTER_WAITS = 2  # extra waits honored before giving up, on top of normal retries


class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=60.0,
            write_timeout=60.0
        )
        self._bot = Bot(token=bot_token, request=request)
        self._chat_id = chat_id

    async def _with_retry_after(self, coro_factory):
        """Runs an awaitable-producing callable, honoring Telegram's
        RetryAfter flood-control wait time before retrying."""
        for _ in range(MAX_RETRY_AFTER_WAITS + 1):
            try:
                return await coro_factory()
            except RetryAfter as exc:
                wait = float(exc.retry_after) + 0.5
                logger.warning("Telegram flood control: sleeping %.1fs before retry.", wait)
                await asyncio.sleep(wait)
        # Last attempt, let any exception propagate to the caller/decorator.
        return await coro_factory()

    @retry_async(exceptions=(TelegramError,), attempts=3)
    async def _send_photo(self, photo: BytesIO, caption: str) -> None:
        try:
            photo.seek(0)
            async with self._bot:
                await self._with_retry_after(
                    lambda: self._bot.send_photo(
                        chat_id=self._chat_id,
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        read_timeout=60,
                        write_timeout=60,
                    )
                )
            logger.info("Photo report sent to Telegram chat %s", self._chat_id)
        except TelegramError as exc:
            raise TelegramSendError(f"Failed to send Telegram photo: {exc}") from exc

    @retry_async(exceptions=(TelegramError,), attempts=3)
    async def send_text(self, text: str) -> None:
        try:
            async with self._bot:
                for chunk in chunk_message(text):
                    await self._with_retry_after(
                        lambda c=chunk: self._bot.send_message(
                            chat_id=self._chat_id, 
                            text=c, 
                            parse_mode=ParseMode.MARKDOWN_V2,
                            read_timeout=60,
                            write_timeout=60,
                        )
                    )
            logger.info("Text message sent to Telegram chat %s", self._chat_id)
        except TelegramError as exc:
            raise TelegramSendError(f"Failed to send Telegram message: {exc}") from exc

    async def send_report(self, photo: BytesIO, full_caption: str, short_caption: str) -> None:
        """Sends the chart with the full caption if it fits Telegram's 1024-char
        photo-caption limit; otherwise sends the chart with a short caption and
        the full report as a separate (possibly chunked) text message."""
        if fits_caption(full_caption):
            await self._send_photo(photo, full_caption)
        else:
            logger.info(
                "Caption (%d chars) exceeds Telegram's photo-caption limit; "
                "sending short caption + follow-up text message.",
                len(full_caption),
            )
            await self._send_photo(photo, short_caption)
            await self.send_text(full_caption)


def get_telegram_sender(bot_token: str, chat_id: str) -> TelegramSender:
    return TelegramSender(bot_token=bot_token, chat_id=chat_id)
