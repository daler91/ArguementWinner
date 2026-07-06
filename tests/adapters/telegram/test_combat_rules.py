"""Telegram auto-combat: mention detection and the CombatManager guards,
driven through injected stub IO — PTB never imported."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from argumentwinner.adapters.telegram.cache import CachedMessage, ChatCache
from argumentwinner.adapters.telegram.combat import CombatManager, is_deliberate_mention
from argumentwinner.core.models import (
    ArgumentSession,
    CandidateResponse,
    ConversationRef,
    Participant,
    Persona,
    Risk,
)

REF = ConversationRef(platform="telegram", guild_id=None, channel_id="100")
OTHER_REF = ConversationRef(platform="telegram", guild_id=None, channel_id="200")

BOT = Participant(id="999", display_name="argubot", is_bot=True)
OPP = Participant(id="1", display_name="alice")


def rec(message_id: str = "1", content: str = "you're wrong", author: Participant = OPP):
    return CachedMessage(
        message_id=message_id,
        author=author,
        content=content,
        timestamp=datetime(2026, 7, 6, tzinfo=UTC),
    )


# ─── deliberate mentions ──────────────────────────────────────────────────────


def test_typed_mention_counts_case_insensitively():
    assert is_deliberate_mention("hey @ArguBot fight me", "argubot")
    assert is_deliberate_mention("@ARGUBOT you're wrong", "argubot")


def test_prefix_username_does_not_count():
    assert not is_deliberate_mention("@argubotfan agrees with me", "argubot")


def test_none_text_and_missing_username_are_safe():
    assert not is_deliberate_mention(None, "argubot")
    assert not is_deliberate_mention("hello", "")


def test_reply_without_at_is_not_a_mention():
    # Replying to a bot message carries no "@" in the text — the Telegram
    # twin of the Discord reply-ping rule.
    assert not is_deliberate_mention("lol no", "argubot")


# ─── manager guards ───────────────────────────────────────────────────────────


class RecordingStore:
    def __init__(self, session=None):
        self.session = session
        self.get_calls = 0
        self.saved = []

    async def get(self, ref):
        self.get_calls += 1
        return self.session

    async def save(self, session):
        self.session = session
        self.saved.append(session)

    async def delete(self, ref):
        self.session = None


class VanishingStore(RecordingStore):
    """Session on first get, None afterwards — /combat_stop mid-generation."""

    async def get(self, ref):
        self.get_calls += 1
        if self.get_calls > 1:
            return None
        return self.session


class StubEngine:
    def __init__(self):
        self.contexts = []

    async def combat_reply(self, ctx, session=None):
        self.contexts.append(ctx)
        return CandidateResponse(
            text="reply", persona=Persona.LOGICIAN, tactic_note="t", risk=Risk.SAFE
        )


def make_manager(store, engine=None, *, debounce=0.0):
    settings = SimpleNamespace(
        aw_reply_to_bots=False,
        aw_combat_cooldown_seconds=20.0,
        aw_combat_max_replies=12,
        aw_combat_debounce_seconds=debounce,
        aw_max_context_turns=24,
    )
    app = SimpleNamespace(store=store, engine=engine or StubEngine(), settings=settings)
    sent: list[tuple[ConversationRef, str]] = []
    typing: list[ConversationRef] = []

    async def send_reply(ref, record, text):
        sent.append((ref, text))
        return "555"

    async def notify_typing(ref):
        typing.append(ref)

    manager = CombatManager(
        app,
        ChatCache(maxlen=24),
        bot_id="999",
        bot_participant=BOT,
        send_reply=send_reply,
        notify_typing=notify_typing,
    )
    manager._sent = sent  # test handle
    manager._typing = typing
    return manager


def session_with(*opponents: str, **kwargs) -> ArgumentSession:
    return ArgumentSession(ref=REF, opponent_ids=set(opponents), **kwargs)


async def test_busy_ref_drops_outright():
    store = RecordingStore(session_with("1"))
    manager = make_manager(store)
    manager._busy.add(REF)
    await manager.process(REF, rec())
    assert store.get_calls == 0
    assert manager._sent == []


async def test_cooldown_drops_instead_of_queueing():
    session = session_with("1", last_reply_at=datetime.now(UTC))
    manager = make_manager(RecordingStore(session))
    await manager.process(REF, rec())
    assert manager._sent == []
    assert session.replies_sent == 0


async def test_reply_cap_drops():
    manager = make_manager(RecordingStore(session_with("1", replies_sent=12)))
    await manager.process(REF, rec())
    assert manager._sent == []


async def test_successful_reply_sends_and_bookkeeps():
    session = session_with("1")
    store = RecordingStore(session)
    manager = make_manager(store)
    manager.cache.record(REF, rec("1"))
    await manager.process(REF, rec("1"))
    assert manager._sent == [(REF, "reply")]
    assert manager._typing == [REF]
    assert session.replies_sent == 1
    assert session.last_reply_at is not None
    # ...and the bot's own reply landed in the cache (polling won't echo it)
    assert any(m.author.id == "999" for m in manager.cache.get(REF))


async def test_stop_mid_generation_not_resurrected():
    session = session_with("1")
    store = VanishingStore(session)
    manager = make_manager(store)
    await manager.process(REF, rec())
    assert manager._sent != []  # reply was in flight — it sends
    assert store.saved == []  # ...but the dead session is NOT re-saved
    assert session.replies_sent == 0


async def test_replied_lru_is_keyed_per_chat():
    """Telegram message ids are per-chat counters: replying to message '7' in
    one chat must not suppress replies to message '7' in another chat."""
    manager = make_manager(RecordingStore(session_with("1")))
    manager._mark_replied(REF, "7")
    other_session = ArgumentSession(ref=OTHER_REF, opponent_ids={"1"})
    store = RecordingStore(other_session)
    manager.app = SimpleNamespace(
        store=store, engine=StubEngine(), settings=manager.settings
    )
    await manager.process(OTHER_REF, rec("7"))
    assert manager._sent == [(OTHER_REF, "reply")]  # not blocked by chat 100's id 7


async def test_double_reply_guard_within_a_chat():
    session = session_with("1")
    manager = make_manager(RecordingStore(session))
    manager._mark_replied(REF, "7")
    await manager.process(REF, rec("7"))
    assert manager._sent == []


async def test_combat_context_is_cache_built_and_voiceless():
    engine = StubEngine()
    session = session_with("1")
    manager = make_manager(RecordingStore(session), engine)
    manager.cache.record(REF, rec("1", "earlier salvo"))
    target = rec("2", "and another thing")
    manager.cache.record(REF, target)
    await manager.process(REF, target)
    ctx = engine.contexts[0]
    assert [t.content for t in ctx.transcript] == ["earlier salvo", "and another thing"]
    assert ctx.voice is None


async def test_mention_recruits_opponent_and_resets_cap():
    store = RecordingStore(None)
    manager = make_manager(store, debounce=0.0)
    import asyncio

    await manager.on_message(REF, rec("1"), mentions_bot=True, is_proxy=False)
    assert store.session is not None
    assert "1" in store.session.opponent_ids
    assert store.session.replies_sent == 0
    # let the debounce task run so it doesn't leak into other tests
    for task in list(manager._debounce.values()):
        task.cancel()
    await asyncio.sleep(0)


async def test_proxy_authors_never_engage():
    store = RecordingStore(session_with("1"))
    manager = make_manager(store)
    await manager.on_message(REF, rec("1"), mentions_bot=True, is_proxy=True)
    assert manager._debounce == {}  # dropped before debounce


async def test_bot_authors_ignored_without_opt_in():
    bot_author = Participant(id="777", display_name="otherbot", is_bot=True)
    store = RecordingStore(session_with("777"))
    manager = make_manager(store)
    await manager.on_message(REF, rec("1", author=bot_author), mentions_bot=True, is_proxy=False)
    assert manager._debounce == {}


async def test_start_and_stop_commands():
    store = RecordingStore(None)
    manager = make_manager(store)
    text = await manager.start(REF, persona=Persona.SAVAGE, opponent_id="1")
    assert "ON" in text
    assert store.session.persona is Persona.SAVAGE
    assert store.session.persona_forced is True
    assert store.session.opponent_ids == {"1"}
    text = await manager.stop(REF)
    assert "OFF" in text
    assert store.session is None
