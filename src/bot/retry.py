"""Shared retry-with-backoff decorators for sync and async I/O calls.

Kept dependency-free (no tenacity) to minimize the project's footprint —
this is simple enough to own directly and tune without fighting a
third-party API.
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from typing import Any, Callable, Tuple, Type, TypeVar

from .logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_sync(
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    attempts: int = 3,
    base_delay: float = 1.5,
    max_delay: float = 20.0,
) -> Callable[[F], F]:
    """Retries a synchronous function with exponential backoff + jitter."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == attempts:
                        break
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay += random.uniform(0, 0.5)
                    logger.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                        func.__qualname__, attempt, attempts, exc, delay,
                    )
                    time.sleep(delay)
            logger.error("%s failed after %d attempts", func.__qualname__, attempts)
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator


def retry_async(
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    attempts: int = 3,
    base_delay: float = 1.5,
    max_delay: float = 20.0,
) -> Callable[[F], F]:
    """Retries an async function with exponential backoff + jitter."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == attempts:
                        break
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay += random.uniform(0, 0.5)
                    logger.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                        func.__qualname__, attempt, attempts, exc, delay,
                    )
                    await asyncio.sleep(delay)
            logger.error("%s failed after %d attempts", func.__qualname__, attempts)
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
