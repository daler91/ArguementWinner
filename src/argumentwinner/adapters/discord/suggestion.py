"""Suggestion mode: message context menu + /argue. Ephemeral candidate picker;
the user sends via the bot or copies the text to send as themselves."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from argumentwinner.core.models import Persona

from . import translate
from .views import CandidateView, build_embeds

if TYPE_CHECKING:
    from .bot import ArgumentWinnerBot

log = logging.getLogger(__name__)

PERSONA_CHOICES = [
    app_commands.Choice(name=p.value.title(), value=p.value)
    for p in (Persona.LOGICIAN, Persona.SAVAGE, Persona.DIPLOMAT, Persona.SOCRATIC)
]


async def _suggest(
    bot: ArgumentWinnerBot,
    interaction: discord.Interaction,
    target_message: discord.Message,
    forced: Persona | None,
) -> None:
    # 3-second rule: defer immediately, always ephemeral + thinking.
    await interaction.response.defer(ephemeral=True, thinking=True)

    async def regenerate(persona: Persona | None):
        ctx = await translate.build_context(
            target_message.channel,
            target_message,
            bot_user=bot.user,
            beneficiary=interaction.user,
            forced_persona=persona,
            history_limit=bot.app.settings.aw_max_context_turns,
        )
        return await bot.app.engine.suggest(ctx)

    try:
        result = await regenerate(forced)
    except ValueError:
        await interaction.followup.send(
            "That message has no content I can argue against.", ephemeral=True
        )
        return
    except Exception:  # noqa: BLE001 — never leave the interaction hanging
        log.exception("suggest failed")
        await interaction.followup.send(
            "Couldn't generate a comeback right now — try again in a moment.", ephemeral=True
        )
        return

    view = CandidateView(result, target_message, regenerate)
    await interaction.followup.send(embeds=build_embeds(result), view=view, ephemeral=True)


def register(bot: ArgumentWinnerBot) -> None:
    @bot.tree.context_menu(name="Win this argument")
    async def win_argument(interaction: discord.Interaction, message: discord.Message) -> None:
        forced = None
        if message.author.id == bot.user.id:
            await interaction.response.send_message(
                "I'm not arguing with myself.", ephemeral=True
            )
            return
        await _suggest(bot, interaction, message, forced)

    @bot.tree.command(
        name="argue", description="Get winning replies to the latest message in this channel"
    )
    @app_commands.describe(persona="Force a persona for the replies")
    @app_commands.choices(persona=PERSONA_CHOICES)
    async def argue(
        interaction: discord.Interaction,
        persona: app_commands.Choice[str] | None = None,
    ) -> None:
        target: discord.Message | None = None
        async for m in interaction.channel.history(limit=25):
            if m.author.id in (interaction.user.id, bot.user.id):
                continue
            if translate.annotate_content(m):
                target = m
                break
        if target is None:
            await interaction.response.send_message(
                "No recent opponent message found in this channel.", ephemeral=True
            )
            return
        forced = Persona(persona.value) if persona else None
        await _suggest(bot, interaction, target, forced)
