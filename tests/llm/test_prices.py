"""Data-driven price table: bundled defaults load, longest-prefix precedence
is automatic, AW_PRICE_TABLE overrides fail loud, and the LiteLLM refresh
converts offline (the fetch itself is monkeypatched)."""

from __future__ import annotations

import json

import pytest

from argumentwinner.llm import prices as prices_mod
from argumentwinner.llm.prices import (
    LITELLM_URL,
    PriceTable,
    convert_litellm,
    load_price_table,
    main,
)


def test_bundled_table_loads_and_prices_known_models():
    table = load_price_table()
    assert table.lookup("claude-opus-4-8") is not None
    assert table.lookup("gpt-4o") is not None
    assert table.lookup("llama3.1") is None


def test_longest_prefix_wins_regardless_of_json_order():
    table = PriceTable(
        updated="2026-01-01",
        prices=[
            {"prefix": "gpt-4o", "input_per_mtok": 2.5, "output_per_mtok": 10.0},
            {"prefix": "gpt-4o-mini", "input_per_mtok": 0.15, "output_per_mtok": 0.6},
        ],
    )
    assert table.lookup("gpt-4o-mini-2024-07-18").prefix == "gpt-4o-mini"
    assert table.lookup("gpt-4o-2024-08-06").prefix == "gpt-4o"


def test_bundled_gpt_4o_mini_priced_as_mini():
    entry = load_price_table().lookup("gpt-4o-mini")
    assert entry.input_per_mtok == pytest.approx(0.15)


def test_custom_path_replaces_bundled_table(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps(
            {
                "updated": "2030-01-01",
                "prices": [{"prefix": "mymodel", "input_per_mtok": 1.0, "output_per_mtok": 2.0}],
            }
        )
    )
    table = load_price_table(str(path))
    assert table.updated == "2030-01-01"
    assert table.lookup("mymodel-v2").output_per_mtok == 2.0
    assert table.lookup("gpt-4o") is None  # replace, not merge


def test_missing_file_error_names_the_env_var(tmp_path):
    with pytest.raises(RuntimeError, match="AW_PRICE_TABLE"):
        load_price_table(str(tmp_path / "nope.json"))


def test_malformed_file_error_names_the_env_var(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(RuntimeError, match="AW_PRICE_TABLE"):
        load_price_table(str(path))


# ─── LiteLLM refresh ──────────────────────────────────────────────────────────

LITELLM_FIXTURE = {
    "sample_spec": {
        "litellm_provider": "one of https://docs.litellm.ai/docs/providers",
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
    },
    "gpt-4o-mini": {
        "litellm_provider": "openai",
        "input_cost_per_token": 1.5e-07,
        "output_cost_per_token": 6e-07,
    },
    "claude-opus-4-8": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 5e-06,
        "output_cost_per_token": 2.5e-05,
    },
    "anthropic/claude-opus-4-8": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 9e-06,  # duplicate under a prefixed key — first wins
        "output_cost_per_token": 9e-05,
    },
    "bedrock-model": {
        "litellm_provider": "bedrock",
        "input_cost_per_token": 1e-06,
        "output_cost_per_token": 1e-06,
    },
    "text-embedding-3-small": {"litellm_provider": "openai", "mode": "embedding"},
}


def test_litellm_conversion_scales_filters_and_dedupes():
    table = convert_litellm(LITELLM_FIXTURE, source="test", updated="2026-07-06")
    assert {e.prefix for e in table.prices} == {"gpt-4o-mini", "claude-opus-4-8"}
    assert table.lookup("gpt-4o-mini").input_per_mtok == pytest.approx(0.15)
    assert table.lookup("claude-opus-4-8").output_per_mtok == pytest.approx(25.0)


def test_refresh_cli_writes_reloadable_json(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_mod, "_fetch", lambda: LITELLM_FIXTURE)
    out = tmp_path / "refreshed.json"
    assert main(["--refresh", "--out", str(out)]) == 0
    table = load_price_table(str(out))
    assert table.source == LITELLM_URL
    assert table.lookup("gpt-4o-mini") is not None


def test_cli_without_refresh_flag_errors():
    with pytest.raises(SystemExit):
        main([])
