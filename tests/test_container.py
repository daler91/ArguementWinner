"""Composition-root wiring: voice-profile loading is loud on misconfig and
silent when off."""

from __future__ import annotations

import pytest

from argumentwinner.config import Settings
from argumentwinner.container import build_app

VOICE_MD = """\
## Style notes
lowercase, terse

## Samples
- nah that's not how any of this works
"""


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, aw_llm_provider="fake", **kwargs)


def test_unset_voice_profile_means_off():
    assert build_app(settings()).voice is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_voice_profile_means_off(blank):
    assert build_app(settings(aw_voice_profile=blank)).voice is None


def test_missing_voice_profile_file_fails_fast(tmp_path):
    with pytest.raises(RuntimeError, match="AW_VOICE_PROFILE"):
        build_app(settings(aw_voice_profile=str(tmp_path / "nope.md")))


def test_voice_profile_loads_and_parses(tmp_path):
    path = tmp_path / "voice.md"
    path.write_text(VOICE_MD)
    app = build_app(settings(aw_voice_profile=str(path)))
    assert app.voice is not None
    assert "lowercase, terse" in app.voice.notes
    assert app.voice.samples == ("nah that's not how any of this works",)


def test_empty_voice_profile_file_fails_fast(tmp_path):
    path = tmp_path / "voice.md"
    path.write_text("## Samples\n\n")  # parses to an empty profile
    with pytest.raises(RuntimeError, match="empty profile"):
        build_app(settings(aw_voice_profile=str(path)))