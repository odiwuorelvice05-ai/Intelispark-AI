"""Structured conversation state, owned by the application (not by the model).

The model *proposes* an update in its final answer; the application validates it against
the shop's catalog and this turn's evidence, merges it and stores it. State holds only
references (product ids) and what the CUSTOMER said they want (quantity, budget, place).
It never stores prices or stock, so it cannot go stale or turn a customer's claim into a
shop fact: facts are re-read from the database every turn.
"""
from __future__ import annotations

from typing import Any

from app.assistant.repository import is_uuid

STATE_SCHEMA: dict[str, Any] = {"type": "object", "properties": {
    "focus_product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 5,
                          "description": "Ids of the products the customer is now talking about, most relevant first."},
    "quantity": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "How many the customer said they want."},
    "budget_max_kes": {"type": "number", "minimum": 0},
    "fulfilment": {"type": "string", "enum": ["pickup", "delivery"]},
    "delivery_location": {"type": "string", "maxLength": 80},
}}


def sanitize_update(update: dict[str, Any], *, known_ids: set[str]) -> dict[str, Any]:
    """Keep only fields that are safe to store; product ids must be ones this shop actually has."""
    clean = {k: v for k, v in update.items() if k in STATE_SCHEMA["properties"] and v not in (None, "", [])}
    if "focus_product_ids" in clean:
        ids = [i for i in dict.fromkeys(clean["focus_product_ids"]) if is_uuid(i) and i in known_ids]
        if ids:
            clean["focus_product_ids"] = ids
        else:
            clean.pop("focus_product_ids")
    return clean


def merge(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    return {**state, **update}


def for_prompt(state: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """State as shown to the model: product ids resolved to names (no prices or stock)."""
    by_id = {str(p.get("id")): p for p in catalog}
    out = {k: v for k, v in state.items() if k != "focus_product_ids"}
    focus = [{"id": i, "name": by_id[i].get("name"), "variant": by_id[i].get("variant")} for i in state.get("focus_product_ids", []) if i in by_id]
    if focus:
        out["focus_products"] = focus
    return out
