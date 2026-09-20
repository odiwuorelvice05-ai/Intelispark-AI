"""Model-provider abstraction.

Everything in Intelispark talks to ``AIProvider``; nothing else imports a vendor SDK.
A provider implements ONE primitive, ``chat``. The higher-level helpers
(``respond``, ``generate_structured``, ``choose_tool``) are derived from it, so a new
vendor (or a self-hosted model behind an OpenAI-compatible server) only needs ``chat``.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.agent.types import AssistantTurn, ToolCall


class ProviderError(Exception):
    """The model call failed. Message is safe to log; never show it to customers."""


class ProviderUnavailable(ProviderError):
    """Provider is not configured (missing key/SDK)."""


class AIProvider(ABC):
    name: str = "provider"
    model: str = ""

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: str = "auto",  # "auto" | "any" | "none"
        json_mode: bool = False,
        max_tokens: int = 700,
        temperature: float = 0.2,
        timeout_s: float = 15.0,
    ) -> AssistantTurn: ...

    # ---- derived helpers -------------------------------------------------
    def respond(self, messages: list[dict[str, Any]], **kw: Any) -> str:
        return self.chat(messages, None, **kw).content

    def generate_structured(self, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        turn = self.chat(messages, None, json_mode=True, **kw)
        try:
            data = json.loads(turn.content or "{}")
        except json.JSONDecodeError as exc:
            raise ProviderError("model returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("model returned non-object JSON")
        return data

    def choose_tool(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kw: Any) -> list[ToolCall]:
        return self.chat(messages, tools, tool_choice=kw.pop("tool_choice", "any"), **kw).tool_calls
