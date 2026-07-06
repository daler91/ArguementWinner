"""The argument engine: analyze → select strategy → generate → order.

Two LLM calls per invocation. Stages are module-level helpers composed by
ArgumentEngine — no pipeline framework.
"""

from __future__ import annotations

from . import prompts, ranking, strategy
from .models import (
    Analysis,
    ArgumentContext,
    ArgumentSession,
    CandidateResponse,
    EngineResult,
    EngineSettings,
    GenerationBatch,
    Persona,
)
from .ports import ChatMessage, LLMProvider, LLMRequest, StructuredOutputError


def build_state_digest(analysis: Analysis) -> str:
    """One line of argument state for the UI — pure string assembly."""
    bits: list[str] = []
    if analysis.fallacies:
        names = ", ".join(f.name for f in analysis.fallacies[:3])
        bits.append(f"Fallacies spotted: {names}.")
    if analysis.dodged_points:
        bits.append(f"They dodged: {analysis.dodged_points[0]}.")
    bits.append(f"Tone: {analysis.tone}.")
    return " ".join(bits)


class ArgumentEngine:
    def __init__(self, llm: LLMProvider, settings: EngineSettings) -> None:
        self._llm = llm
        self._settings = settings

    async def _analyze(self, ctx: ArgumentContext) -> Analysis:
        request = LLMRequest(
            system=prompts.ANALYSIS_SYSTEM,
            messages=(ChatMessage(role="user", content=prompts.analysis_user(ctx)),),
            max_tokens=1024,
            temperature=0.2,
            role_hint="analysis",
        )
        try:
            return await self._llm.complete_structured(request, Analysis)
        except StructuredOutputError:
            return Analysis.fallback()

    async def _generate(
        self,
        ctx: ArgumentContext,
        analysis: Analysis,
        primary: Persona,
        runner_up: Persona,
        n: int,
        combat: bool,
    ) -> tuple[CandidateResponse, ...]:
        request = LLMRequest(
            system=prompts.generation_system(self._settings.spice),
            messages=(
                ChatMessage(
                    role="user",
                    content=prompts.generation_user(ctx, analysis, primary, runner_up, n, combat),
                ),
            ),
            max_tokens=2048,
            temperature=0.8,
            role_hint="generation",
        )
        batch = await self._llm.complete_structured(request, GenerationBatch)
        candidates = [
            CandidateResponse(
                text=c.text.strip(),
                persona=c.persona,
                tactic_note=c.tactic_note,
                risk=c.risk,
            )
            for c in batch.candidates
            if c.text.strip()
        ]
        return ranking.order_candidates(
            candidates,
            strategy.ALLOWED_RISKS[self._settings.spice],
            self._settings.max_reply_chars,
        )

    async def suggest(self, ctx: ArgumentContext, n: int | None = None) -> EngineResult:
        """Suggestion mode: return ranked candidates for the user to pick from.
        Stateless — context comes entirely from the adapter's fresh fetch."""
        n = n or self._settings.suggest_candidates
        analysis = await self._analyze(ctx)
        primary, runner_up = strategy.select_personas(
            analysis, ctx.forced_persona, self._settings.spice
        )
        candidates = await self._generate(ctx, analysis, primary, runner_up, n, combat=False)
        return EngineResult(
            analysis=analysis,
            candidates=candidates,
            state_digest=build_state_digest(analysis),
        )

    async def combat_reply(
        self, ctx: ArgumentContext, session: ArgumentSession | None = None
    ) -> CandidateResponse:
        """Auto-combat mode: one reply, persona sticky per session (the session
        is mutated; the adapter owns saving it and all send bookkeeping)."""
        analysis = await self._analyze(ctx)
        recommended, _ = strategy.select_personas(
            analysis, ctx.forced_persona, self._settings.spice
        )
        if session is not None and (ctx.forced_persona in (None, Persona.AUTO)):
            primary = strategy.apply_stickiness(session, recommended)
        else:
            primary = recommended
        runner_up = strategy.COMPLEMENT[primary]
        candidates = await self._generate(ctx, analysis, primary, runner_up, 2, combat=True)
        if not candidates:
            raise StructuredOutputError("generation produced no usable candidates")
        return candidates[0]
