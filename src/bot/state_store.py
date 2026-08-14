"""Persistent JSON-file idempotency guard."""

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

        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:

        if not self._path.exists():
            return {}

        try:

            raw = self._path.read_text(
                encoding="utf-8"
            )

            data = json.loads(raw)

            if not isinstance(data, dict):
                logger.warning(
                    "State file does not contain a JSON object. "
                    "Starting with empty state."
                )

                return {}

            return data

        except (
            json.JSONDecodeError,
            OSError,
        ) as exc:

            logger.warning(
                "Could not read state file (%s); "
                "starting fresh.",
                exc,
            )

            return {}

    def _save(self) -> None:

        tmp_path = self._path.with_suffix(
            self._path.suffix + ".tmp"
        )

        try:

            payload = json.dumps(
                self._data,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )

            tmp_path.write_text(
                payload,
                encoding="utf-8",
            )

            # Atomic replacement.
            os.replace(
                tmp_path,
                self._path,
            )

        except OSError as exc:

            logger.error(
                "Could not persist state file: %s",
                exc,
            )

            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

            raise

    def is_done(
        self,
        job_id: str,
    ) -> bool:

        return self._data.get(job_id) is not None

    def mark_done(
        self,
        job_id: str,
        marker: str,
    ) -> None:

        self._data[job_id] = marker

        self._save()

    def get(
        self,
        job_id: str,
    ) -> Any:

        return self._data.get(job_id)

    def all(self) -> dict[str, Any]:

        return dict(self._data)


def get_state_store(
    path: str,
) -> StateStore:

    return StateStore(path)
