"""Structured, non-sensitive record of what the agent did (no chain-of-thought)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTrace:
    steps: list[dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    customer_intent: str | None = None
    action: str | None = None
    missing_information: list[str] = field(default_factory=list)
    evidence_product_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    structured_final: bool = False
    grounding: dict[str, Any] = field(default_factory=lambda: {"first_pass_ok": None, "violations": [], "retried": False})
    security_events: list[str] = field(default_factory=list)
    fallback_reason: str | None = None

    @property
    def tools_called(self) -> list[str]:
        return [s["tool"] for s in self.steps if s.get("type") == "tool"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools_called": self.tools_called, "steps": self.steps, "model_calls": self.model_calls,
            "tokens": {"prompt": self.prompt_tokens, "completion": self.completion_tokens},
            "customer_intent": self.customer_intent, "action": self.action,
            "missing_information": self.missing_information, "evidence_product_ids": self.evidence_product_ids,
            "confidence": self.confidence, "structured_final": self.structured_final,
            "grounding": self.grounding, "security_events": self.security_events, "fallback_reason": self.fallback_reason,
        }
