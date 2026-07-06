"""Anthropic backend. Structured output via forced tool use: the pydantic
schema becomes the tool's input schema, so the API guarantees a JSON object
shaped roughly right and pydantic validates the rest.

Notes:
- The SDK auto-retries 429/5xx/connection errors (max_retries), so there is no
  hand-rolled retry wrapper here.
- `LLMRequest.temperature` is intentionally NOT forwarded: current Claude
  models (Opus 4.7+, Sonnet 5, Fable 5) reject sampling parameters.
"""

from __future__ import annotations

from typing import Any, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from argumentwinner.core.ports import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    StructuredOutputError,
)

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-4-8"
_EMIT_TOOL = "emit"


def _to_messages(messages: tuple[ChatMessage, ...]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self._client = client or AsyncAnthropic(api_key=api_key)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self._client.messages.create(
            model=self.model,
            system=request.system,
            messages=_to_messages(request.messages),
            max_tokens=request.max_tokens,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def complete_structured(self, request: LLMRequest, schema: type[T]) -> T:
        tool = {
            "name": _EMIT_TOOL,
            "description": f"Emit the {schema.__name__} result.",
            "input_schema": schema.model_json_schema(),
        }
        messages = _to_messages(request.messages)
        last_error: Exception | None = None
        for _attempt in range(2):
            response = await self._client.messages.create(
                model=self.model,
                system=request.system,
                messages=messages,
                max_tokens=request.max_tokens,
                tools=[tool],
                tool_choice={"type": "tool", "name": _EMIT_TOOL},
            )
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason == "max_tokens":
                # An identical retry would truncate identically — fail now
                # with an actionable message instead.
                raise StructuredOutputError(
                    f"output truncated at max_tokens={request.max_tokens} — raise max_tokens"
                )
            if stop_reason == "refusal":
                raise StructuredOutputError("the model refused this request")
            tool_use = next((b for b in response.content if b.type == "tool_use"), None)
            if tool_use is None:
                last_error = StructuredOutputError("model returned no tool_use block")
                messages = messages + [
                    {
                        "role": "user",
                        "content": f"You must call the `{_EMIT_TOOL}` tool with the result.",
                    }
                ]
                continue
            try:
                return schema.model_validate(tool_use.input)
            except ValidationError as exc:
                last_error = exc
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            "Your previous output failed validation:\n"
                            f"{exc}\n"
                            f"Call the `{_EMIT_TOOL}` tool again with corrected data."
                        ),
                    }
                ]
        raise StructuredOutputError(str(last_error)) from last_error
