"""Centralized logging configuration.

All modules call ``get_logger(__name__)`` instead of configuring logging
themselves, so log format/level stays consistent across the project and
can be changed in exactly one place.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


class _RunIdFilter(logging.Filter):
    """Injects the current RUN_ID (asset + mode + date) into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = os.environ.get("RUN_ID", "-")
        return True


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | run=%(run_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(_RunIdFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Returns a configured logger for the given module name."""
    _configure_root()
    return logging.getLogger(name)
