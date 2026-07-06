"""UsageMeter accumulation, the estimated-cost report, and the fake
provider's zero-token metering."""

from __future__ import annotations

import logging

import pytest

from argumentwinner.core.models import Analysis
from argumentwinner.core.ports import ChatMessage, LLMRequest, StructuredOutputError
from argumentwinner.llm.fake import FakeLLMProvider
from argumentwinner.llm.prices import PriceTable
from argumentwinner.llm.usage import UsageEvent, UsageMeter

REQUEST = LLMRequest(system="s", messages=(ChatMessage(role="user", content="x"),))


def event(model="claude-opus-4-8", provider="anthropic", inp=1000, out=500) -> UsageEvent:
    return UsageEvent(
        provider=provider, model=model, role_hint="generation", input_tokens=inp, output_tokens=out
    )


def test_accumulates_per_provider_and_model():
    meter = UsageMeter()
    meter.record(event())
    meter.record(event())
    meter.record(event(model="gpt-4o", provider="openai"))
    assert meter.snapshot()[("anthropic", "claude-opus-4-8")] == (2, 2000, 1000)
    assert meter.snapshot()[("openai", "gpt-4o")] == (1, 1000, 500)


def test_report_labels_estimates_and_prices_known_models():
    meter = UsageMeter()
    meter.record(event())
    report = meter.format_report()
    assert "estimate" in report.lower()
    line = next(ln for ln in report.splitlines() if "claude-opus-4-8" in ln)
    # 1000 in × $5/M + 500 out × $25/M
    assert "~$0.0175" in line


def test_unknown_model_gets_tokens_only_no_dollars():
    meter = UsageMeter()
    meter.record(event(model="llama3.1", provider="ollama"))
    line = next(ln for ln in meter.format_report().splitlines() if "llama3.1" in ln)
    assert "$" not in line
    assert "no price data" in line
    assert "excludes unpriced" in meter.format_report()


def test_gpt_4o_mini_priced_as_mini_not_gpt_4o():
    meter = UsageMeter()
    meter.record(event(model="gpt-4o-mini", provider="openai", inp=1_000_000, out=0))
    line = next(ln for ln in meter.format_report().splitlines() if "gpt-4o-mini" in ln)
    assert "~$0.1500" in line  # $2.50 here would mean the gpt-4o prefix matched


def test_injected_custom_table_is_used():
    table = PriceTable(
        updated="2030-12-31",
        prices=[{"prefix": "mymodel", "input_per_mtok": 100.0, "output_per_mtok": 200.0}],
    )
    meter = UsageMeter(table)
    meter.record(event(model="mymodel", provider="x", inp=1_000_000, out=0))
    report = meter.format_report()
    assert "2030-12-31" in report
    assert "~$100.0000" in report


def test_empty_meter_message():
    assert "No LLM calls" in UsageMeter().format_report()


def test_one_info_line_per_record_and_no_content(caplog):
    meter = UsageMeter()
    with caplog.at_level(logging.INFO, logger="argumentwinner.llm.usage"):
        meter.record(event())
        meter.record(event())
    records = [r for r in caplog.records if r.name == "argumentwinner.llm.usage"]
    assert len(records) == 2
    assert "in=1000" in records[0].getMessage()


# ─── fake provider metering ───────────────────────────────────────────────────


async def test_fake_provider_records_zero_token_events():
    meter = UsageMeter()
    fake = FakeLLMProvider(meter=meter)
    await fake.complete(REQUEST)
    await fake.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("fake", "fake")] == (2, 0, 0)


async def test_fake_records_before_a_queued_exception_raises():
    meter = UsageMeter()
    fake = FakeLLMProvider([StructuredOutputError("boom")], meter=meter)
    with pytest.raises(StructuredOutputError):
        await fake.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("fake", "fake")] == (1, 0, 0)
