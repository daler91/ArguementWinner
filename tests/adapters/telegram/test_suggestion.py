from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argumentwinner.adapters.telegram.cache import CachedMessage
from argumentwinner.adapters.telegram.suggestion import (
    PendingSuggestion,
    SuggestionRegistry,
    keyboard_spec,
    make_callback_data,
    new_token,
    parse_callback,
    render_full_text,
    render_picker,
)
from argumentwinner.core.models import (
    CandidateResponse,
    ConversationRef,
    EngineResult,
    Participant,
    Persona,
    Risk,
)
from tests.conftest import make_analysis

REF = ConversationRef(platform="telegram", guild_id=None, channel_id="100")
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def result(*texts: str) -> EngineResult:
    return EngineResult(
        analysis=make_analysis(),
        candidates=tuple(
            CandidateResponse(
                text=t, persona=Persona.LOGICIAN, tactic_note="tactic", risk=Risk.SAFE
            )
            for t in texts
        ),
        state_digest="Tone: smug.",
    )


def pending(token: str = "tok", created_at: datetime = NOW) -> PendingSuggestion:
    target = CachedMessage(
        message_id="5", author=Participant(id="1", display_name="a"), content="x", timestamp=NOW
    )
    return PendingSuggestion(
        token=token,
        result=result("comeback one", "comeback two"),
        ref=REF,
        target=target,
        invoker_id="2",
        forced_persona=None,
        created_at=created_at,
    )


# ─── registry ─────────────────────────────────────────────────────────────────


def test_put_get_pop_roundtrip():
    registry = SuggestionRegistry(now=lambda: NOW)
    registry.put(pending("t1"))
    assert registry.get("t1") is not None
    assert registry.pop("t1") is not None
    assert registry.get("t1") is None


def test_ttl_expiry_via_injected_clock():
    clock = {"now": NOW}
    registry = SuggestionRegistry(ttl_seconds=1800, now=lambda: clock["now"])
    registry.put(pending("t1", created_at=NOW))
    clock["now"] = NOW + timedelta(seconds=1801)
    assert registry.get("t1") is None


def test_max_entries_evicts_oldest():
    registry = SuggestionRegistry(max_entries=2, now=lambda: NOW)
    for token in ("t1", "t2", "t3"):
        registry.put(pending(token))
    assert registry.get("t1") is None
    assert registry.get("t3") is not None


def test_bind_message():
    registry = SuggestionRegistry(now=lambda: NOW)
    registry.put(pending("t1"))
    registry.bind_message("t1", "chat9", "msg8")
    entry = registry.get("t1")
    assert (entry.picker_chat_id, entry.picker_message_id) == ("chat9", "msg8")


# ─── callback protocol ────────────────────────────────────────────────────────


def test_callback_roundtrip():
    data = make_callback_data("abc123", "s1")
    assert parse_callback(data) == ("abc123", "s1")


def test_foreign_and_malformed_payloads_rejected():
    assert parse_callback("other:abc:s1") is None
    assert parse_callback("aw:missing") is None
    assert parse_callback("") is None


def test_persona_action_keeps_its_colon():
    token, action = parse_callback(make_callback_data("t", "p:socratic"))
    assert action == "p:socratic"


def test_every_action_fits_64_callback_bytes():
    token = new_token()  # secrets.token_urlsafe(6) → 8 chars
    for row in keyboard_spec(token, 3):
        for _label, data in row:
            assert len(data.encode()) <= 64, data


def test_keyboard_spec_rows():
    rows = keyboard_spec("tok", 2)
    assert [label for label, _ in rows[0]] == ["Send #1", "Send #2"]
    assert [label for label, _ in rows[1]] == ["Full text", "🎲 Reroll"]
    assert len(rows[2]) == 4  # persona row


# ─── rendering ────────────────────────────────────────────────────────────────


def test_picker_contains_digest_candidates_and_badges():
    text = render_picker(result("first comeback", "second comeback"))
    assert "Tone: smug." in text
    assert "first comeback" in text
    assert "🟢 SAFE" in text


def test_picker_fits_telegram_limit_with_max_length_candidates():
    huge = result("x" * 2000, "y" * 2000, "z" * 2000)
    assert len(render_picker(huge)) <= 4096


def test_full_text_contains_complete_candidates():
    huge = "x" * 1500
    assert huge in render_full_text(result(huge))
