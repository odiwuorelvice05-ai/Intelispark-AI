from __future__ import annotations

from app.agent.providers.base import AIProvider, ProviderError, ProviderUnavailable


def get_provider(name: str, *, api_key: str = "", model: str = "", reasoning_effort: str | None = None) -> AIProvider:
    """Factory. Add a vendor by adding a branch here and one AIProvider subclass."""
    if name == "mistral":
        from app.agent.providers.mistral import MistralProvider
        return MistralProvider(api_key=api_key, model=model or "mistral-small-latest", reasoning_effort=reasoning_effort)
    raise ProviderUnavailable(f"unknown AI provider: {name!r}")


__all__ = ["AIProvider", "ProviderError", "ProviderUnavailable", "get_provider"]
