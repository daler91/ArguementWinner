"""Outbound message shaping for Discord (hard cap: 2000 characters).
The pure chunking logic lives in adapters/common.py, shared with Telegram."""

from __future__ import annotations

from typing import Any

import discord

from argumentwinner.adapters import common

DISCORD_LIMIT = 2000


def truncate_at_boundary(text: str, limit: int = DISCORD_LIMIT) -> str:
    return common.truncate_at_boundary(text, limit)


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    return common.split_message(text, limit)


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
