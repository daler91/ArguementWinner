"""The extracted cross-platform helpers, exercised at a non-Discord limit.
(The Discord suites keep testing the delegating wrappers.)"""

from __future__ import annotations

from argumentwinner.adapters.common import (
    should_engage,
    split_message,
    tag_role,
    truncate_at_boundary,
)
from argumentwinner.core.models import Role


def test_split_at_telegram_limit():
    sentences = " ".join(f"Sentence number {i} makes a point." for i in range(500))
    chunks = split_message(sentences, 4096)
    assert all(len(c) <= 4096 for c in chunks)
    assert len(chunks) > 1


def test_truncate_requires_explicit_limit():
    assert len(truncate_at_boundary("word " * 2000, 4096)) <= 4096


def test_moved_helpers_are_importable_and_behave():
    assert (
        tag_role("1", False, bot_id="9", beneficiary_id="2", opponent_ids=frozenset({"1"}))
        is Role.OPPONENT
    )
    assert should_engage(
        author_id="1",
        author_is_bot=False,
        is_webhook=False,
        bot_id="9",
        mentions_bot=True,
        session=None,
        reply_to_bots=False,
    )
