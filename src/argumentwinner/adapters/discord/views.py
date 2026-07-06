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

Regenerate = Callable[[Persona | None], Awaitable[EngineResult]]


def build_embeds(result: EngineResult) -> list[discord.Embed]:
    embed = discord.Embed(
        title="Win this argument",
        description=f"*{result.state_digest}*",
        color=discord.Color.red(),
    )
    for i, c in enumerate(result.candidates[:3], start=1):
        badge = _RISK_BADGES.get(c.risk.value, c.risk.value)
        text = c.text if len(c.text) <= 900 else c.text[:900] + "…"
        embed.add_field(
            name=f"#{i} · {c.persona.value} · {badge}",
            value=f"{text}\n-# {c.tactic_note}",
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

    def _make_send(self, index: int):
        async def send(interaction: discord.Interaction) -> None:
            if index >= len(self.result.candidates):
                await interaction.response.defer()
                return
            candidate = self.result.candidates[index]
            await sending.send_reply(self.target_message, candidate.text)
            for item in self.children:
                item.disabled = True  # type: ignore[attr-defined]
            self.stop()
            await interaction.response.edit_message(
                content=f"✅ Sent #{index + 1}.", view=self
            )

        return send

    async def _plain_text(self, interaction: discord.Interaction) -> None:
        blocks = "\n".join(
            f"**#{i + 1}**\n```text\n{c.text}\n```"
            for i, c in enumerate(self.result.candidates[:3])
        )
        await interaction.response.send_message(
            blocks or "No candidates.", ephemeral=True
        )

    async def _regen(self, interaction: discord.Interaction, forced: Persona | None) -> None:
        await interaction.response.defer()
        try:
            self.result = await self.regenerate(forced)
        except Exception:  # noqa: BLE001 — surface failure in the ephemeral UI
            await interaction.followup.send("Couldn't regenerate, try again.", ephemeral=True)
            return
        self._build_items()
        await interaction.edit_original_response(embeds=build_embeds(self.result), view=self)

    async def _reroll(self, interaction: discord.Interaction) -> None:
        await self._regen(interaction, None)

    def _persona_select(self, select: discord.ui.Select):
        async def on_select(interaction: discord.Interaction) -> None:
            await self._regen(interaction, Persona(select.values[0]))

        return on_select

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
