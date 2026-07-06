"""Voice-profile parser: markdown in, VoiceProfile out. Forgiving format —
sample-headed sections contribute bullets, everything else is notes."""

from __future__ import annotations

from argumentwinner.core.voice import parse_voice_profile

FULL = """\
# Voice profile

## Style notes
- mostly lowercase, minimal punctuation
- dry, deadpan

## Samples
- nah that's not how any of this works
- source: you made it up
"""


def test_full_format_populates_notes_and_samples():
    profile = parse_voice_profile(FULL)
    assert "mostly lowercase" in profile.notes
    assert "deadpan" in profile.notes
    assert profile.samples == (
        "nah that's not how any of this works",
        "source: you made it up",
    )


def test_star_bullets_parse_too():
    profile = parse_voice_profile("## Samples\n* first one\n* second one\n")
    assert profile.samples == ("first one", "second one")


def test_no_headings_treats_whole_file_as_notes():
    profile = parse_voice_profile("i type in lowercase\nand keep it short\n")
    assert profile.notes == "i type in lowercase\nand keep it short"
    assert profile.samples == ()


def test_samples_only_file_has_empty_notes():
    profile = parse_voice_profile("## Samples\n- just this\n")
    assert profile.notes == ""
    assert profile.samples == ("just this",)


def test_preamble_before_first_heading_lands_in_notes_and_title_is_dropped():
    profile = parse_voice_profile("# My voice\nsome preamble here\n## Samples\n- msg\n")
    assert "some preamble here" in profile.notes
    assert "My voice" not in profile.notes


def test_heading_match_is_case_insensitive():
    profile = parse_voice_profile("## STYLE NOTES\nterse\n## SAMPLES\n- hey\n")
    assert profile.notes == "terse"
    assert profile.samples == ("hey",)


def test_empty_and_whitespace_files_parse_to_empty_profile():
    for text in ("", "   \n\n  "):
        profile = parse_voice_profile(text)
        assert profile.notes == ""
        assert profile.samples == ()


def test_non_bullet_lines_in_samples_section_are_ignored():
    profile = parse_voice_profile(
        "## Samples\nthis prose line is not a sample\n- but this is\n"
    )
    assert profile.samples == ("but this is",)


def test_section_after_samples_returns_to_notes():
    profile = parse_voice_profile(
        "## Samples\n- a sample\n## More notes\nback to notes\n"
    )
    assert profile.samples == ("a sample",)
    assert "back to notes" in profile.notes
