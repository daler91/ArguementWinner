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
    # Path to a JSON price table for /usage cost estimates, replacing the
    # bundled one. Generate with `python -m argumentwinner.llm.prices
    # --refresh`. Unset = bundled defaults. Same `str` rationale as
    # aw_voice_profile below.
    aw_price_table: str | None = None

    # Discord
    discord_bot_token: SecretStr | None = None
    aw_discord_dev_guild_ids: str = ""

    # Telegram
    telegram_bot_token: SecretStr | None = None

    # Engine
    aw_spice_level: SpiceLevel = SpiceLevel.MEDIUM
    # Path to a voice-profile markdown file (style notes + sample messages you
    # wrote) so replies read like YOU typed them. Unset/blank = off;
    # set-but-missing = startup failure. Deliberately `str` not `Path`:
    # pydantic coerces "" to Path("."), which would turn an accidentally blank
    # env var into a confusing failure instead of "off".
    aw_voice_profile: str | None = None

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

    # Session persistence: "memory" forgets active arguments on restart,
    # "sqlite" survives them (file at AW_SQLITE_PATH; *.db is gitignored).
    aw_session_store: Literal["memory", "sqlite"] = "memory"
    aw_sqlite_path: str = "argumentwinner.db"

    def engine_settings(self) -> EngineSettings:
        return EngineSettings(spice=self.aw_spice_level)

    def dev_guild_ids(self) -> list[int]:
        return [int(g) for g in self.aw_discord_dev_guild_ids.split(",") if g.strip()]
