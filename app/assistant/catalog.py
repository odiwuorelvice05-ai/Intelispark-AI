"""Deterministic catalog retrieval over ONE shop's products.

This is search, not understanding. The model turns what the customer said into a query
plus structured filters (in any language); this module only matches those against the
shop's own rows and reports precisely what did and did not match. It contains no customer
phrases, no product-name special cases and no canned replies.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+")
_UNIT = re.compile(r"^(\d+)(gb|tb|mb|mp|mah|hz|w|inch)$")
_RELAXABLE = ("in_stock_only", "max_price_kes", "min_price_kes", "condition", "installment_only", "brand", "category")
MAX_LIMIT = 20


def num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def stock_of(p: dict[str, Any]) -> int:
    return int(num(p.get("stock_quantity")) or 0)


def _forms(token: str) -> set[str]:
    """A token plus harmless variants: '256gb' also answers to '256'; 'phones' also to 'phone'."""
    forms = {token}
    unit = _UNIT.match(token)
    if unit:
        forms.add(unit.group(1))
    if len(token) > 3 and token.endswith("s") and not token[-2].isdigit():
        forms.add(token[:-1])
    return forms


def _token_set(text: str) -> set[str]:
    out: set[str] = set()
    for tok in _TOKEN.findall(text.lower()):
        out |= _forms(tok)
    return out


def _term_hit(term: str, tokens: set[str]) -> bool:
    forms = _forms(term)
    if forms & tokens:
        return True
    if term.isalpha() and len(term) >= 5:  # tolerate typos in words ("samsng"), never in model codes ("a05")
        return any(t.isalpha() and len(t) >= 5 and SequenceMatcher(None, term, t).ratio() >= 0.84 for t in tokens)
    return False


def _name_tokens(p: dict[str, Any]) -> set[str]:
    return _token_set(" ".join(str(p.get(k) or "") for k in ("name", "brand", "variant")))


def _meta_tokens(p: dict[str, Any]) -> set[str]:
    specs = p.get("specs") if isinstance(p.get("specs"), dict) else {}
    return _token_set(" ".join(str(p.get(k) or "") for k in ("category", "condition", "description")) + " " + json.dumps(specs, ensure_ascii=False))


def compact(p: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    """The record the model sees. Prices/stock here are the only figures it may quote."""
    specs = p.get("specs") if isinstance(p.get("specs"), dict) else {}
    price = num(p.get("price"))
    stock = stock_of(p)
    return {
        "id": str(p.get("id")), "name": p.get("name"), "brand": p.get("brand"), "category": p.get("category"),
        "variant": p.get("variant"), "condition": p.get("condition"),
        "price_kes": None if price is None else (int(price) if price == int(price) else price),
        "stock_quantity": stock, "in_stock": stock > 0,
        "installment_available": bool(p.get("installment_available")),
        "specs": dict(list(specs.items())[: 40 if full else 12]),
        "description": (p.get("description") or "")[: 1200 if full else 240],
    }


def _passes_filters(p: dict[str, Any], f: dict[str, Any]) -> bool:
    price, name_toks = num(p.get("price")), _name_tokens(p)
    if f.get("in_stock_only") and stock_of(p) <= 0:
        return False
    if f.get("max_price_kes") is not None and (price is None or price > f["max_price_kes"]):
        return False
    if f.get("min_price_kes") is not None and (price is None or price < f["min_price_kes"]):
        return False
    if f.get("condition") and str(p.get("condition") or "").lower() != f["condition"].lower():
        return False
    if f.get("installment_only") and not p.get("installment_available"):
        return False
    if f.get("brand") and not all(_term_hit(t, name_toks) for t in _TOKEN.findall(f["brand"].lower())):
        return False
    if f.get("category") and not all(_term_hit(t, _meta_tokens(p) | name_toks) for t in _TOKEN.findall(f["category"].lower())):
        return False
    if str(p.get("id")) in set(f.get("exclude_product_ids") or []):
        return False
    return True


def _match_query(p: dict[str, Any], terms: list[str]) -> tuple[float, list[str], list[str]]:
    name_toks, meta_toks = _name_tokens(p), _meta_tokens(p)
    matched, unmatched, score = [], [], 0.0
    for t in terms:
        if _term_hit(t, name_toks):
            matched.append(t); score += 1.0
        elif _term_hit(t, meta_toks):
            matched.append(t); score += 0.6
        else:
            unmatched.append(t)
    return score / len(terms), matched, unmatched


def _run(products: list[dict[str, Any]], f: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    terms = _TOKEN.findall(str(f.get("query") or "").lower())
    rows: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for p in products:
        if not _passes_filters(p, f):
            continue
        if not terms:
            rows.append((0.0, p, {}))
            continue
        coverage, matched, unmatched = _match_query(p, terms)
        if len(matched) / len(terms) < 0.5:  # must explain at least half the customer's product words
            continue
        rows.append((coverage, p, {"match": "exact" if not unmatched else "partial", "unmatched_terms": unmatched}))
    sort = f.get("sort") or "relevance"
    price = lambda p: (num(p.get("price")) is None, num(p.get("price")) or 0.0)  # noqa: E731
    if sort == "price_asc":
        rows.sort(key=lambda r: price(r[1]))
    elif sort == "price_desc":
        rows.sort(key=lambda r: (num(r[1].get("price")) is None, -(num(r[1].get("price")) or 0.0)))
    elif terms:
        rows.sort(key=lambda r: (-r[0], stock_of(r[1]) <= 0, price(r[1])))
    else:
        rows.sort(key=lambda r: (stock_of(r[1]) <= 0, str(r[1].get("name") or "").lower()))
    return [(p, info) for _, p, info in rows]


def _relaxations(products: list[dict[str, Any]], f: dict[str, Any], *, exact_only: bool):
    """Yield (constraint, hits) for each single constraint that, when dropped, produces results."""
    for constraint in _RELAXABLE:
        if f.get(constraint) in (None, False, [], ""):
            continue
        relaxed = {k: v for k, v in f.items() if k != constraint}
        if not (relaxed.get("query") or any(relaxed.get(k) for k in _RELAXABLE)):
            continue  # dropping it would return arbitrary items unrelated to the request
        hits = [h for h in _run(products, relaxed) if not exact_only or h[1].get("match") == "exact"]
        if hits:
            yield constraint, hits


def search(products: list[dict[str, Any]], filters: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (tool payload, compact records shown to the model).

    Stock is NOT filtered unless asked, so a sold-out item the customer names is reported as sold
    out rather than as "not found". When the exact item is missing only because a constraint
    excluded it (budget, stock, condition...), that is reported separately.
    """
    f = dict(filters)
    limit = min(int(f.pop("limit", 5) or 5), MAX_LIMIT)
    hits = _run(products, f)
    shown = [{**compact(p), **info} for p, info in hits[:limit]]
    payload: dict[str, Any] = {
        "applied_filters": {k: v for k, v in f.items() if v not in (None, [], "")},
        "total_matches": len(hits), "products": shown,
    }
    seen = list(shown)
    notes: list[str] = []
    if f.get("query") and not any(info.get("match") == "exact" for _, info in hits):
        for constraint, alt in _relaxations(products, f, exact_only=True):
            blocked = [{**compact(p), **info} for p, info in alt[:3]]
            payload["exact_match_blocked_by"] = {"constraint": constraint, "products": blocked}
            notes.append(f"The exact item exists but was excluded by '{constraint}'. Tell the customer that; do not say the shop has none.")
            seen += blocked
            break
    if not hits:
        for constraint, alt in _relaxations(products, f, exact_only=False):
            payload["alternatives"] = [{**compact(p), **info} for p, info in alt[:3]]
            payload["relaxed_constraint"] = constraint
            notes.append(f"Nothing matched every requirement. These match if '{constraint}' is dropped. Say so explicitly; never present them as exact matches.")
            seen += payload["alternatives"]
            break
        else:
            notes.append("Nothing in this shop matches, even with filters relaxed.")
    if not products:
        notes = ["This shop has no products recorded."]
    if notes:
        payload["note"] = " ".join(notes)
    return payload, seen
