"""Lightweight JSON-file idempotency guard.

Prevents sending the same report twice (e.g. if a workflow's tolerance
window overlaps two runs). Primary defense against duplicates is the
narrow `is_due()` tolerance window in TimeManager; this store is a
cheap, dependency-free second layer.

Note: GitHub Actions runners are ephemeral, so this file does not persist
across runs unless the workflow explicitly restores/commits it (see
README "Persisting state across runs"). That's an acceptable trade-off
here because each job's cron fires at most once (or twice, for the
EST/EDT pair, of which only one passes the tolerance check) per day —
so the realistic duplicate risk without persistence is already very low.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .logger import get_logger

logger = get_logger(__name__)


class StateStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read state file (%s); starting fresh.", exc)
            return {}

    def _save(self) -> None:
        try:
            tmp_path = self._path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.warning("Could not persist state file: %s", exc)

    def is_done(self, job_id: str) -> bool:
        return self._data.get(job_id) is not None

    def mark_done(self, job_id: str, marker: str) -> None:
        self._data[job_id] = marker
        self._save()


def get_state_store(path: str) -> StateStore:
    return StateStore(path)
