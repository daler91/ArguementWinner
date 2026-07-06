from __future__ import annotations

from argumentwinner.core.engine import ArgumentEngine, build_state_digest
from argumentwinner.core.models import (
    ArgumentSession,
    EngineSettings,
    Persona,
    Risk,
    SpiceLevel,
)
from argumentwinner.core.ports import StructuredOutputError
from argumentwinner.llm.fake import FakeLLMProvider
from tests.conftest import REF, make_analysis, make_batch, make_context

SETTINGS = EngineSettings(spice=SpiceLevel.MEDIUM)


def engine_with(queue) -> tuple[ArgumentEngine, FakeLLMProvider]:
    fake = FakeLLMProvider(queue)
    return ArgumentEngine(fake, SETTINGS), fake


async def test_suggest_happy_path():
    analysis = make_analysis()
    batch = make_batch(
        ("Popularity is not evidence.", Persona.LOGICIAN, Risk.SAFE),
        ("Cite one study. I'll wait.", Persona.LOGICIAN, Risk.SPICY),
        ("What would change your mind?", Persona.SOCRATIC, Risk.SAFE),
    )
    engine, fake = engine_with([analysis, batch])

    result = await engine.suggest(make_context())

    assert len(result.candidates) == 3
    assert result.candidates[0].text == "Popularity is not evidence."
    assert result.analysis is analysis
    assert "Fallacies spotted" in result.state_digest
    # exactly two LLM calls: analyze + generate
    assert len(fake.requests) == 2
    assert fake.requests[0].role_hint == "analysis"
    assert fake.requests[1].role_hint == "generation"


async def test_generation_prompt_contains_the_ammunition():
    engine, fake = engine_with(
        [make_analysis(), make_batch(("reply", Persona.LOGICIAN, Risk.SAFE))]
    )
    await engine.suggest(
        make_context(our_recent_lines=("configurable width helps screen readers",))
    )
    gen_prompt = fake.requests[1].messages[0].content
    # fallacy quote is injected verbatim so callouts cite real words
    assert '"everyone knows this"' in gen_prompt
    # our prior lines become never-contradict constraints
    assert "configurable width helps screen readers" in gen_prompt
    assert "NEVER contradict" in gen_prompt


async def test_analysis_parse_failure_degrades_to_fallback_and_still_replies():
    engine, fake = engine_with(
        [
            StructuredOutputError("unparseable"),
            make_batch(("still got a reply out", Persona.LOGICIAN, Risk.SAFE)),
        ]
    )
    result = await engine.suggest(make_context())
    assert result.candidates[0].text == "still got a reply out"
    assert result.analysis.tone == "unknown"  # the fallback analysis


async def test_generation_failure_propagates():
    engine, _ = engine_with([make_analysis(), StructuredOutputError("boom")])
    try:
        await engine.suggest(make_context())
    except StructuredOutputError:
        pass
    else:
        raise AssertionError("generation failure must propagate to the adapter")


async def test_combat_reply_returns_single_best_and_applies_stickiness():
    session = ArgumentSession(ref=REF, persona=Persona.DIPLOMAT)
    analysis = make_analysis(recommended_persona=Persona.SAVAGE)
    engine, fake = engine_with(
        [analysis, make_batch(("one punchy line", Persona.DIPLOMAT, Risk.SAFE))]
    )
    candidate = await engine.combat_reply(make_context(), session)
    assert candidate.text == "one punchy line"
    # first disagreement: persona held, streak counted
    assert session.persona is Persona.DIPLOMAT
    assert session.persona_mismatch_streak == 1
    # combat prompt asks for the sticky persona, not the fresh recommendation
    assert "diplomat" in fake.requests[1].messages[0].content


async def test_combat_forced_persona_skips_stickiness():
    session = ArgumentSession(ref=REF, persona=Persona.SAVAGE, persona_forced=True)
    engine, fake = engine_with(
        [
            make_analysis(recommended_persona=Persona.DIPLOMAT),
            make_batch(("heat", Persona.SAVAGE, Risk.SPICY)),
        ]
    )
    ctx = make_context(forced_persona=Persona.SAVAGE)
    await engine.combat_reply(ctx, session)
    assert session.persona_mismatch_streak == 0
    assert "savage" in fake.requests[1].messages[0].content


def test_state_digest_is_one_line_of_plain_string_assembly():
    digest = build_state_digest(make_analysis())
    assert "appeal to popularity" in digest
    assert "They dodged" in digest
    assert "\n" not in digest
