"""Post-generation grounding check: the database wins, always.

The model may reason and phrase freely, but any money amount, stock count or
"order placed" claim in its reply must be backed by tool evidence gathered this turn.
This is a backstop against fabrication; it does not replace the prompt or evaluation.

What it checks (deterministically):
  * money amounts (KES/KSh/"/=", 5+ digit or comma-grouped numbers, "45k") must equal a
    price seen in tool results, a quantity multiple / sum / difference of those prices,
    a number in the shop's own policy text, or a number the customer wrote;
  * stock statements ("only 3 left", "5 in stock") must equal a stock_quantity retrieved;
  * cited product ids must have been retrieved this turn;
  * the reply must not say an order is placed/confirmed unless the backend confirmed one.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

from app.agent.tools import Evidence

_MONEY_MARKED = re.compile(r"(?:KES|KSh|Ksh|Kshs|Sh)\.?\s*([\d][\d,]*(?:\.\d+)?)\s*([kK]\b)?|(?<![\w.,])([\d][\d,]*(?:\.\d+)?)\s*(?:/=|KES\b|KSh\b|Ksh\b|shillings?\b)", re.I)
_MONEY_GROUPED = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+)(?![\d,]|\.\d)")
_MONEY_LONG = re.compile(r"(?<![\d.,+])(\d{5,7})(?![\d,]|\s?(?:mah|gb|tb|mp|hz|w)\b)", re.I)
_MONEY_K = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d)?)\s?[kK]\b")
_STOCK = re.compile(r"(?:only\s+)?(?<![\w.,])(\d+)\s+(?:units?\s+|pieces?\s+|pcs\s+)?(?:left|remaining|in stock)\b|stock(?:\s+level)?\s*(?:is|:)\s*(\d+)", re.I)
_ORDER_CLAIM = re.compile(
    r"\border\b[^.!?\n]{0,50}\b(?:has been|have been|is now|was|is)\s+(?:placed|created|confirmed|recorded|received|booked|processed|complete)\b"
    r"|\bI(?:'ve| have)\s+(?:placed|created|recorded|booked|confirmed)\b[^.!?\n]{0,30}\border\b", re.I)


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def money_amounts(text: str) -> list[float]:
    """All money-looking amounts in `text` (KES)."""
    out: list[float] = []
    for m in _MONEY_MARKED.finditer(text):
        if m.group(1):
            v = _to_float(m.group(1)) * (1000 if m.group(2) else 1)
        else:
            v = _to_float(m.group(3))
        out.append(v)
    out += [_to_float(m.group(1)) for m in _MONEY_GROUPED.finditer(text)]
    out += [float(m.group(1)) for m in _MONEY_LONG.finditer(text) if not m.group(1).startswith("0")]
    return out


def _k_amounts(text: str) -> list[float]:
    return [float(m.group(1)) * 1000 for m in _MONEY_K.finditer(text)]


def customer_numbers(texts: list[str]) -> set[float]:
    nums = set(money_amounts(" ".join(texts))) | set(_k_amounts(" ".join(texts)))
    nums |= {float(n) for n in re.findall(r"(?<![\d.])\d{1,4}(?![\d.])", " ".join(texts))}
    return nums


@dataclass
class GroundingReport:
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def allowed_amounts(ev: Evidence, customer_texts: list[str], state: dict) -> set[float]:
    prices = sorted({float(p["price_kes"]) for p in ev.products.values() if p.get("price_kes") is not None})[:8]
    policy_nums: set[float] = set()
    for t in ev.texts:
        policy_nums |= set(money_amounts(t)) | {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)}
    qty = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20}
    if state.get("quantity"):
        qty.add(int(state["quantity"]))
    allowed: set[float] = set(prices) | policy_nums | customer_numbers(customer_texts)
    for p in prices:
        for k in qty:
            allowed.add(p * k)
            for q in policy_nums:
                allowed.add(p * k + q)
    for a, b in itertools.combinations(prices, 2):
        allowed |= {a + b, abs(a - b)}
    if state.get("budget_max_kes") is not None:
        allowed.add(float(state["budget_max_kes"]))
    return allowed


def check_reply(reply: str, ev: Evidence, customer_texts: list[str], state: dict, cited_product_ids: list[str] | None = None,
                claims_order_confirmed: bool = False) -> GroundingReport:
    rep = GroundingReport()
    allowed = allowed_amounts(ev, customer_texts, state)
    for amt in dict.fromkeys(money_amounts(reply)):
        if amt not in allowed:
            rep.violations.append(f"The amount {amt:,.0f} in your reply is not supported by any tool result. Quote only prices returned by tools this turn.")
    for approx in dict.fromkeys(_k_amounts(reply)):
        if not any(abs(approx - a) <= max(500, 0.015 * a) for a in allowed):
            rep.violations.append(f"The approximate amount {approx:,.0f} is not close to any price returned by tools.")
    stocks = {p["stock_quantity"] for p in ev.products.values()}
    cust = customer_numbers(customer_texts) | ({float(state["quantity"])} if state.get("quantity") else set())
    for m in _STOCK.finditer(reply):
        n = int(m.group(1) or m.group(2))
        if n not in stocks and float(n) not in cust:
            rep.violations.append(f"You stated a stock count of {n}, but no retrieved product has that stock_quantity.")
    for pid in cited_product_ids or []:
        if pid not in ev.products:
            rep.violations.append(f"You cited product id {pid} which was not retrieved this turn. Retrieve it with get_product first.")
    if (claims_order_confirmed or _ORDER_CLAIM.search(reply)) and not ev.order_confirmed:
        rep.violations.append("Your reply says an order is placed/confirmed, but no order was created by the backend. Say the request was passed to the shop for confirmation instead.")
    return rep
