"""Settings → provider. Fails fast at startup on unknown provider or missing
key. If AW_MODEL_ANALYZER is set, wraps two provider instances in a RoleRouter
that dispatches on `request.role_hint` — cheap model for analysis, strong model
for generation, zero engine changes."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from argumentwinner.config import Settings
from argumentwinner.core.ports import LLMProvider, LLMRequest, LLMResponse

from .anthropic_provider import DEFAULT_MODEL as ANTHROPIC_DEFAULT
from .anthropic_provider import AnthropicProvider
from .fake import FakeLLMProvider
from .openai_provider import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
    OpenAICompatibleProvider,
)

T = TypeVar("T", bound=BaseModel)


class RoleRouter:
    """Dispatches analysis-role requests to a cheaper model."""

    def __init__(self, generation: LLMProvider, analysis: LLMProvider) -> None:
        self.name = f"router({analysis.name}->{generation.name})"
        self._generation = generation
        self._analysis = analysis

    def _pick(self, request: LLMRequest) -> LLMProvider:
        return self._analysis if request.role_hint == "analysis" else self._generation

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await self._pick(request).complete(request)

    async def complete_structured(self, request: LLMRequest, schema: type[T]) -> T:
        return await self._pick(request).complete_structured(request, schema)


def _build_single(settings: Settings, model: str) -> LLMProvider:
    provider = settings.aw_llm_provider
    if provider == "fake":
        return FakeLLMProvider()
    if provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise RuntimeError("AW_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(
            model=model, api_key=settings.anthropic_api_key.get_secret_value()
        )
    if provider == "openai":
        if settings.openai_api_key is None:
            raise RuntimeError("AW_LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAICompatibleProvider(
            model=model, api_key=settings.openai_api_key.get_secret_value(), name="openai"
        )
    if provider == "ollama":
        return OpenAICompatibleProvider(
            model=model, api_key="ollama", base_url=settings.aw_ollama_base_url, name="ollama"
        )
    raise RuntimeError(f"Unknown AW_LLM_PROVIDER: {provider!r}")


def default_model(settings: Settings) -> str:
    return {
        "anthropic": ANTHROPIC_DEFAULT,
        "openai": DEFAULT_OPENAI_MODEL,
        "ollama": DEFAULT_OLLAMA_MODEL,
        "fake": "fake",
    }[settings.aw_llm_provider]


def build_provider(settings: Settings) -> LLMProvider:
    model = settings.aw_llm_model or default_model(settings)
    provider = _build_single(settings, model)
    if settings.aw_model_analyzer and settings.aw_llm_provider != "fake":
        analyzer = _build_single(settings, settings.aw_model_analyzer)
        return RoleRouter(generation=provider, analysis=analyzer)
    return provider
