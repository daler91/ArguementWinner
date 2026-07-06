from __future__ import annotations

import pytest

from argumentwinner.config import Settings
from argumentwinner.core.models import Analysis, GenerationBatch
from argumentwinner.core.ports import ChatMessage, LLMRequest
from argumentwinner.llm.factory import RoleRouter, build_provider
from argumentwinner.llm.fake import FakeLLMProvider
from argumentwinner.llm.usage import UsageMeter


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_fake_provider_builds_without_keys():
    provider = build_provider(settings(aw_llm_provider="fake"))
    assert provider.name == "fake"


def test_anthropic_without_key_fails_fast():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_provider(settings(aw_llm_provider="anthropic", anthropic_api_key=None))


def test_openai_without_key_fails_fast():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_provider(settings(aw_llm_provider="openai"))


def test_ollama_needs_no_key():
    provider = build_provider(settings(aw_llm_provider="ollama"))
    assert provider.name == "ollama"


async def test_role_router_dispatches_on_role_hint():
    generation = FakeLLMProvider()
    analysis_provider = FakeLLMProvider()
    router = RoleRouter(generation=generation, analysis=analysis_provider)

    analysis_req = LLMRequest(
        system="s", messages=(ChatMessage(role="user", content="x"),), role_hint="analysis"
    )
    generation_req = LLMRequest(
        system="s", messages=(ChatMessage(role="user", content="x"),), role_hint="generation"
    )
    await router.complete_structured(analysis_req, Analysis)
    await router.complete_structured(generation_req, GenerationBatch)

    assert len(analysis_provider.requests) == 1
    assert analysis_provider.requests[0].role_hint == "analysis"
    assert len(generation.requests) == 1
    assert generation.requests[0].role_hint == "generation"


def test_meter_reaches_single_provider_leaf():
    meter = UsageMeter()
    provider = build_provider(settings(aw_llm_provider="fake"), meter=meter)
    assert provider._meter is meter


def test_meter_reaches_both_role_router_leaves():
    meter = UsageMeter()
    provider = build_provider(
        settings(aw_llm_provider="ollama", aw_model_analyzer="llama-cheap"), meter=meter
    )
    assert isinstance(provider, RoleRouter)
    assert provider._generation._meter is meter
    assert provider._analysis._meter is meter
