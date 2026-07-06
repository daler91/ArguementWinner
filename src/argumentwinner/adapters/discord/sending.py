"""Outbound message shaping: pure, unit-tested. Discord hard-caps messages at
2000 characters."""

from __future__ import annotations

from typing import Any

DISCORD_LIMIT = 2000
_BOUNDARIES = (". ", "! ", "? ", "\n")


def truncate_at_boundary(text: str, limit: int = DISCORD_LIMIT) -> str:
    """Hard backstop: cut at the last sentence boundary under the limit,
    falling back to a word boundary, then a plain slice."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    best = max(window.rfind(b) + len(b.rstrip()) for b in _BOUNDARIES)
    if best > limit // 4:
        return window[:best].rstrip()
    space = window.rfind(" ")
    if space > limit // 4:
        return window[:space].rstrip() + "…"
    return window[: limit - 1].rstrip() + "…"


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Chunk genuinely long content at sentence boundaries; each chunk fits."""
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        head = truncate_at_boundary(remaining, limit)
        chunks.append(head)
        remaining = remaining[len(head) :].lstrip("… ").lstrip()
        if not remaining:
            return chunks
    if remaining:
        chunks.append(remaining)
    return chunks


async def send_reply(target_message: Any, text: str) -> None:
    """Reply to the target with the first chunk; overflow goes as follow-up
    sends in the same channel."""
    chunks = split_message(text)
    if not chunks:
        return
    await target_message.reply(chunks[0])
    for chunk in chunks[1:]:
        await target_message.channel.send(chunk)
