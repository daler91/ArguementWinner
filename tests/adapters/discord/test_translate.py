from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from argumentwinner.adapters.discord.translate import (
    annotate_content,
    ref_for_channel,
    tag_role,
    to_turn,
)
from argumentwinner.core.models import Role


def msg(content="", attachments=(), embeds=(), stickers=(), author_id=1, bot=False):
    return SimpleNamespace(
        content=content,
        attachments=list(attachments),
        embeds=list(embeds),
        stickers=list(stickers),
        author=SimpleNamespace(
            id=author_id, name=f"user{author_id}", display_name=f"user{author_id}", bot=bot
        ),
        id=42,
        created_at=datetime(2026, 7, 6, tzinfo=UTC),
    )


# ─── attachment/embed annotation ──────────────────────────────────────────────


def test_plain_text_passes_through():
    assert annotate_content(msg("explain this")) == "explain this"


def test_image_only_message_never_reaches_engine_as_empty_string():
    annotated = annotate_content(msg("", attachments=["img.png"]))
    assert annotated == "[User attached an image/file]"


def test_taunt_plus_screenshot_keeps_both():
    annotated = annotate_content(msg("Explain this, genius.", attachments=["img.png"]))
    assert annotated == "Explain this, genius. [User attached an image/file]"


def test_embed_and_sticker_annotations():
    assert "[User shared a link/card]" in annotate_content(msg("look", embeds=["e"]))
    assert "[User sent a sticker]" in annotate_content(msg("", stickers=["s"]))


def test_empty_message_yields_no_turn():
    turn = to_turn(msg(""), bot_id="9", beneficiary_id="8", opponent_ids=frozenset())
    assert turn is None


# ─── role tagging ─────────────────────────────────────────────────────────────


def test_role_tagging_rules():
    kwargs = dict(bot_id="bot", beneficiary_id="me", opponent_ids=frozenset({"foe"}))
    assert tag_role("bot", True, **kwargs) is Role.US
    assert tag_role("me", False, **kwargs) is Role.US
    assert tag_role("foe", False, **kwargs) is Role.OPPONENT
    assert tag_role("rando", False, **kwargs) is Role.BYSTANDER


# ─── conversation refs ────────────────────────────────────────────────────────


def test_channel_ref():
    channel = SimpleNamespace(id=100, guild=SimpleNamespace(id=7))
    ref = ref_for_channel(channel)
    assert (ref.guild_id, ref.channel_id, ref.thread_id) == ("7", "100", None)


def test_thread_ref_scopes_separately_from_parent():
    guild = SimpleNamespace(id=7)
    parent = SimpleNamespace(id=100, guild=guild)
    # threads are detected via parent_id — always populated, unlike the
    # cache-dependent .parent property
    thread = SimpleNamespace(id=200, guild=guild, parent_id=100)
    assert ref_for_channel(thread) != ref_for_channel(parent)
    assert ref_for_channel(thread).thread_id == "200"
    assert ref_for_channel(thread).channel_id == "100"


def test_dm_ref_has_no_guild():
    dm = SimpleNamespace(id=300, guild=None)
    assert ref_for_channel(dm).guild_id is None
