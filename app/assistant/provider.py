"""Model-provider boundary.

The rest of the application talks to ``LLMProvider.chat`` and nothing else. The one
shipped implementation speaks the OpenAI-style chat-completions protocol, which Mistral,
OpenAI, Groq, Together, Google Gemini's compatibility endpoint and self-hosted servers
(vLLM, Ollama) all accept, so changing vendor is three environment variables
(LLM_BASE_URL, LLM_MODEL, LLM_API_KEY), not a code change. Anything with a different wire
format needs one new subclass implementing ``chat``.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.assistant.types import AssistantTurn, ToolCall


class ProviderError(Exception):
    """The model call failed. The message is safe to log; never show it to customers."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(ABC):
    name = "provider"
    model = ""

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
             tool_choice: str = "auto", max_tokens: int = 700, temperature: float = 0.2,
             timeout_s: float = 6.0) -> AssistantTurn: ...


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self, *, api_key: str, base_url: str, model: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self._client = client or httpx.Client()

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self.model and self._url)

    # ---- wire translation ---------------------------------------------------------------
    @staticmethod
    def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                wire.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}}
                    for tc in m["tool_calls"]]})
            elif m["role"] == "tool":
                wire.append({"role": "tool", "tool_call_id": m["tool_call_id"], "name": m["name"], "content": m["content"]})
            else:
                wire.append({"role": m["role"], "content": m.get("content") or ""})
        return wire

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # chunked content: keep visible text only
            return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type", "text") == "text")
        return ""

    @staticmethod
    def _parse_calls(raw_calls: Any) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for i, tc in enumerate(raw_calls or []):
            fn = (tc or {}).get("function") or {}
            raw, err = fn.get("arguments"), None
            if isinstance(raw, dict):
                args = raw
            else:
                try:
                    args = json.loads(raw or "{}")
                    if not isinstance(args, dict):
                        args, err = {}, "arguments were not a JSON object"
                except (json.JSONDecodeError, TypeError):
                    args, err = {}, "arguments were not valid JSON"
            calls.append(ToolCall(id=str(tc.get("id") or f"call_{i}"), name=str(fn.get("name") or ""), arguments=args, arguments_error=err))
        return calls

    # ---- the one primitive --------------------------------------------------------------
    def chat(self, messages, tools=None, *, tool_choice="auto", max_tokens=700, temperature=0.2, timeout_s=6.0) -> AssistantTurn:
        if not self.enabled:
            raise ProviderError("language model is not configured")
        body: dict[str, Any] = {"model": self.model, "messages": self._wire_messages(messages),
                                "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]
            body["tool_choice"] = tool_choice
        started = time.monotonic()
        try:
            resp = self._client.post(self._url, json=body, timeout=timeout_s,
                                     headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        except httpx.HTTPError as exc:  # timeout, DNS, connection reset...
            raise ProviderError(f"request failed: {type(exc).__name__}", retryable=True) from None
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {self._scrub(resp.text)[:200]}", retryable=resp.status_code in (408, 409, 429) or resp.status_code >= 500)
        try:
            data = resp.json()
            message = data["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError("message is not an object")
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("malformed response from model provider", retryable=True) from None
        usage = data.get("usage") or {}
        return AssistantTurn(
            content=self._text(message.get("content")),
            tool_calls=self._parse_calls(message.get("tool_calls")),
            usage={"prompt_tokens": int(usage.get("prompt_tokens") or 0), "completion_tokens": int(usage.get("completion_tokens") or 0)},
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def _scrub(self, text: str) -> str:
        return text.replace(self._api_key, "***") if self._api_key else text


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider | None:
    """Process-wide provider built from settings; None when no key is configured."""
    global _provider
    from app.config import settings
    if _provider is None:
        _provider = OpenAICompatibleProvider(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model)
    return _provider if _provider.enabled else None
