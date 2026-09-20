"""Agent tools: the ONLY way the model can read or change shop data.

Design rules
* The model never supplies a tenant. ``ToolContext.repo`` is bound to the authenticated
  business by the backend; tool schemas contain no business/owner id, and any such
  argument the model invents is discarded and logged as a security event.
* Arguments are validated against each tool's JSON schema before any handler runs.
* Handlers return compact, factual JSON. Everything returned is recorded as *evidence*
  so the grounding check can compare the final reply against it.
* Tools do search/filter/rank over the shop's own rows. The MODEL does the language
  understanding (mapping "poa ya around 50k" to max_price_kes=50000); tools contain no
  customer-phrase dictionaries.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable

from app.agent.repository import ShopRepository, is_uuid
from app.agent.types import ToolCall

FORBIDDEN_ARG_KEYS = {"business_id", "tenant_id", "owner_id", "shop_id", "user_id", "customer_id"}
MAX_TOOL_RESULT_CHARS = 12_000


# --------------------------------------------------------------------------- context / evidence
@dataclass
class Evidence:
    products: dict[str, dict[str, Any]] = field(default_factory=dict)   # id -> compact record shown to the model
    texts: list[str] = field(default_factory=list)                      # policy / profile passages shown to the model
    escalation_recorded: bool = False
    order_confirmed: bool = False  # only a real order tool + DB confirmation may set this (none exists yet)

    def add_products(self, items: list[dict[str, Any]]) -> None:
        for p in items:
            self.products[str(p["id"])] = p


@dataclass
class ToolContext:
    repo: ShopRepository
    conversation_id: str
    customer_id: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    recent_history: list[dict[str, Any]] = field(default_factory=list)
    evidence: Evidence = field(default_factory=Evidence)
    security_events: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    name: str
    ok: bool
    payload: dict[str, Any]
    summary: dict[str, Any] = field(default_factory=dict)

    def to_message_content(self) -> str:
        text = json.dumps(self.payload if self.ok else {"error": self.payload.get("error")}, ensure_ascii=False, default=str)
        return text if len(text) <= MAX_TOOL_RESULT_CHARS else text[:MAX_TOOL_RESULT_CHARS] + '..."[truncated]'


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    read_only: bool = True

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


# --------------------------------------------------------------------------- argument validation
def _coerce(value: Any, spec: dict[str, Any], path: str, errors: list[str]) -> Any:
    t = spec.get("type")
    if t == "string":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            errors.append(f"{path}: expected a string")
            return None
        value = value.strip()
        if "enum" in spec:
            match = next((e for e in spec["enum"] if e.lower() == value.lower()), None)
            if match is None:
                errors.append(f"{path}: must be one of {spec['enum']}")
                return None
            return match
        return value[: spec.get("maxLength", 500)]
    if t in ("integer", "number"):
        if isinstance(value, str):
            try:
                value = float(value.replace(",", "").strip())
            except ValueError:
                errors.append(f"{path}: expected a number")
                return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: expected a number")
            return None
        if t == "integer":
            if float(value) != int(value):
                errors.append(f"{path}: expected an integer")
                return None
            value = int(value)
        if "minimum" in spec and value < spec["minimum"]:
            errors.append(f"{path}: must be >= {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            errors.append(f"{path}: must be <= {spec['maximum']}")
        return value
    if t == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        errors.append(f"{path}: expected true or false")
        return None
    if t == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected a list")
            return None
        if len(value) > spec.get("maxItems", 50):
            errors.append(f"{path}: at most {spec['maxItems']} items")
            return None
        if len(value) < spec.get("minItems", 0):
            errors.append(f"{path}: at least {spec['minItems']} items")
            return None
        return [_coerce(v, spec.get("items", {"type": "string"}), f"{path}[]", errors) for v in value]
    errors.append(f"{path}: unsupported schema type")
    return None


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    props = schema.get("properties", {})
    clean: dict[str, Any] = {}
    for key, value in args.items():
        if key not in props:
            errors.append(f"unknown argument '{key}' (allowed: {sorted(props)})")
            continue
        if value is None:
            continue
        coerced = _coerce(value, props[key], key, errors)
        if coerced is not None or props[key].get("type") == "array":
            clean[key] = coerced
    for req in schema.get("required", []):
        if req not in clean:
            errors.append(f"missing required argument '{req}'")
    return clean, errors


# --------------------------------------------------------------------------- helpers
def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def compact_product(p: dict[str, Any], full: bool = False) -> dict[str, Any]:
    specs = p.get("specs") if isinstance(p.get("specs"), dict) else {}
    stock = int(_num(p.get("stock_quantity")) or 0)
    price = _num(p.get("price"))
    return {
        "id": str(p.get("id")), "name": p.get("name"), "brand": p.get("brand"), "category": p.get("category"),
        "variant": p.get("variant"), "condition": p.get("condition"),
        "price_kes": None if price is None else (int(price) if price == int(price) else price),
        "stock_quantity": stock, "in_stock": stock > 0,
        "installment_available": bool(p.get("installment_available")),
        "specs": dict(list(specs.items())[: 40 if full else 12]),
        "description": (p.get("description") or "")[: 1200 if full else 240],
    }


def _name_tokens(p: dict[str, Any]) -> set[str]:
    return set(_tokens(" ".join(str(p.get(k) or "") for k in ("name", "brand", "variant", "category"))))


def _all_tokens(p: dict[str, Any]) -> set[str]:
    return set(_tokens(" ".join(str(p.get(k) or "") for k in ("name", "brand", "variant", "category", "condition", "description")) + " " + json.dumps(p.get("specs") or {})))


def _fuzzy_in(tok: str, toks: set[str]) -> bool:
    if tok in toks:
        return True
    if len(tok) < 3:
        return False
    return any(tok in t or (len(t) >= 4 and t in tok) or (len(tok) >= 4 and SequenceMatcher(None, tok, t).ratio() >= 0.86) for t in toks)


def _term_matches(term: str, toks: set[str]) -> bool:
    parts = _tokens(term)
    return bool(parts) and all(_fuzzy_in(pt, toks) for pt in parts)


def _reference_candidates(ctx: ToolContext, reference: str, limit: int = 5) -> list[dict[str, Any]]:
    """Resolve a natural-language product reference against this shop's catalog and recent turns."""
    ref_tokens = set(_tokens(reference))
    if not ref_tokens:
        return []
    products = ctx.repo.list_products()
    recent_tokens = set(_tokens("\n".join(str(m.get("content") or "") for m in ctx.recent_history[-12:])))
    state_ids = set(str(x) for x in (ctx.state.get("selected_product_ids") or []) + (ctx.state.get("candidate_product_ids") or []))
    ranked: list[tuple[float, dict[str, Any]]] = []
    for product in products:
        name_tokens = _name_tokens(product)
        exact = len(ref_tokens & name_tokens)
        fuzzy = sum(1 for token in ref_tokens if any(_fuzzy_in(token, nt) for nt in name_tokens))
        recent = len(name_tokens & recent_tokens)
        state_bonus = 3.0 if str(product.get("id")) in state_ids else 0.0
        score = 3.0 * exact + 1.5 * fuzzy + recent + state_bonus
        if score > 0:
            ranked.append((score, product))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("name") or "")))
    return [compact_product(product, full=True) for _, product in ranked[:limit]]


def _resolve_product_reference(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    matches = _reference_candidates(ctx, a["reference"], limit=5)
    if not matches:
        return {
            "resolved": False,
            "reference": a["reference"],
            "matches": [],
            "note": "No product in this shop could be confidently linked to that reference. Ask one brief clarification question."
        }
    ctx.evidence.add_products(matches)
    return {
        "resolved": True,
        "reference": a["reference"],
        "matches": matches,
        "note": "Use the strongest match only when the conversation clearly identifies it; otherwise ask for clarification."
    }


def _list_catalog(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    products = ctx.repo.list_products()
    if a.get("in_stock_only", True):
        products = [p for p in products if int(_num(p.get("stock_quantity")) or 0) > 0]
    if a.get("category"):
        products = [p for p in products if _term_matches(a["category"], _name_tokens(p))]
    if a.get("brand"):
        brand = a["brand"].lower()
        products = [p for p in products if brand in str(p.get("brand") or "").lower() or brand in str(p.get("name") or "").lower()]
    products.sort(key=lambda p: str(p.get("name") or "").lower())
    limit = a.get("limit", 30)
    items = [compact_product(p) for p in products[:limit]]
    ctx.evidence.add_products(items)
    return {
        "in_stock_only": a.get("in_stock_only", True),
        "total": len(products),
        "products": items,
        "truncated": len(products) > limit,
    }


def _apply_filters(products: list[dict[str, Any]], f: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for p in products:
        price, stock = _num(p.get("price")), int(_num(p.get("stock_quantity")) or 0)
        if f.get("in_stock_only") and stock <= 0:
            continue
        if f.get("max_price_kes") is not None and (price is None or price > f["max_price_kes"]):
            continue
        if f.get("min_price_kes") is not None and (price is None or price < f["min_price_kes"]):
            continue
        if f.get("condition") and str(p.get("condition") or "").lower() != f["condition"].lower():
            continue
        if f.get("brand"):
            b = f["brand"].lower()
            if b not in str(p.get("brand") or "").lower() and b not in str(p.get("name") or "").lower():
                continue
        if f.get("category") and not _term_matches(f["category"], _name_tokens(p)):
            continue
        if f.get("installment_only") and not p.get("installment_available"):
            continue
        kws = f.get("keywords") or []
        if kws:
            names = _name_tokens(p)
            hit = sum(1 for k in kws if _term_matches(k, names) or _term_matches(k, _all_tokens(p)))
            if hit < max(1, (len(kws) + 1) // 2):
                continue
        out.append(p)
    return out


def _rank(products: list[dict[str, Any]], f: dict[str, Any]) -> list[dict[str, Any]]:
    kws, prefs = f.get("keywords") or [], f.get("preferences") or []
    sort = f.get("sort", "relevance")

    def score(p: dict[str, Any]) -> float:
        names, toks = _name_tokens(p), _all_tokens(p)
        kw = sum(1 for k in kws if _term_matches(k, names)) / len(kws) if kws else 0.0
        pref = sum(1 for k in prefs if any(pt in toks or any(t.startswith(pt) for t in toks) for pt in _tokens(k) if len(pt) >= 3)) / len(prefs) if prefs else 0.0
        return 3 * kw + 1.5 * pref + (0.3 if (_num(p.get("stock_quantity")) or 0) > 0 else 0)

    if sort == "price_asc":
        return sorted(products, key=lambda p: (_num(p.get("price")) is None, _num(p.get("price")) or 0))
    if sort == "price_desc":
        return sorted(products, key=lambda p: -(_num(p.get("price")) or 0))
    return sorted(products, key=lambda p: (-score(p), _num(p.get("price")) or 0))


# --------------------------------------------------------------------------- handlers
def _search_products(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    a = {"in_stock_only": True, **a}
    limit = a.pop("limit", 5)
    catalog = ctx.repo.list_products()
    ranked = _rank(_apply_filters(catalog, a), a)
    result: dict[str, Any] = {"applied_filters": {k: v for k, v in a.items() if v not in (None, [], "")}, "total_matches": len(ranked), "products": [compact_product(p) for p in ranked[:limit]]}
    notes: list[str] = []
    if not ranked:
        for constraint in ("in_stock_only", "max_price_kes", "min_price_kes", "condition", "installment_only", "brand", "category", "keywords"):
            if a.get(constraint) in (None, False, [], ""):
                continue
            relaxed = {k: v for k, v in a.items() if k != constraint}
            substantive = [k for k in ("max_price_kes", "min_price_kes", "condition", "installment_only", "brand", "category", "keywords") if relaxed.get(k) not in (None, False, [], "")]
            if not substantive:  # dropping this filter would return arbitrary items unrelated to the request
                continue
            alt = _rank(_apply_filters(catalog, relaxed), relaxed)
            if alt:
                result["alternatives"] = [compact_product(p) for p in alt[:3]]
                result["relaxed_constraint"] = constraint
                notes.append(f"Nothing matched every filter. These match if '{constraint}' is dropped. Say so explicitly; do not present them as exact matches.")
                break
        else:
            notes.append("No products in this shop match, even with filters relaxed.")
    if not catalog:
        notes.append("This shop has no products recorded.")
    if notes:
        result["notes"] = notes
    ctx.evidence.add_products(result["products"] + result.get("alternatives", []))
    return result


def _get_product(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    pid = a["product_id"]
    if not is_uuid(pid):
        return {"error": "product_id must be an id returned by search_products"}
    p = ctx.repo.get_product(pid)
    if not p:
        return {"error": "No product with that id in this shop."}
    c = compact_product(p, full=True)
    ctx.evidence.add_products([c])
    return {"product": c}


def _compare_products(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    items, missing = [], []
    for pid in dict.fromkeys(a["product_ids"]):
        p = ctx.repo.get_product(pid) if is_uuid(pid) else None
        (items if p else missing).append(compact_product(p, full=True) if p else pid)
    if len(items) < 2:
        return {"error": "Need at least two valid product ids from this shop.", "unknown_ids": missing}
    keys = list(dict.fromkeys(k for it in items for k in it["specs"]))[:15]
    ctx.evidence.add_products(items)
    return {"products": items, "spec_comparison": {k: {it["id"]: it["specs"].get(k) for it in items} for k in keys}, "unknown_ids": missing}


def _business_information(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    b = ctx.repo.get_business()
    info = {k: b.get(k) for k in ("name", "industry", "phone", "whatsapp_number", "email", "timezone")}
    info["profile_text"] = (b.get("description") or "")[:2000]
    ctx.evidence.texts.append(json.dumps(info, ensure_ascii=False))
    return {"business": info}


POLICY_CUES = {
    "delivery": ("deliver", "delivery", "shipping", "courier", "dispatch", "pickup", "pick up", "collect", "free"),
    "payment": ("pay", "payment", "mpesa", "m-pesa", "cash", "card", "till", "paybill", "deposit", "installment", "instalment"),
    "warranty": ("warranty", "guarantee", "repair", "defect"),
    "returns": ("return", "refund", "exchange", "replace"),
    "opening_hours": ("open", "close", "hours", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "am", "pm"),
    "location": ("located", "location", "address", "street", "road", "building", "floor", "town", "find us", "visit"),
    "other": (),
}


def _shop_policy(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    text = (ctx.repo.get_business().get("description") or "")
    passages = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) >= 8]
    cues, q = POLICY_CUES[a["topic"]], set(_tokens(a.get("question", "")))
    scored = []
    for s in passages:
        low, toks = s.lower(), set(_tokens(s))
        sc = sum(2 for c in cues if re.search(rf"\b{re.escape(c)}", low)) + len(q & toks)
        if sc > 0:
            scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    found = [s for _, s in scored[:4]]
    ctx.evidence.texts.extend(found)
    out: dict[str, Any] = {"topic": a["topic"], "found": bool(found), "passages": found, "source": "shop profile text written by the owner"}
    if not found:
        out["note"] = "The shop has not recorded this. Do not guess; say it is not on record and offer to ask the owner (escalate_to_owner)."
    return out


def _get_state(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    return {"state": ctx.state}


STATE_SCHEMA = {"type": "object", "properties": {
    "stage": {"type": "string", "enum": ["discovery", "recommendation", "product_selected", "questions", "purchase_intent", "ordering", "delivery", "escalated"]},
    "selected_product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    "candidate_product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    "budget_max_kes": {"type": "number", "minimum": 0},
    "preferences": {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 8},
    "quantity": {"type": "integer", "minimum": 1, "maximum": 1000},
    "fulfilment": {"type": "string", "enum": ["pickup", "delivery"]},
    "delivery_location": {"type": "string", "maxLength": 80},
}, "additionalProperties": False}


def _save_state(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    for key in ("selected_product_ids", "candidate_product_ids"):
        for pid in a.get(key, []):
            if not is_uuid(pid) or not ctx.repo.get_product(pid):
                return {"error": f"{key} contains an id that is not a product of this shop"}
    ctx.state.update(a)
    persisted = ctx.repo.save_state(ctx.conversation_id, ctx.state)
    return {"saved": True, "persisted": persisted, "state": ctx.state}


def _escalate(ctx: ToolContext, a: dict[str, Any]) -> dict[str, Any]:
    if ctx.evidence.escalation_recorded:
        return {"handoff_recorded": True, "note": "Already escalated this turn."}
    res = ctx.repo.create_escalation(ctx.conversation_id, ctx.customer_id, a["reason"], a["summary"], a.get("urgency", "normal"))
    ctx.evidence.escalation_recorded = bool(res.get("recorded"))
    b = ctx.repo.get_business()
    out = {"handoff_recorded": bool(res.get("recorded")), "owner_contact": {"phone": b.get("phone"), "whatsapp": b.get("whatsapp_number")}}
    if not out["handoff_recorded"]:
        out["note"] = "The handoff could NOT be saved. Do not promise that the shop was notified; give the owner_contact details instead."
    return out


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def default_tools() -> list[Tool]:
    return [
        Tool("resolve_product_reference",
             "Resolve references such as 'the calculator', 'that Samsung', 'the first one', or 'the cheaper one' using recent conversation and THIS shop's catalog. Use this before answering a product follow-up.",
             _obj({"reference": {"type": "string", "maxLength": 160}}, ["reference"]), _resolve_product_reference),
        Tool("search_products",
             "Search THIS shop's catalog. Map the customer's request to structured filters yourself (in any language). "
             "Returns real records with price_kes and stock_quantity; these are the only source of price/stock/spec facts.",
             _obj({
                 "category": {"type": "string", "description": "Catalog category as listed in the shop snapshot, e.g. 'phone'."},
                 "brand": {"type": "string"},
                 "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "description": "Model/product words that must appear, e.g. ['galaxy','s24']. Only for named products."},
                 "preferences": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "description": "Soft wants used for ranking, with synonyms, e.g. ['camera','photo','MP']."},
                 "min_price_kes": {"type": "number", "minimum": 0}, "max_price_kes": {"type": "number", "minimum": 0},
                 "condition": {"type": "string", "enum": ["new", "refurbished", "used"]},
                 "in_stock_only": {"type": "boolean", "description": "Default true. Set false only if the customer asks about out-of-stock items."},
                 "installment_only": {"type": "boolean"},
                 "sort": {"type": "string", "enum": ["relevance", "price_asc", "price_desc"]},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 8},
             }), _search_products),
        Tool("get_product", "Fetch the full, current record (all specs, price, stock) for one product id. Use it to verify facts before quoting them.",
             _obj({"product_id": {"type": "string"}}, ["product_id"]), _get_product),
        Tool("list_catalog",
             "List the shop's current catalog. Use for requests such as 'what products do you have in stock?' so the answer reflects the real catalog.",
             _obj({
                 "category": {"type": "string"},
                 "brand": {"type": "string"},
                 "in_stock_only": {"type": "boolean", "description": "Default true."},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 30}
             }), _list_catalog),
        Tool("compare_products", "Compare 2-4 products of this shop side by side.",
             _obj({"product_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4}}, ["product_ids"]), _compare_products),
        Tool("get_business_information", "Shop name, contact numbers, timezone and the owner's profile text.", _obj({}), _business_information),
        Tool("get_shop_policy", "Look up what the owner has recorded about delivery, payment, warranty, returns, opening hours or location.",
             _obj({"topic": {"type": "string", "enum": list(POLICY_CUES)}, "question": {"type": "string", "maxLength": 200, "description": "The customer's question in your own words."}}, ["topic"]), _shop_policy),
        Tool("get_conversation_state", "The structured state saved for this conversation (selected product, budget, quantity, delivery...).", _obj({}), _get_state),
        Tool("save_conversation_state", "Save structured facts about this conversation so later turns can rely on them. Only ids returned by tools are accepted.",
             STATE_SCHEMA, _save_state, read_only=False),
        Tool("escalate_to_owner",
             "Hand the conversation to the shop owner: unknown information, complaints, price negotiation, custom requests, or when the customer wants to buy (the owner confirms orders).",
             _obj({"reason": {"type": "string", "enum": ["unknown_information", "complaint", "negotiation", "order_help", "custom_request", "other"]},
                   "summary": {"type": "string", "maxLength": 400, "description": "What the owner needs to know, incl. product, quantity, delivery place."},
                   "urgency": {"type": "string", "enum": ["low", "normal", "high"]}}, ["reason", "summary"]), _escalate, read_only=False),
    ]


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools = {t.name: t for t in (tools if tools is not None else default_tools())}

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def execute(self, ctx: ToolContext, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.name, False, {"error": f"unknown tool '{call.name}'. Available: {self.names()}"})
        if call.arguments_error:
            return ToolResult(call.name, False, {"error": call.arguments_error})
        args = dict(call.arguments)
        for key in FORBIDDEN_ARG_KEYS & set(args):
            ctx.security_events.append(f"{call.name}: model supplied '{key}' (ignored; tenant is fixed by the backend)")
            args.pop(key)
        clean, errors = validate_args(tool.parameters, args)
        if errors:
            return ToolResult(call.name, False, {"error": "; ".join(errors)})
        try:
            payload = tool.handler(ctx, clean)
        except Exception as exc:  # a tool bug must never crash the conversation
            print(f"[Intelispark agent tool {call.name}] {exc!r}")
            return ToolResult(call.name, False, {"error": "tool failed; try a different approach or escalate"})
        if "error" in payload:
            return ToolResult(call.name, False, payload)
        summary = {"count": len(payload.get("products", [])) if "products" in payload else None, "total_matches": payload.get("total_matches")}
        return ToolResult(call.name, True, payload, {k: v for k, v in summary.items() if v is not None})
