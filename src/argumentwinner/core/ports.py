"""Ports: the protocols the core depends on, implemented outside the hexagon."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

from .models import ArgumentSession, ConversationRef

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """A provider could not produce output matching the requested schema,
    even after its internal parse-retry."""


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: tuple[ChatMessage, ...]
    max_tokens: int = 1024
    temperature: float = 0.8
    # "analysis" | "generation" — consumed only by the optional RoleRouter.
    role_hint: str = "generation"


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    name: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def complete_structured(self, request: LLMRequest, schema: type[T]) -> T:
        """Return a validated instance of `schema`. Each provider owns its
        JSON-forcing mechanism and retries a failed parse once (with the
        validation error fed back) before raising StructuredOutputError."""
        ...


class SessionStore(Protocol):
    async def get(self, ref: ConversationRef) -> ArgumentSession | None: ...

    async def save(self, session: ArgumentSession) -> None: ...

    async def delete(self, ref: ConversationRef) -> None: ...
