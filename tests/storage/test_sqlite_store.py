"""SQLite store: passes the SessionStore contract unchanged, survives a
"restart" (new instance, same file), and treats corrupt rows as missing.

Expiry tests differ from the InMemory ones by design: those mutate the saved
object post-save, which can't transfer to a serialized snapshot — here a
ttl_minutes=0 store makes every row born expired instead.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from argumentwinner.core.models import ArgumentSession, ConversationRef, Persona
from argumentwinner.storage.sqlite_store import SqliteSessionStore, ref_key
from tests.contracts.test_session_store import OTHER_REF, REF, SessionStoreContract


class TestSqliteSessionStore(SessionStoreContract):
    @pytest.fixture(autouse=True)
    def _tmp_db(self, tmp_path):
        self._path = tmp_path / "sessions.db"

    def make_store(self, ttl_minutes: int = 60) -> SqliteSessionStore:
        return SqliteSessionStore(self._path, ttl_minutes=ttl_minutes)

    def _row_count(self) -> int:
        with sqlite3.connect(self._path) as db:
            return db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    async def test_expired_session_is_evicted_on_get(self):
        store = self.make_store(ttl_minutes=0)  # born expired
        await store.save(ArgumentSession(ref=REF))
        assert await store.get(REF) is None
        assert self._row_count() == 0  # evicted, not just hidden

    async def test_save_sweeps_expired_rows_for_refs_never_queried_again(self):
        await self.make_store(ttl_minutes=0).save(ArgumentSession(ref=REF))
        await self.make_store(ttl_minutes=60).save(ArgumentSession(ref=OTHER_REF))
        with sqlite3.connect(self._path) as db:
            rows = db.execute("SELECT ref_key FROM sessions").fetchall()
        assert rows == [(ref_key(OTHER_REF),)]

    async def test_sessions_survive_a_restart_with_all_fields(self):
        session = ArgumentSession(
            ref=REF,
            opponent_ids={"o1", "o2"},
            persona=Persona.SAVAGE,
            persona_forced=True,
            persona_mismatch_streak=1,
            replies_sent=3,
            last_reply_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        )
        await self.make_store().save(session)

        loaded = await self.make_store().get(REF)  # fresh instance = restart
        assert loaded is not None
        assert loaded.opponent_ids == {"o1", "o2"}
        assert loaded.persona is Persona.SAVAGE  # enum identity, not a str
        assert loaded.persona_forced is True
        assert loaded.persona_mismatch_streak == 1
        assert loaded.replies_sent == 3
        assert loaded.last_reply_at == datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        assert loaded.last_reply_at.tzinfo is not None  # aware, not naive
        assert loaded.expires_at is not None and loaded.expires_at > datetime.now(UTC)

    @pytest.mark.parametrize("corrupt", ["{broken", '{"persona": "warlock"}', '"not-a-dict"'])
    async def test_corrupt_row_is_treated_as_missing_and_removed(self, corrupt, caplog):
        store = self.make_store()
        await store.save(ArgumentSession(ref=REF))
        with sqlite3.connect(self._path) as db:
            db.execute("UPDATE sessions SET data = ?", (corrupt,))
        assert await store.get(REF) is None  # not an exception
        assert self._row_count() == 0  # removed: no warn-loop
        assert "corrupt session row" in caplog.text
        await store.save(ArgumentSession(ref=REF))  # and save recovers
        assert await store.get(REF) is not None

    async def test_none_guild_and_real_guild_do_not_collide(self):
        store = self.make_store()
        none_ref = ConversationRef(platform="test", guild_id=None, channel_id="c")
        await store.save(ArgumentSession(ref=none_ref, persona=Persona.SAVAGE))
        await store.save(ArgumentSession(ref=REF, persona=Persona.DIPLOMAT))
        assert (await store.get(none_ref)).persona is Persona.SAVAGE
        assert (await store.get(REF)).persona is Persona.DIPLOMAT
