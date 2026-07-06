"""SQLite-backed SessionStore: combat sessions survive restarts.

Semantics mirror InMemorySessionStore exactly — get() evicts expired rows,
save() refreshes the TTL on the caller's object and opportunistically sweeps
rows for refs that are never queried again. One deliberate delta: get()
returns a FRESH object per call rather than the saved identity, which is safe
because every adapter does get → mutate → save.

Sessions are control state only — conversation content is never stored.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from argumentwinner.core.models import ArgumentSession, ConversationRef, Persona

log = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sessions (
    ref_key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    expires_at TEXT NOT NULL
)"""


def ref_key(ref: ConversationRef) -> str:
    """ON-DISK FORMAT — FROZEN FOREVER (old databases must keep loading).
    A JSON list encodes the None-able fields unambiguously in a single TEXT
    primary key; separate columns would let SQL's NULL-is-never-equal rule
    admit duplicate rows for the same ref."""
    return json.dumps([ref.platform, ref.guild_id, ref.channel_id, ref.thread_id])


def _iso(dt: datetime) -> str:
    """Pinned timespec for every stored timestamp and SQL comparison operand:
    bare isoformat() drops zero microseconds, and mixed precision would break
    the lexicographic-order-is-chronological-order property the expires_at
    string comparisons rely on."""
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def _serialize(session: ArgumentSession) -> str:
    return json.dumps(
        {
            "opponent_ids": sorted(session.opponent_ids),
            "persona": session.persona.value,
            "persona_forced": session.persona_forced,
            "persona_mismatch_streak": session.persona_mismatch_streak,
            "replies_sent": session.replies_sent,
            "last_reply_at": _iso(session.last_reply_at) if session.last_reply_at else None,
            "expires_at": _iso(session.expires_at) if session.expires_at else None,
        }
    )


def _deserialize(ref: ConversationRef, data: str) -> ArgumentSession:
    raw = json.loads(data)
    return ArgumentSession(
        ref=ref,
        opponent_ids=set(raw["opponent_ids"]),
        persona=Persona(raw["persona"]),
        persona_forced=raw["persona_forced"],
        persona_mismatch_streak=raw["persona_mismatch_streak"],
        replies_sent=raw["replies_sent"],
        last_reply_at=(
            datetime.fromisoformat(raw["last_reply_at"]) if raw["last_reply_at"] else None
        ),
        expires_at=datetime.fromisoformat(raw["expires_at"]) if raw["expires_at"] else None,
    )


class SqliteSessionStore:
    def __init__(self, path: str | Path, ttl_minutes: int = 60) -> None:
        self._path = str(path)
        self._ttl = timedelta(minutes=ttl_minutes)
        self._schema_ready = False

    def _now(self) -> datetime:
        return datetime.now(UTC)

    @asynccontextmanager
    async def _connect(self):
        # One connection per call: aiosqlite connections are threads, and a
        # per-instance connection would leak one thread per store built (the
        # contract suite alone builds dozens).
        async with aiosqlite.connect(self._path) as db:
            if not self._schema_ready:
                await db.execute(_SCHEMA)
                await db.commit()
                self._schema_ready = True
            yield db

    async def get(self, ref: ConversationRef) -> ArgumentSession | None:
        key = ref_key(ref)
        async with self._connect() as db:
            async with db.execute(
                "SELECT data, expires_at FROM sessions WHERE ref_key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            try:
                expires_at = datetime.fromisoformat(row[1])
                session = _deserialize(ref, row[0])
            except (ValueError, KeyError, TypeError) as exc:
                # Treat-as-missing: one corrupt row must not brick combat.
                # Deleting it stops a warn-loop and lets the next save recover.
                log.warning("dropping corrupt session row for %s: %s", key, exc)
                await db.execute("DELETE FROM sessions WHERE ref_key = ?", (key,))
                await db.commit()
                return None
            if expires_at <= self._now():
                await db.execute("DELETE FROM sessions WHERE ref_key = ?", (key,))
                await db.commit()
                return None
            return session

    async def save(self, session: ArgumentSession) -> None:
        now = self._now()
        # Refresh the TTL on the caller's object BEFORE serializing, exactly
        # like InMemorySessionStore mutates before storing.
        session.expires_at = now + self._ttl
        async with self._connect() as db:
            await db.execute("DELETE FROM sessions WHERE expires_at <= ?", (_iso(now),))
            await db.execute(
                "INSERT INTO sessions (ref_key, data, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(ref_key) DO UPDATE SET "
                "data = excluded.data, expires_at = excluded.expires_at",
                (ref_key(session.ref), _serialize(session), _iso(session.expires_at)),
            )
            await db.commit()

    async def delete(self, ref: ConversationRef) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM sessions WHERE ref_key = ?", (ref_key(ref),))
            await db.commit()
