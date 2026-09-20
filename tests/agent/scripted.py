"""A scripted stand-in for the model, used ONLY to test the agent machinery
(tool execution, tenant scoping, grounding, retries, fallbacks). It does not test
language understanding: for that use tests/agent/eval_live.py with a real model."""
from __future__ import annotations

import copy
import itertools
from typing import Any, Callable

from app.agent.providers.base import AIProvider, ProviderError
from app.agent.types import AssistantTurn, ToolCall

_ids = itertools.count(1)


def call(name: str, **arguments: Any) -> AssistantTurn:
    return AssistantTurn(tool_calls=[ToolCall(id=f"call{next(_ids):05d}", name=name, arguments=arguments)], usage={"prompt_tokens": 100, "completion_tokens": 20})


def calls(*specs: tuple[str, dict]) -> AssistantTurn:
    return AssistantTurn(tool_calls=[ToolCall(id=f"call{next(_ids):05d}", name=n, arguments=a) for n, a in specs], usage={"prompt_tokens": 100, "completion_tokens": 20})


def say(reply: str, action: str = "answer", **extra: Any) -> AssistantTurn:
    return call("respond_to_customer", reply=reply, action=action, **extra)


def text(content: str) -> AssistantTurn:
    return AssistantTurn(content=content, usage={"prompt_tokens": 100, "completion_tokens": 20})


class ScriptedProvider(AIProvider):
    name, model = "scripted", "scripted-1"

    def __init__(self, script: list[Any]) -> None:
        self.script, self.seen = list(script), []

    @property
    def enabled(self) -> bool:
        return True

    def chat(self, messages, tools=None, **kw) -> AssistantTurn:
        self.seen.append(copy.deepcopy(messages))
        if not self.script:
            raise ProviderError("script exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if isinstance(step, Callable) else step
