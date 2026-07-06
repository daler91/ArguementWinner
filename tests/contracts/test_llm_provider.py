"""LLMProvider contract, run against the Fake always. Real providers run only
under `pytest -m live` (skipped in CI) — see tests/llm/test_live_providers.py."""

from __future__ import annotations

import pytest

from argumentwinner.core.models import Analysis, GenerationBatch, Persona
from argumentwinner.core.ports import ChatMessage, LLMRequest, StructuredOutputError
from argumentwinner.llm.fake import FakeLLMProvider
from tests.conftest import make_analysis

REQUEST = LLMRequest(system="sys", messages=(ChatMessage(role="user", content="hi"),))


class LLMProviderContract:
    def make_provider(self):
        raise NotImplementedError

    async def test_complete_returns_text(self):
        response = await self.make_provider().complete(REQUEST)
        assert isinstance(response.text, str) and response.text

    async def test_complete_structured_returns_schema_instance(self):
        provider = self.make_provider()
        result = await provider.complete_structured(REQUEST, Analysis)
        assert isinstance(result, Analysis)


class TestFakeProvider(LLMProviderContract):
    def make_provider(self):
        return FakeLLMProvider()

    async def test_queued_items_pop_in_order(self):
        analysis = make_analysis()
        fake = FakeLLMProvider([analysis, "raw text"])
        assert await fake.complete_structured(REQUEST, Analysis) is analysis
        assert (await fake.complete(REQUEST)).text == "raw text"

    async def test_records_every_request(self):
        fake = FakeLLMProvider()
        await fake.complete(REQUEST)
        await fake.complete_structured(REQUEST, GenerationBatch)
        assert len(fake.requests) == 2

    async def test_queued_exception_raises(self):
        fake = FakeLLMProvider([StructuredOutputError("nope")])
        with pytest.raises(StructuredOutputError):
            await fake.complete_structured(REQUEST, Analysis)

    async def test_queued_json_string_is_parsed(self):
        fake = FakeLLMProvider([make_analysis().model_dump_json()])
        result = await fake.complete_structured(REQUEST, Analysis)
        assert result.recommended_persona is Persona.LOGICIAN

    async def test_queued_invalid_json_raises_structured_output_error(self):
        fake = FakeLLMProvider(["{not json"])
        with pytest.raises(StructuredOutputError):
            await fake.complete_structured(REQUEST, Analysis)

    async def test_wrong_queued_schema_is_a_test_bug(self):
        fake = FakeLLMProvider([make_analysis()])
        with pytest.raises(AssertionError):
            await fake.complete_structured(REQUEST, GenerationBatch)
