"""Test doubles: an in-memory Supabase client and a scripted model.

The scripted model tests the APPLICATION (tool execution, tenant scoping, grounding, state,
failure handling). It does not test language understanding: use scripts/live_eval.py with a real model.
"""
from __future__ import annotations

import copy
import itertools
from types import SimpleNamespace as NS
from typing import Any, Callable

from app.assistant.provider import LLMProvider, ProviderError
from app.assistant.types import AssistantTurn, ToolCall

_ids = itertools.count(1)


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self._op, self._payload, self._limit, self._order, self._cols = db, name, [], "select", None, None, None, "*"

    def select(self, cols="*"): self._op, self._cols = "select", cols; return self
    def eq(self, col, val): self.filters.append((col, val)); return self
    def limit(self, n): self._limit = n; return self
    def order(self, col, desc=False): self._order = (col, desc); return self
    def insert(self, row): self._op, self._payload = "insert", row; return self
    def update(self, row): self._op, self._payload = "update", row; return self

    def execute(self):
        if self.name in self.db.fail_tables or (self._op == "select" and self.name in self.db.fail_select):
            raise RuntimeError(f"simulated outage on {self.name}")
        if self._op == "update" and any((self.name, c) in self.db.missing_columns for c in self._payload):
            raise RuntimeError(f'column {self.name}.{next(iter(self._payload))} does not exist')
        if self._op == "select" and self._cols != "*" and any((self.name, c) in self.db.missing_columns for c in self._cols.split(",")):
            raise RuntimeError(f"column {self.name}.{self._cols} does not exist")
        rows = self.db.tables.setdefault(self.name, [])
        match = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        if self._op == "insert":
            row = {"id": f"{next(_ids):08d}-0000-0000-0000-000000000000", "created_at": f"2026-01-01T00:00:{next(_ids):06d}", **self._payload}
            rows.append(row)
            return NS(data=[row])
        if self._op == "update":
            for r in match:
                r.update(self._payload)
            return NS(data=[dict(r) for r in match])
        out = [dict(r) for r in match]
        if self._cols != "*":  # honour the column list like PostgREST does
            keep = self._cols.split(",")
            out = [{k: r.get(k) for k in keep} for r in out]
        if self._order:
            out.sort(key=lambda r: r.get(self._order[0], ""), reverse=self._order[1])
        return NS(data=out[: self._limit] if self._limit else out)


class FakeSupabase:
    def __init__(self, user_id="owner-1"):
        self.tables: dict[str, list[dict]] = {}
        self.fail_tables: set[str] = set()   # every operation on these tables raises
        self.fail_select: set[str] = set()   # only reads raise
        self.missing_columns: set[tuple[str, str]] = set()
        self.user_id = user_id
        self.auth = NS(get_user=lambda token: NS(user=NS(id=self.user_id) if token == "good-token" else None))

    def table(self, name): return Query(self, name)


# ---- scripted model -------------------------------------------------------------------------
def turn(*calls: ToolCall) -> AssistantTurn:
    return AssistantTurn(tool_calls=list(calls), usage={"prompt_tokens": 100, "completion_tokens": 20})


def tc(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"call{next(_ids):05d}", name=name, arguments=arguments)


def call(name: str, **arguments: Any) -> AssistantTurn:
    return turn(tc(name, **arguments))


def say(reply: str, action: str = "answer", **extra: Any) -> AssistantTurn:
    return call("reply_to_customer", reply=reply, action=action, **extra)


def text(content: str) -> AssistantTurn:
    return AssistantTurn(content=content, usage={"prompt_tokens": 100, "completion_tokens": 20})


class ScriptedProvider(LLMProvider):
    name, model = "scripted", "scripted-1"

    def __init__(self, script: list[Any]) -> None:
        self.script, self.seen, self.tool_names = list(script), [], []

    @property
    def enabled(self) -> bool:
        return True

    def chat(self, messages, tools=None, **kw) -> AssistantTurn:
        self.seen.append(copy.deepcopy(messages))
        self.tool_names.append([t["name"] for t in tools or []])
        if not self.script:
            raise ProviderError("script exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if isinstance(step, Callable) else step


def tool_results(messages: list[dict]) -> list[dict]:
    """Parsed JSON of every tool message the model was shown."""
    import json
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
