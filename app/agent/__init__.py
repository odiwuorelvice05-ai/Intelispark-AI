"""Intelispark agent foundation.

A foundation model (behind ``AIProvider``) reasons and orchestrates; backend tools
(tenant-scoped, validated) fetch authoritative facts from Supabase; a grounding
check refuses answers that contradict tool evidence. See docs/AGENT_ARCHITECTURE.md.
"""
