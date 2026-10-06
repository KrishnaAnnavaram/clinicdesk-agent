"""Adapter for OpenAI-compatible chat-completions APIs (OpenAI, or a local server via base URL).

Install with ``pip install clinicdesk-agent[openai]``. The adapter only turns
messages into requests and responses into :class:`AssistantTurn`; it never
touches the database.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from clinicdesk_agent.agent.llm import AssistantTurn, LLMError, ToolCall


def _to_wire(message: dict[str, Any]) -> dict[str, Any]:
    role = message["role"]
    if role == "assistant" and message.get("tool_calls"):
        return {
            "role": "assistant",
            "content": message.get("content") or None,
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments or {})}}
                for c in message["tool_calls"]
            ],
        }
    if role == "tool":
        return {"role": "tool", "tool_call_id": message["tool_call_id"], "content": message["content"]}
    return {"role": role, "content": message.get("content", "")}


def parse_tool_arguments(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class OpenAIChatModel:
    def __init__(self, model: str, *, api_key: str | None = None, base_url: str | None = None,
                 timeout: float = 30.0, client: Any = None) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise LLMError("the 'openai' package is not installed; pip install 'clinicdesk-agent[openai]'") from exc
            client = OpenAI(api_key=api_key or "not-needed-for-local-servers", base_url=base_url, timeout=timeout)
        self.client = client
        self.model = model

    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> AssistantTurn:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[_to_wire(m) for m in messages],
                tools=[{"type": "function", "function": t} for t in tools] or None,
                temperature=0,
            )
            message = response.choices[0].message
        except Exception as exc:  # network, auth, rate limit, schema...
            raise LLMError(f"model call failed: {type(exc).__name__}") from exc
        calls = tuple(
            ToolCall(id=c.id, name=c.function.name, arguments=parse_tool_arguments(c.function.arguments),
                     raw_arguments=c.function.arguments or "")
            for c in (message.tool_calls or [])
        )
        return AssistantTurn(text=message.content or "", tool_calls=calls)
