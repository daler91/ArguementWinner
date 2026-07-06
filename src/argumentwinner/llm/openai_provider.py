"""OpenAI-compatible backend — also serves Ollama via `base_url`
(two classes' worth of behavior, three backends, one implementation).

Structured output: try `response_format={"type": "json_schema", ...}` first;
endpoints that reject it (older Ollama builds) degrade to `json_object` with
the schema embedded in the system prompt. Parse failures retry once with the
validation error fed back, then raise StructuredOutputError.

The SDK auto-retries 429/5xx/connection errors (max_retries), so there is no
hand-rolled retry wrapper here.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from argumentwinner.core.ports import (
    LLMRequest,
    LLMResponse,
    StructuredOutputError,
)

T = TypeVar("T", bound=BaseModel)

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OLLAMA_MODEL = "llama3.1"


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class OpenAICompatibleProvider:
    def __init__(
        self,
        model: str = DEFAULT_OPENAI_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        name: str = "openai",
        client: Any | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._json_schema_supported = True
        # Newer OpenAI chat models reject `max_tokens` in favor of
        # `max_completion_tokens`; Ollama's /v1 shim only knows `max_tokens`.
        self._max_tokens_param = "max_tokens" if name == "ollama" else "max_completion_tokens"

    async def _chat(self, **kwargs):
        try:
            return await self._client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            # Reasoning-family models reject non-default temperature —
            # retry once without it rather than failing the reply.
            if "temperature" in str(exc).lower() and "temperature" in kwargs:
                kwargs.pop("temperature")
                return await self._client.chat.completions.create(**kwargs)
            raise

    def _messages(self, request: LLMRequest, system_suffix: str = "") -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = [
            {"role": "system", "content": request.system + system_suffix}
        ]
        msgs += [{"role": m.role, "content": m.content} for m in request.messages]
        return msgs

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self._chat(
            model=self.model,
            messages=self._messages(request),
            temperature=request.temperature,
            **{self._max_tokens_param: request.max_tokens},
        )
        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def _create_structured(
        self, request: LLMRequest, schema: type[T], extra_messages: list[dict[str, str]]
    ) -> str:
        schema_note = (
            "\n\nRespond ONLY with a JSON object matching this JSON Schema:\n"
            + json.dumps(schema.model_json_schema())
        )
        messages = self._messages(request, system_suffix=schema_note) + extra_messages
        common = {
            "model": self.model,
            "messages": messages,
            "temperature": request.temperature,
            self._max_tokens_param: request.max_tokens,
        }
        if self._json_schema_supported:
            try:
                response = await self._chat(
                    **common,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema.__name__,
                            "schema": schema.model_json_schema(),
                        },
                    },
                )
                return response.choices[0].message.content or ""
            except openai.BadRequestError as exc:
                # Degrade to json_object + schema-in-prompt only when the
                # endpoint actually rejected the response_format (e.g. an
                # older Ollama) — any other 400 is a real error.
                text = str(exc).lower()
                if "response_format" not in text and "json_schema" not in text:
                    raise
                self._json_schema_supported = False
        response = await self._chat(**common, response_format={"type": "json_object"})
        return response.choices[0].message.content or ""

    async def complete_structured(self, request: LLMRequest, schema: type[T]) -> T:
        extra: list[dict[str, str]] = []
        last_error: Exception | None = None
        for _attempt in range(2):
            raw = await self._create_structured(request, schema, extra)
            try:
                return schema.model_validate_json(_strip_fences(raw))
            except (ValidationError, ValueError) as exc:
                last_error = exc
                extra = [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "That output failed validation:\n"
                            f"{exc}\n"
                            "Respond again with ONLY a corrected JSON object."
                        ),
                    },
                ]
        raise StructuredOutputError(str(last_error)) from last_error
