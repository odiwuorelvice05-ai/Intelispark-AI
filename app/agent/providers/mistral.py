"""Mistral implementation of AIProvider (chat + native function calling)."""
from __future__ import annotations

import json
import time
from typing import Any

from app.agent.providers.base import AIProvider, ProviderError, ProviderUnavailable
from app.agent.types import AssistantTurn, ToolCall


class MistralProvider(AIProvider):
    name = "mistral"

    def __init__(self, api_key: str = "", model: str = "mistral-small-latest",
                 reasoning_effort: str | None = None, client: Any = None) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort or None
        self._client = client
        if self._client is None and api_key:
            try:  # lazy: the SDK is only needed when a key is configured
                from mistralai.client import Mistral
                self._client = Mistral(api_key=api_key)
            except Exception:
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    # ---- translation -----------------------------------------------------
    @staticmethod
    def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = []
        for m in messages:
            role = m["role"]
            if role == "assistant" and m.get("tool_calls"):
                wire.append({
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": [{
                        "id": tc["id"], "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
                    } for tc in m["tool_calls"]],
                })
            elif role == "tool":
                wire.append({"role": "tool", "tool_call_id": m["tool_call_id"], "name": m["name"], "content": m["content"]})
            else:
                wire.append({"role": role, "content": m.get("content") or ""})
        return wire

    @staticmethod
    def _wire_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # chunked content; keep visible text only (drop reasoning chunks)
            return "".join(getattr(p, "text", "") for p in content if getattr(p, "type", "text") == "text")
        return ""

    def _parse(self, resp: Any, latency_ms: int) -> AssistantTurn:
        choice = resp.choices[0]
        msg = choice.message
        calls: list[ToolCall] = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            raw, err = tc.function.arguments, None
            if isinstance(raw, dict):
                args = raw
            else:
                try:
                    args = json.loads(raw or "{}")
                    if not isinstance(args, dict):
                        args, err = {}, "arguments were not a JSON object"
                except json.JSONDecodeError:
                    args, err = {}, "arguments were not valid JSON"
            calls.append(ToolCall(id=str(tc.id), name=tc.function.name, arguments=args, arguments_error=err))
        usage = getattr(resp, "usage", None)
        return AssistantTurn(
            content=self._text(getattr(msg, "content", "")),
            tool_calls=calls,
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
            usage={"prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0), "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0)},
            model=self.model,
            latency_ms=latency_ms,
        )

    # ---- the one primitive -------------------------------------------------
    def chat(self, messages, tools=None, *, tool_choice="auto", json_mode=False,
             max_tokens=700, temperature=0.2, timeout_s=15.0) -> AssistantTurn:
        if not self.enabled:
            raise ProviderUnavailable("Mistral is not configured")
        kwargs: dict[str, Any] = dict(
            model=self.model, messages=self._wire_messages(messages),
            temperature=temperature, max_tokens=max_tokens, timeout_ms=int(timeout_s * 1000),
        )
        if tools:
            kwargs.update(tools=self._wire_tools(tools), tool_choice=tool_choice, parallel_tool_calls=True)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        started = time.monotonic()
        try:
            resp = self._client.chat.complete(**kwargs)
        except Exception as exc:  # network, auth, rate limit, malformed request...
            raise ProviderError(f"mistral request failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        return self._parse(resp, int((time.monotonic() - started) * 1000))
