"""Intelispark's intelligence layer.

A foundation model (behind ``LLMProvider``) understands the customer and decides what it needs;
tenant-bound tools fetch authoritative facts from Supabase; a grounding check refuses replies that
contradict those facts; the application, not the model, owns conversation state.
See docs/INTELLIGENCE.md.
"""
from app.assistant.service import TurnResult, respond, status

__all__ = ["TurnResult", "respond", "status"]
