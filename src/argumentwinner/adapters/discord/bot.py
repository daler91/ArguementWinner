"""Discord client wiring: intents, command tree, dev-guild vs global sync."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from argumentwinner.container import App

from . import suggestion
from .combat import CombatManager

log = logging.getLogger(__name__)


class ArgumentWinnerBot(discord.Client):
    def __init__(self, app: App) -> None:
        intents = discord.Intents.default()
        # PRIVILEGED: must also be toggled in the Developer Portal under
        # Bot → Privileged Gateway Intents, or every message reads as empty.
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.app = app
        self.combat = CombatManager(self)

    async def setup_hook(self) -> None:
        suggestion.register(self)
        self.combat.register(self.tree)
        dev_ids = self.app.settings.dev_guild_ids()
        if dev_ids:
            for gid in dev_ids:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            log.info("commands synced to dev guilds: %s", dev_ids)
        else:
            await self.tree.sync()
            log.info("commands synced globally (may take up to an hour to appear)")

    async def on_ready(self) -> None:
        log.info("logged in as %s (provider: %s)", self.user, self.app.provider.name)

    async def on_message(self, message: discord.Message) -> None:
        await self.combat.on_message(message)


def run_bot(app: App) -> None:
    token = app.settings.discord_bot_token
    if token is None:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN is not set — put it in .env (see .env.example)"
        )
    logging.basicConfig(level=logging.INFO)
    ArgumentWinnerBot(app).run(token.get_secret_value())
