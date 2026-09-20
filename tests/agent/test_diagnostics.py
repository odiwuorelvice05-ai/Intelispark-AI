"""Diagnostics: silent provider failures must be visible in logs without leaking secrets or conversations."""
from types import SimpleNamespace as NS

import mistralai.client as mistral_sdk

import app.agent.service as service
from app.agent.providers.mistral import MistralProvider
from app.mistral_assist import MistralAssist

KEY = "unit-test-secret-1234567890"
JWT = "unit-test-jwt-header.payload.signature"


class HttpError(Exception):
    """Shaped like the SDK's MistralError (status_code + body)."""

    def __init__(self, message, status_code, body):
        super().__init__(message)
        self.status_code, self.body = status_code, body


def test_assist_failure_is_logged_safely_and_still_falls_back(monkeypatch, capsys):
    monkeypatch.setenv("MISTRAL_API_KEY", KEY)
    assist = MistralAssist()
    assert assist.enabled

    def boom(**_):
        raise HttpError(f"API error Status 422 Bearer {KEY}", 422,
                        f'{{"detail":[{{"loc":["body","reasoning_effort"],"msg":"invalid","token":"{JWT}"}}]}}')

    assist.client = NS(chat=NS(complete=boom))
    result = assist.understand("PRIVATE-CUSTOMER-MESSAGE", "customer: PRIVATE-HISTORY", {"name": "Shop"}, [])

    assert result is None
    out = capsys.readouterr().out
    assert "[Intelispark assist]" in out and "HttpError" in out and "status=422" in out
    assert "reasoning_effort_in_error=True" in out
    for secret in (KEY, "SECRET", JWT, "PRIVATE-CUSTOMER-MESSAGE", "PRIVATE-HISTORY"):
        assert secret not in out


def test_key_is_redacted_before_truncation(monkeypatch, capsys):
    monkeypatch.setenv("MISTRAL_API_KEY", KEY)
    assist = MistralAssist()

    def boom(**_):
        raise HttpError("x" * 190 + KEY, 500, "")

    assist.client = NS(chat=NS(complete=boom))
    assert assist.understand("m", "", {}, []) is None
    out = capsys.readouterr().out
    assert "SECRET" not in out and "unit-test-secret" not in out


def test_provider_init_failure_is_reported_by_class_name_only(monkeypatch, capsys):
    def boom(**_):
        raise RuntimeError(f"{KEY} rejected")

    monkeypatch.setattr(mistral_sdk, "Mistral", boom)
    provider = MistralProvider(api_key=KEY)
    assert provider.enabled is False
    out = capsys.readouterr().out
    assert "init failed: RuntimeError" in out and "unit-test-secret" not in out


def test_provider_state_is_logged_once_with_reasoning_effort_and_no_secrets(monkeypatch, capsys):
    monkeypatch.setattr(service, "_provider", None)
    for name, value in (("ai_provider", "mistral"), ("mistral_api_key", KEY),
                        ("agent_model", "mistral-small-latest"), ("agent_reasoning_effort", "none")):
        monkeypatch.setattr(service.settings, name, value)
    assert service._get_provider() is not None
    assert service._get_provider() is not None
    out = capsys.readouterr().out
    assert out.count("[Intelispark agent] provider=") == 1
    assert "model=mistral-small-latest" in out and "enabled=True" in out and "reasoning_effort=none" in out
    assert "unit-test-secret" not in out


def test_unconfigured_provider_is_reported_instead_of_silent(monkeypatch, capsys):
    monkeypatch.setattr(service, "_provider", None)
    monkeypatch.setattr(service.settings, "ai_provider", "mistral")
    monkeypatch.setattr(service.settings, "mistral_api_key", "")
    monkeypatch.setattr(service.settings, "agent_reasoning_effort", "")
    assert service._get_provider() is None
    out = capsys.readouterr().out
    assert "enabled=False" in out and "reasoning_effort=unset" in out and "legacy engine will answer" in out


def _reply():
    return NS(choices=[NS(message=NS(content="hi", tool_calls=None), finish_reason="stop")],
              usage=NS(prompt_tokens=1, completion_tokens=1))


def test_reasoning_effort_is_only_sent_when_configured():
    """The forwarding patch is a strict no-op unless AGENT_REASONING_EFFORT is set."""
    seen = {}
    client = NS(chat=NS(complete=lambda **kw: seen.update(kw) or _reply()))
    MistralProvider(client=client).chat([{"role": "user", "content": "x"}])
    assert "reasoning_effort" not in seen
    seen.clear()
    MistralProvider(client=client, reasoning_effort="none").chat([{"role": "user", "content": "x"}])
    assert seen["reasoning_effort"] == "none"
