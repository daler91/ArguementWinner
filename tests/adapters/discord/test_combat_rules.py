"""Auto-combat guards, tested through the pure parts + stub objects:
engagement rules, the fail-fast busy drop, and cooldown drop-not-queue."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from argumentwinner.adapters.discord.combat import CombatManager, should_engage
from argumentwinner.core.models import ArgumentSession, ConversationRef

REF = ConversationRef(platform="discord", guild_id="g", channel_id="c")


def session_with(*opponents: str, **kwargs) -> ArgumentSession:
    return ArgumentSession(ref=REF, opponent_ids=set(opponents), **kwargs)


BASE = dict(
    author_id="user1",
    author_is_bot=False,
    is_webhook=False,
    bot_id="bot",
    mentions_bot=False,
    session=None,
    reply_to_bots=False,
)


def engage(**overrides) -> bool:
    return should_engage(**{**BASE, **overrides})


# ─── should_engage (guards 1 & 2) ────────────────────────────────────────────


def test_never_replies_to_self():
    assert not engage(author_id="bot", mentions_bot=True, session=session_with("bot"))


def test_never_replies_to_webhooks():
    assert not engage(is_webhook=True, mentions_bot=True)


def test_bot_authors_ignored_unless_opted_in():
    assert not engage(author_is_bot=True, mentions_bot=True)
    assert engage(author_is_bot=True, mentions_bot=True, reply_to_bots=True)


def test_mention_engages_without_session():
    assert engage(mentions_bot=True)


def test_session_opponent_engages_without_mention():
    assert engage(session=session_with("user1"))


def test_non_opponent_bystander_is_ignored():
    assert not engage(session=session_with("someone_else"))


def test_no_session_no_mention_is_ignored():
    assert not engage()


# ─── busy set: fail-fast drop, never a queue (guard 5) ───────────────────────


class RecordingStore:
    def __init__(self, session=None):
        self.session = session
        self.get_calls = 0

    async def get(self, ref):
        self.get_calls += 1
        return self.session

    async def save(self, session):
        self.session = session

    async def delete(self, ref):
        self.session = None


def make_manager(store) -> CombatManager:
    settings = SimpleNamespace(
        aw_reply_to_bots=False,
        aw_combat_cooldown_seconds=20.0,
        aw_combat_max_replies=12,
        aw_combat_debounce_seconds=0.0,
        aw_max_context_turns=24,
    )
    app = SimpleNamespace(store=store, engine=None, settings=settings)
    bot = SimpleNamespace(app=app, user=SimpleNamespace(id=999))
    return CombatManager(bot)


async def test_busy_ref_drops_event_outright():
    store = RecordingStore(session_with("user1"))
    manager = make_manager(store)
    manager._busy.add(REF)

    await manager.process(REF, SimpleNamespace(id=1))

    # dropped before any work — not even a store read, and definitely no queue
    assert store.get_calls == 0
    assert REF in manager._busy  # untouched: the in-flight generation owns it


async def test_cooldown_drops_instead_of_queueing():
    session = session_with("user1", last_reply_at=datetime.now(UTC))
    store = RecordingStore(session)
    manager = make_manager(store)

    # engine is None: reaching generation would raise AttributeError, so a
    # clean return proves the cooldown dropped the event before generating.
    await manager.process(REF, SimpleNamespace(id=1))
    assert session.replies_sent == 0


async def test_reply_cap_drops():
    session = session_with("user1", replies_sent=12)
    manager = make_manager(RecordingStore(session))
    await manager.process(REF, SimpleNamespace(id=1))
    assert session.replies_sent == 12


async def test_stopped_session_mid_debounce_drops():
    manager = make_manager(RecordingStore(None))
    await manager.process(REF, SimpleNamespace(id=1))  # no session -> clean drop


async def test_busy_is_released_after_processing():
    manager = make_manager(RecordingStore(None))
    await manager.process(REF, SimpleNamespace(id=1))
    assert REF not in manager._busy


async def test_double_reply_guard():
    session = session_with("user1")
    manager = make_manager(RecordingStore(session))
    manager._mark_replied(1)
    await manager.process(REF, SimpleNamespace(id=1))
    assert session.replies_sent == 0
