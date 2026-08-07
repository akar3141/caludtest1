"""Renders professional dark-theme price charts as in-memory PNGs.

Returns raw bytes (BytesIO) rather than writing to disk — the caller
(telegram_sender) streams it straight into `send_photo`, so no temp
files need to be created or cleaned up.
"""

from __future__ import annotations

from io import BytesIO

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")  # headless rendering for CI

from .exceptions import ChartGenerationError
from .logger import get_logger

logger = get_logger(__name__)

BG_COLOR = "#0d1117"
GRID_COLOR = "#30363d"
LINE_COLOR = "#58a6ff"
UP_COLOR = "#3fb950"
DOWN_COLOR = "#f85149"
TEXT_COLOR = "#c9d1d9"


def build_price_chart(df: pd.DataFrame, title: str, subtitle: str = "") -> BytesIO:
    try:
        fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)

        closes = df["Close"].astype(float)
        opens = df["Open"].astype(float)
        overall_up = closes.iloc[-1] >= opens.iloc[0]
        line_color = UP_COLOR if overall_up else DOWN_COLOR

        ax.plot(df.index, closes, color=line_color, linewidth=1.4)
        ax.fill_between(df.index, closes, closes.min(), color=line_color, alpha=0.08)

        ax.set_title(title, color=TEXT_COLOR, fontsize=14, fontweight="bold", pad=14)
        if subtitle:
            ax.text(
                0.5, 1.02, subtitle, transform=ax.transAxes,
                ha="center", color=TEXT_COLOR, fontsize=9, alpha=0.75,
            )

        ax.grid(True, color=GRID_COLOR, linewidth=0.6, alpha=0.6)
        ax.tick_params(colors=TEXT_COLOR, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(GRID_COLOR)

        fig.autofmt_xdate(rotation=25)
        fig.tight_layout()

        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as exc:  # noqa: BLE001
        raise ChartGenerationError(f"Failed to render chart: {exc}") from exc
