"""The controlled agent loop.

model -> (tool calls -> validated, tenant-scoped execution -> results) x N -> respond_to_customer
-> grounding check -> (retry once with the violations) -> answer | fallback

Bounded on model calls, tool calls, tokens and wall-clock. Any failure returns
status="fallback" so the caller can use the legacy engine; the agent never leaves a
customer without an answer and never returns an ungrounded one.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.agent.grounding import check_reply
from app.agent.prompt import build_system_prompt, catalog_snapshot
from app.agent.providers.base import AIProvider, ProviderError
from app.agent.tools import ToolContext, ToolRegistry, validate_args
from app.agent.trace import AgentTrace
from app.agent.types import ToolCall

FINAL_TOOL_NAME = "respond_to_customer"
FINAL_TOOL: dict[str, Any] = {
    "name": FINAL_TOOL_NAME,
    "description": "Send your final message to the customer and end the turn. Call it once, alone, after you have all the tool results you need.",
    "parameters": {"type": "object", "required": ["reply", "action"], "additionalProperties": False, "properties": {
        "reply": {"type": "string", "maxLength": 1200, "description": "The message to send to the customer."},
        "action": {"type": "string", "enum": ["answer", "clarify", "escalate"]},
        "customer_intent": {"type": "string", "maxLength": 60, "description": "Short label for what the customer wants, e.g. product_recommendation, price_question, delivery_question, purchase, comparison, greeting."},
        "missing_information": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 6},
        "evidence_product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "states_order_confirmed": {"type": "boolean", "description": "True only if your reply says an order was placed/confirmed. It must normally be false."},
    }},
}


@dataclass
class AgentResult:
    status: str  # "answered" | "fallback"
    reply: str | None
    trace: AgentTrace
    ctx: ToolContext


def compute_confidence(action: str, self_confidence: float | None, ctx: ToolContext, first_pass_ok: bool, missing: list[str]) -> float:
    """Evidence-based, transparent, and meant to be calibrated against the eval suite."""
    understanding = 0.7 if self_confidence is None else max(0.0, min(1.0, self_confidence))
    has_evidence = bool(ctx.evidence.products or ctx.evidence.texts)
    evidence = 1.0 if has_evidence else (0.6 if action == "clarify" else 0.3)
    grounding = 1.0 if first_pass_ok else 0.7
    conf = 0.3 * understanding + 0.4 * evidence + 0.3 * grounding
    if missing and action == "answer":
        conf *= 0.7
    return round(conf, 3)


class AgentRunner:
    def __init__(self, provider: AIProvider, registry: ToolRegistry, *, max_model_calls: int = 6, max_tool_calls: int = 8,
                 max_total_tokens: int = 24_000, deadline_s: float = 20.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.provider, self.registry = provider, registry
        self.max_model_calls, self.max_tool_calls = max_model_calls, max_tool_calls
        self.max_total_tokens, self.deadline_s, self.clock = max_total_tokens, deadline_s, clock

    def run(self, ctx: ToolContext, *, shop_name: str, history: list[dict[str, Any]], customer_message: str) -> AgentResult:
        trace = AgentTrace()
        started = self.clock()
        ctx.state = ctx.repo.get_state(ctx.conversation_id) or ctx.state
        system = build_system_prompt(shop_name, catalog_snapshot(ctx.repo.list_products()), ctx.state)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history, {"role": "user", "content": customer_message}]
        customer_texts = [m["content"] for m in history if m["role"] == "user"] + [customer_message]
        tools = self.registry.specs() + [FINAL_TOOL]
        seen: dict[str, Any] = {}
        tool_calls_used = 0
        retried = False

        def fallback(reason: str) -> AgentResult:
            trace.fallback_reason = reason
            trace.security_events = list(ctx.security_events)
            return AgentResult("fallback", None, trace, ctx)

        while trace.model_calls < self.max_model_calls:
            remaining = self.deadline_s - (self.clock() - started)
            if remaining <= 1.0:
                return fallback("deadline")
            try:
                turn = self.provider.chat(messages, tools, tool_choice="auto", max_tokens=700, temperature=0.2, timeout_s=min(15.0, remaining))
            except ProviderError as exc:
                return fallback(f"provider_error: {exc}")
            trace.model_calls += 1
            trace.prompt_tokens += turn.usage.get("prompt_tokens", 0)
            trace.completion_tokens += turn.usage.get("completion_tokens", 0)
            if trace.prompt_tokens + trace.completion_tokens > self.max_total_tokens:
                return fallback("token_budget")

            final_call = next((c for c in turn.tool_calls if c.name == FINAL_TOOL_NAME), None)
            other_calls = [c for c in turn.tool_calls if c.name != FINAL_TOOL_NAME]

            # ---- plain-text answer (model did not use the final tool) --------------------------------
            if not turn.tool_calls:
                text = (turn.content or "").strip()
                if not text:
                    return fallback("empty_model_reply")
                report = check_reply(text, ctx.evidence, customer_texts, ctx.state)
                if trace.grounding["first_pass_ok"] is None:
                    trace.grounding["first_pass_ok"] = report.ok
                if report.ok:
                    return self._finish(ctx, trace, text, "answer", {}, retried)
                trace.grounding["violations"] += report.violations
                if retried:
                    return fallback("grounding_failed")
                retried = trace.grounding["retried"] = True
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": "[system check] Your reply was rejected: " + " ".join(report.violations) + " Rewrite it using only tool evidence, and finish with respond_to_customer."}]
                continue

            messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in turn.tool_calls]})

            # ---- execute data tools ---------------------------------------------------------------
            for call in other_calls:
                key = call.name + json.dumps(call.arguments, sort_keys=True, default=str)
                if key in seen:
                    result_content = seen[key]
                else:
                    if tool_calls_used >= self.max_tool_calls:
                        result_content = json.dumps({"error": "tool budget exhausted; finish with what you have or escalate"})
                        trace.steps.append({"type": "tool", "tool": call.name, "ok": False, "error": "tool_budget"})
                    else:
                        tool_calls_used += 1
                        res = self.registry.execute(ctx, call)
                        result_content = res.to_message_content()
                        step: dict[str, Any] = {"type": "tool", "tool": call.name, "arguments": call.arguments, "ok": res.ok, **res.summary}
                        if not res.ok:
                            step["error"] = res.payload.get("error")
                        trace.steps.append(step)
                        seen[key] = result_content
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result_content})

            if not final_call:
                continue
            if other_calls:  # final reply was written before seeing these results -> ignore it
                messages.append({"role": "tool", "tool_call_id": final_call.id, "name": FINAL_TOOL_NAME,
                                 "content": json.dumps({"error": "You must see the tool results before replying. Call respond_to_customer again now."})})
                continue

            # ---- final structured reply ----------------------------------------------------------
            args, errors = validate_args(FINAL_TOOL["parameters"], final_call.arguments) if not final_call.arguments_error else ({}, [final_call.arguments_error])
            if errors or not args.get("reply", "").strip():
                messages.append({"role": "tool", "tool_call_id": final_call.id, "name": FINAL_TOOL_NAME,
                                 "content": json.dumps({"error": "; ".join(errors) or "reply must not be empty"})})
                continue
            report = check_reply(args["reply"], ctx.evidence, customer_texts, ctx.state, args.get("evidence_product_ids"), bool(args.get("states_order_confirmed")))
            if args["action"] == "escalate" and not ctx.evidence.escalation_recorded:
                report.violations.append("You set action=escalate but escalate_to_owner did not record a handoff. If it failed, give the owner's contact details and use action=answer.")
            if trace.grounding["first_pass_ok"] is None:
                trace.grounding["first_pass_ok"] = report.ok
            if report.ok:
                messages.append({"role": "tool", "tool_call_id": final_call.id, "name": FINAL_TOOL_NAME, "content": '{"accepted": true}'})
                trace.structured_final = True
                return self._finish(ctx, trace, args["reply"].strip(), args["action"], args, retried)
            trace.grounding["violations"] += report.violations
            if retried:
                return fallback("grounding_failed")
            retried = trace.grounding["retried"] = True
            messages.append({"role": "tool", "tool_call_id": final_call.id, "name": FINAL_TOOL_NAME,
                             "content": json.dumps({"accepted": False, "violations": report.violations, "instruction": "Rewrite using only tool evidence (retrieve what you need first), then call respond_to_customer again."})})

        return fallback("max_model_calls")

    @staticmethod
    def _finish(ctx: ToolContext, trace: AgentTrace, reply: str, action: str, args: dict[str, Any], retried: bool) -> AgentResult:
        trace.action = action
        trace.customer_intent = args.get("customer_intent") or None
        trace.missing_information = list(args.get("missing_information") or [])
        trace.evidence_product_ids = [p for p in (args.get("evidence_product_ids") or []) if p in ctx.evidence.products]
        first_ok = bool(trace.grounding["first_pass_ok"]) and not retried
        trace.confidence = compute_confidence(action, args.get("confidence"), ctx, first_ok, trace.missing_information)
        trace.security_events = list(ctx.security_events)
        return AgentResult("answered", reply, trace, ctx)
