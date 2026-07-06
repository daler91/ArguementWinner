"""Structured-output robustness for the Anthropic provider, tested hardest:
malformed tool input → retry once with the error fed back → raise."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from argumentwinner.core.models import Analysis
from argumentwinner.core.ports import ChatMessage, LLMRequest, StructuredOutputError
from argumentwinner.llm.anthropic_provider import AnthropicProvider
from argumentwinner.llm.usage import UsageMeter
from tests.conftest import make_analysis

REQUEST = LLMRequest(system="sys", messages=(ChatMessage(role="user", content="analyze"),))


def _tool_use_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=payload)],
        model="stub-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def _text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        model="stub-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class StubClient:
    def __init__(self, responses: list) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses)
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def make_provider(
    responses: list, meter: UsageMeter | None = None
) -> tuple[AnthropicProvider, StubClient]:
    stub = StubClient(responses)
    return AnthropicProvider(model="stub-model", client=stub, meter=meter), stub


VALID = make_analysis().model_dump()


async def test_happy_path_forces_the_emit_tool():
    provider, stub = make_provider([_tool_use_response(VALID)])
    result = await provider.complete_structured(REQUEST, Analysis)
    assert isinstance(result, Analysis)
    call = stub.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "emit"}
    assert call["tools"][0]["input_schema"] == Analysis.model_json_schema()


async def test_malformed_input_retries_once_with_error_fed_back():
    provider, stub = make_provider(
        [_tool_use_response({"claims": "not-a-list"}), _tool_use_response(VALID)]
    )
    result = await provider.complete_structured(REQUEST, Analysis)
    assert isinstance(result, Analysis)
    assert len(stub.calls) == 2
    retry_messages = stub.calls[1]["messages"]
    assert "failed validation" in retry_messages[-1]["content"]


async def test_two_failures_raise_structured_output_error():
    provider, stub = make_provider(
        [_tool_use_response({"bogus": 1}), _tool_use_response({"bogus": 2})]
    )
    with pytest.raises(StructuredOutputError):
        await provider.complete_structured(REQUEST, Analysis)
    assert len(stub.calls) == 2


async def test_missing_tool_use_block_also_retries_then_raises():
    provider, stub = make_provider([_text_response("chatty"), _text_response("still chatty")])
    with pytest.raises(StructuredOutputError):
        await provider.complete_structured(REQUEST, Analysis)
    assert len(stub.calls) == 2


async def test_complete_joins_text_blocks_and_reports_usage():
    provider, _ = make_provider([_text_response("hello world")])
    response = await provider.complete(REQUEST)
    assert response.text == "hello world"
    assert response.input_tokens == 10
    assert response.output_tokens == 5


# ─── metering: one UsageEvent per API roundtrip ───────────────────────────────


async def test_meter_records_one_event_per_happy_structured_call():
    meter = UsageMeter()
    provider, _ = make_provider([_tool_use_response(VALID)], meter=meter)
    await provider.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("anthropic", "stub-model")] == (1, 10, 5)


async def test_meter_records_both_roundtrips_on_parse_retry():
    meter = UsageMeter()
    provider, _ = make_provider(
        [_tool_use_response({"claims": "not-a-list"}), _tool_use_response(VALID)], meter=meter
    )
    await provider.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("anthropic", "stub-model")] == (2, 20, 10)


async def test_meter_records_spend_even_when_both_attempts_fail():
    meter = UsageMeter()
    provider, _ = make_provider(
        [_tool_use_response({"bogus": 1}), _tool_use_response({"bogus": 2})], meter=meter
    )
    with pytest.raises(StructuredOutputError):
        await provider.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("anthropic", "stub-model")][0] == 2


async def test_meter_records_truncated_response_before_the_raise():
    truncated = SimpleNamespace(
        content=[],
        model="stub-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        stop_reason="max_tokens",
    )
    meter = UsageMeter()
    provider, _ = make_provider([truncated], meter=meter)
    with pytest.raises(StructuredOutputError):
        await provider.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("anthropic", "stub-model")] == (1, 10, 5)
