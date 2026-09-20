"""The agent loop: bounded, tenant-scoped, grounded, and failing cleanly."""
import json

import pytest

from app.assistant.agent import Agent, FINAL_TOOL_NAME
from app.assistant.provider import ProviderError
from app.assistant.repository import DataUnavailable, SupabaseShopRepository
from app.assistant.tools import ToolContext, ToolRegistry
from tests.fakes import FakeSupabase, ScriptedProvider, call, say, text, tc, turn, tool_results
from tests.fixtures import SHOP_A, pid, seed


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def build(script, *, clock=None, deadline=7.0, **kw):
    db = FakeSupabase()
    seed(db)
    ctx = ToolContext(repo=SupabaseShopRepository(db, SHOP_A), conversation_id="cccccccc-cccc-cccc-cccc-cccccccccccc")
    prov = ScriptedProvider(script)
    agent = Agent(prov, ToolRegistry(), deadline_s=deadline, clock=clock or Clock(), sleep=lambda s: None, **kw)
    return agent, ctx, prov


def run(agent, ctx, msg="hi", history=()):
    return agent.run(ctx, system_prompt="SYS", history=list(history), customer_message=msg, state={})


def test_search_then_grounded_answer():
    agent, ctx, prov = build([call("search_products", query="galaxy a05"),
                              say("Galaxy A05 ni KES 12,500, tunayo 6.", intent="price", product_claims=[{"product_id": pid(11), "availability": "in_stock", "price_kes": 12500}])])
    r = run(agent, ctx, "bei ya a05?")
    assert r.status == "answered" and "12,500" in r.reply and r.intent == "price"
    assert r.trace.tools_called == ["search_products"] and r.trace.model_calls == 2
    assert tool_results(prov.seen[1])[0]["products"][0]["name"] == "Galaxy A05"


def test_every_step_requires_a_tool_call_and_the_last_step_offers_only_the_final_tool():
    agent, ctx, prov = build([call("get_shop_info"), call("get_shop_info", ), say("ok")], max_model_calls=3)
    run(agent, ctx)
    assert prov.tool_names[0] == ["search_products", "get_products", "get_shop_info", "escalate_to_owner", FINAL_TOOL_NAME]
    assert prov.tool_names[-1] == [FINAL_TOOL_NAME]


def test_final_answer_written_before_seeing_tool_results_is_ignored():
    agent, ctx, prov = build([turn(tc("search_products", query="a05"), tc(FINAL_TOOL_NAME, reply="A05 is KES 9,999", action="answer")),
                              say("Galaxy A05 is KES 12,500.")])
    r = run(agent, ctx)
    assert r.status == "answered" and "12,500" in r.reply
    assert "must see the tool results" in json.dumps(tool_results(prov.seen[1]))


def test_duplicate_tool_calls_run_once():
    agent, ctx, _ = build([call("search_products", query="a05"), call("search_products", query="a05"), say("Galaxy A05 is KES 12,500.")])
    assert len(run(agent, ctx).trace.steps) == 1


def test_invalid_tool_arguments_get_a_corrective_result_and_the_turn_continues():
    agent, ctx, prov = build([call("search_products", sort="bogus"), call("search_products", query="a05"), say("Galaxy A05 is KES 12,500.")])
    assert run(agent, ctx).status == "answered"
    assert "sort" in tool_results(prov.seen[1])[0]["error"]


def test_malformed_final_arguments_are_retried():
    bad = turn(type(tc("x"))(id="f1", name=FINAL_TOOL_NAME, arguments={}, arguments_error="arguments were not valid JSON"))
    agent, ctx, _ = build([bad, say("Hello! How can I help?", intent="greeting")])
    assert run(agent, ctx).status == "answered"


def test_ungrounded_price_is_fed_back_once_then_the_corrected_reply_is_accepted():
    agent, ctx, prov = build([call("search_products", query="a05"), say("A05 is KES 9,999"), say("Galaxy A05 is KES 12,500.")])
    r = run(agent, ctx)
    assert r.status == "answered" and r.trace.grounding_retried and "9,999" in r.trace.violations[0]
    assert tool_results(prov.seen[2])[-1]["accepted"] is False


def test_two_ungrounded_replies_fail_the_turn_rather_than_ship_a_wrong_price():
    agent, ctx, _ = build([call("search_products", query="a05"), say("A05 is KES 9,999"), say("A05 is KES 11,111")])
    r = run(agent, ctx)
    assert r.status == "failed" and r.reply is None and r.trace.failure == "grounding_failed"


def test_claiming_an_order_is_blocked_and_the_honest_handoff_is_accepted():
    agent, ctx, _ = build([call("search_products", query="a05"), call("escalate_to_owner", reason="order_help", summary="wants 2 A05"),
                           say("Great, your order has been placed!", action="escalate"),
                           say("I've passed your request to the shop; they will confirm availability and payment.", action="escalate", intent="purchase")])
    r = run(agent, ctx)
    assert r.status == "answered" and "placed" not in r.reply and ctx.evidence.escalation_recorded


def test_escalate_action_without_a_recorded_handoff_is_rejected():
    agent, ctx, _ = build([say("I'll ask the owner.", action="escalate"), say("Please call the shop on +254700111222.", action="answer")])
    r = run(agent, ctx)
    assert r.status == "answered" and r.action == "answer" and r.trace.grounding_retried


def test_free_text_is_nudged_once_then_fails_as_a_protocol_error():
    agent, ctx, _ = build([text("Yes we have it for 5,000"), say("Hello!")])
    assert run(agent, ctx).status == "answered"
    agent, ctx, _ = build([text("a"), text("b")])
    assert run(agent, ctx).trace.failure.startswith("protocol_error")


def test_transient_provider_error_is_retried_once():
    agent, ctx, prov = build([ProviderError("HTTP 429", retryable=True), say("Hello!")])
    r = run(agent, ctx)
    assert r.status == "answered" and r.trace.model_calls == 1 and len(prov.seen) == 2


def test_persistent_or_permanent_provider_errors_fail_cleanly():
    agent, ctx, _ = build([ProviderError("HTTP 500", retryable=True), ProviderError("HTTP 500", retryable=True)])
    assert run(agent, ctx).trace.failure.startswith("provider_error")
    agent, ctx, prov = build([ProviderError("HTTP 401", retryable=False), say("never reached")])
    assert run(agent, ctx).status == "failed" and len(prov.seen) == 1


def test_wall_clock_deadline_stops_the_loop():
    clock = Clock()
    def slow(messages):
        clock.t += 6.5
        return call("get_shop_info")
    agent, ctx, prov = build([slow, say("too late")], clock=clock, deadline=7.0)
    r = run(agent, ctx)
    assert r.trace.failure == "deadline" and len(prov.seen) == 1


def test_token_budget_stops_the_loop():
    agent, ctx, _ = build([call("get_shop_info"), say("Hi")], max_total_tokens=100)
    assert run(agent, ctx).trace.failure == "token_budget"


def test_model_call_budget_ends_in_failure_not_an_endless_loop():
    agent, ctx, _ = build([turn(tc("get_shop_info", n=i)) for i in range(10)], max_model_calls=3)
    assert run(agent, ctx).trace.failure == "max_model_calls"


def test_database_outage_mid_turn_propagates_to_the_caller():
    agent, ctx, _ = build([call("search_products", query="a05")])
    ctx.repo._db.fail_tables.add("products")
    with pytest.raises(DataUnavailable):
        run(agent, ctx)


def test_history_and_current_message_reach_the_model_in_order():
    agent, ctx, prov = build([say("Hi!")])
    run(agent, ctx, "and the cheaper one?", history=[{"role": "user", "content": "A55?"}, {"role": "assistant", "content": "KES 48,500"}])
    assert [m["role"] for m in prov.seen[0]] == ["system", "user", "assistant", "user"]
