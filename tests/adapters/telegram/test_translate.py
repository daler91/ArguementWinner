from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from argumentwinner.adapters.telegram.cache import CachedMessage
from argumentwinner.adapters.telegram.translate import (
    annotate_content,
    build_context,
    ref_for_message,
    to_cached,
    to_participant,
)
from argumentwinner.core.models import ConversationRef, Participant, Role
from tests.conftest import make_voice

REF = ConversationRef(platform="telegram", guild_id=None, channel_id="100")


def tg_user(user_id=1, full_name="Alice", is_bot=False, username=None):
    return SimpleNamespace(
        id=user_id, full_name=full_name, first_name=full_name, username=username, is_bot=is_bot
    )


def tg_msg(
    text="you're wrong",
    *,
    caption=None,
    photo=(),
    document=None,
    video=None,
    sticker=None,
    user=None,
    message_id=10,
    chat_id=100,
    thread_id=None,
    is_topic=False,
    reply_to=None,
):
    return SimpleNamespace(
        text=text,
        caption=caption,
        photo=list(photo),
        document=document,
        video=video,
        sticker=sticker,
        from_user=user if user is not None else tg_user(),
        message_id=message_id,
        chat=SimpleNamespace(id=chat_id),
        message_thread_id=thread_id,
        is_topic_message=is_topic,
        reply_to_message=reply_to,
        date=datetime(2026, 7, 6, tzinfo=UTC),
    )


def cached(message_id: str, content: str, author: Participant) -> CachedMessage:
    return CachedMessage(
        message_id=message_id,
        author=author,
        content=content,
        timestamp=datetime(2026, 7, 6, tzinfo=UTC),
    )


# ─── annotation ───────────────────────────────────────────────────────────────


def test_text_passes_through():
    assert annotate_content(tg_msg("explain this")) == "explain this"


def test_caption_used_when_no_text():
    assert "look at this" in annotate_content(tg_msg(None, caption="look at this", photo=["p"]))


def test_photo_only_message_never_empty():
    assert annotate_content(tg_msg(None, photo=["p"])) == "[User attached an image/file]"


def test_sticker_annotated():
    assert annotate_content(tg_msg(None, sticker=object())) == "[User sent a sticker]"


# ─── participants and refs ────────────────────────────────────────────────────


def test_participant_name_fallbacks():
    assert to_participant(tg_user(full_name="Alice")).display_name == "Alice"
    bare = SimpleNamespace(id=9, full_name=None, first_name=None, username="al", is_bot=False)
    assert to_participant(bare).display_name == "al"


def test_group_chat_ref():
    ref = ref_for_message(tg_msg(chat_id=-100123))
    assert (ref.platform, ref.channel_id, ref.thread_id) == ("telegram", "-100123", None)


def test_forum_topic_gets_thread_id():
    ref = ref_for_message(tg_msg(thread_id=7, is_topic=True))
    assert ref.thread_id == "7"


def test_plain_reply_thread_does_not_split_the_conversation():
    """message_thread_id is also set on ordinary reply-threads in supergroups —
    only real forum topics (is_topic_message) may scope separately."""
    ref = ref_for_message(tg_msg(thread_id=55, is_topic=False))
    assert ref.thread_id is None


# ─── to_cached ────────────────────────────────────────────────────────────────


def test_to_cached_captures_reply_id():
    parent = tg_msg(message_id=5)
    record = to_cached(tg_msg(message_id=6, reply_to=parent))
    assert record.reply_to_id == "5"
    assert record.message_id == "6"


def test_to_cached_rejects_empty_and_authorless():
    assert to_cached(tg_msg("")) is None
    channel_post = tg_msg("announcement", user=tg_user())
    channel_post.from_user = None
    assert to_cached(channel_post) is None


# ─── build_context ────────────────────────────────────────────────────────────

BOT = Participant(id="999", display_name="bot", is_bot=True)
OPP = Participant(id="1", display_name="alice")
ME = Participant(id="2", display_name="me")


def test_build_context_prepends_evicted_target():
    target = cached("1", "the old hot take", OPP)
    records = [cached("2", "newer message", OPP)]
    ctx = build_context(REF, records, target, bot_id="999", beneficiary=ME)
    assert ctx.transcript[0].content == "the old hot take"  # prepended, not appended
    assert ctx.target.content == "the old hot take"


def test_build_context_tags_roles_and_collects_our_lines():
    target = cached("3", "wrong again", OPP)
    records = [
        cached("1", "my earlier point", ME),
        cached("2", "bot said this", BOT),
        target,
    ]
    ctx = build_context(REF, records, target, bot_id="999", beneficiary=ME)
    roles = [t.role for t in ctx.transcript]
    assert roles == [Role.US, Role.US, Role.OPPONENT]
    assert "my earlier point" in ctx.our_recent_lines
    assert "bot said this" in ctx.our_recent_lines


def test_build_context_passes_voice_and_persona():
    profile = make_voice()
    target = cached("1", "x", OPP)
    ctx = build_context(REF, [target], target, bot_id="999", beneficiary=ME, voice=profile)
    assert ctx.voice is profile
    assert build_context(REF, [target], target, bot_id="999", beneficiary=ME).voice is None


def test_build_context_extra_opponents_tagged():
    target = cached("2", "pile-on", OPP)
    ally_of_opp = Participant(id="5", display_name="crony")
    records = [cached("1", "me too", ally_of_opp), target]
    ctx = build_context(
        REF, records, target, bot_id="999", beneficiary=ME, extra_opponent_ids=frozenset({"5"})
    )
    assert ctx.transcript[0].role is Role.OPPONENT
