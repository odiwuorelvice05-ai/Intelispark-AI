"""The controlled agent loop.

    model -> (data tools -> validated, tenant-scoped execution -> results) x N -> reply_to_customer
          -> grounding check -> (one retry with the reasons) -> answer | failure

One code path, bounded on model calls, tool calls, tokens and wall-clock time. The model must
call a tool on every step (`tool_choice=required`); the last allowed step exposes only the final
tool so a turn always ends in a decision. Any failure returns status="failed" with a reason;
the loop never returns an ungrounded reply.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.assistant.grounding import check_reply
from app.assistant.provider import LLMProvider, ProviderError
from app.assistant.schema import validate
from app.assistant.state import STATE_SCHEMA
from app.assistant.tools import ToolContext, ToolRegistry
from app.assistant.types import ToolCall

FINAL_TOOL_NAME = "reply_to_customer"
INTENTS = ["greeting", "product_search", "product_details", "price", "availability", "comparison", "recommendation",
           "delivery", "payment", "warranty", "shop_info", "purchase", "reservation", "negotiation", "complaint", "thanks", "other"]
FINAL_TOOL: dict[str, Any] = {
    "name": FINAL_TOOL_NAME,
    "description": "Send your final message to the customer and end the turn. Call it once, alone, after you have every tool result you need.",
    "parameters": {"type": "object", "required": ["reply", "action"], "properties": {
        "reply": {"type": "string", "maxLength": 1200, "description": "The message to send to the customer."},
        "action": {"type": "string", "enum": ["answer", "clarify", "escalate"]},
        "intent": {"type": "string", "enum": INTENTS},
        "product_claims": {"type": "array", "maxItems": 10, "description": "One entry per product whose availability or price your reply states.",
                           "items": {"type": "object", "required": ["product_id"], "properties": {
                               "product_id": {"type": "string"},
                               "availability": {"type": "string", "enum": ["in_stock", "out_of_stock"]},
                               "price_kes": {"type": "number", "minimum": 0}}}},
        "state_update": STATE_SCHEMA,
        "states_order_confirmed": {"type": "boolean", "description": "True only if your reply says an order or reservation was placed. Must normally be false."},
    }},
}


@dataclass
class AgentTrace:
    steps: list[dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    grounding_retried: bool = False
    violations: list[str] = field(default_factory=list)
    security_events: list[str] = field(default_factory=list)
    failure: str | None = None

    @property
    def tools_called(self) -> list[str]:
        return [s["tool"] for s in self.steps]

    def to_dict(self) -> dict[str, Any]:
        return {"tools_called": self.tools_called, "model_calls": self.model_calls,
                "tokens": {"prompt": self.prompt_tokens, "completion": self.completion_tokens}, "latency_ms": self.latency_ms,
                "grounding_retried": self.grounding_retried, "violations": self.violations, "security_events": self.security_events,
                "failure": self.failure}


@dataclass
class AgentResult:
    status: str                      # "answered" | "failed"
    reply: str | None
    trace: AgentTrace
    action: str | None = None
    intent: str | None = None
    state_update: dict[str, Any] = field(default_factory=dict)


class Agent:
    def __init__(self, provider: LLMProvider, registry: ToolRegistry, *, deadline_s: float, max_model_calls: int = 5,
                 max_tool_calls: int = 8, max_total_tokens: int = 20_000,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.provider, self.registry = provider, registry
        self.deadline_s, self.max_model_calls, self.max_tool_calls, self.max_total_tokens = deadline_s, max_model_calls, max_tool_calls, max_total_tokens
        self.clock, self.sleep = clock, sleep

    def run(self, ctx: ToolContext, *, system_prompt: str, history: list[dict[str, Any]], customer_message: str, state: dict[str, Any]) -> AgentResult:
        trace, started = AgentTrace(), self.clock()
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": customer_message}]
        tools = self.registry.specs() + [FINAL_TOOL]
        seen: dict[str, str] = {}
        tool_calls_used, provider_retried, nudged = 0, False, False

        def fail(reason: str) -> AgentResult:
            trace.failure = reason
            trace.security_events = list(ctx.security_events)
            trace.latency_ms = int((self.clock() - started) * 1000)
            return AgentResult("failed", None, trace)

        while trace.model_calls < self.max_model_calls:
            remaining = self.deadline_s - (self.clock() - started)
            if remaining <= 1.0:
                return fail("deadline")
            last_step = trace.model_calls == self.max_model_calls - 1 or tool_calls_used >= self.max_tool_calls or remaining < 3.0
            try:
                turn = self.provider.chat(messages, [FINAL_TOOL] if last_step else tools, tool_choice="required", max_tokens=700,
                                          temperature=0.2, timeout_s=min(6.0, remaining))
            except ProviderError as exc:
                if exc.retryable and not provider_retried and self.deadline_s - (self.clock() - started) > 3.0:
                    provider_retried = True
                    self.sleep(0.3)
                    continue
                return fail(f"provider_error: {exc}")
            trace.model_calls += 1
            trace.prompt_tokens += turn.usage.get("prompt_tokens", 0)
            trace.completion_tokens += turn.usage.get("completion_tokens", 0)
            if trace.prompt_tokens + trace.completion_tokens > self.max_total_tokens:
                return fail("token_budget")

            if not turn.tool_calls:  # the model ignored tool_choice=required and wrote free text
                if nudged:
                    return fail("protocol_error: no tool call")
                nudged = True
                messages += [{"role": "assistant", "content": turn.content or ""},
                             {"role": "user", "content": "[system] Reply only by calling a tool. To answer the customer, call reply_to_customer (retrieve facts with the data tools first)."}]
                continue

            final = next((c for c in turn.tool_calls if c.name == FINAL_TOOL_NAME), None)
            data_calls = [c for c in turn.tool_calls if c.name != FINAL_TOOL_NAME]
            messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in turn.tool_calls]})

            for call in data_calls:
                key = call.name + json.dumps(call.arguments, sort_keys=True, default=str)
                if key not in seen:
                    if tool_calls_used >= self.max_tool_calls:
                        seen[key] = json.dumps({"error": "tool budget used up; answer with what you have or escalate"})
                    else:
                        tool_calls_used += 1
                        result = self.registry.execute(ctx, call)  # DataUnavailable propagates to the caller on purpose
                        seen[key] = result.content()
                        step: dict[str, Any] = {"tool": call.name, "ok": result.ok}
                        if call.name == "search_products":
                            step["arguments"] = {k: v for k, v in call.arguments.items() if k not in ("exclude_product_ids",)}
                            step["total_matches"] = result.payload.get("total_matches")
                        trace.steps.append(step)
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": seen[key]})

            if final is None:
                continue
            if data_calls:  # a final answer written before seeing the results is ignored
                messages.append({"role": "tool", "tool_call_id": final.id, "name": FINAL_TOOL_NAME,
                                 "content": json.dumps({"error": "You must see the tool results before replying. Call reply_to_customer again now."})})
                continue

            args, errors = ({}, [final.arguments_error]) if final.arguments_error else validate(FINAL_TOOL["parameters"], final.arguments)
            if errors or not args.get("reply", "").strip():
                messages.append({"role": "tool", "tool_call_id": final.id, "name": FINAL_TOOL_NAME,
                                 "content": json.dumps({"error": "; ".join(e for e in errors if e) or "reply must not be empty"})})
                continue

            violations = check_reply(args["reply"], ctx.evidence, {**state, **(args.get("state_update") or {})}, args.get("product_claims"), bool(args.get("states_order_confirmed")))
            if args["action"] == "escalate" and not ctx.evidence.escalation_recorded:
                violations.append("You set action=escalate but escalate_to_owner did not record a handoff. Give the owner's contact details and use action=answer.")
            if not violations:
                messages.append({"role": "tool", "tool_call_id": final.id, "name": FINAL_TOOL_NAME, "content": '{"accepted": true}'})
                trace.security_events = list(ctx.security_events)
                trace.latency_ms = int((self.clock() - started) * 1000)
                return AgentResult("answered", args["reply"].strip(), trace, args["action"], args.get("intent"), args.get("state_update") or {})
            trace.violations += violations
            if trace.grounding_retried:
                return fail("grounding_failed")
            trace.grounding_retried = True
            messages.append({"role": "tool", "tool_call_id": final.id, "name": FINAL_TOOL_NAME,
                             "content": json.dumps({"accepted": False, "violations": violations,
                                                    "instruction": "Rewrite using only tool evidence (retrieve what you need first), then call reply_to_customer again."})})
        return fail("max_model_calls")
