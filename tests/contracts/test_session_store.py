"""SessionStore contract: any implementation (in-memory now, SQLite later)
must pass this suite unchanged — subclass and override `make_store`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argumentwinner.core.models import ArgumentSession, ConversationRef, Persona
from argumentwinner.core.sessions import InMemorySessionStore

REF = ConversationRef(platform="test", guild_id="g", channel_id="c")
OTHER_REF = ConversationRef(platform="test", guild_id="g", channel_id="c", thread_id="t")


class SessionStoreContract:
    def make_store(self):
        raise NotImplementedError

    async def test_get_missing_returns_none(self):
        assert await self.make_store().get(REF) is None

    async def test_save_then_get_roundtrip(self):
        store = self.make_store()
        session = ArgumentSession(ref=REF, persona=Persona.SAVAGE, opponent_ids={"o1"})
        await store.save(session)
        loaded = await store.get(REF)
        assert loaded is not None
        assert loaded.persona is Persona.SAVAGE
        assert loaded.opponent_ids == {"o1"}

    async def test_thread_and_parent_channel_are_different_arguments(self):
        store = self.make_store()
        await store.save(ArgumentSession(ref=REF))
        assert await store.get(OTHER_REF) is None

    async def test_delete(self):
        store = self.make_store()
        await store.save(ArgumentSession(ref=REF))
        await store.delete(REF)
        assert await store.get(REF) is None

    async def test_delete_missing_is_a_noop(self):
        await self.make_store().delete(REF)

    async def test_save_refreshes_ttl(self):
        store = self.make_store()
        await store.save(ArgumentSession(ref=REF))
        loaded = await store.get(REF)
        assert loaded.expires_at is not None
        assert loaded.expires_at > datetime.now(UTC)


class TestInMemorySessionStore(SessionStoreContract):
    def make_store(self):
        return InMemorySessionStore(ttl_minutes=60)

    async def test_expired_session_is_evicted_on_get(self):
        store = InMemorySessionStore(ttl_minutes=60)
        session = ArgumentSession(ref=REF)
        await store.save(session)
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert await store.get(REF) is None

    async def test_save_sweeps_expired_sessions_for_refs_never_queried_again(self):
        store = InMemorySessionStore(ttl_minutes=60)
        stale = ArgumentSession(ref=REF)
        await store.save(stale)
        stale.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await store.save(ArgumentSession(ref=OTHER_REF))  # unrelated save sweeps
        assert REF not in store._sessions  # no leak for never-again-queried refs
