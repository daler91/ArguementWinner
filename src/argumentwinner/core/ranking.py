"""Candidate ordering: a pure-function sanity pass over the LLM's best-first
order. No LLM, no port — deliberately not a Protocol in v1."""

from __future__ import annotations

from .models import CandidateResponse, Risk

_DUPLICATE_JACCARD = 0.7


def _tokens(text: str) -> set[str]:
    return {w for w in text.lower().split() if len(w) > 2}


def _near_duplicate(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= _DUPLICATE_JACCARD


def order_candidates(
    candidates: list[CandidateResponse],
    allowed_risks: frozenset[Risk],
    max_chars: int,
) -> tuple[CandidateResponse, ...]:
    """Trust the prompt's best-first order, then demote candidates that are
    overlength, exceed the spice cap, or near-duplicate an earlier candidate.
    Stable sort keeps the original order as tiebreak."""
    demerits: list[int] = []
    for i, c in enumerate(candidates):
        score = 0
        if c.risk not in allowed_risks:
            score += 3
        if len(c.text) > max_chars:
            score += 2
        if any(_near_duplicate(c.text, candidates[j].text) for j in range(i)):
            score += 1
        demerits.append(score)
    ordered = sorted(
        zip(demerits, range(len(candidates)), candidates, strict=True),
        key=lambda t: (t[0], t[1]),
    )
    return tuple(c for _, _, c in ordered)
