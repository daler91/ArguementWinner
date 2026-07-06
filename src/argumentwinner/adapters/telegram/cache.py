"""Adapter-owned message cache.

The Telegram Bot API cannot fetch message history, so this adapter keeps its
own bounded per-conversation window fed by incoming updates (precedent: the
CLI REPL's local transcript — adapter state, never core state). Long polling
also never delivers the bot's OWN outbound messages, so every successful send
must be record()ed here or the engine's never-contradict rule starves.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime

from argumentwinner.core.models import ConversationRef, Participant


@dataclass
class CachedMessage:
    # NOTE: Telegram message ids are small per-chat counters, NOT globally
    # unique — never key anything on a bare message_id across chats.
    message_id: str
    author: Participant
    content: str
    timestamp: datetime
    reply_to_id: str | None = None


class ChatCache:
    """Bounded per-ref message window. Refs are LRU-capped so a bot in many
    groups can't grow unbounded; messages per ref are capped at maxlen."""

    def __init__(self, maxlen: int = 24, max_refs: int = 256) -> None:
        self._maxlen = maxlen
        self._max_refs = max_refs
        self._chats: OrderedDict[ConversationRef, OrderedDict[str, CachedMessage]] = OrderedDict()

    def record(self, ref: ConversationRef, msg: CachedMessage) -> None:
        window = self._chats.get(ref)
        if window is None:
            window = OrderedDict()
            self._chats[ref] = window
        self._chats.move_to_end(ref)
        if msg.message_id in window:
            window[msg.message_id] = msg  # replace in place, keep position
        else:
            window[msg.message_id] = msg
            while len(window) > self._maxlen:
                window.popitem(last=False)
        while len(self._chats) > self._max_refs:
            self._chats.popitem(last=False)

    def update(self, ref: ConversationRef, message_id: str, content: str) -> bool:
        """Apply an edited_message in place. Returns False (and inserts
        nothing) when the id was evicted or never seen — re-inserting would
        make an old message masquerade as the newest turn."""
        window = self._chats.get(ref)
        if window is None or message_id not in window:
            return False
        window[message_id].content = content
        return True

    def get(self, ref: ConversationRef) -> tuple[CachedMessage, ...]:
        """Oldest-first snapshot of the window."""
        window = self._chats.get(ref)
        return tuple(window.values()) if window else ()

    def find(self, ref: ConversationRef, message_id: str) -> CachedMessage | None:
        window = self._chats.get(ref)
        return window.get(message_id) if window else None
