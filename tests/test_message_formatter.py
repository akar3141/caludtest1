from __future__ import annotations

from bot.message_formatter import (
    TELEGRAM_CAPTION_LIMIT,
    chunk_message,
    escape_mdv2,
    fits_caption,
)


def test_escape_mdv2_escapes_all_special_chars() -> None:
    raw = "Price: 2,000.50 (up!) [confirmed] -> #trend"
    escaped = escape_mdv2(raw)
    for ch in "_*[]()~`>#+-=|{}.!":
        if ch in raw:
            assert f"\\{ch}" in escaped


def test_fits_caption_respects_safety_margin() -> None:
    short_text = "x" * 500
    long_text = "x" * (TELEGRAM_CAPTION_LIMIT + 10)
    assert fits_caption(short_text)
    assert not fits_caption(long_text)


def test_chunk_message_splits_long_text_on_line_boundaries() -> None:
    lines = [f"line {i}" for i in range(2000)]
    text = "\n".join(lines)
    chunks = chunk_message(text, limit=200)

    assert len(chunks) > 1
    # No chunk should exceed the requested limit (minus internal safety margin).
    assert all(len(c) <= 200 for c in chunks)
    # Reassembling should reproduce all original lines, in order.
    reassembled = "\n".join(chunks).split("\n")
    assert reassembled == lines


def test_chunk_message_single_chunk_when_short() -> None:
    text = "short message"
    assert chunk_message(text) == [text]
