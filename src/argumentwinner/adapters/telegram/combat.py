"""Auto-combat for Telegram: same guard order and drop-not-queue semantics as
the Discord adapter, with outbound IO injected so everything here tests with
stubs and no telegram import.

Guard order (mirrors adapters/discord/combat.py):
 1. ignore self / proxy authors (sender_chat, via_bot) / bots unless opted in
 2. engage iff deliberately @mentioned OR active session and author registered
 3. replied-to LRU — keyed (channel_id, message_id): Telegram message ids are
    per-chat counters, so bare ids would collide across chats
 4. cooldown + reply cap — events DISCARDED, never queued
 5. synchronous per-ref busy set — fail-fast drop
 6. debounce: rapid consecutive opponent messages collapse into one reply
 7. typing indicator while generating
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from argumentwinner.adapters.common import should_engage
from argumentwinner.core.models import ArgumentSession, ConversationRef, Participant, Persona
from argumentwinner.core.ports import StructuredOutputError

from . import translate
from .cache import CachedMessage, ChatCache

if TYPE_CHECKING:
    from argumentwinner.container import App

log = logging.getLogger(__name__)

_REPLIED_LRU_SIZE = 1024

# Injected by bot.py: sends chunks as a reply into the ref (recording the sent
# text into the cache) and returns the sent message id, or None on failure.
ReplySender = Callable[[ConversationRef, CachedMessage, str], Awaitable[str | None]]
TypingFn = Callable[[ConversationRef], Awaitable[None]]


def is_deliberate_mention(text: str | None, bot_username: str) -> bool:
    """A typed @username in the text/caption. Replying to a bot message
    carries no '@' in the text, so it is naturally NOT a mention (the Telegram
    twin of the Discord reply-ping rule). Word-boundary so @argubot does not
    match @argubotfan; case-insensitive because Telegram usernames are."""
    if not text or not bot_username:
        return False
    return re.search(rf"@{re.escape(bot_username)}\b", text, re.IGNORECASE) is not None


class CombatManager:
    def __init__(
        self,
        app: App,
        cache: ChatCache,
        *,
        bot_id: str,
        bot_participant: Participant,
        send_reply: ReplySender,
        notify_typing: TypingFn,
    ) -> None:
        self.app = app
        self.settings = app.settings
        self.cache = cache
        self.bot_id = bot_id
        self.bot_participant = bot_participant
        self._send_reply = send_reply
        self._notify_typing = notify_typing
        self._busy: set[ConversationRef] = set()
        self._replied: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._debounce: dict[ConversationRef, asyncio.Task] = {}

    # ─── commands (bot.py calls these from its handlers) ──────────────────────

    async def start(
        self, ref: ConversationRef, *, persona: Persona | None, opponent_id: str | None
    ) -> str:
        session = ArgumentSession(
            ref=ref,
            opponent_ids={opponent_id} if opponent_id else set(),
            persona=persona or Persona.AUTO,
            persona_forced=persona is not None,
        )
        await self.app.store.save(session)
        who = "that user" if opponent_id else "anyone who @mentions me"
        return f"⚔️ Combat mode ON — arguing with {who}. /combat_stop to end it."

    async def stop(self, ref: ConversationRef) -> str:
        await self.app.store.delete(ref)
        return "🕊️ Combat mode OFF."

    # ─── message flow ──────────────────────────────────────────────────────────

    async def on_message(
        self,
        ref: ConversationRef,
        record: CachedMessage,
        *,
        mentions_bot: bool,
        is_proxy: bool,
    ) -> None:
        session = await self.app.store.get(ref)
        if not should_engage(
            author_id=record.author.id,
            author_is_bot=record.author.is_bot,
            is_webhook=is_proxy,
            bot_id=self.bot_id,
            mentions_bot=mentions_bot,
            session=session,
            reply_to_bots=self.settings.aw_reply_to_bots,
        ):
            return
        if (ref.channel_id, record.message_id) in self._replied:
            return

        if mentions_bot:
            # A fresh mention creates/refreshes the session, recruits the
            # author as an opponent, and resets the reply cap.
            if session is None:
                session = ArgumentSession(ref=ref)
            session.opponent_ids.add(record.author.id)
            session.replies_sent = 0
            await self.app.store.save(session)

        pending = self._debounce.pop(ref, None)
        if pending is not None:
            pending.cancel()
        self._debounce[ref] = asyncio.create_task(self._debounced(ref, record))

    async def _debounced(self, ref: ConversationRef, record: CachedMessage) -> None:
        try:
            await asyncio.sleep(self.settings.aw_combat_debounce_seconds)
        except asyncio.CancelledError:
            return
        self._debounce.pop(ref, None)
        try:
            await self.process(ref, record)
        except Exception:  # noqa: BLE001 — a failed reply must not kill the task
            log.exception("combat reply failed for %s", ref)

    async def process(self, ref: ConversationRef, record: CachedMessage) -> None:
        # Fail-fast drop: no await between check and add.
        if ref in self._busy:
            return
        self._busy.add(ref)
        try:
            session = await self.app.store.get(ref)
            if session is None:  # /combat_stop landed mid-debounce
                return
            now = datetime.now(UTC)
            if (
                session.last_reply_at is not None
                and (now - session.last_reply_at).total_seconds()
                < self.settings.aw_combat_cooldown_seconds
            ):
                return  # drop, never queue
            if session.replies_sent >= self.settings.aw_combat_max_replies:
                return
            if (ref.channel_id, record.message_id) in self._replied:
                return

            ctx = translate.build_context(
                ref,
                self.cache.get(ref),
                record,
                bot_id=self.bot_id,
                beneficiary=self.bot_participant,
                forced_persona=session.persona if session.persona_forced else None,
                extra_opponent_ids=frozenset(session.opponent_ids),
                voice=None,  # combat speaks as the bot (engine also guards this)
            )
            await self._notify_typing(ref)
            try:
                candidate = await self.app.engine.combat_reply(ctx, session)
            except StructuredOutputError:
                log.warning("combat generation failed for %s", ref)
                return

            sent_id = await self._send_reply(ref, record, candidate.text)
            if sent_id is None:
                return
            # Long polling never echoes the bot's own messages back — record
            # the reply here or our_recent_lines starves. (bot.py's sender
            # also records; same id → idempotent replace.)
            self.cache.record(
                ref,
                CachedMessage(
                    message_id=sent_id,
                    author=self.bot_participant,
                    content=candidate.text,
                    timestamp=datetime.now(UTC),
                    reply_to_id=record.message_id,
                ),
            )
            self._mark_replied(ref, record.message_id)
            # Re-fetch before saving: /combat_stop mid-generation must not be
            # resurrected, and a /combat_start that replaced the config wins.
            current = await self.app.store.get(ref)
            if current is None:
                return
            current.replies_sent += 1
            current.last_reply_at = datetime.now(UTC)
            await self.app.store.save(current)
        finally:
            self._busy.discard(ref)

    def _mark_replied(self, ref: ConversationRef, message_id: str) -> None:
        self._replied[(ref.channel_id, message_id)] = None
        while len(self._replied) > _REPLIED_LRU_SIZE:
            self._replied.popitem(last=False)
