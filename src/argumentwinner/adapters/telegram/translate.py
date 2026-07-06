"""Telegram types ↔ core models. Duck-typed over python-telegram-bot objects
so the pure logic tests with plain stubs — this module never imports telegram.

Unlike Discord there is no history fetch: build_context is SYNCHRONOUS and
consumes records from the adapter-owned ChatCache.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from argumentwinner.adapters.common import tag_role
from argumentwinner.core.models import (
    ArgumentContext,
    ArgumentTurn,
    ConversationRef,
    Participant,
    Persona,
    Role,
    VoiceProfile,
)

from .cache import CachedMessage

PLATFORM = "telegram"
TELEGRAM_LIMIT = 4096  # telegram.constants.MessageLimit.MAX_TEXT_LENGTH


def annotate_content(message: Any) -> str:
    """Same never-empty guarantee as the Discord adapter: an image-only
    'explain this, genius' must not reach the engine as an empty string."""
    content = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    if (
        getattr(message, "photo", None)
        or getattr(message, "document", None)
        or getattr(message, "video", None)
    ):
        content = (content + " [User attached an image/file]").strip()
    if getattr(message, "sticker", None):
        content = (content + " [User sent a sticker]").strip()
    return content


def to_participant(user: Any) -> Participant:
    name = (
        getattr(user, "full_name", None)
        or getattr(user, "first_name", None)
        or getattr(user, "username", None)
        or str(user.id)
    )
    return Participant(
        id=str(user.id), display_name=name, is_bot=bool(getattr(user, "is_bot", False))
    )


def ref_for_message(message: Any) -> ConversationRef:
    """Forum topics are separate arguments (thread_id set). Plain reply-threads
    in supergroups also carry message_thread_id but are NOT topics and must not
    split the conversation — hence the is_topic_message gate."""
    thread_id = None
    if getattr(message, "is_topic_message", False) and getattr(message, "message_thread_id", None):
        thread_id = str(message.message_thread_id)
    return ConversationRef(
        platform=PLATFORM,
        guild_id=None,
        channel_id=str(message.chat.id),
        thread_id=thread_id,
    )


def to_cached(message: Any) -> CachedMessage | None:
    """None for messages the engine can't use: empty content after annotation,
    or authorless posts (channel posts have from_user=None)."""
    user = getattr(message, "from_user", None)
    if user is None:
        return None
    content = annotate_content(message)
    if not content:
        return None
    reply_to = getattr(message, "reply_to_message", None)
    return CachedMessage(
        message_id=str(message.message_id),
        author=to_participant(user),
        content=content,
        timestamp=message.date,
        reply_to_id=str(reply_to.message_id) if reply_to is not None else None,
    )


def to_turn(
    record: CachedMessage,
    *,
    bot_id: str,
    beneficiary_id: str,
    opponent_ids: frozenset[str],
) -> ArgumentTurn:
    return ArgumentTurn(
        role=tag_role(
            record.author.id,
            record.author.is_bot,
            bot_id=bot_id,
            beneficiary_id=beneficiary_id,
            opponent_ids=opponent_ids,
        ),
        author=record.author,
        content=record.content,
        message_id=record.message_id,
        timestamp=record.timestamp,
    )


def build_context(
    ref: ConversationRef,
    records: Sequence[CachedMessage],
    target: CachedMessage,
    *,
    bot_id: str,
    beneficiary: Participant,
    forced_persona: Persona | None = None,
    extra_opponent_ids: frozenset[str] = frozenset(),
    voice: VoiceProfile | None = None,
) -> ArgumentContext:
    opponent_ids = extra_opponent_ids | {target.author.id}
    ordered = list(records)
    if not any(r.message_id == target.message_id for r in ordered):
        # A target absent from the window predates it — prepend, never append,
        # or an old message would masquerade as the newest turn.
        ordered.insert(0, target)

    turns = tuple(
        to_turn(r, bot_id=bot_id, beneficiary_id=beneficiary.id, opponent_ids=opponent_ids)
        for r in ordered
    )
    target_turn = to_turn(
        target, bot_id=bot_id, beneficiary_id=beneficiary.id, opponent_ids=opponent_ids
    )
    our_lines = tuple(t.content for t in turns if t.role is Role.US)[-8:]
    return ArgumentContext(
        ref=ref,
        target=target_turn,
        transcript=turns,
        beneficiary=beneficiary,
        forced_persona=forced_persona,
        our_recent_lines=our_lines,
        voice=voice,
    )
