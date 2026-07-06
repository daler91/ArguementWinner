"""Behavioral prompt tests (goldens pin the full renders; these pin edge
cases)."""

from __future__ import annotations

from argumentwinner.core import prompts
from argumentwinner.core.models import Persona, SpiceLevel
from tests.conftest import make_analysis, make_context, make_turn


def test_transcript_clamps_a_single_oversized_line_instead_of_dropping_it():
    huge = make_turn("x" * 10_000)
    rendered = prompts.render_transcript((huge,), max_chars=200)
    assert rendered != "(no prior messages)"
    assert len(rendered) <= 201  # the "…" prefix + clamped tail
    assert rendered.startswith("…")


def test_transcript_trims_oldest_first():
    turns = tuple(make_turn(f"message number {i} with some padding words") for i in range(50))
    rendered = prompts.render_transcript(turns, max_chars=300)
    assert "message number 49" in rendered  # newest survives
    assert "message number 0" not in rendered  # oldest trimmed


def test_generation_user_n1_asks_for_exactly_one_candidate():
    text = prompts.generation_user(
        make_context(), make_analysis(), Persona.LOGICIAN, Persona.SOCRATIC, 1
    )
    assert "Write 1 candidate reply in the logician persona." in text
    assert "and 1 in the" not in text  # no contradictory runner-up ask


def test_generation_system_renders_the_configured_length_cap():
    assert "under 900 characters" in prompts.generation_system(SpiceLevel.MEDIUM, 900)
    assert "under 1800 characters" in prompts.generation_system(SpiceLevel.MEDIUM)
