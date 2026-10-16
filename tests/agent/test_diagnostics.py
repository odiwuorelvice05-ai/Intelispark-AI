"""Provider diagnostics: configuration failures stay visible without leaking secrets."""
import app.agent.service as service


KEY = "unit-test-secret-1234567890"


def test_provider_state_is_logged_once_without_secrets(monkeypatch, capsys):
    monkeypatch.setattr(service, "_provider", None)
    monkeypatch.setattr(service.settings, "ai_provider", "gemini")
    monkeypatch.setattr(service.settings, "gemini_api_key", KEY)
    monkeypatch.setattr(service.settings, "agent_model", "gemini-test")
    assert service._get_provider() is not None
    assert service._get_provider() is not None
    out = capsys.readouterr().out
    assert out.count("[Intelispark agent] provider=") == 1
    assert "provider=gemini" in out and "model=gemini-test" in out and "enabled=True" in out
    assert KEY not in out


def test_unconfigured_provider_is_reported_without_crashing(monkeypatch, capsys):
    monkeypatch.setattr(service, "_provider", None)
    monkeypatch.setattr(service.settings, "ai_provider", "gemini")
    monkeypatch.setattr(service.settings, "gemini_api_key", "")
    assert service._get_provider() is None
    out = capsys.readouterr().out
    assert "enabled=False" in out and "not configured" in out
