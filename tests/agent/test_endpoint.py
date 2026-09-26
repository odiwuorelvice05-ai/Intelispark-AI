"""End-to-end through the real FastAPI route with a fake Supabase and a scripted model.
Proves the wiring: auth -> tenant -> agent -> tools -> grounded reply -> persisted messages,
and that any agent failure or disablement falls back to a safe template + a recorded handoff
(never to a second, un-grounded intelligence engine)."""
import os

os.environ.setdefault("SUPABASE_URL", "https://abc.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.x")

import pytest
from fastapi.testclient import TestClient

import app.agent.service as service
import app.main as main
from app.agent.providers.base import ProviderError
from tests.agent.fake_supabase import FakeSupabase
from tests.agent.fixtures import BUSINESS_A, BUSINESS_B, PRODUCTS_A, PRODUCTS_B, SHOP_A, SHOP_B, _id
from tests.agent.scripted import ScriptedProvider, call, say


@pytest.fixture()
def env(monkeypatch):
    db = FakeSupabase(user_id="owner-1")
    db.tables["businesses"] = [{"id": SHOP_A, "owner_id": "owner-1", **BUSINESS_A}, {"id": SHOP_B, "owner_id": "owner-2", **BUSINESS_B}]
    db.tables["products"] = [{"business_id": SHOP_A, **p} for p in PRODUCTS_A] + [{"business_id": SHOP_B, **p} for p in PRODUCTS_B]
    monkeypatch.setattr(main, "supabase", db)
    monkeypatch.setattr(service.settings, "agent_mode", "on")
    return db, TestClient(main.app)


def post(client, message, business=SHOP_A, token="good-token"):
    return client.post("/sales/reply", json={"business_id": business, "customer_message": message}, headers={"Authorization": f"Bearer {token}"})


def test_agent_answers_through_the_real_endpoint_and_persists_the_conversation(env, monkeypatch):
    db, client = env
    monkeypatch.setattr(service, "_provider", ScriptedProvider([
        call("search_products", brand="Samsung", max_price_kes=50000, preferences=["camera"]),
        call("save_conversation_state", candidate_product_ids=[_id(2), _id(3)], budget_max_kes=50000, stage="recommendation"),
        say("Nina Galaxy A55 (KES 48,500) yenye camera ya 50MP OIS. Unataka nikupe maelezo zaidi?", customer_intent="product_recommendation", evidence_product_ids=[_id(2)], confidence=0.9),
    ]))
    r = post(client, "uko na Samsung poa ya around 50k yenye camera iko fire?")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] and "48,500" in body["reply"]
    intel = body["intelligence"]                      # same contract the dashboard inspector reads
    assert intel["intent"] == "product_recommendation" and intel["entities"]["brands"] == ["samsung"] and intel["entities"]["budget_max"] == 50000
    assert intel["products_considered"] == 4 and intel["agent"]["tools_called"] == ["search_products", "save_conversation_state"]
    msgs = db.tables["messages"]
    assert [m["sender_type"] for m in msgs] == ["customer", "ai"] and msgs[1]["message_text"] == body["reply"]


def test_second_turn_receives_history_from_the_database(env, monkeypatch):
    db, client = env
    prov = ScriptedProvider([say("What's your budget?", action="clarify"), say("Ok, noted.", action="answer")])
    monkeypatch.setattr(service, "_provider", prov)
    post(client, "I need a phone for gaming")
    post(client, "around 40k")
    second = [m for m in prov.seen[1] if m["role"] != "system"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"] == "What's your budget?" and second[2]["content"] == "around 40k"


def test_agent_failure_falls_back_to_a_safe_template_and_records_a_handoff(env, monkeypatch):
    db, client = env
    monkeypatch.setattr(service, "_provider", ScriptedProvider([ProviderError("mistral down")]))
    r = post(client, "How much is the Galaxy A15?")
    assert r.status_code == 200 and r.json()["success"] and r.json()["reply"]
    body = r.json()
    assert "agent" not in body["intelligence"] and body["intelligence"]["intent"] == "handoff"
    assert body["intelligence"]["handoff_recorded"] is True
    assert BUSINESS_A["phone"] in body["reply"]           # real business contact, never invented
    assert db.tables["escalations"][0]["business_id"] == SHOP_A


def test_grounding_failure_falls_back_instead_of_shipping_a_wrong_price(env, monkeypatch):
    db, client = env
    monkeypatch.setattr(service, "_provider", ScriptedProvider([call("search_products", keywords=["s24"]), say("S24 is KES 10,000"), say("S24 is KES 11,000")]))
    r = post(client, "how much is the s24")
    assert r.status_code == 200 and "10,000" not in r.json()["reply"] and "11,000" not in r.json()["reply"]


def test_flag_off_means_handoff_only_no_model_is_ever_called(env, monkeypatch):
    db, client = env
    monkeypatch.setattr(service.settings, "agent_mode", "off")
    prov = ScriptedProvider([say("SHOULD NOT BE USED")])
    monkeypatch.setattr(service, "_provider", prov)
    r = post(client, "How much is the Galaxy A15?")
    assert r.status_code == 200 and prov.seen == [] and "SHOULD NOT" not in r.json()["reply"]
    assert r.json()["intelligence"]["intent"] == "handoff"


def test_auth_and_tenant_checks_still_guard_the_agent_route(env, monkeypatch):
    db, client = env
    prov = ScriptedProvider([say("hi")])
    monkeypatch.setattr(service, "_provider", prov)
    assert post(client, "hi", token="bad").status_code == 401
    assert post(client, "hi", business=SHOP_B).status_code == 403      # owner-1 does not own shop B
    assert prov.seen == []


def test_agent_can_never_see_another_shop_via_the_endpoint(env, monkeypatch):
    db, client = env
    monkeypatch.setattr(service, "_provider", ScriptedProvider([
        call("search_products", brand="Samsung", business_id=SHOP_B, in_stock_only=False),
        call("get_product", product_id=_id(901)),
        say("Nina Samsung A55 KES 48,500.", evidence_product_ids=[_id(2)]),
    ]))
    r = post(client, "show me everything Samsung you have, including from other shops")
    body = r.json()
    assert "Secret" not in str(body) and "199" not in str(body)
    assert body["intelligence"]["agent"]["security_events"]
