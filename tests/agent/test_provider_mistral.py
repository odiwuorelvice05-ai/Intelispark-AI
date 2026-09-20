import json
from types import SimpleNamespace as NS

import pytest

from app.agent.providers import get_provider
from app.agent.providers.base import ProviderError, ProviderUnavailable
from app.agent.providers.mistral import MistralProvider


class FakeClient:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.kwargs = response, exc, None
        self.chat = NS(complete=self._complete)

    def _complete(self, **kw):
        self.kwargs = kw
        if self.exc:
            raise self.exc
        return self.response


def resp(content="", tool_calls=None, finish="stop"):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls), finish_reason=finish)], usage=NS(prompt_tokens=11, completion_tokens=7))


TOOLS = [{"name": "search_products", "description": "d", "parameters": {"type": "object", "properties": {}}}]


def test_translates_messages_tools_and_parses_tool_calls():
    tc = NS(id="abc123xyz", function=NS(name="search_products", arguments='{"brand": "Samsung", "max_price_kes": 50000}'))
    client = FakeClient(resp(tool_calls=[tc], finish="tool_calls"))
    p = MistralProvider(model="m-test", client=client)
    turn = p.chat([
        {"role": "system", "content": "sys"}, {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "abc123xyz", "name": "search_products", "arguments": {"brand": "Samsung"}}]},
        {"role": "tool", "tool_call_id": "abc123xyz", "name": "search_products", "content": "{}"},
    ], TOOLS, timeout_s=9)
    kw = client.kwargs
    assert kw["model"] == "m-test" and kw["timeout_ms"] == 9000 and kw["tool_choice"] == "auto"
    assert kw["tools"] == [{"type": "function", "function": TOOLS[0]}]
    assert kw["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"brand": "Samsung"}'
    assert kw["messages"][3] == {"role": "tool", "tool_call_id": "abc123xyz", "name": "search_products", "content": "{}"}
    assert turn.tool_calls[0].arguments == {"brand": "Samsung", "max_price_kes": 50000} and turn.usage == {"prompt_tokens": 11, "completion_tokens": 7}


def test_bad_json_arguments_are_flagged_not_crashed_and_dict_args_accepted():
    bad = NS(id="1", function=NS(name="x", arguments="{not json"))
    good = NS(id="2", function=NS(name="y", arguments={"a": 1}))
    turn = MistralProvider(client=FakeClient(resp(tool_calls=[bad, good]))).chat([{"role": "user", "content": "x"}], TOOLS)
    assert turn.tool_calls[0].arguments_error and turn.tool_calls[1].arguments == {"a": 1}


def test_chunked_content_keeps_only_visible_text():
    chunks = [NS(type="thinking", thinking="secret reasoning"), NS(type="text", text="Habari! ")]
    turn = MistralProvider(client=FakeClient(resp(content=chunks))).chat([{"role": "user", "content": "x"}])
    assert turn.content == "Habari! "


def test_json_mode_and_derived_helpers():
    client = FakeClient(resp(content='{"intent": "greeting"}'))
    p = MistralProvider(client=client, reasoning_effort="low")
    assert p.generate_structured([{"role": "user", "content": "x"}]) == {"intent": "greeting"}
    assert client.kwargs["response_format"] == {"type": "json_object"} and client.kwargs["reasoning_effort"] == "low"
    assert p.respond([{"role": "user", "content": "x"}]) == '{"intent": "greeting"}'


def test_invalid_structured_output_raises_provider_error():
    with pytest.raises(ProviderError):
        MistralProvider(client=FakeClient(resp(content="nope"))).generate_structured([{"role": "user", "content": "x"}])


def test_sdk_failures_become_provider_errors_and_missing_key_is_unavailable():
    with pytest.raises(ProviderError):
        MistralProvider(client=FakeClient(exc=RuntimeError("429 rate limited"))).chat([{"role": "user", "content": "x"}])
    p = MistralProvider(api_key="")
    assert not p.enabled
    with pytest.raises(ProviderUnavailable):
        p.chat([{"role": "user", "content": "x"}])


def test_factory():
    assert get_provider("mistral", api_key="", model="m").model == "m"
    with pytest.raises(ProviderUnavailable):
        get_provider("nope")
