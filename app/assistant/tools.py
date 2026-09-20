"""The model's data capabilities: four tools, each a real business operation.

  search_products   find products in THIS shop (query + structured filters)
  get_products      exact, current records for known product ids
  get_shop_info     the shop's contact details and the owner's written policies
  escalate_to_owner hand the conversation to a human

Rules enforced here: the tenant is fixed by the repository (no tool takes a business id; one
the model invents is discarded and logged); arguments are validated; everything a tool returns
is recorded as *evidence* that the final answer is checked against.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.assistant import catalog
from app.assistant.repository import DataUnavailable, ShopRepository, is_uuid
from app.assistant.schema import validate
from app.assistant.types import ToolCall

log = logging.getLogger("intelispark.assistant")
FORBIDDEN_ARG_KEYS = {"business_id", "tenant_id", "owner_id", "shop_id", "user_id", "customer_id"}
MAX_TOOL_RESULT_CHARS = 10_000
PROFILE_CHARS = 4000


@dataclass
class Evidence:
    """Everything the model was shown this turn. The final answer may only rest on this."""
    products: dict[str, dict[str, Any]] = field(default_factory=dict)   # id -> record shown
    texts: list[str] = field(default_factory=list)                      # shop profile text shown
    escalation_recorded: bool = False


@dataclass
class ToolContext:
    repo: ShopRepository
    conversation_id: str
    customer_id: str | None = None
    evidence: Evidence = field(default_factory=Evidence)
    security_events: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    ok: bool
    payload: dict[str, Any]

    def content(self) -> str:
        text = json.dumps(self.payload if self.ok else {"error": self.payload.get("error")}, ensure_ascii=False, default=str)
        return text if len(text) <= MAX_TOOL_RESULT_CHARS else text[:MAX_TOOL_RESULT_CHARS] + '..."[truncated]'


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


# ---- handlers ---------------------------------------------------------------------------
def _search_products(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    payload, shown = catalog.search(ctx.repo.list_products(), a)
    for p in shown:
        ctx.evidence.products[p["id"]] = p
    return payload


def _get_products(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    found, missing = [], []
    for pid in dict.fromkeys(a["product_ids"]):
        p = ctx.repo.get_product(pid) if is_uuid(pid) else None
        if p:
            found.append(catalog.compact(p, full=True))
        else:
            missing.append(pid)
    for c in found:
        ctx.evidence.products[c["id"]] = c
    if not found:
        return {"error": "None of those ids are products of this shop. Use ids returned by search_products.", "unknown_ids": missing}
    return {"products": found, "unknown_ids": missing}


def _get_shop_info(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    b = ctx.repo.get_business()
    info = {k: b.get(k) for k in ("name", "industry", "phone", "whatsapp_number", "email", "timezone")}
    profile = (b.get("description") or "")[:PROFILE_CHARS]
    ctx.evidence.texts.append(json.dumps(info, ensure_ascii=False) + " " + profile)
    out: dict[str, Any] = {"shop": info, "owner_written_profile": profile or None,
                           "note": "Location, opening hours, delivery, payment, warranty and return policies exist ONLY if written in owner_written_profile or the fields above."}
    if not profile:
        out["note"] = "The owner has not written a profile. Anything not in 'shop' is not on record."
    return out


def _escalate(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    if not ctx.evidence.escalation_recorded:
        ctx.evidence.escalation_recorded = ctx.repo.create_escalation(
            ctx.conversation_id, ctx.customer_id, a["reason"], a["summary"], a.get("urgency", "normal"))
    b = ctx.repo.get_business()
    out: dict[str, Any] = {"handoff_recorded": ctx.evidence.escalation_recorded, "owner_contact": {"phone": b.get("phone"), "whatsapp": b.get("whatsapp_number")}}
    if not ctx.evidence.escalation_recorded:
        out["note"] = "The handoff could NOT be saved. Do not say the shop was notified; give owner_contact instead."
    return out


def default_tools() -> list[Tool]:
    return [
        Tool("search_products",
             "Search THIS shop's catalog. Put the product words the customer used (model, variant, storage size) in `query`; put brand, category, budget, condition etc. in the filters. "
             "Leave `query` empty to browse (e.g. 'what Samsung phones do you have'). Each result says match=exact|partial and lists unmatched_terms. "
             "Returns real records; price_kes and stock_quantity here are the only source of price/stock.",
             _obj({
                 "query": {"type": "string", "maxLength": 120, "description": "Product words only, e.g. 'galaxy a05 128gb'."},
                 "brand": {"type": "string"},
                 "category": {"type": "string", "description": "A category as listed in the shop snapshot."},
                 "min_price_kes": {"type": "number", "minimum": 0}, "max_price_kes": {"type": "number", "minimum": 0},
                 "condition": {"type": "string", "enum": ["new", "refurbished", "used"]},
                 "in_stock_only": {"type": "boolean", "description": "Set true when browsing or recommending. Leave unset when the customer asks about a specific item, so a sold-out item is reported as sold out rather than as missing."},
                 "installment_only": {"type": "boolean"},
                 "exclude_product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "description": "For 'what else do you have': ids already shown."},
                 "sort": {"type": "string", "enum": ["relevance", "price_asc", "price_desc"]},
                 "limit": {"type": "integer", "minimum": 1, "maximum": catalog.MAX_LIMIT},
             }), _search_products),
        Tool("get_products",
             "Get the full, current record (all specs, price, stock) for 1-5 product ids. Use it to re-check anything you will quote about a product discussed earlier, and to compare products.",
             _obj({"product_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5}}, ["product_ids"]), _get_products),
        Tool("get_shop_info",
             "The shop's name, phone/WhatsApp, timezone and the owner's written profile (location, hours, delivery, payment, warranty, returns).",
             _obj({}), _get_shop_info),
        Tool("escalate_to_owner",
             "Hand the conversation to the shop owner: information you do not have, complaints, price negotiation, custom requests, reservations, or a customer ready to buy (only the owner can confirm orders and reservations).",
             _obj({"reason": {"type": "string", "enum": ["unknown_information", "complaint", "negotiation", "order_help", "custom_request", "other"]},
                   "summary": {"type": "string", "maxLength": 400, "description": "What the owner needs: product, quantity, pickup/delivery place, what the customer asked."},
                   "urgency": {"type": "string", "enum": ["low", "normal", "high"]}}, ["reason", "summary"]), _escalate),
    ]


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools = {t.name: t for t in (tools if tools is not None else default_tools())}

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def execute(self, ctx: ToolContext, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(False, {"error": f"unknown tool '{call.name}'. Available: {list(self._tools)}"})
        if call.arguments_error:
            return ToolResult(False, {"error": call.arguments_error})
        args = dict(call.arguments)
        for key in FORBIDDEN_ARG_KEYS & set(args):
            ctx.security_events.append(f"{call.name}: model supplied '{key}' (discarded; the tenant is fixed by the backend)")
            args.pop(key)
        clean, errors = validate(tool.parameters, args)
        if errors:
            return ToolResult(False, {"error": "; ".join(errors)})
        try:
            payload = tool.handler(ctx, clean)
        except DataUnavailable:
            raise  # the shop's data cannot be read: the turn must fail, never continue on guesses
        except Exception as exc:
            log.error("tool_failed tool=%s error=%r", call.name, exc)
            return ToolResult(False, {"error": "tool failed; try a different approach or escalate"})
        return ToolResult("error" not in payload, payload)
