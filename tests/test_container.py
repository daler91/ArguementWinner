"""Composition-root wiring: voice-profile loading is loud on misconfig and
silent when off."""

from __future__ import annotations

import pytest

from argumentwinner.config import Settings
from argumentwinner.container import build_app
from argumentwinner.core.sessions import InMemorySessionStore
from argumentwinner.storage.sqlite_store import SqliteSessionStore

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


def test_app_meter_is_shared_with_the_provider():
    app = build_app(settings())
    assert app.provider._meter is app.meter


def test_custom_price_table_reaches_the_meter(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(
        '{"updated": "2030-01-01", "prices": '
        '[{"prefix": "m", "input_per_mtok": 1.0, "output_per_mtok": 2.0}]}'
    )
    app = build_app(settings(aw_price_table=str(path)))
    assert app.meter.prices.updated == "2030-01-01"


def test_missing_price_table_fails_fast(tmp_path):
    with pytest.raises(RuntimeError, match="AW_PRICE_TABLE"):
        build_app(settings(aw_price_table=str(tmp_path / "nope.json")))


def test_default_store_is_memory():
    assert isinstance(build_app(settings()).store, InMemorySessionStore)


def test_sqlite_store_selected_by_env(tmp_path):
    app = build_app(
        settings(aw_session_store="sqlite", aw_sqlite_path=str(tmp_path / "aw.db"))
    )
    assert isinstance(app.store, SqliteSessionStore)