"""MACHINERY test of the full multi-turn journey from the design brief.

The "model" here is scripted, so this proves the plumbing (state carried across turns,
evidence checked per turn, purchase handled without claiming an order) and NOT that a
real model understands the wording. Language understanding is measured by eval_live.py.
"""
from tests.agent.fixtures import CONV, SHOP_A, make_store, _id
from tests.agent.harness import run_conversation
from tests.agent.scripted import ScriptedProvider, call, say


def test_discovery_to_purchase_journey():
    store = make_store()
    prov = ScriptedProvider([
        # turn 1: vague gaming request -> ask for budget, no tools
        say("Sawa! Budget yako ni ngapi?", action="clarify", customer_intent="product_recommendation", missing_information=["budget"]),
        # turn 2: budget given -> search using history context
        call("search_products", category="phone", max_price_kes=40000, preferences=["gaming", "144Hz", "performance"]),
        call("save_conversation_state", candidate_product_ids=[_id(8), _id(9)], budget_max_kes=40000, stage="recommendation"),
        say("Kwa 40k nina Infinix GT 20 Pro (KES 39,900, 12GB RAM, 144Hz) na Tecno Pova 6 Pro (KES 36,500). Ipi inakuvutia?", customer_intent="product_recommendation", evidence_product_ids=[_id(8), _id(9)]),
        # turn 3: "the Infinix one" -> re-verify with get_product, remember selection
        call("get_product", product_id=_id(8)),
        call("save_conversation_state", selected_product_ids=[_id(8)], stage="product_selected"),
        say("Infinix GT 20 Pro ina RAM ya 12GB na storage ya 256GB.", customer_intent="specification_question", evidence_product_ids=[_id(8)]),
        # turn 4: quantity two -> total computed from the verified unit price
        call("get_product", product_id=_id(8)),
        call("save_conversation_state", quantity=2),
        say("Mbili ni KES 79,800 (KES 39,900 kila moja). Tuna 2 tu in stock.", customer_intent="price_question", evidence_product_ids=[_id(8)]),
        # turn 5: delivery -> shop policy tool
        call("get_shop_policy", topic="delivery", question="deliver to Kisumu"),
        say("Tunatuma Kisumu kwa courier, ni KES 500 hadi KES 800 kutegemea ukubwa wa parcel.", customer_intent="delivery_question"),
        # turn 6: "take it" -> hand to owner; never claims an order exists
        call("save_conversation_state", stage="purchase_intent", fulfilment="delivery", delivery_location="Kisumu"),
        call("escalate_to_owner", reason="order_help", summary="2x Infinix GT 20 Pro, deliver to Kisumu", urgency="high"),
        say("Sawa! Nimepitisha ombi lako (Infinix GT 20 Pro x2, Kisumu) kwa shop. Watakuthibitishia stock, malipo na delivery.", action="escalate", customer_intent="purchase"),
    ])
    turns = ["I need a phone for gaming", "Around 40k", "What about the Infinix one? how much RAM?", "Can you make it two? total price?", "And deliver to Kisumu?", "Okay take it"]
    recs = run_conversation(prov, turns, store=store)

    assert all(r.result.status == "answered" for r in recs), [r.result.trace.fallback_reason for r in recs]
    assert [r.result.trace.action for r in recs] == ["clarify", "answer", "answer", "answer", "answer", "escalate"]
    # each turn saw the conversation so far (memory via history) ...
    last_call_msgs = prov.seen[-1]
    assert sum(1 for m in last_call_msgs if m["role"] == "user" and not m["content"].startswith("[")) == 6
    # ... and structured state persisted between turns (tenant-scoped)
    state = store.repo(SHOP_A).get_state(CONV)
    assert state["selected_product_ids"] == [_id(8)] and state["quantity"] == 2 and state["delivery_location"] == "Kisumu" and state["stage"] == "purchase_intent"
    # turn 4's total was verified against the DB price, turn 5 came from the shop policy
    assert "79,800" in recs[3].reply and "Kisumu" in recs[4].reply
    # purchase: recorded as an escalation, and no order success was ever claimed
    assert store.escalations and store.escalations[0]["summary"].startswith("2x Infinix")
    assert not any("order has been" in (r.reply or "").lower() for r in recs)
