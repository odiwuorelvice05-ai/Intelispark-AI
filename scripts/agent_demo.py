"""Run the design-brief conversation against a REAL model and print every decision.

    MISTRAL_API_KEY=... python -m scripts.agent_demo

Uses the fictional fixture shop (tests/agent/fixtures.py), not your Supabase data.
Read the transcript: the tool calls the model chose, the arguments it produced from
never-before-seen wording, the evidence returned, and the final grounded answers.
"""
from __future__ import annotations

import sys

from tests.agent.harness import describe_turn, run_conversation

TURNS = [
    "Bro natafuta Samsung poa ya around 50k, camera iwe noma. Uko na anything?",
    "That second one iko na how much RAM?",
    "Na ukipea two, price?",
    "Can you deliver to Kisumu?",
    "Okay take it.",
]


def main() -> int:
    from app.agent.providers import get_provider
    from app.config import settings
    provider = get_provider(settings.ai_provider, api_key=settings.mistral_api_key, model=settings.agent_model)
    if not provider.enabled:
        print("No model configured. Set MISTRAL_API_KEY and run again.")
        return 2
    print(f"model: {provider.name}:{provider.model}\n")
    for rec in run_conversation(provider, TURNS):
        print(describe_turn(rec) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
