from __future__ import annotations

import sys
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from argumentwinner.core.models import (
    Analysis,
    ArgumentContext,
    ArgumentTurn,
    ConversationRef,
    Fallacy,
    GeneratedCandidate,
    GenerationBatch,
    Participant,
    Persona,
    Risk,
    Role,
    VoiceProfile,
)

_ids = count(1)

REF = ConversationRef(platform="test", guild_id="g1", channel_id="c1")
OPPONENT = Participant(id="opp", display_name="Opponent")
US = Participant(id="me", display_name="Me")


def make_turn(
    content: str,
    role: Role = Role.OPPONENT,
    author: Participant | None = None,
) -> ArgumentTurn:
    if author is None:
        author = OPPONENT if role is Role.OPPONENT else US
    return ArgumentTurn(
        role=role,
        author=author,
        content=content,
        message_id=f"m{next(_ids)}",
        timestamp=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
    )


def make_context(
    target_content: str = "Tabs are objectively better than spaces, everyone knows this.",
    prior: tuple[ArgumentTurn, ...] = (),
    forced_persona: Persona | None = None,
    our_recent_lines: tuple[str, ...] = (),
    voice: VoiceProfile | None = None,
) -> ArgumentContext:
    target = make_turn(target_content)
    return ArgumentContext(
        ref=REF,
        target=target,
        transcript=(*prior, target),
        beneficiary=US,
        forced_persona=forced_persona,
        our_recent_lines=our_recent_lines,
        voice=voice,
    )


def make_voice(
    notes: str = "lowercase, terse, dry humor, never uses exclamation marks",
    samples: tuple[str, ...] = (
        "nah that's not how any of this works",
        "source: you made it up",
    ),
) -> VoiceProfile:
    return VoiceProfile(notes=notes, samples=samples)


def make_analysis(**overrides) -> Analysis:
    base = dict(
        claims=["tabs are better than spaces"],
        fallacies=[
            Fallacy(
                name="appeal to popularity",
                quote="everyone knows this",
                explanation="popularity is not evidence of correctness",
            )
        ],
        tone="smug",
        weak_points=["no argument beyond assertion"],
        dodged_points=["accessibility of configurable tab width"],
        recommended_persona=Persona.LOGICIAN,
        opponent_summary="asserts tabs superiority without evidence",
    )
    base.update(overrides)
    return Analysis(**base)


def make_batch(*texts_and_risks: tuple[str, Persona, Risk]) -> GenerationBatch:
    return GenerationBatch(
        candidates=[
            GeneratedCandidate(text=t, persona=p, tactic_note=f"tactic for {t[:20]}", risk=r)
            for t, p, r in texts_and_risks
        ]
    )


@pytest.fixture
def analysis() -> Analysis:
    return make_analysis()
