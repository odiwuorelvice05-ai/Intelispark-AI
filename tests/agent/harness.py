"""Run multi-turn conversations through the real AgentRunner against the fixture shop.
Used by the live evaluation, the demo script and the machinery tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.loop import AgentResult, AgentRunner
from app.agent.providers.base import AIProvider
from app.agent.tools import ToolContext, ToolRegistry
from tests.agent.fixtures import CONV, SHOP_A, make_store


@dataclass
class TurnRecord:
    user: str
    result: AgentResult

    @property
    def reply(self) -> str | None:
        return self.result.reply


def run_conversation(provider: AIProvider, user_turns: list[str], *, shop: str = SHOP_A, store: Any = None,
                     conversation_id: str = CONV, **runner_kw: Any) -> list[TurnRecord]:
    store = store or make_store()
    repo = store.repo(shop)
    registry = ToolRegistry()
    shop_name = repo.get_business().get("name", "the shop")
    history: list[dict[str, Any]] = []
    records: list[TurnRecord] = []
    for message in user_turns:
        ctx = ToolContext(repo=repo, conversation_id=conversation_id)
        res = AgentRunner(provider, registry, **runner_kw).run(ctx, shop_name=shop_name, history=list(history), customer_message=message)
        records.append(TurnRecord(message, res))
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": res.reply or "(no answer: fell back to legacy engine)"})
    return records


def describe_turn(rec: TurnRecord) -> str:
    t = rec.result.trace
    lines = [f"CUSTOMER: {rec.user}"]
    for s in t.steps:
        args = ", ".join(f"{k}={v}" for k, v in (s.get("arguments") or {}).items())
        extra = f" -> {s.get('count')} products" if s.get("count") is not None else ""
        lines.append(f"  TOOL {s['tool']}({args}){extra}{'' if s.get('ok') else '  [ERROR: ' + str(s.get('error')) + ']'}")
    if rec.result.status == "answered":
        lines.append(f"  DECISION: action={t.action} intent={t.customer_intent} confidence={t.confidence} grounding_first_pass={t.grounding['first_pass_ok']}")
        lines.append(f"AGENT: {rec.reply}")
    else:
        lines.append(f"  FALLBACK to legacy engine: {t.fallback_reason}")
    return "\n".join(lines)
