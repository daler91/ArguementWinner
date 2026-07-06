"""Domain models for the argument engine.

Frozen dataclasses for engine inputs (built by adapters); pydantic models for
anything parsed from LLM output (they double as structured-output schemas).

This module — like everything under core/ — must import only stdlib + pydantic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Role(StrEnum):
    OPPONENT = "opponent"
    US = "us"
    BYSTANDER = "bystander"


class Persona(StrEnum):
    AUTO = "auto"
    LOGICIAN = "logician"
    SAVAGE = "savage"
    DIPLOMAT = "diplomat"
    SOCRATIC = "socratic"


class Risk(StrEnum):
    SAFE = "safe"
    SPICY = "spicy"
    NUCLEAR = "nuclear"


class SpiceLevel(StrEnum):
    MILD = "mild"
    MEDIUM = "medium"
    SAVAGE = "savage"


@dataclass(frozen=True)
class ConversationRef:
    """The scoping key for all state. `platform` is an open string ("discord",
    "cli", "telegram", ...) so new platforms need zero core edits."""

    platform: str
    guild_id: str | None
    channel_id: str
    thread_id: str | None = None


@dataclass(frozen=True)
class Participant:
    id: str
    display_name: str
    is_bot: bool = False


@dataclass(frozen=True)
class ArgumentTurn:
    role: Role
    author: Participant
    content: str
    message_id: str
    timestamp: datetime


@dataclass(frozen=True)
class ArgumentContext:
    """Everything the engine needs for one invocation.

    The adapter builds this from a FRESH history fetch every time — the engine
    never fetches or stores conversation content, so message edits/deletions
    are handled for free.
    """

    ref: ConversationRef
    target: ArgumentTurn
    transcript: tuple[ArgumentTurn, ...]
    beneficiary: Participant
    forced_persona: Persona | None = None
    our_recent_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineSettings:
    spice: SpiceLevel = SpiceLevel.MEDIUM
    max_reply_chars: int = 1800
    suggest_candidates: int = 3


# ─── LLM-parsed models (pydantic; used directly as structured-output schemas) ──


class Fallacy(BaseModel):
    name: str = Field(description="Name of the logical fallacy, e.g. 'strawman'")
    quote: str = Field(description="EXACT text quoted from the opponent's message")
    explanation: str = Field(description="One sentence on why it is that fallacy")


class Analysis(BaseModel):
    claims: list[str] = Field(description="Distinct claims the opponent is making")
    fallacies: list[Fallacy] = Field(description="Logical fallacies present, with exact quotes")
    tone: str = Field(description="Opponent's tone: hostile, smug, reasonable, mocking, ...")
    weak_points: list[str] = Field(description="Weakest parts of the opponent's position")
    dodged_points: list[str] = Field(
        description="Points or questions from our side that the opponent ignored"
    )
    recommended_persona: Persona = Field(
        description="Best persona to win: logician, savage, diplomat or socratic"
    )
    opponent_summary: str = Field(description="One-line summary of the opponent's position")

    @classmethod
    def fallback(cls) -> Analysis:
        """Degraded analysis used when the LLM's structured output can't be
        parsed — a parse failure must never kill a reply."""
        return cls(
            claims=[],
            fallacies=[],
            tone="unknown",
            weak_points=[],
            dodged_points=[],
            recommended_persona=Persona.LOGICIAN,
            opponent_summary="unknown",
        )


class GeneratedCandidate(BaseModel):
    text: str = Field(description="The reply, ready to send verbatim")
    persona: Persona = Field(description="Persona this reply is written in")
    tactic_note: str = Field(
        description=(
            "One short line on the tactic, e.g. "
            "'calls out the strawman, re-asks the dodged question'"
        )
    )
    risk: Risk = Field(description="How inflammatory the reply is: safe, spicy or nuclear")

    @field_validator("persona")
    @classmethod
    def _no_auto(cls, v: Persona) -> Persona:
        # AUTO is a request-side sentinel, not a writing style — an LLM that
        # emits it must not leak "auto" into the UI or strategy tables.
        return Persona.LOGICIAN if v is Persona.AUTO else v


class GenerationBatch(BaseModel):
    candidates: list[GeneratedCandidate] = Field(description="Candidate replies, best first")


# ─── Engine outputs (adapter-agnostic render contract) ─────────────────────────


@dataclass(frozen=True)
class CandidateResponse:
    """Any platform's picker UI needs nothing beyond these fields."""

    text: str
    persona: Persona
    tactic_note: str
    risk: Risk


@dataclass(frozen=True)
class EngineResult:
    analysis: Analysis
    candidates: tuple[CandidateResponse, ...]
    state_digest: str


# ─── Combat session (control state only — conversation content is never stored) ─


@dataclass
class ArgumentSession:
    ref: ConversationRef
    opponent_ids: set[str] = field(default_factory=set)
    persona: Persona = Persona.AUTO
    # True when the user forced the persona at /combat start — the stickiness
    # counter must never pivot away from a user-forced persona.
    persona_forced: bool = False
    persona_mismatch_streak: int = 0
    replies_sent: int = 0
    last_reply_at: datetime | None = None
    expires_at: datetime | None = None
