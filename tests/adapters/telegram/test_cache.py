from __future__ import annotations

from datetime import UTC, datetime

from argumentwinner.adapters.telegram.cache import CachedMessage, ChatCache
from argumentwinner.core.models import ConversationRef, Participant

REF = ConversationRef(platform="telegram", guild_id=None, channel_id="100")
TOPIC_REF = ConversationRef(platform="telegram", guild_id=None, channel_id="100", thread_id="7")
OTHER_REF = ConversationRef(platform="telegram", guild_id=None, channel_id="200")

ALICE = Participant(id="1", display_name="alice")


def rec(message_id: str, content: str = "hi") -> CachedMessage:
    return CachedMessage(
        message_id=message_id,
        author=ALICE,
        content=content,
        timestamp=datetime(2026, 7, 6, tzinfo=UTC),
    )


def test_record_and_get_oldest_first():
    cache = ChatCache(maxlen=10)
    cache.record(REF, rec("1", "first"))
    cache.record(REF, rec("2", "second"))
    assert [m.content for m in cache.get(REF)] == ["first", "second"]


def test_maxlen_evicts_oldest():
    cache = ChatCache(maxlen=3)
    for i in range(5):
        cache.record(REF, rec(str(i)))
    assert [m.message_id for m in cache.get(REF)] == ["2", "3", "4"]


def test_edit_updates_in_place():
    cache = ChatCache(maxlen=10)
    cache.record(REF, rec("1", "original"))
    cache.record(REF, rec("2", "later"))
    assert cache.update(REF, "1", "edited") is True
    assert [m.content for m in cache.get(REF)] == ["edited", "later"]  # position kept


def test_edit_of_evicted_or_unknown_id_inserts_nothing():
    cache = ChatCache(maxlen=2)
    cache.record(REF, rec("1"))
    cache.record(REF, rec("2"))
    cache.record(REF, rec("3"))  # evicts "1"
    assert cache.update(REF, "1", "zombie") is False
    assert cache.update(REF, "99", "never seen") is False
    assert [m.message_id for m in cache.get(REF)] == ["2", "3"]


def test_re_record_same_id_replaces_not_duplicates():
    cache = ChatCache(maxlen=10)
    cache.record(REF, rec("1", "v1"))
    cache.record(REF, rec("1", "v2"))
    window = cache.get(REF)
    assert len(window) == 1
    assert window[0].content == "v2"


def test_forum_topic_ref_isolated_from_parent_chat():
    cache = ChatCache(maxlen=10)
    cache.record(REF, rec("1", "in main chat"))
    cache.record(TOPIC_REF, rec("1", "in topic"))
    assert [m.content for m in cache.get(REF)] == ["in main chat"]
    assert [m.content for m in cache.get(TOPIC_REF)] == ["in topic"]


def test_ref_lru_cap_evicts_least_recent_chat():
    cache = ChatCache(maxlen=10, max_refs=2)
    cache.record(REF, rec("1"))
    cache.record(OTHER_REF, rec("1"))
    cache.record(TOPIC_REF, rec("1"))  # third ref evicts the least recent (REF)
    assert cache.get(REF) == ()
    assert cache.get(OTHER_REF) != ()
    assert cache.get(TOPIC_REF) != ()


def test_find():
    cache = ChatCache(maxlen=10)
    cache.record(REF, rec("42", "found me"))
    assert cache.find(REF, "42").content == "found me"
    assert cache.find(REF, "43") is None
    assert cache.find(OTHER_REF, "42") is None
