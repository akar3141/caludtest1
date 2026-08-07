"""CLI entrypoint for Market Report Bot."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Literal

from .config import load_settings
from .exceptions import MarketReportError
from .gemini_analyst import get_gemini_analyst
from .jobs import is_job_due, run_daily_job, run_weekly_job
from .logger import get_logger
from .market_calendar import get_market_calendar
from .market_data import get_market_data_client
from .news_filter import get_news_filter
from .state_store import get_state_store
from .telegram_sender import get_telegram_sender
from .time_manager import get_time_manager

AssetName = Literal["gold", "dow", "bitcoin"]
ReportMode = Literal["daily", "weekly"]

logger = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market Report Bot")
    parser.add_argument("--asset", required=True, choices=["gold", "dow", "bitcoin"])
    parser.add_argument("--mode", required=True, choices=["daily", "weekly"])
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass time gates.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Telegram send.",
    )
    return parser.parse_args(argv)


async def _async_main(asset: AssetName, mode: ReportMode, force: bool, dry_run: bool) -> int:
    try:
        settings = load_settings()
    except MarketReportError as exc:
        logger.error("Configuration error: %s", exc)
        return 2

    os.environ["RUN_ID"] = f"{asset}-{mode}"

    tm = get_time_manager()
    calendar = get_market_calendar()

    if not force and not is_job_due(asset, mode, settings, tm, calendar):
        logger.info("Nothing to do for %s/%s at this time.", asset, mode)
        return 0

    news_filter = get_news_filter(settings.news_calendar_url, tm)
    market_data = get_market_data_client()
    analyst = get_gemini_analyst(settings.gemini_api_key, settings.gemini_model_chain())
    sender = get_telegram_sender(settings.telegram_bot_token, settings.telegram_chat_id)
    state = get_state_store(settings.state_file_path)

    try:
        if mode == "daily":
            await run_daily_job(
                asset, settings, tm, news_filter, market_data, analyst, sender, state,
                dry_run=dry_run,
            )
        else:
            await run_weekly_job(
                asset, settings, tm, news_filter, market_data, analyst, sender, state,
                dry_run=dry_run,
            )
    except MarketReportError as exc:
        logger.error("Job %s/%s failed: %s", asset, mode, exc)
        return 1

    logger.info("Job %s/%s completed successfully.", asset, mode)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args.asset, args.mode, args.force, args.dry_run))
    except Exception:  # noqa: BLE001
        logger.exception("Unhandled exception in main().")
        return 1


if __name__ == "__main__":
    sys.exit(main())
