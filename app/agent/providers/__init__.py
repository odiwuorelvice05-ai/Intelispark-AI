from __future__ import annotations

from app.agent.providers.base import AIProvider, ProviderError, ProviderUnavailable


def get_provider(name: str, *, api_key: str = "", model: str = "", reasoning_effort: str | None = None) -> AIProvider:
    """Provider factory. The agent loop and its contracts stay vendor-neutral."""
    if name == "gemini":
        from app.agent.providers.gemini import GeminiProvider
        return GeminiProvider(api_key=api_key, model=model or "gemini-2.5-flash")
    raise ProviderUnavailable(f"unknown AI provider: {name!r}")


__all__ = ["AIProvider", "ProviderError", "ProviderUnavailable", "get_provider"]
