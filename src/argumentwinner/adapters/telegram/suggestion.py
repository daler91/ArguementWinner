"""Suggestion-mode plumbing: the pending-picker registry and pure render /
callback-protocol helpers. No telegram imports — bot.py maps these onto
InlineKeyboardButton rows.

Telegram has no ephemeral messages and callback_data is capped at 64 BYTES,
so candidates live server-side in this registry (the Telegram analogue of
candidates living on the Discord View) and buttons carry only
"aw:{token}:{action}".
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from argumentwinner.core.models import ConversationRef, EngineResult, Persona

from .cache import CachedMessage

CB_PREFIX = "aw"
_RISK_BADGES = {"safe": "🟢 SAFE", "spicy": "🟠 SPICY", "nuclear": "☢️ NUCLEAR"}

# One picker message must fit Telegram's 4096-char limit with 3 candidates.
_PICKER_CANDIDATE_CLAMP = 1000


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class PendingSuggestion:
    token: str
    result: EngineResult
    ref: ConversationRef  # origin chat — where Send posts the reply
    target: CachedMessage  # kept whole so reroll survives cache eviction
    invoker_id: str  # only the invoker may press buttons
    forced_persona: Persona | None
    created_at: datetime
    picker_chat_id: str | None = None
    picker_message_id: str | None = None
    # Synchronous double-click guard, mirrors CandidateView._working.
    working: bool = field(default=False)


class SuggestionRegistry:
    def __init__(
        self,
        max_entries: int = 256,
        ttl_seconds: float = 1800.0,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._max_entries = max_entries
        self._ttl = timedelta(seconds=ttl_seconds)
        self._now = now
        self._entries: OrderedDict[str, PendingSuggestion] = OrderedDict()

    def put(self, pending: PendingSuggestion) -> str:
        self._entries[pending.token] = pending
        self._entries.move_to_end(pending.token)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return pending.token

    def get(self, token: str) -> PendingSuggestion | None:
        pending = self._entries.get(token)
        if pending is None:
            return None
        if self._now() - pending.created_at > self._ttl:
            del self._entries[token]
            return None
        return pending

    def bind_message(self, token: str, chat_id: str, message_id: str) -> None:
        pending = self._entries.get(token)
        if pending is not None:
            pending.picker_chat_id = chat_id
            pending.picker_message_id = message_id

    def pop(self, token: str) -> PendingSuggestion | None:
        return self._entries.pop(token, None)


def new_token() -> str:
    return secrets.token_urlsafe(6)


# ─── callback protocol ("aw:{token}:{action}", ≤ 64 bytes) ────────────────────


def make_callback_data(token: str, action: str) -> str:
    return f"{CB_PREFIX}:{token}:{action}"


def parse_callback(data: str) -> tuple[str, str] | None:
    """Returns (token, action) or None for foreign/malformed payloads."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != CB_PREFIX:
        return None
    return parts[1], parts[2]


def keyboard_spec(token: str, n_candidates: int) -> list[list[tuple[str, str]]]:
    """Rows of (label, callback_data) — bot.py maps these onto
    InlineKeyboardButton. Persona buttons are reroll-with-persona (Telegram
    has no select menus)."""
    rows: list[list[tuple[str, str]]] = []
    if n_candidates:
        rows.append(
            [
                (f"Send #{i + 1}", make_callback_data(token, f"s{i}"))
                for i in range(min(3, n_candidates))
            ]
        )
    rows.append(
        [
            ("Full text", make_callback_data(token, "ft")),
            ("🎲 Reroll", make_callback_data(token, "rr")),
        ]
    )
    rows.append(
        [
            (p.value.title(), make_callback_data(token, f"p:{p.value}"))
            for p in (Persona.LOGICIAN, Persona.SAVAGE, Persona.DIPLOMAT, Persona.SOCRATIC)
        ]
    )
    return rows


# ─── rendering (plain text — NO parse_mode: LLM text with _*[ breaks Markdown) ─


def _clamp(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_picker(result: EngineResult) -> str:
    lines = [f"~ {result.state_digest}", ""]
    for i, c in enumerate(result.candidates[:3], start=1):
        badge = _RISK_BADGES.get(c.risk.value, c.risk.value)
        lines.append(f"#{i} · {c.persona.value} · {badge} — {_clamp(c.tactic_note, 200)}")
        lines.append(_clamp(c.text, _PICKER_CANDIDATE_CLAMP))
        lines.append("")
    lines.append("Send #N posts it as a reply; Full text gives copyable versions.")
    return "\n".join(lines).strip()


def render_full_text(result: EngineResult) -> str:
    blocks = []
    for i, c in enumerate(result.candidates[:3], start=1):
        blocks.append(f"#{i}\n{c.text}")
    return "\n\n".join(blocks) or "No candidates."
