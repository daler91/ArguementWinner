"""Live provider checks — real API calls, real keys. Skipped by default;
run with `pytest -m live`.

Includes the analysis-quality golden that guards RoleRouter garbage-in: a
fixture with a known strawman that the analyzer model must catch.
"""

from __future__ import annotations

import os

import pytest

from argumentwinner.core import prompts
from argumentwinner.core.models import Analysis
from argumentwinner.core.ports import ChatMessage, LLMRequest
from tests.conftest import make_context

pytestmark = pytest.mark.live

STRAWMAN_MESSAGE = (
    "So you think we should improve the bus network? Interesting that you want "
    "to ban all cars and force everyone to walk everywhere. Typical."
)


@pytest.fixture
def anthropic_provider():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from argumentwinner.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider()


async def test_analysis_catches_the_strawman(anthropic_provider):
    ctx = make_context(target_content=STRAWMAN_MESSAGE)
    request = LLMRequest(
        system=prompts.ANALYSIS_SYSTEM,
        messages=(ChatMessage(role="user", content=prompts.analysis_user(ctx)),),
        role_hint="analysis",
    )
    analysis = await anthropic_provider.complete_structured(request, Analysis)
    names = " ".join(f.name.lower() for f in analysis.fallacies)
    assert "straw" in names, f"analyzer missed the strawman: {analysis.fallacies}"


async def test_analyzer_model_is_structured_output_proficient():
    """Run the same golden against AW_MODEL_ANALYZER when set — guards the
    RoleRouter's garbage-in risk."""
    analyzer = os.environ.get("AW_MODEL_ANALYZER")
    if not analyzer:
        pytest.skip("AW_MODEL_ANALYZER not set")
    if os.environ.get("AW_LLM_PROVIDER", "anthropic") != "anthropic":
        pytest.skip("analyzer golden currently only wired for the anthropic provider")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from argumentwinner.llm.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(model=analyzer)
    ctx = make_context(target_content=STRAWMAN_MESSAGE)
    request = LLMRequest(
        system=prompts.ANALYSIS_SYSTEM,
        messages=(ChatMessage(role="user", content=prompts.analysis_user(ctx)),),
        role_hint="analysis",
    )
    analysis = await provider.complete_structured(request, Analysis)
    names = " ".join(f.name.lower() for f in analysis.fallacies)
    assert "straw" in names, (
        f"AW_MODEL_ANALYZER={analyzer} missed the strawman — it is not "
        "structured-output/analysis proficient enough to feed the generator"
    )
