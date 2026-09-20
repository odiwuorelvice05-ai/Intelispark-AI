import json

from app.agent.loop import AgentRunner
from app.agent.tools import ToolContext, ToolRegistry
from app.agent.providers.base import ProviderError
from tests.agent.fixtures import CONV, SHOP_A, make_store, _id
from tests.agent.scripted import ScriptedProvider, call, calls, say, text


def run_agent(script, message="niko looking for a phone", history=None, store=None, **runner_kw):
    store = store or make_store()
    prov = ScriptedProvider(script)
    ctx = ToolContext(repo=store.repo(SHOP_A), conversation_id=CONV, customer_id=None)
    res = AgentRunner(prov, ToolRegistry(), **runner_kw).run(ctx, shop_name="Nairobi Mobile Hub", history=history or [], customer_message=message)
    return res, prov, store


def test_search_then_grounded_answer():
    res, prov, _ = run_agent([
        call("search_products", brand="Samsung", max_price_kes=50000, preferences=["camera"]),
        say("Nina Galaxy A55 (KES 48,500, camera ya 50MP OIS) na A35 (KES 38,500). Ipi ungependa?", customer_intent="product_recommendation",
            evidence_product_ids=[_id(2), _id(3)], confidence=0.9),
    ], "Bro natafuta Samsung poa ya around 50k, camera iwe noma. Uko na anything?")
    assert res.status == "answered" and "48,500" in res.reply
    t = res.trace
    assert t.tools_called == ["search_products"] and t.model_calls == 2
    assert t.customer_intent == "product_recommendation" and t.action == "answer" and t.structured_final
    assert t.grounding["first_pass_ok"] is True and t.confidence > 0.85
    assert set(t.evidence_product_ids) == {_id(2), _id(3)}
    # the model saw the customer's raw message, the tool schema and the tenant-scoped result, never a DB credential
    first = prov.seen[0]
    assert first[-1] == {"role": "user", "content": "Bro natafuta Samsung poa ya around 50k, camera iwe noma. Uko na anything?"}
    tool_msg = next(m for m in prov.seen[1] if m["role"] == "tool")
    assert "Galaxy A55" in tool_msg["content"] and "Secret Fold" not in tool_msg["content"]
    assert "service_role" not in json.dumps(prov.seen).lower() and "SUPABASE" not in json.dumps(prov.seen)


def test_hallucinated_price_is_rejected_then_corrected():
    res, prov, _ = run_agent([
        call("search_products", keywords=["s24"]),
        say("The S24 costs KES 75,000."),
        say("The Galaxy S24 is KES 82,000, 3 in stock.", evidence_product_ids=[_id(1)]),
    ], "how much is the s24")
    assert res.status == "answered" and "82,000" in res.reply
    assert res.trace.grounding["retried"] and res.trace.grounding["first_pass_ok"] is False
    rejection = json.loads(next(m for m in prov.seen[2] if m["role"] == "tool" and m["name"] == "respond_to_customer")["content"])
    assert rejection["accepted"] is False and "75,000" in rejection["violations"][0]
    assert res.trace.confidence < 0.95        # corrected answers are trusted less than clean ones


def test_repeated_hallucination_falls_back_and_never_answers_ungrounded():
    res, _, _ = run_agent([call("search_products", keywords=["s24"]), say("KES 75,000"), say("It is KES 70,000")], "s24 price?")
    assert res.status == "fallback" and res.reply is None and res.trace.fallback_reason == "grounding_failed"


def test_order_success_cannot_be_claimed_without_backend_confirmation():
    res, _, _ = run_agent([
        call("search_products", keywords=["a55"]),
        say("Great! Your order has been placed. Total KES 97,000.", states_order_confirmed=True),
        say("I have passed your request to the shop; they will confirm availability and payment.", action="answer"),
    ], "okay take it")
    assert res.status == "answered" and "placed" not in res.reply.lower()
    assert res.trace.grounding["violations"]


def test_final_reply_in_same_step_as_tool_calls_is_ignored():
    res, prov, _ = run_agent([
        calls(("search_products", {"keywords": ["a55"]}), ("respond_to_customer", {"reply": "The A55 is KES 1,000", "action": "answer"})),
        say("The Galaxy A55 is KES 48,500.", evidence_product_ids=[_id(2)]),
    ])
    assert res.status == "answered" and "48,500" in res.reply


def test_plain_text_final_is_accepted_when_grounded_and_rejected_when_not():
    ok, _, _ = run_agent([call("search_products", keywords=["a55"]), text("Galaxy A55 iko KES 48,500.")])
    assert ok.status == "answered" and not ok.trace.structured_final
    bad, _, _ = run_agent([call("search_products", keywords=["a55"]), text("Galaxy A55 iko KES 20,000."), text("Sawa, ni KES 48,500.")])
    assert bad.status == "answered" and "48,500" in bad.reply and bad.trace.grounding["retried"]


def test_tool_errors_are_returned_to_the_model_and_it_can_recover():
    res, prov, _ = run_agent([
        call("search_products", max_price_kes="lots"),
        call("search_products", max_price_kes=50000, brand="Samsung"),
        say("Nina A55 KES 48,500.", evidence_product_ids=[_id(2)]),
    ])
    assert res.status == "answered"
    assert [s["ok"] for s in res.trace.steps] == [False, True]


def test_clarification_without_tools_is_valid():
    res, _, _ = run_agent([say("Budget yako ni ngapi?", action="clarify", customer_intent="product_recommendation", missing_information=["budget"])], "I need a phone for gaming")
    assert res.status == "answered" and res.trace.action == "clarify" and res.trace.missing_information == ["budget"]
    assert res.trace.tools_called == []


def test_escalation_flow_records_handoff():
    res, _, store = run_agent([
        call("save_conversation_state", selected_product_ids=[_id(2)], quantity=2, stage="purchase_intent", fulfilment="delivery", delivery_location="Kisumu"),
        call("escalate_to_owner", reason="order_help", summary="2x Galaxy A55 to Kisumu", urgency="high"),
        say("Nimepitisha ombi lako kwa shop, watakuthibitishia stock na malipo.", action="escalate", customer_intent="purchase"),
    ], "sawa nachukua mbili, peleka Kisumu")
    assert res.status == "answered" and res.trace.action == "escalate"
    assert store.escalations and store.escalations[0]["summary"].startswith("2x")
    assert store.repo(SHOP_A).get_state(CONV)["delivery_location"] == "Kisumu"


def test_escalate_action_without_recorded_handoff_is_rejected():
    res, _, _ = run_agent([say("I'll pass this to the shop.", action="escalate"), say("Please call the shop on +254700111222.", action="answer")])
    assert res.status == "answered" and res.trace.action == "answer" and res.trace.grounding["retried"]


def test_provider_failure_max_calls_tokens_and_deadline_all_fall_back():
    r, _, _ = run_agent([ProviderError("boom")])
    assert r.status == "fallback" and r.trace.fallback_reason.startswith("provider_error")
    r, _, _ = run_agent([call("get_business_information")] * 3, max_model_calls=2)
    assert r.status == "fallback" and r.trace.fallback_reason == "max_model_calls"
    r, _, _ = run_agent([call("get_business_information")] * 3, max_total_tokens=150)
    assert r.trace.fallback_reason == "token_budget"
    ticks = iter([0, 0, 100, 100, 100])
    r, _, _ = run_agent([call("get_business_information")] * 3, clock=lambda: next(ticks), deadline_s=20)
    assert r.trace.fallback_reason == "deadline"


def test_tenant_override_attempt_is_neutralised_and_reported():
    res, _, _ = run_agent([
        call("search_products", brand="Samsung", business_id="99999999-9999-9999-9999-999999999999"),
        say("Nina Samsung A55 KES 48,500.", evidence_product_ids=[_id(2)]),
    ])
    assert res.status == "answered" and res.trace.security_events and "Secret" not in res.reply


def test_saved_state_is_given_to_the_model_next_turn():
    store = make_store()
    run_agent([call("save_conversation_state", selected_product_ids=[_id(2)], quantity=2), say("Sawa, mbili.", action="answer")], "nataka mbili za A55", store=store)
    _, prov, _ = run_agent([say("Ok", action="clarify")], "na delivery?", store=store)
    system = prov.seen[0][0]["content"]
    assert _id(2) in system and '"quantity": 2' in system


def test_multi_turn_history_is_passed_to_the_model_in_order():
    hist = [{"role": "user", "content": "I need a phone for gaming"}, {"role": "assistant", "content": "What's your budget?"}]
    _, prov, _ = run_agent([say("Ok", action="clarify")], "around 40k", history=hist)
    roles = [m["role"] for m in prov.seen[0]]
    assert roles == ["system", "user", "assistant", "user"] and prov.seen[0][-1]["content"] == "around 40k"
