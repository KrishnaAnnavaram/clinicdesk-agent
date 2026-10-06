"""Provider-neutral chat-model interface with native tool calling.

Messages use a small neutral format::

    {"role": "system" | "user" | "assistant" | "tool", "content": str,
     "tool_calls": [ToolCall, ...],          # assistant only
     "tool_call_id": str, "name": str}       # tool only

Adapters (offline rule-based, OpenAI-compatible, scripted fakes) translate to
and from their own wire formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence


class LLMError(RuntimeError):
    """The model call failed (network, quota, malformed response...)."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None  # None when the model sent un-parseable JSON
    raw_arguments: str = ""


@dataclass(frozen=True)
class AssistantTurn:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


class ChatModel(Protocol):
    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> AssistantTurn:
        """Return the next assistant turn. ``tools`` are JSON-schema function specs."""
        ...


class ScriptedChatModel:
    """Test double: returns pre-written turns (or calls a function) and records what it was sent."""

    def __init__(self, script: Sequence[AssistantTurn | Exception] | Callable[..., AssistantTurn]) -> None:
        self._script = script if callable(script) else list(script)
        self.calls: list[list[dict[str, Any]]] = []

    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> AssistantTurn:
        self.calls.append([dict(m) for m in messages])
        if callable(self._script):
            return self._script(messages, tools)
        if not self._script:
            raise LLMError("script exhausted")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
