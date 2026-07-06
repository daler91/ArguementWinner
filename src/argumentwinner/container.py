"""Composition root: Settings → provider → store → engine → adapter(s).
The only module allowed to import adapters."""

from __future__ import annotations

from dataclasses import dataclass

from argumentwinner.config import Settings
from argumentwinner.core.engine import ArgumentEngine
from argumentwinner.core.ports import LLMProvider, SessionStore
from argumentwinner.core.sessions import InMemorySessionStore
from argumentwinner.llm.factory import build_provider


@dataclass
class App:
    settings: Settings
    provider: LLMProvider
    store: SessionStore
    engine: ArgumentEngine


def build_app(settings: Settings | None = None) -> App:
    settings = settings or Settings()
    provider = build_provider(settings)
    store = InMemorySessionStore(ttl_minutes=settings.aw_session_ttl_minutes)
    engine = ArgumentEngine(provider, settings.engine_settings())
    return App(settings=settings, provider=provider, store=store, engine=engine)
