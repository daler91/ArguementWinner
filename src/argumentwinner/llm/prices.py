"""Model pricing as DATA, never code: the bundled prices.json ships defaults,
AW_PRICE_TABLE points at your own file, and `--refresh` regenerates one from
the community-maintained LiteLLM table. Adding a model or fixing a price is a
JSON edit (or one command) — no Python changes.

Match precedence is automatic: entries are sorted longest-prefix-first at
validation time, so `gpt-4o-mini` always wins over `gpt-4o` regardless of how
a file happens to be ordered.

Metering itself never touches the network — the LiteLLM fetch runs only when
you explicitly invoke `python -m argumentwinner.llm.prices --refresh`.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ValidationError, model_validator

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
_LITELLM_PROVIDERS = {"anthropic", "openai"}


class PriceEntry(BaseModel):
    prefix: str
    input_per_mtok: float
    output_per_mtok: float


class PriceTable(BaseModel):
    updated: str
    source: str = "manual"
    prices: list[PriceEntry]

    @model_validator(mode="after")
    def _sort_longest_prefix_first(self) -> PriceTable:
        self.prices.sort(key=lambda e: (-len(e.prefix), e.prefix))
        return self

    def lookup(self, model: str) -> PriceEntry | None:
        return next((e for e in self.prices if model.startswith(e.prefix)), None)


def load_price_table(path: str | None = None) -> PriceTable:
    """None → the bundled table; a path → the user's replacement table
    (typically written by `--refresh`), failing fast on problems so a broken
    AW_PRICE_TABLE surfaces at startup, not mid-argument."""
    if path is None:
        text = resources.files(__package__).joinpath("prices.json").read_text("utf-8")
        return PriceTable.model_validate_json(text)
    try:
        text = Path(path).expanduser().read_text("utf-8")
        return PriceTable.model_validate_json(text)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"AW_PRICE_TABLE={path!r} but no such file exists — generate one with "
            f"`python -m argumentwinner.llm.prices --refresh --out {path}` "
            "or unset the variable"
        ) from exc
    except ValidationError as exc:
        raise RuntimeError(f"AW_PRICE_TABLE={path!r} is not a valid price table:\n{exc}") from exc


# ─── refresh from the LiteLLM community table ─────────────────────────────────


def convert_litellm(raw: dict, *, source: str, updated: str) -> PriceTable:
    """Pure conversion of LiteLLM's model_prices_and_context_window.json:
    keep anthropic/openai entries with per-token costs, scale to per-mtok,
    model names become exact-match prefixes (longest-first sort makes exact
    names beat any shorter generic prefix)."""
    by_prefix: dict[str, PriceEntry] = {}
    for model_name, info in raw.items():
        if not isinstance(info, dict):
            continue
        provider = info.get("litellm_provider")
        if provider not in _LITELLM_PROVIDERS:
            continue
        cost_in = info.get("input_cost_per_token")
        cost_out = info.get("output_cost_per_token")
        if not isinstance(cost_in, int | float) or not isinstance(cost_out, int | float):
            continue
        # Some entries carry a "provider/model" key — store the bare name,
        # which is what API responses report back.
        name = model_name.removeprefix(f"{provider}/")
        by_prefix.setdefault(
            name,
            PriceEntry(
                prefix=name, input_per_mtok=cost_in * 1e6, output_per_mtok=cost_out * 1e6
            ),
        )
    return PriceTable(updated=updated, source=source, prices=list(by_prefix.values()))


def _fetch(url: str = LITELLM_URL) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 — https const
        return json.load(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m argumentwinner.llm.prices",
        description="Maintain the ArgumentWinner model price table.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="fetch current prices from the LiteLLM community table and write them out",
    )
    parser.add_argument(
        "--out",
        default="aw_prices.json",
        help="where to write the refreshed table (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if not args.refresh:
        parser.error("nothing to do — pass --refresh")
    table = convert_litellm(
        _fetch(),
        source=LITELLM_URL,
        updated=datetime.now(UTC).date().isoformat(),
    )
    Path(args.out).write_text(table.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(table.prices)} model prices to {args.out} — "
        f"set AW_PRICE_TABLE={args.out} to use them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
