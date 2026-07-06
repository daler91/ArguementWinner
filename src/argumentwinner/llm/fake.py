"""FakeLLMProvider: the keystone of the test suite, and a fully offline
backend for the REPL (AW_LLM_PROVIDER=fake).

Queued scripted responses pop in order; when the queue is empty it falls back
to deterministic canned output keyed by schema, so the whole pipeline runs
end-to-end with no network. Every request is recorded for assertions.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from argumentwinner.core.models import (
    Analysis,
    GeneratedCandidate,
    GenerationBatch,
    Persona,
    Risk,
)
from argumentwinner.core.ports import LLMRequest, LLMResponse, StructuredOutputError

T = TypeVar("T", bound=BaseModel)


class FakeLLMProvider:
    name = "fake"

    def __init__(self, queue: list[BaseModel | str | Exception] | None = None) -> None:
        self.queue: list[BaseModel | str | Exception] = list(queue or [])
        self.requests: list[LLMRequest] = []

    def _pop(self) -> BaseModel | str | Exception | None:
        return self.queue.pop(0) if self.queue else None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        item = self._pop()
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else "canned response"
        return LLMResponse(text=text, model="fake")

    async def complete_structured(self, request: LLMRequest, schema: type[T]) -> T:
        self.requests.append(request)
        item = self._pop()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, BaseModel):
            if not isinstance(item, schema):
                raise AssertionError(
                    f"queued {type(item).__name__} but engine asked for {schema.__name__}"
                )
            return item
        if isinstance(item, str):
            try:
                return schema.model_validate_json(item)
            except Exception as exc:  # noqa: BLE001 — surfaced as the port's error type
                raise StructuredOutputError(str(exc)) from exc
        return self._canned(schema)

    def _canned(self, schema: type[T]) -> T:
        if schema is Analysis:
            return Analysis(  # type: ignore[return-value]
                claims=["their claim"],
                fallacies=[],
                tone="smug",
                weak_points=["no evidence offered"],
                dodged_points=[],
                recommended_persona=Persona.LOGICIAN,
                opponent_summary="an unsupported hot take",
            )
        if schema is GenerationBatch:
            return GenerationBatch(  # type: ignore[return-value]
                candidates=[
                    GeneratedCandidate(
                        text="Bold claim. Where's the evidence?",
                        persona=Persona.LOGICIAN,
                        tactic_note="demands evidence for the unsupported claim",
                        risk=Risk.SAFE,
                    ),
                    GeneratedCandidate(
                        text="You've stated it twice now; repetition still isn't proof.",
                        persona=Persona.LOGICIAN,
                        tactic_note="names the repetition, keeps burden of proof on them",
                        risk=Risk.SPICY,
                    ),
                    GeneratedCandidate(
                        text="What would change your mind, exactly?",
                        persona=Persona.SOCRATIC,
                        tactic_note="commits them to falsifiability",
                        risk=Risk.SAFE,
                    ),
                ]
            )
        raise StructuredOutputError(f"no canned output for schema {schema.__name__}")
