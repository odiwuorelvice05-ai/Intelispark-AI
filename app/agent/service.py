"""Glue between the FastAPI endpoint and the agent.

Returns None whenever the agent cannot produce a grounded answer (disabled, not
configured, provider failure, timeout, grounding failure) so the caller falls back to
the legacy engine. The agent is additive and cannot take the product down.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.loop import AgentRunner
from app.agent.providers import AIProvider, get_provider
from app.agent.providers.base import ProviderError
from app.agent.repository import ShopRepository, SupabaseShopRepository
from app.agent.tools import ToolContext, ToolRegistry
from app.config import settings

_provider: AIProvider | None = None


def agent_enabled() -> bool:
    return settings.agent_mode == "on"


def _get_provider() -> AIProvider | None:
    global _provider
    if _provider is None:
        try:
            _provider = get_provider(settings.ai_provider, api_key=settings.mistral_api_key, model=settings.agent_model,
                                     reasoning_effort=settings.agent_reasoning_effort or None)
        except ProviderError as exc:
            print(f"[Intelispark agent] provider unavailable: {exc}")
            return None
        print(f"[Intelispark agent] provider={_provider.name} model={_provider.model} enabled={_provider.enabled} "
              f"reasoning_effort={getattr(_provider, 'reasoning_effort', None) or 'unset'}"
              + ("" if _provider.enabled else " (not configured: legacy engine will answer)"))
    return _provider if _provider.enabled else None


def status() -> dict[str, Any]:
    prov = _get_provider() if agent_enabled() else None
    return {"mode": settings.agent_mode, "provider": settings.ai_provider, "model": settings.agent_model, "active": bool(prov)}


def normalize_history(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Chat rows (sender_type, message_text) -> alternating user/assistant messages."""
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
    if out and out[-1]["role"] == "user":  # the current message is appended by the runner
        out.append({"role": "assistant", "content": "(no reply was sent)"})
    return out


@dataclass
class AgentOutcome:
    reply: str
    intelligence: dict[str, Any]


def to_intelligence(result: Any, provider: AIProvider) -> dict[str, Any]:
    """Map the agent's result onto the response shape the dashboard already reads."""
    t, ctx = result.trace, result.ctx
    last_search = next((s["arguments"] for s in reversed(t.steps) if s.get("tool") == "search_products" and s.get("ok")), {})
    stage = str(ctx.state.get("stage") or "")
    return {
        "intent": t.customer_intent or "general",
        "confidence": t.confidence,
        "entities": {
            "brands": [last_search["brand"].lower()] if last_search.get("brand") else [],
            "product_type": last_search.get("category"),
            "budget_max": last_search.get("max_price_kes", ctx.state.get("budget_max_kes")),
            "condition": last_search.get("condition"),
            "priorities": last_search.get("preferences", ctx.state.get("preferences", [])),
            "product_mentions": last_search.get("keywords", []),
        },
        "sales_signal": {"purchase_intent": stage in {"purchase_intent", "ordering", "delivery"} or "purchase" in (t.customer_intent or ""), "objection": None},
        "products_considered": len(ctx.evidence.products),
        "model": f"{provider.name}:{provider.model} (tool-calling agent)",
        "agent": t.to_dict(),
    }


def run_agent_turn(*, db: Any, business: dict[str, Any], conversation_id: str, customer_id: str | None,
                   customer_message: str, history_rows: list[dict[str, Any]], repo: ShopRepository | None = None,
                   provider: AIProvider | None = None) -> AgentOutcome | None:
    provider = provider or _get_provider()
    if provider is None:
        return None
    try:
        repo = repo or SupabaseShopRepository(db, business["id"])  # tenant fixed HERE, from the authenticated business
        ctx = ToolContext(repo=repo, conversation_id=conversation_id, customer_id=customer_id)
        runner = AgentRunner(provider, ToolRegistry(), deadline_s=settings.agent_deadline_s)
        result = runner.run(ctx, shop_name=business.get("name", "the shop"),
                            history=normalize_history(history_rows, settings.agent_history_messages), customer_message=customer_message)
    except Exception as exc:
        print(f"[Intelispark agent] {exc!r}")
        return None
    if result.status != "answered" or not result.reply:
        print(f"[Intelispark agent] fallback: {result.trace.fallback_reason}")
        return None
    return AgentOutcome(result.reply, to_intelligence(result, provider))
