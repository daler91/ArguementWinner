"""In-memory session store: dict + lazy TTL eviction.

Sessions are control state only — conversation content is never stored (context
is rebuilt from a fresh history fetch each turn)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import ArgumentSession, ConversationRef


class InMemorySessionStore:
    def __init__(self, ttl_minutes: int = 60) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._sessions: dict[ConversationRef, ArgumentSession] = {}

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def get(self, ref: ConversationRef) -> ArgumentSession | None:
        session = self._sessions.get(ref)
        if session is None:
            return None
        if session.expires_at is not None and session.expires_at <= self._now():
            del self._sessions[ref]
            return None
        return session

    async def save(self, session: ArgumentSession) -> None:
        now = self._now()
        # Opportunistic sweep: refs that are never queried again must not
        # leak forever (get() only evicts the ref it is asked about).
        self._sessions = {
            ref: s
            for ref, s in self._sessions.items()
            if s.expires_at is None or s.expires_at > now
        }
        session.expires_at = now + self._ttl
        self._sessions[session.ref] = session

    async def delete(self, ref: ConversationRef) -> None:
        self._sessions.pop(ref, None)
