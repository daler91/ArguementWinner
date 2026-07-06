"""Token/cost metering. Providers record one UsageEvent per API roundtrip
(retries included — they were real spend); the meter accumulates per
(provider, model) and prices totals from the data-driven table in prices.py.

Costs are always labeled ESTIMATES: the table is a snapshot, not a bill.
One INFO log line per event carries counts only — never request content, so
there is no transcript leak surface. Everything runs on the single event
loop, so plain dicts need no locking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .prices import PriceTable, load_price_table

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageEvent:
    provider: str
    model: str
    role_hint: str
    input_tokens: int
    output_tokens: int


@dataclass
class _Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class UsageMeter:
    def __init__(self, prices: PriceTable | None = None) -> None:
        self._prices = prices
        self._totals: dict[tuple[str, str], _Totals] = {}

    @property
    def prices(self) -> PriceTable:
        if self._prices is None:
            self._prices = load_price_table()
        return self._prices

    def record(self, event: UsageEvent) -> None:
        totals = self._totals.setdefault((event.provider, event.model), _Totals())
        totals.calls += 1
        totals.input_tokens += event.input_tokens
        totals.output_tokens += event.output_tokens
        log.info(
            "llm usage: provider=%s model=%s role=%s in=%d out=%d",
            event.provider,
            event.model,
            event.role_hint,
            event.input_tokens,
            event.output_tokens,
        )

    def snapshot(self) -> dict[tuple[str, str], tuple[int, int, int]]:
        """(provider, model) → (calls, input_tokens, output_tokens)."""
        return {k: (t.calls, t.input_tokens, t.output_tokens) for k, t in self._totals.items()}

    def format_report(self) -> str:
        if not self._totals:
            return "No LLM calls recorded yet."
        lines = [f"LLM usage — costs are estimates (price table dated {self.prices.updated}):"]
        total_cost = 0.0
        any_unpriced = False
        for (provider, model), t in sorted(self._totals.items()):
            line = (
                f"  {provider}/{model}: {t.calls} call(s), "
                f"{t.input_tokens:,} in / {t.output_tokens:,} out tokens"
            )
            entry = self.prices.lookup(model)
            if entry is not None:
                cost = (
                    t.input_tokens * entry.input_per_mtok
                    + t.output_tokens * entry.output_per_mtok
                ) / 1e6
                total_cost += cost
                line += f", ~${cost:.4f}"
            else:
                any_unpriced = True
                line += ", no price data"
            lines.append(line)
        suffix = " (excludes unpriced models)" if any_unpriced else ""
        lines.append(f"  Estimated total: ~${total_cost:.4f}{suffix}")
        return "\n".join(lines)
