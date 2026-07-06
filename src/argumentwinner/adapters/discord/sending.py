"""Outbound message shaping: pure, unit-tested. Discord hard-caps messages at
2000 characters."""

from __future__ import annotations

from typing import Any

import discord

DISCORD_LIMIT = 2000
_BOUNDARIES = (". ", "! ", "? ", "\n")


def _cut(text: str, limit: int) -> tuple[str, int]:
    """Return (chunk, consumed) where `consumed` is the number of ORIGINAL
    characters the chunk covers — the '…' continuation marker is display-only
    and never counts as consumed input, so splitting loses nothing."""
    if len(text) <= limit:
        return text, len(text)
    window = text[:limit]
    best = max(window.rfind(b) + len(b.rstrip()) for b in _BOUNDARIES)
    if best > limit // 4:
        return window[:best].rstrip(), best
    space = window.rfind(" ")
    if space > limit // 4:
        return window[:space].rstrip() + "…", space
    return window[: limit - 1].rstrip() + "…", limit - 1


def truncate_at_boundary(text: str, limit: int = DISCORD_LIMIT) -> str:
    """Hard backstop: cut at the last sentence boundary under the limit,
    falling back to a word boundary, then a plain slice."""
    return _cut(text, limit)[0]


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Chunk genuinely long content at sentence boundaries; each chunk fits
    and no original characters are lost across chunks."""
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        chunk, consumed = _cut(remaining, limit)
        chunks.append(chunk)
        remaining = remaining[consumed:].lstrip()
    return chunks


async def send_reply(target_message: Any, text: str) -> None:
    """Reply to the target with the first chunk; overflow goes as follow-up
    sends in the same channel. If the target was deleted mid-generation, fall
    back to a plain channel send instead of dropping the reply."""
    chunks = split_message(text)
    if not chunks:
        return
    try:
        await target_message.reply(chunks[0])
    except discord.HTTPException:
        await target_message.channel.send(chunks[0])
    for chunk in chunks[1:]:
        await target_message.channel.send(chunk)
