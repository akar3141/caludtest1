"""CLI entrypoint.

Invoked by each GitHub Actions workflow as:

    python -m bot.main --asset gold --mode daily

Each (asset, mode) pair is its own workflow/cron trigger (per project
spec), but the *actual* decision of whether to run is still made inside
`jobs.is_job_due()` using DST-aware zoneinfo math — the cron schedule
only gets the process running near the right time; the code confirms
it's really due before doing any paid/rate-limited work (news, market
data, Gemini, Telegram).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import get_args

from .config import AssetName, ReportMode, load_settings
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

logger = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market Report Bot")
    parser.add_argument("--asset", required=True, choices=get_args(AssetName))
    parser.add_argument("--mode", required=True, choices=get_args(ReportMode))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the time/tolerance and trading-day gate. News is never a "
        "gate (it only affects report content) so this has no interaction "
        "with it. Useful for manual workflow_dispatch runs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline (data, analytics, Gemini, chart) but skip the "
        "Telegram send and the state-store write. Useful for local/manual testing "
        "without spamming the channel or consuming an idempotency slot.",
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
        # Last-resort safety net: any truly unexpected exception (e.g. a bug
        # in a third-party SDK we didn't anticipate) still gets logged
        # through our structured logger — with the run_id already set by
        # _async_main where possible — instead of dumping a bare Python
        # traceback into CI logs with no context. GitHub Actions still
        # marks the job as failed either way (exit code 1).
        logger.exception("Unhandled exception in main().")
        return 1


if __name__ == "__main__":
    sys.exit(main())
