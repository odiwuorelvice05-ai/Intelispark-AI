import pytest

from app.agent.providers import get_provider
from app.agent.providers.base import ProviderError, ProviderUnavailable
from app.agent.providers.gemini import GeminiProvider


TOOLS = [{"name": "search_products", "description": "Find catalog products",
          "parameters": {"type": "object", "required": ["brand"],
                         "properties": {"brand": {"type": "string"}},
                         "additionalProperties": False}}]


def response(parts=None, usage=None):
    return {"candidates": [{"content": {"role": "model", "parts": parts or []},
                            "finishReason": "STOP"}],
            "usageMetadata": usage or {"promptTokenCount": 11, "candidatesTokenCount": 7}}


class FakeClient:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.payload, self.timeout = result or response(), exc, None, None

    def __call__(self, *, payload, timeout_s):
        self.payload, self.timeout = payload, timeout_s
        if self.exc:
            raise self.exc
        return self.result


def test_translates_system_history_tools_and_function_responses():
    client = FakeClient(response([{"functionCall": {"name": "search_products",
                                                    "args": {"brand": "Samsung", "max_price_kes": 50000}}}],
                                {"promptTokenCount": 11, "candidatesTokenCount": 7}))
    provider = GeminiProvider(model="gemini-test", client=client)
    turn = provider.chat([
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "abc", "name": "search_products", "arguments": {"brand": "Samsung"}}]},
        {"role": "tool", "tool_call_id": "abc", "name": "search_products", "content": '{"items": []}'},
    ], TOOLS, timeout_s=9)
    payload = client.payload
    assert payload["systemInstruction"]["parts"][0]["text"] == "system instructions"
    assert payload["contents"][0] == {"role": "user", "parts": [{"text": "hi"}]}
    assert payload["contents"][1]["parts"][0]["functionCall"]["name"] == "search_products"
    assert payload["contents"][2]["parts"][0]["functionResponse"]["response"] == {"items": []}
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "search_products"
    assert "additionalProperties" not in payload["tools"][0]["functionDeclarations"][0]["parameters"]
    assert client.timeout == 9
    assert turn.tool_calls[0].arguments == {"brand": "Samsung", "max_price_kes": 50000}
    assert turn.usage == {"prompt_tokens": 11, "completion_tokens": 7}


def test_text_json_mode_and_function_choice():
    client = FakeClient(response([{"text": '{"intent":"greeting"}'}]))
    provider = GeminiProvider(client=client)
    assert provider.generate_structured([{"role": "user", "content": "hello"}]) == {"intent": "greeting"}
    assert client.payload["generationConfig"]["responseMimeType"] == "application/json"
    provider.chat([{"role": "user", "content": "find a phone"}], TOOLS, tool_choice="any")
    assert client.payload["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"


def test_invalid_structured_output_raises_provider_error():
    with pytest.raises(ProviderError):
        GeminiProvider(client=FakeClient(response([{"text": "not json"}]))).generate_structured(
            [{"role": "user", "content": "x"}])


def test_failures_and_missing_key_are_safe():
    with pytest.raises(ProviderError, match="Gemini request failed"):
        GeminiProvider(api_key="secret", client=FakeClient(exc=RuntimeError("secret leaked"))).chat(
            [{"role": "user", "content": "x"}])
    provider = GeminiProvider(api_key="")
    assert not provider.enabled
    with pytest.raises(ProviderUnavailable):
        provider.chat([{"role": "user", "content": "x"}])


def test_factory_defaults_to_gemini_and_rejects_unknown_provider():
    assert get_provider("gemini", api_key="", model="gemini-test").model == "gemini-test"
    assert get_provider("gemini", api_key="", model="").model == "gemini-2.5-flash"
    with pytest.raises(ProviderUnavailable):
        get_provider("unknown")
