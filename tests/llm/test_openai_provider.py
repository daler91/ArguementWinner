"""OpenAI/Ollama provider: fenced-JSON parsing, json_schema → json_object
degradation, retry-once-then-raise."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest

from argumentwinner.core.models import Analysis
from argumentwinner.core.ports import ChatMessage, LLMRequest, StructuredOutputError
from argumentwinner.llm.openai_provider import OpenAICompatibleProvider, _strip_fences
from argumentwinner.llm.usage import UsageMeter
from tests.conftest import make_analysis

REQUEST = LLMRequest(system="sys", messages=(ChatMessage(role="user", content="analyze"),))
VALID_JSON = make_analysis().model_dump_json()


def _response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        model="stub-model",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


def _bad_request() -> openai.BadRequestError:
    request = httpx.Request("POST", "http://stub")
    response = httpx.Response(400, request=request)
    return openai.BadRequestError("json_schema unsupported", response=response, body=None)


class StubClient:
    def __init__(self, results: list) -> None:
        self.calls: list[dict] = []
        self._results = list(results)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_provider(
    results: list, meter: UsageMeter | None = None
) -> tuple[OpenAICompatibleProvider, StubClient]:
    stub = StubClient(results)
    return OpenAICompatibleProvider(model="stub-model", client=stub, meter=meter), stub


def test_strip_fences():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences('{"a": 1}') == '{"a": 1}'
    assert _strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'


async def test_happy_path_uses_json_schema_format():
    provider, stub = make_provider([_response(VALID_JSON)])
    result = await provider.complete_structured(REQUEST, Analysis)
    assert isinstance(result, Analysis)
    assert stub.calls[0]["response_format"]["type"] == "json_schema"


async def test_fenced_json_is_parsed():
    provider, _ = make_provider([_response(f"```json\n{VALID_JSON}\n```")])
    result = await provider.complete_structured(REQUEST, Analysis)
    assert isinstance(result, Analysis)


async def test_json_schema_rejection_degrades_to_json_object_and_sticks():
    provider, stub = make_provider([_bad_request(), _response(VALID_JSON), _response(VALID_JSON)])
    await provider.complete_structured(REQUEST, Analysis)
    assert stub.calls[1]["response_format"] == {"type": "json_object"}
    # the degradation is remembered — no second json_schema attempt
    await provider.complete_structured(REQUEST, Analysis)
    assert stub.calls[2]["response_format"] == {"type": "json_object"}


async def test_invalid_json_retries_once_with_error_fed_back_then_raises():
    provider, stub = make_provider([_response("{truncated"), _response("also not json")])
    with pytest.raises(StructuredOutputError):
        await provider.complete_structured(REQUEST, Analysis)
    assert len(stub.calls) == 2
    retry_messages = stub.calls[1]["messages"]
    assert "failed validation" in retry_messages[-1]["content"]


async def test_complete_returns_text_and_usage():
    provider, _ = make_provider([_response("plain answer")])
    response = await provider.complete(REQUEST)
    assert response.text == "plain answer"
    assert response.input_tokens == 10


async def test_openai_sends_max_completion_tokens_but_ollama_sends_max_tokens():
    provider, stub = make_provider([_response("x")])
    await provider.complete(REQUEST)
    assert "max_completion_tokens" in stub.calls[0]
    assert "max_tokens" not in stub.calls[0]

    ollama_stub = StubClient([_response("x")])
    ollama = OpenAICompatibleProvider(model="llama3.1", name="ollama", client=ollama_stub)
    await ollama.complete(REQUEST)
    assert "max_tokens" in ollama_stub.calls[0]


async def test_temperature_rejection_retries_without_it():
    request = httpx.Request("POST", "http://stub")
    err = openai.BadRequestError(
        "Unsupported value: 'temperature'", response=httpx.Response(400, request=request), body=None
    )
    provider, stub = make_provider([err, _response("ok")])
    response = await provider.complete(REQUEST)
    assert response.text == "ok"
    assert "temperature" not in stub.calls[1]


async def test_unrelated_bad_request_does_not_degrade_json_schema_mode():
    request = httpx.Request("POST", "http://stub")
    err = openai.BadRequestError(
        "context length exceeded", response=httpx.Response(400, request=request), body=None
    )
    provider, _ = make_provider([err])
    with pytest.raises(openai.BadRequestError):
        await provider.complete_structured(REQUEST, Analysis)
    assert provider._json_schema_supported  # not misclassified as unsupported


# ─── metering: one UsageEvent per API roundtrip ───────────────────────────────


async def test_meter_records_one_event_on_complete():
    meter = UsageMeter()
    provider, _ = make_provider([_response("plain answer")], meter=meter)
    await provider.complete(REQUEST)
    assert meter.snapshot()[("openai", "stub-model")] == (1, 10, 5)


async def test_meter_records_both_roundtrips_on_parse_retry():
    meter = UsageMeter()
    provider, _ = make_provider([_response("{truncated"), _response(VALID_JSON)], meter=meter)
    await provider.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("openai", "stub-model")] == (2, 20, 10)


async def test_meter_records_once_on_schema_degrade():
    # The rejected json_schema attempt yields no response — nothing to meter;
    # only the successful json_object roundtrip counts.
    meter = UsageMeter()
    provider, _ = make_provider([_bad_request(), _response(VALID_JSON)], meter=meter)
    await provider.complete_structured(REQUEST, Analysis)
    assert meter.snapshot()[("openai", "stub-model")] == (1, 10, 5)


async def test_meter_records_once_on_temperature_retry():
    request = httpx.Request("POST", "http://stub")
    err = openai.BadRequestError(
        "Unsupported value: 'temperature'", response=httpx.Response(400, request=request), body=None
    )
    meter = UsageMeter()
    provider, _ = make_provider([err, _response("ok")], meter=meter)
    await provider.complete(REQUEST)
    assert meter.snapshot()[("openai", "stub-model")] == (1, 10, 5)
