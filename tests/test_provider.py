import json

import httpx
import pytest

from app.assistant.provider import OpenAICompatibleProvider, ProviderError

KEY = "sk-super-secret-key"
TOOLS = [{"name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}}]


def provider(handler, key=KEY):
    return OpenAICompatibleProvider(api_key=key, base_url="https://llm.example/v1/", model="m-1", client=httpx.Client(transport=httpx.MockTransport(handler)))


def ok(message, usage=None):
    return httpx.Response(200, json={"choices": [{"message": message}], "usage": usage or {"prompt_tokens": 11, "completion_tokens": 3}})


def test_request_shape_and_tool_call_parsing():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return ok({"content": None, "tool_calls": [{"id": "a1", "type": "function", "function": {"name": "t", "arguments": '{"x": 1}'}}]})

    turn = provider(handler).chat([{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}], TOOLS, tool_choice="required")
    assert seen["url"] == "https://llm.example/v1/chat/completions" and seen["auth"] == f"Bearer {KEY}"
    assert seen["body"]["tool_choice"] == "required" and seen["body"]["tools"][0]["function"]["name"] == "t" and seen["body"]["model"] == "m-1"
    assert turn.tool_calls[0].name == "t" and turn.tool_calls[0].arguments == {"x": 1} and turn.usage == {"prompt_tokens": 11, "completion_tokens": 3}


def test_assistant_tool_calls_and_tool_results_are_translated_to_the_wire_format():
    seen = {}
    provider(lambda req: (seen.update(body=json.loads(req.content)), ok({"content": "hi"}))[1]).chat([
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a1", "name": "t", "arguments": {"q": "é"}}]},
        {"role": "tool", "tool_call_id": "a1", "name": "t", "content": "{}"}])
    msgs = seen["body"]["messages"]
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"q": "é"}' and msgs[1]["tool_call_id"] == "a1"


def test_malformed_tool_arguments_are_flagged_not_raised():
    turn = provider(lambda r: ok({"tool_calls": [{"id": "1", "function": {"name": "t", "arguments": "{not json"}},
                                                   {"id": "2", "function": {"name": "t", "arguments": "[1]"}}]})).chat([{"role": "user", "content": "x"}], TOOLS)
    assert [c.arguments_error for c in turn.tool_calls] == ["arguments were not valid JSON", "arguments were not a JSON object"]


def test_chunked_content_is_flattened():
    turn = provider(lambda r: ok({"content": [{"type": "text", "text": "Hel"}, {"type": "thinking", "thinking": "x"}, {"type": "text", "text": "lo"}]})).chat([{"role": "user", "content": "x"}])
    assert turn.content == "Hello"


@pytest.mark.parametrize("status,retryable", [(429, True), (500, True), (503, True), (401, False), (400, False)])
def test_http_errors_are_classified_and_never_leak_the_key(status, retryable):
    with pytest.raises(ProviderError) as e:
        provider(lambda r: httpx.Response(status, text=f"bad key {KEY}")).chat([{"role": "user", "content": "x"}])
    assert e.value.retryable is retryable and KEY not in str(e.value)


def test_timeouts_and_network_errors_are_retryable_provider_errors():
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)
    with pytest.raises(ProviderError) as e:
        provider(boom).chat([{"role": "user", "content": "x"}])
    assert e.value.retryable and KEY not in str(e.value)


@pytest.mark.parametrize("body", [{"nope": 1}, {"choices": []}, {"choices": [{"message": None}]}])
def test_malformed_provider_responses_raise_provider_error(body):
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(200, json=body)).chat([{"role": "user", "content": "x"}])


def test_unconfigured_provider_is_disabled_and_refuses_to_call():
    p = provider(lambda r: ok({"content": "x"}), key="")
    assert not p.enabled
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "x"}])
