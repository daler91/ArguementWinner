"""discord types ↔ core models: the only dual-world file in this adapter.

Functions are duck-typed over the attributes they use so the pure parts test
with plain stub objects — no live gateway needed.
"""

from __future__ import annotations

from typing import Any

from argumentwinner.core.models import (
    ArgumentContext,
    ArgumentTurn,
    ConversationRef,
    Participant,
    Persona,
    Role,
    VoiceProfile,
)

PLATFORM = "discord"


def annotate_content(message: Any) -> str:
    """Online arguments are rarely pure text: 'explain this, genius' + a
    screenshot must not reach the engine as an empty string."""
    content = (message.content or "").strip()
    if getattr(message, "attachments", None):
        content = (content + " [User attached an image/file]").strip()
    if getattr(message, "embeds", None):
        content = (content + " [User shared a link/card]").strip()
    if getattr(message, "stickers", None):
        content = (content + " [User sent a sticker]").strip()
    return content


def tag_role(
    author_id: str,
    author_is_bot: bool,
    *,
    bot_id: str,
    beneficiary_id: str,
    opponent_ids: frozenset[str],
) -> Role:
    if author_id == bot_id or author_id == beneficiary_id:
        return Role.US
    if author_id in opponent_ids:
        return Role.OPPONENT
    return Role.BYSTANDER


def to_participant(user: Any) -> Participant:
    return Participant(
        id=str(user.id),
        display_name=getattr(user, "display_name", None) or user.name,
        is_bot=bool(getattr(user, "bot", False)),
    )


def ref_for_channel(channel: Any) -> ConversationRef:
    """Threads and their parent channel are DIFFERENT arguments.

    Threads are detected via `parent_id` (always populated on discord.Thread),
    not the cache-dependent `.parent` property — a cache miss must not yield a
    different ref for the same thread."""
    guild = getattr(channel, "guild", None)
    parent_id = getattr(channel, "parent_id", None)
    if parent_id is not None:  # discord.Thread
        return ConversationRef(
            platform=PLATFORM,
            guild_id=str(guild.id) if guild else None,
            channel_id=str(parent_id),
            thread_id=str(channel.id),
        )
    return ConversationRef(
        platform=PLATFORM,
        guild_id=str(guild.id) if guild else None,
        channel_id=str(channel.id),
    )


def to_turn(
    message: Any,
    *,
    bot_id: str,
    beneficiary_id: str,
    opponent_ids: frozenset[str],
) -> ArgumentTurn | None:
    content = annotate_content(message)
    if not content:
        return None
    author = message.author
    return ArgumentTurn(
        role=tag_role(
            str(author.id),
            bool(getattr(author, "bot", False)),
            bot_id=bot_id,
            beneficiary_id=beneficiary_id,
            opponent_ids=opponent_ids,
        ),
        author=to_participant(author),
        content=content,
        message_id=str(message.id),
        timestamp=message.created_at,
    )


async def build_context(
    channel: Any,
    target_message: Any,
    *,
    bot_user: Any,
    beneficiary: Any,
    forced_persona: Persona | None = None,
    extra_opponent_ids: frozenset[str] = frozenset(),
    history_limit: int = 24,
    voice: VoiceProfile | None = None,
) -> ArgumentContext:
    """Fresh history fetch every invocation — the engine always argues against
    exactly what's still on screen (edits/deletes handled for free)."""
    bot_id = str(bot_user.id)
    beneficiary_id = str(beneficiary.id)
    opponent_ids = extra_opponent_ids | {str(target_message.author.id)}

    raw = [m async for m in channel.history(limit=history_limit)]
    raw.reverse()  # discord returns newest first; the engine wants oldest first
    if not any(m.id == target_message.id for m in raw):
        # A target absent from the window predates it — prepend, never append,
        # or the oldest message would masquerade as the newest turn.
        raw.insert(0, target_message)

    turns: list[ArgumentTurn] = []
    for m in raw:
        turn = to_turn(m, bot_id=bot_id, beneficiary_id=beneficiary_id, opponent_ids=opponent_ids)
        if turn is not None:
            turns.append(turn)

    target = to_turn(
        target_message, bot_id=bot_id, beneficiary_id=beneficiary_id, opponent_ids=opponent_ids
    )
    if target is None:
        raise ValueError("target message has no usable content")

    our_lines = tuple(t.content for t in turns if t.role is Role.US)[-8:]
    return ArgumentContext(
        ref=ref_for_channel(channel),
        target=target,
        transcript=tuple(turns),
        beneficiary=to_participant(beneficiary),
        forced_persona=forced_persona,
        our_recent_lines=our_lines,
        voice=voice,
    )
