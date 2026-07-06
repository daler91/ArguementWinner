from __future__ import annotations

import pytest

from argumentwinner.core.models import ArgumentSession, Persona, SpiceLevel
from argumentwinner.core.strategy import apply_stickiness, recommend, select_personas
from tests.conftest import REF, make_analysis


@pytest.mark.parametrize(
    ("analysis_kwargs", "spice", "expected"),
    [
        # analysis recommendation wins when concrete
        ({"recommended_persona": Persona.SOCRATIC}, SpiceLevel.MEDIUM, Persona.SOCRATIC),
        # AUTO + fallacies present -> logician
        (
            {"recommended_persona": Persona.AUTO},
            SpiceLevel.MEDIUM,
            Persona.LOGICIAN,
        ),
        # AUTO + no fallacies but dodged points -> socratic
        (
            {"recommended_persona": Persona.AUTO, "fallacies": []},
            SpiceLevel.MEDIUM,
            Persona.SOCRATIC,
        ),
        # AUTO + hostile tone, nothing else -> savage
        (
            {
                "recommended_persona": Persona.AUTO,
                "fallacies": [],
                "dodged_points": [],
                "tone": "hostile",
            },
            SpiceLevel.MEDIUM,
            Persona.SAVAGE,
        ),
        # same but MILD spice caps savage to diplomat
        (
            {
                "recommended_persona": Persona.AUTO,
                "fallacies": [],
                "dodged_points": [],
                "tone": "hostile",
            },
            SpiceLevel.MILD,
            Persona.DIPLOMAT,
        ),
        # AUTO + reasonable tone -> diplomat
        (
            {
                "recommended_persona": Persona.AUTO,
                "fallacies": [],
                "dodged_points": [],
                "tone": "reasonable",
            },
            SpiceLevel.MEDIUM,
            Persona.DIPLOMAT,
        ),
        # explicit savage recommendation capped on mild
        ({"recommended_persona": Persona.SAVAGE}, SpiceLevel.MILD, Persona.DIPLOMAT),
    ],
)
def test_recommend_table(analysis_kwargs, spice, expected):
    assert recommend(make_analysis(**analysis_kwargs), spice) is expected


def test_forced_persona_always_wins():
    analysis = make_analysis(recommended_persona=Persona.DIPLOMAT)
    primary, runner_up = select_personas(analysis, Persona.SAVAGE, SpiceLevel.SAVAGE)
    assert primary is Persona.SAVAGE
    assert runner_up is Persona.LOGICIAN


def test_runner_up_differs_from_primary():
    for persona in (Persona.LOGICIAN, Persona.SAVAGE, Persona.DIPLOMAT, Persona.SOCRATIC):
        primary, runner_up = select_personas(
            make_analysis(recommended_persona=persona), None, SpiceLevel.SAVAGE
        )
        assert primary is not runner_up


# ─── the whipsaw counter state machine ────────────────────────────────────────


def test_streak_increments_on_mismatch_and_pivots_at_two():
    session = ArgumentSession(ref=REF, persona=Persona.LOGICIAN)
    # first disagreement: hold, streak 1
    assert apply_stickiness(session, Persona.SAVAGE) is Persona.LOGICIAN
    assert session.persona_mismatch_streak == 1
    # second consecutive disagreement: pivot, streak resets
    assert apply_stickiness(session, Persona.SAVAGE) is Persona.SAVAGE
    assert session.persona is Persona.SAVAGE
    assert session.persona_mismatch_streak == 0


def test_streak_resets_on_match():
    session = ArgumentSession(ref=REF, persona=Persona.LOGICIAN, persona_mismatch_streak=1)
    assert apply_stickiness(session, Persona.LOGICIAN) is Persona.LOGICIAN
    assert session.persona_mismatch_streak == 0


def test_alternating_recommendations_never_pivot():
    session = ArgumentSession(ref=REF, persona=Persona.LOGICIAN)
    apply_stickiness(session, Persona.SAVAGE)  # streak 1
    apply_stickiness(session, Persona.LOGICIAN)  # match, reset
    apply_stickiness(session, Persona.SAVAGE)  # streak 1 again
    assert session.persona is Persona.LOGICIAN
    assert session.persona_mismatch_streak == 1


def test_auto_session_adopts_first_recommendation():
    session = ArgumentSession(ref=REF)  # persona AUTO
    assert apply_stickiness(session, Persona.SOCRATIC) is Persona.SOCRATIC
    assert session.persona is Persona.SOCRATIC
