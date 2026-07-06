"""Runtime configuration: env vars + optional git-ignored .env file.

All tokens are SecretStr — never logged. Constructed once in __main__ and
passed down via the container; no global singletons.
"""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from argumentwinner.core.models import EngineSettings, Persona, SpiceLevel


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    aw_llm_provider: Literal["anthropic", "openai", "ollama", "fake"] = "anthropic"
    aw_llm_model: str | None = None
    aw_model_analyzer: str | None = None
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    aw_ollama_base_url: str = "http://localhost:11434/v1"

    # Discord
    discord_bot_token: SecretStr | None = None
    aw_discord_dev_guild_ids: str = ""

    # Engine
    aw_spice_level: SpiceLevel = SpiceLevel.MEDIUM

    # Desktop helper (works in any app: copy a message, press the hotkey, the
    # comeback lands on your clipboard ready to paste)
    aw_desktop_hotkey: str = "<ctrl>+<alt>+w"
    aw_desktop_cycle_hotkey: str = "<ctrl>+<alt>+e"
    aw_desktop_persona: Persona | None = None

    # Auto-combat guardrails
    aw_combat_cooldown_seconds: float = 20.0
    aw_combat_max_replies: int = 12
    aw_combat_debounce_seconds: float = 2.5
    aw_max_context_turns: int = 24
    aw_session_ttl_minutes: int = 60
    aw_reply_to_bots: bool = False

    def engine_settings(self) -> EngineSettings:
        return EngineSettings(spice=self.aw_spice_level)

    def dev_guild_ids(self) -> list[int]:
        return [int(g) for g in self.aw_discord_dev_guild_ids.split(",") if g.strip()]
