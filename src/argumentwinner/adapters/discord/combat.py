"""Auto-combat: the bot argues publicly on its own.

on_message guards, in strict order:
 1. ignore self / webhooks / bots (unless AW_REPLY_TO_BOTS)
 2. engage iff @mentioned OR active session and author in opponent_ids
 3. replied-to LRU message-id set — absolute double-reply guard
 4. cooldown + max-replies cap — events during cooldown are DISCARDED, never
    queued (resets on fresh mention)
 5. per-ref fail-fast busy guard: a synchronous set checked-and-set with no
    await in between (race-free on the event loop) — if the ref is already
    generating, the event is dropped outright. No queue means no burst-spam of
    stale replies; dropped messages aren't lost context, because the next
    engagement's fresh history fetch sees them anyway.
 6. debounce: rapid consecutive opponent messages collapse into one reply
 7. typing indicator while generating
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

from argumentwinner.core.models import ArgumentSession, ConversationRef, Persona
from argumentwinner.core.ports import StructuredOutputError

from . import sending, translate

if TYPE_CHECKING:
    from .bot import ArgumentWinnerBot

log = logging.getLogger(__name__)

_REPLIED_LRU_SIZE = 1024

PERSONA_CHOICES = [
    app_commands.Choice(name=p.value.title(), value=p.value)
    for p in (Persona.LOGICIAN, Persona.SAVAGE, Persona.DIPLOMAT, Persona.SOCRATIC)
]


def should_engage(
    *,
    author_id: str,
    author_is_bot: bool,
    is_webhook: bool,
    bot_id: str,
    mentions_bot: bool,
    session: ArgumentSession | None,
    reply_to_bots: bool,
) -> bool:
    """Pure engagement rule — guards 1 and 2."""
    if author_id == bot_id or is_webhook:
        return False
    if author_is_bot and not reply_to_bots:
        return False
    if mentions_bot:
        return True
    return session is not None and author_id in session.opponent_ids


def is_deliberate_mention(message: Any, bot_id: str, self_role: Any = None) -> bool:
    """A typed @mention (or a ping of the bot's managed role) — NOT a
    reply-ping. message.mentions includes reply-pings, so trusting it would
    let every opponent reply reset the runaway-guard reply cap."""
    content = message.content or ""
    if f"<@{bot_id}>" in content or f"<@!{bot_id}>" in content:
        return True
    role_mentions = getattr(message, "role_mentions", None) or []
    return self_role is not None and self_role in role_mentions


class CombatManager:
    def __init__(self, bot: ArgumentWinnerBot) -> None:
        self.bot = bot
        self.app = bot.app
        self.settings = bot.app.settings
        # Guard 5: synchronous busy set — NOT an asyncio.Lock. A lock would
        # queue waiters and burst-spam stale replies once the cooldown clears.
        self._busy: set[ConversationRef] = set()
        self._replied: OrderedDict[int, None] = OrderedDict()
        self._debounce: dict[ConversationRef, asyncio.Task] = {}

    # ─── commands ──────────────────────────────────────────────────────────────

    def register(self, tree: app_commands.CommandTree) -> None:
        group = app_commands.Group(
            name="combat",
            description="Let the bot argue on its own in this channel",
            guild_only=True,  # the Member opponent option can't resolve in DMs
        )

        @group.command(name="start", description="Start auto-combat here")
        @app_commands.describe(
            persona="Lock the bot into one persona", opponent="Who the bot should argue with"
        )
        @app_commands.choices(persona=PERSONA_CHOICES)
        async def start(
            interaction: discord.Interaction,
            persona: app_commands.Choice[str] | None = None,
            opponent: discord.Member | None = None,
        ) -> None:
            ref = translate.ref_for_channel(interaction.channel)
            session = ArgumentSession(
                ref=ref,
                opponent_ids={str(opponent.id)} if opponent else set(),
                persona=Persona(persona.value) if persona else Persona.AUTO,
                persona_forced=persona is not None,
            )
            await self.app.store.save(session)
            who = opponent.display_name if opponent else "anyone who @mentions me"
            await interaction.response.send_message(
                f"⚔️ Combat mode ON — arguing with {who}. `/combat stop` to end it.",
                ephemeral=True,
            )

        @group.command(name="stop", description="Stop auto-combat here")
        async def stop(interaction: discord.Interaction) -> None:
            ref = translate.ref_for_channel(interaction.channel)
            await self.app.store.delete(ref)
            await interaction.response.send_message("🕊️ Combat mode OFF.", ephemeral=True)

        tree.add_command(group)

    # ─── message flow ──────────────────────────────────────────────────────────

    async def on_message(self, message: Any) -> None:
        if self.bot.user is None:
            return
        ref = translate.ref_for_channel(message.channel)
        session = await self.app.store.get(ref)
        guild = getattr(message, "guild", None)
        mentions_bot = is_deliberate_mention(
            message, str(self.bot.user.id), getattr(guild, "self_role", None)
        )

        if not should_engage(
            author_id=str(message.author.id),
            author_is_bot=bool(message.author.bot),
            is_webhook=message.webhook_id is not None,
            bot_id=str(self.bot.user.id),
            mentions_bot=mentions_bot,
            session=session,
            reply_to_bots=self.settings.aw_reply_to_bots,
        ):
            return
        if message.id in self._replied:  # guard 3
            return

        if mentions_bot:
            # A fresh mention creates/refreshes the session, recruits the
            # author as an opponent, and resets the reply cap.
            if session is None:
                session = ArgumentSession(ref=ref)
            session.opponent_ids.add(str(message.author.id))
            session.replies_sent = 0
            await self.app.store.save(session)

        # Guard 6: debounce — supersede any pending reply for this ref.
        pending = self._debounce.pop(ref, None)
        if pending is not None:
            pending.cancel()
        self._debounce[ref] = asyncio.create_task(self._debounced(ref, message))

    async def _debounced(self, ref: ConversationRef, message: Any) -> None:
        try:
            await asyncio.sleep(self.settings.aw_combat_debounce_seconds)
        except asyncio.CancelledError:
            return
        self._debounce.pop(ref, None)
        try:
            await self.process(ref, message)
        except Exception:  # noqa: BLE001 — a failed reply must not kill the task
            log.exception("combat reply failed for %s", ref)

    async def process(self, ref: ConversationRef, message: Any) -> None:
        # Guard 5: fail-fast drop. No await between check and add.
        if ref in self._busy:
            return
        self._busy.add(ref)
        try:
            session = await self.app.store.get(ref)
            if session is None:  # /combat stop landed mid-debounce
                return
            now = datetime.now(UTC)
            if (  # guard 4: cooldown — drop, never queue
                session.last_reply_at is not None
                and (now - session.last_reply_at).total_seconds()
                < self.settings.aw_combat_cooldown_seconds
            ):
                return
            if session.replies_sent >= self.settings.aw_combat_max_replies:
                return
            if message.id in self._replied:
                return

            ctx = await translate.build_context(
                message.channel,
                message,
                bot_user=self.bot.user,
                beneficiary=self.bot.user,
                forced_persona=session.persona if session.persona_forced else None,
                extra_opponent_ids=frozenset(session.opponent_ids),
                history_limit=self.settings.aw_max_context_turns,
            )
            try:
                async with message.channel.typing():  # guard 7
                    candidate = await self.app.engine.combat_reply(ctx, session)
            except StructuredOutputError:
                log.warning("combat generation failed for %s", ref)
                return

            await sending.send_reply(message, candidate.text)
            self._mark_replied(message.id)
            # Re-fetch before saving: /combat stop mid-generation must not be
            # resurrected by a blind save of the stale object, and a /combat
            # start that replaced the config mid-generation must win.
            current = await self.app.store.get(ref)
            if current is None:
                return
            current.replies_sent += 1
            current.last_reply_at = datetime.now(UTC)
            await self.app.store.save(current)
        finally:
            self._busy.discard(ref)

    def _mark_replied(self, message_id: int) -> None:
        self._replied[message_id] = None
        while len(self._replied) > _REPLIED_LRU_SIZE:
            self._replied.popitem(last=False)
