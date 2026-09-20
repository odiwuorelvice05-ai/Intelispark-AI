"""Public entry point of the intelligence layer: one function, one outcome type.

``respond`` is called by the API after it has authenticated the owner and resolved the
business, conversation and customer. It fixes the tenant, runs the agent, applies the
validated state update and returns either a grounded reply or a controlled "unavailable".
It never raises for model, network or data failures.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.assistant import state as conv_state
from app.assistant.agent import Agent
from app.assistant.prompt import build_system_prompt, catalog_snapshot
from app.assistant.provider import LLMProvider, get_provider
from app.assistant.repository import DataUnavailable, ShopRepository, SupabaseShopRepository
from app.assistant.tools import ToolContext, ToolRegistry
from app.config import settings

log = logging.getLogger("intelispark.assistant")


@dataclass
class TurnResult:
    status: str                       # "answered" | "unavailable"
    reply: str | None = None
    intelligence: dict[str, Any] = field(default_factory=dict)
    failure: str | None = None


def status() -> dict[str, Any]:
    provider = get_provider()
    return {"configured": provider is not None, "model": settings.llm_model if provider else None}


def normalize_history(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Message rows (sender_type, message_text) -> alternating user/assistant messages for the model."""
    out: list[dict[str, Any]] = []
    for r in rows[-limit:]:
        text = (r.get("message_text") or "").strip()
        if not text:
            continue
        role = "user" if r.get("sender_type") == "customer" else "assistant"
        if role == "assistant" and r.get("sender_type") not in ("ai", "assistant"):
            text = f"[shop staff] {text}"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":  # the current message is appended by the agent
        out.append({"role": "assistant", "content": "(no reply was sent)"})
    return out


def _confidence(action: str | None, has_evidence: bool, retried: bool) -> float:
    """Grounding-based reliability score (not a model self-report): answers backed by tool evidence
    that passed the check first time score highest."""
    score = 0.9 if has_evidence else 0.75
    return round(score - (0.2 if retried else 0.0), 2)


def _intelligence(result: Any, ctx: ToolContext, state: dict[str, Any], model: str) -> dict[str, Any]:
    search = next((s["arguments"] for s in reversed(result.trace.steps) if s["tool"] == "search_products" and s.get("ok")), {})
    return {
        "intent": result.intent or "other",
        "confidence": _confidence(result.action, bool(ctx.evidence.products or ctx.evidence.texts), result.trace.grounding_retried),
        "entities": {
            "brands": [str(search["brand"]).lower()] if search.get("brand") else [],
            "product_type": search.get("category"),
            "budget_max": search.get("max_price_kes", state.get("budget_max_kes")),
            "condition": search.get("condition"),
            "priorities": [],
            "product_mentions": [search["query"]] if search.get("query") else [],
        },
        "sales_signal": {"purchase_intent": result.intent in ("purchase", "reservation"), "objection": None},
        "products_considered": len(ctx.evidence.products),
        "action": result.action,
        "model": model,
        "trace": result.trace.to_dict(),
    }


def respond(*, db: Any, business: dict[str, Any], conversation_id: str, customer_id: str | None, customer_message: str,
            history_rows: list[dict[str, Any]], provider: LLMProvider | None = None, repo: ShopRepository | None = None,
            registry: ToolRegistry | None = None) -> TurnResult:
    provider = provider or get_provider()
    if provider is None:
        log.error("assistant_unavailable reason=not_configured")
        return TurnResult("unavailable", failure="not_configured")
    business_id = business["id"]
    try:
        repo = repo or SupabaseShopRepository(db, business_id, business)  # tenant fixed HERE, from the authenticated business
        shop, products = repo.get_business(), repo.list_products()
        state = repo.get_state(conversation_id)
        ctx = ToolContext(repo=repo, conversation_id=conversation_id, customer_id=customer_id)
        agent = Agent(provider, registry or ToolRegistry(), deadline_s=settings.assistant_deadline_s)
        result = agent.run(
            ctx,
            system_prompt=build_system_prompt(shop.get("name") or business.get("name"), shop.get("timezone"),
                                              catalog_snapshot(products), conv_state.for_prompt(state, products)),
            history=normalize_history(history_rows, settings.assistant_history_messages),
            customer_message=customer_message, state=state)
    except DataUnavailable as exc:
        log.error("assistant_unavailable business=%s reason=data_unavailable detail=%s", business_id, exc)
        return TurnResult("unavailable", failure="data_unavailable")
    except Exception:
        log.exception("assistant_unavailable business=%s reason=internal_error", business_id)
        return TurnResult("unavailable", failure="internal_error")

    trace = result.trace
    if result.status != "answered":
        log.warning("assistant_unavailable business=%s reason=%s model_calls=%d tokens=%d latency_ms=%d",
                    business_id, trace.failure, trace.model_calls, trace.prompt_tokens + trace.completion_tokens, trace.latency_ms)
        return TurnResult("unavailable", failure=trace.failure)

    catalog_ids = {str(p.get("id")) for p in products}
    known = (set(ctx.evidence.products) | set(state.get("focus_product_ids", []))) & catalog_ids
    merged = conv_state.merge(state, conv_state.sanitize_update(result.state_update, known_ids=known))
    if merged != state and not repo.save_state(conversation_id, merged):
        log.info("state_not_persisted business=%s (conversations.agent_state unavailable)", business_id)
    log.info("assistant_turn business=%s conversation=%s action=%s model=%s model_calls=%d tools=%s tokens=%d latency_ms=%d retried=%s",
             business_id, conversation_id, result.action, provider.model, trace.model_calls, trace.tools_called,
             trace.prompt_tokens + trace.completion_tokens, trace.latency_ms, trace.grounding_retried)
    return TurnResult("answered", result.reply, _intelligence(result, ctx, merged, provider.model))
