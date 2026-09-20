"""Post-generation checks: the database wins.

The model chooses what to say and how; this module only refuses replies that contradict
what the tools returned this turn. It is a narrow safety net, not the intelligence:

  * money amounts in the reply must equal a price the tools returned, a simple multiple or
    sum of those prices, a figure in the shop's own profile text, or the budget the customer
    stated (as recorded in conversation state). A figure that only the CUSTOMER wrote ("the owner
    said 30,000") is never accepted as a shop fact;
  * "N left / N in stock" must equal a stock_quantity the tools returned;
  * per-product claims the model declares (availability, price) must match the record it saw;
  * the reply may never say an order/reservation is placed or confirmed (the application cannot create one).

A rejected reply is sent back to the model once with the reasons, then discarded.
"""
from __future__ import annotations

import itertools
import re
from typing import Any

from app.assistant.tools import Evidence

_MONEY_MARKED = re.compile(r"(?:KES|KSh|Ksh|Kshs|Sh)\.?\s*([\d][\d,]*(?:\.\d+)?)\s*([kK]\b)?|(?<![\w.,])([\d][\d,]*(?:\.\d+)?)\s*(?:/=|KES\b|KSh\b|Ksh\b|shillings?\b)", re.I)
_MONEY_GROUPED = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+)(?![\d,]|\.\d)")
_MONEY_LONG = re.compile(r"(?<![\d.,+])(\d{5,7})(?![\d,]|\s?(?:mah|gb|tb|mp|hz|w)\b)", re.I)
_MONEY_K = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d)?)\s?[kK]\b")
_STOCK = re.compile(r"(?:only\s+)?(?<![\w.,])(\d+)\s+(?:units?\s+|pieces?\s+|pcs\s+)?(?:left|remaining|in stock)\b|stock(?:\s+level)?\s*(?:is|:)\s*(\d+)", re.I)
_ORDER_CLAIM = re.compile(
    r"\b(?:order|reservation)\b[^.!?\n]{0,50}\b(?:has been|have been|is now|was|is)\s+(?:placed|created|confirmed|recorded|received|booked|processed|complete|reserved)\b"
    r"|\bI(?:'ve| have)\s+(?:placed|created|recorded|booked|confirmed)\b[^.!?\n]{0,30}\b(?:order|reservation)\b"
    r"|\bI(?:'ve| have)\s+(?:reserved|booked|put aside|set aside)\b", re.I)


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def money_amounts(text: str) -> list[float]:
    out: list[float] = []
    for m in _MONEY_MARKED.finditer(text):
        out.append(_f(m.group(1)) * (1000 if m.group(2) else 1) if m.group(1) else _f(m.group(3)))
    out += [_f(m.group(1)) for m in _MONEY_GROUPED.finditer(text)]
    out += [float(m.group(1)) for m in _MONEY_LONG.finditer(text) if not m.group(1).startswith("0")]
    return out


def _k_amounts(text: str) -> list[float]:
    return [float(m.group(1)) * 1000 for m in _MONEY_K.finditer(text)]


def _allowed_amounts(ev: Evidence, state: dict[str, Any]) -> set[float]:
    prices = sorted({float(p["price_kes"]) for p in ev.products.values() if p.get("price_kes") is not None})[:8]
    shop_nums: set[float] = set()
    for t in ev.texts:
        shop_nums |= set(money_amounts(t)) | {_f(n) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)}
    qty = set(range(1, 11)) | {12, 15, 20} | ({int(state["quantity"])} if state.get("quantity") else set())
    allowed = set(prices) | shop_nums
    for p in prices:
        for k in qty:
            allowed.add(p * k)
            allowed |= {p * k + s for s in shop_nums}  # e.g. price plus a delivery fee the shop stated
    for a, b in itertools.combinations(prices, 2):
        allowed |= {a + b, abs(a - b)}
    if state.get("budget_max_kes") is not None:
        allowed.add(float(state["budget_max_kes"]))
    return allowed


def check_reply(reply: str, ev: Evidence, state: dict[str, Any],
                claims: list[dict[str, Any]] | None = None, claims_order_confirmed: bool = False) -> list[str]:
    """Return the reasons this reply must not be sent (empty list = grounded)."""
    violations: list[str] = []
    allowed = _allowed_amounts(ev, state)
    for amt in dict.fromkeys(money_amounts(reply)):
        if amt not in allowed:
            violations.append(f"The amount {amt:,.0f} is not supported by any tool result. Quote only prices the tools returned this turn.")
    for approx in dict.fromkeys(_k_amounts(reply)):
        if not any(abs(approx - a) <= max(500, 0.015 * a) for a in allowed):
            violations.append(f"The approximate amount {approx:,.0f} is not close to any price the tools returned.")
    stocks = {p["stock_quantity"] for p in ev.products.values()}
    for m in _STOCK.finditer(reply):
        n = int(m.group(1) or m.group(2))
        if n not in stocks:
            violations.append(f"You stated a stock count of {n}, but no retrieved product has that stock_quantity.")
    for c in claims or []:
        p = ev.products.get(c.get("product_id", ""))
        if p is None:
            violations.append(f"You made a claim about product {c.get('product_id')} which the tools did not return this turn. Retrieve it first.")
            continue
        if c.get("availability") == "in_stock" and not p["in_stock"]:
            violations.append(f"You said {p['name']} is in stock, but its stock_quantity is 0.")
        if c.get("availability") == "out_of_stock" and p["in_stock"]:
            violations.append(f"You said {p['name']} is out of stock, but stock_quantity is {p['stock_quantity']}.")
        if c.get("price_kes") is not None and (p["price_kes"] is None or abs(float(c["price_kes"]) - float(p["price_kes"])) > 0.5):
            violations.append(f"You quoted {p['name']} at {c['price_kes']}, but its price_kes is {p['price_kes']}.")
    if claims_order_confirmed or _ORDER_CLAIM.search(reply):
        violations.append("Your reply says an order or reservation was placed/confirmed. You cannot create either. Say the request was passed to the shop for confirmation (only if escalate_to_owner recorded it).")
    return violations
