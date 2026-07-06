"""Behavioral prompt tests (goldens pin the full renders; these pin edge
cases)."""

from __future__ import annotations

from argumentwinner.core import prompts
from argumentwinner.core.models import Persona, SpiceLevel, VoiceProfile
from tests.conftest import make_analysis, make_context, make_turn, make_voice


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


# ─── voice profile ────────────────────────────────────────────────────────────


def test_generation_system_has_no_voice_section_without_a_profile():
    assert "user's voice" not in prompts.generation_system(SpiceLevel.MEDIUM)


def test_generation_system_with_voice_includes_notes_samples_and_framing():
    rendered = prompts.generation_system(SpiceLevel.MEDIUM, voice=make_voice())
    assert "lowercase, terse, dry humor" in rendered
    assert "nah that's not how any of this works" in rendered  # sample verbatim
    assert "persona controls the STRATEGY" in rendered
    assert "voice controls the WORDING" in rendered


def test_empty_voice_profile_is_byte_identical_to_no_profile():
    assert prompts.generation_system(SpiceLevel.MEDIUM, voice=VoiceProfile()) == (
        prompts.generation_system(SpiceLevel.MEDIUM)
    )


def test_render_voice_keeps_the_first_samples_when_clamping():
    profile = VoiceProfile(samples=tuple(f"sample number {i}" for i in range(30)))
    rendered = prompts.render_voice(profile, max_samples=20)
    assert "sample number 0" in rendered  # user's ordering is intentional
    assert "sample number 19" in rendered
    assert "sample number 20" not in rendered


def test_render_voice_respects_the_char_budget():
    profile = VoiceProfile(
        notes="n" * 10_000, samples=tuple("x" * 500 for _ in range(20))
    )
    rendered = prompts.render_voice(profile, max_chars=2000)
    assert len(rendered) <= 2100  # header block + clamped content stays bounded
