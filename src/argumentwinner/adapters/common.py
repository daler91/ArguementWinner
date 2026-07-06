"""Cross-platform adapter helpers: pure text shaping, role tagging and
engagement rules. No platform SDK imports — extracted once the second
messaging adapter (Telegram) proved the duplication was real."""

from __future__ import annotations

from argumentwinner.core.models import ArgumentSession, Role

BOUNDARIES = (". ", "! ", "? ", "\n")


def cut(text: str, limit: int) -> tuple[str, int]:
    """Return (chunk, consumed) where `consumed` is the number of ORIGINAL
    characters the chunk covers — the '…' continuation marker is display-only
    and never counts as consumed input, so splitting loses nothing."""
    if len(text) <= limit:
        return text, len(text)
    window = text[:limit]
    best = max(window.rfind(b) + len(b.rstrip()) for b in BOUNDARIES)
    if best > limit // 4:
        return window[:best].rstrip(), best
    space = window.rfind(" ")
    if space > limit // 4:
        return window[:space].rstrip() + "…", space
    return window[: limit - 1].rstrip() + "…", limit - 1


def truncate_at_boundary(text: str, limit: int) -> str:
    """Hard backstop: cut at the last sentence boundary under the limit,
    falling back to a word boundary, then a plain slice."""
    return cut(text, limit)[0]


def split_message(text: str, limit: int) -> list[str]:
    """Chunk genuinely long content at sentence boundaries; each chunk fits
    the platform limit and no original characters are lost across chunks."""
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        chunk, consumed = cut(remaining, limit)
        chunks.append(chunk)
        remaining = remaining[consumed:].lstrip()
    return chunks


def tag_role(
    author_id: str,
    author_is_bot: bool,
    *,
    bot_id: str,
    beneficiary_id: str,
    opponent_ids: frozenset[str],
) -> Role:
    if author_id == bot_id or author_id == beneficiary_id:
        return Role.US
    if author_id in opponent_ids:
        return Role.OPPONENT
    return Role.BYSTANDER


def should_engage(
    *,
    author_id: str,
    author_is_bot: bool,
    is_webhook: bool,
    bot_id: str,
    mentions_bot: bool,
    session: ArgumentSession | None,
    reply_to_bots: bool,
) -> bool:
    """Pure auto-combat engagement rule, shared across platforms.
    `is_webhook` covers any proxy author (Discord webhooks; Telegram
    sender_chat / via_bot messages)."""
    if author_id == bot_id or is_webhook:
        return False
    if author_is_bot and not reply_to_bots:
        return False
    if mentions_bot:
        return True
    return session is not None and author_id in session.opponent_ids
