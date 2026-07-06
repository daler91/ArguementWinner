"""Persona selection: pure functions, table-driven, spice-capped."""

from __future__ import annotations

from .models import Analysis, ArgumentSession, Persona, Risk, SpiceLevel

# Which persona backs up which — used for the runner-up candidate.
COMPLEMENT: dict[Persona, Persona] = {
    Persona.LOGICIAN: Persona.SOCRATIC,
    Persona.SAVAGE: Persona.LOGICIAN,
    Persona.DIPLOMAT: Persona.SOCRATIC,
    Persona.SOCRATIC: Persona.LOGICIAN,
}

ALLOWED_RISKS: dict[SpiceLevel, frozenset[Risk]] = {
    SpiceLevel.MILD: frozenset({Risk.SAFE}),
    SpiceLevel.MEDIUM: frozenset({Risk.SAFE, Risk.SPICY}),
    SpiceLevel.SAVAGE: frozenset({Risk.SAFE, Risk.SPICY, Risk.NUCLEAR}),
}

# How many consecutive disagreeing analyses it takes to pivot a sticky
# combat-session persona.
PIVOT_STREAK = 2


def _cap_for_spice(persona: Persona, spice: SpiceLevel) -> Persona:
    if persona is Persona.SAVAGE and spice is SpiceLevel.MILD:
        return Persona.DIPLOMAT
    return persona


def recommend(analysis: Analysis, spice: SpiceLevel) -> Persona:
    """The engine's own read of the best persona, used when the analysis
    recommendation is AUTO/absent and as a sanity anchor."""
    persona = analysis.recommended_persona
    if persona is Persona.AUTO:
        if analysis.fallacies:
            persona = Persona.LOGICIAN
        elif analysis.dodged_points:
            persona = Persona.SOCRATIC
        elif analysis.tone in ("hostile", "smug", "mocking", "condescending"):
            persona = Persona.SAVAGE
        else:
            persona = Persona.DIPLOMAT
    return _cap_for_spice(persona, spice)


def select_personas(
    analysis: Analysis,
    forced: Persona | None,
    spice: SpiceLevel,
) -> tuple[Persona, Persona]:
    """Return (primary, runner_up). A forced persona always wins; otherwise the
    (spice-capped) recommendation from analysis."""
    if forced is not None and forced is not Persona.AUTO:
        primary = forced
    else:
        primary = recommend(analysis, spice)
    runner_up = _cap_for_spice(COMPLEMENT[primary], spice)
    return primary, runner_up


def apply_stickiness(session: ArgumentSession, recommended: Persona) -> Persona:
    """Sticky combat-session persona with an explicit whipsaw counter.

    If the fresh recommendation disagrees with the session persona, increment
    `persona_mismatch_streak`; at >= PIVOT_STREAK pivot the session persona and
    reset the counter. On agreement, reset to 0. Mutates the session; returns
    the persona to use this turn.
    """
    if session.persona is Persona.AUTO:
        session.persona = recommended
        session.persona_mismatch_streak = 0
        return session.persona
    if recommended is session.persona:
        session.persona_mismatch_streak = 0
        return session.persona
    session.persona_mismatch_streak += 1
    if session.persona_mismatch_streak >= PIVOT_STREAK:
        session.persona = recommended
        session.persona_mismatch_streak = 0
    return session.persona
