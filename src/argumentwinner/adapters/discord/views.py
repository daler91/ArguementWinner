"""Ephemeral candidate-picker View. Candidates live on the View instance —
no store round-trip; they die with the interaction token."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord

from argumentwinner.core.models import EngineResult, Persona

from . import sending

_RISK_BADGES = {"safe": "🟢 SAFE", "spicy": "🟠 SPICY", "nuclear": "☢️ NUCLEAR"}

# Most of the 15-minute interaction token, not an arbitrary 180s.
VIEW_TIMEOUT = 840

# Discord embed hard limits.
_FIELD_VALUE_LIMIT = 1024
_DESCRIPTION_LIMIT = 4096

Regenerate = Callable[[Persona | None], Awaitable[EngineResult]]


def _clamp(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_embeds(result: EngineResult) -> list[discord.Embed]:
    embed = discord.Embed(
        title="Win this argument",
        description=_clamp(f"*{result.state_digest}*", _DESCRIPTION_LIMIT),
        color=discord.Color.red(),
    )
    for i, c in enumerate(result.candidates[:3], start=1):
        badge = _RISK_BADGES.get(c.risk.value, c.risk.value)
        value = _clamp(f"{c.text}\n-# {c.tactic_note}", _FIELD_VALUE_LIMIT)
        embed.add_field(
            name=_clamp(f"#{i} · {c.persona.value} · {badge}", 256),
            value=value,
            inline=False,
        )
    return [embed]


class CandidateView(discord.ui.View):
    def __init__(
        self,
        result: EngineResult,
        target_message: Any,
        regenerate: Regenerate,
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.result = result
        self.target_message = target_message
        self.regenerate = regenerate
        # The ephemeral WebhookMessage this view is attached to; set by the
        # adapter after followup.send so on_timeout can disable the buttons.
        self.message: Any | None = None
        # Each component click runs as its own asyncio task — this flag is the
        # synchronous double-click guard (checked-and-set before any await).
        self._working = False
        self._build_items()

    def _build_items(self) -> None:
        self.clear_items()
        for i in range(min(3, len(self.result.candidates))):
            button = discord.ui.Button(
                label=f"Send #{i + 1}", style=discord.ButtonStyle.primary, row=0
            )
            button.callback = self._make_send(i)
            self.add_item(button)

        plain = discord.ui.Button(label="Plain text", style=discord.ButtonStyle.secondary, row=1)
        plain.callback = self._plain_text
        self.add_item(plain)

        reroll = discord.ui.Button(label="🎲 Reroll", style=discord.ButtonStyle.secondary, row=1)
        reroll.callback = self._reroll
        self.add_item(reroll)

        select = discord.ui.Select(
            placeholder="Force a persona and reroll…",
            options=[
                discord.SelectOption(label=p.value.title(), value=p.value)
                for p in (Persona.LOGICIAN, Persona.SAVAGE, Persona.DIPLOMAT, Persona.SOCRATIC)
            ],
            row=2,
        )
        select.callback = self._persona_select(select)
        self.add_item(select)

    def _set_disabled(self, disabled: bool) -> None:
        for item in self.children:
            item.disabled = disabled  # type: ignore[attr-defined]

    def _make_send(self, index: int):
        async def send(interaction: discord.Interaction) -> None:
            if self._working or self.is_finished() or index >= len(self.result.candidates):
                await interaction.response.defer()
                return
            self._working = True  # synchronous — no await before this line
            candidate = self.result.candidates[index]
            # Acknowledge inside the 3-second window BEFORE the slow public
            # sends, and lock the buttons against a second click.
            self._set_disabled(True)
            await interaction.response.edit_message(content="Sending…", view=self)
            try:
                await sending.send_reply(self.target_message, candidate.text)
            except discord.HTTPException:
                self._working = False
                self._set_disabled(False)
                await interaction.edit_original_response(
                    content="Couldn't send — missing permissions?", view=self
                )
                return
            self.stop()
            await interaction.edit_original_response(content=f"✅ Sent #{index + 1}.", view=self)

        return send

    async def _plain_text(self, interaction: discord.Interaction) -> None:
        blocks = "\n".join(
            f"**#{i + 1}**\n```text\n{c.text}\n```"
            for i, c in enumerate(self.result.candidates[:3])
        )
        chunks = sending.split_message(blocks or "No candidates.")
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

    async def _regen(self, interaction: discord.Interaction, forced: Persona | None) -> None:
        if self._working or self.is_finished():
            await interaction.response.defer()
            return
        self._working = True
        await interaction.response.defer()
        old_result = self.result
        try:
            self.result = await self.regenerate(forced)
            self._build_items()
            await interaction.edit_original_response(embeds=build_embeds(self.result), view=self)
        except Exception:  # noqa: BLE001 — surface failure, restore the old picker
            self.result = old_result
            self._build_items()
            await interaction.followup.send("Couldn't regenerate, try again.", ephemeral=True)
        finally:
            self._working = False

    async def _reroll(self, interaction: discord.Interaction) -> None:
        await self._regen(interaction, None)

    def _persona_select(self, select: discord.ui.Select):
        async def on_select(interaction: discord.Interaction) -> None:
            await self._regen(interaction, Persona(select.values[0]))

        return on_select

    async def on_timeout(self) -> None:
        self._set_disabled(True)
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass  # ephemeral message already gone
