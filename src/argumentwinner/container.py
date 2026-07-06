"""Composition root: Settings → provider → store → engine → adapter(s).
The only module allowed to import adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from argumentwinner.config import Settings
from argumentwinner.core.engine import ArgumentEngine
from argumentwinner.core.models import VoiceProfile
from argumentwinner.core.ports import LLMProvider, SessionStore
from argumentwinner.core.sessions import InMemorySessionStore
from argumentwinner.core.voice import parse_voice_profile
from argumentwinner.llm.factory import build_provider
from argumentwinner.llm.prices import load_price_table
from argumentwinner.llm.usage import UsageMeter
from argumentwinner.storage.sqlite_store import SqliteSessionStore


@dataclass
class App:
    settings: Settings
    provider: LLMProvider
    store: SessionStore
    engine: ArgumentEngine
    voice: VoiceProfile | None = None
    meter: UsageMeter = field(default_factory=UsageMeter)


def _load_voice_profile(settings: Settings) -> VoiceProfile | None:
    raw = (settings.aw_voice_profile or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_file():
        raise RuntimeError(
            f"AW_VOICE_PROFILE={raw!r} but no such file exists — "
            "create it (see voice.example.md) or unset the variable"
        )
    profile = parse_voice_profile(path.read_text(encoding="utf-8"))
    if not (profile.notes or profile.samples):
        raise RuntimeError(
            f"AW_VOICE_PROFILE={raw!r} parsed to an empty profile — "
            "see voice.example.md for the expected format"
        )
    return profile


def _build_store(settings: Settings) -> SessionStore:
    if settings.aw_session_store == "sqlite":
        return SqliteSessionStore(
            settings.aw_sqlite_path, ttl_minutes=settings.aw_session_ttl_minutes
        )
    return InMemorySessionStore(ttl_minutes=settings.aw_session_ttl_minutes)


def build_app(settings: Settings | None = None) -> App:
    settings = settings or Settings()
    meter = UsageMeter(load_price_table(settings.aw_price_table))
    provider = build_provider(settings, meter=meter)
    store = _build_store(settings)
    engine = ArgumentEngine(provider, settings.engine_settings())
    return App(
        settings=settings,
        provider=provider,
        store=store,
        engine=engine,
        voice=_load_voice_profile(settings),
        meter=meter,
    )
