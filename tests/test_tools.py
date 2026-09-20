"""Tenant isolation, argument handling and data boundaries of the model's tools."""
import json

import pytest

from app.assistant.repository import DataUnavailable, SupabaseShopRepository
from app.assistant.schema import validate
from app.assistant.tools import ToolContext, ToolRegistry
from app.assistant.types import ToolCall
from tests.fakes import FakeSupabase
from tests.fixtures import SHOP_A, SHOP_B, pid, seed


@pytest.fixture()
def db():
    d = FakeSupabase()
    seed(d)
    return d


def ctx_for(db, business_id=SHOP_A):
    return ToolContext(repo=SupabaseShopRepository(db, business_id), conversation_id="cccccccc-cccc-cccc-cccc-cccccccccccc")


def run(ctx, name, **args):
    return ToolRegistry().execute(ctx, ToolCall(id="c1", name=name, arguments=args))


def test_repository_returns_only_this_tenants_products_and_only_whitelisted_columns(db):
    rows = SupabaseShopRepository(db, SHOP_A).list_products()
    assert rows and all("cost_price" not in r and "business_id" not in r for r in rows)
    assert not any(r["name"] == "Secret Fold Z" for r in rows)
    assert [r["name"] for r in SupabaseShopRepository(db, SHOP_B).list_products()] == ["Secret Fold Z"]


def test_business_profile_is_whitelisted(db):
    b = SupabaseShopRepository(db, SHOP_A).get_business()
    assert "owner_id" not in b and b["name"] == "Nairobi Mobile Hub"


def test_a_tenant_id_invented_by_the_model_is_discarded_and_logged(db):
    ctx = ctx_for(db)
    res = run(ctx, "search_products", query="secret fold", business_id=SHOP_B)
    assert res.ok and res.payload["total_matches"] == 0
    assert ctx.security_events and "business_id" in ctx.security_events[0]
    assert not ctx.evidence.products


def test_product_ids_from_another_shop_are_not_resolvable(db):
    ctx = ctx_for(db)
    res = run(ctx, "get_products", product_ids=[pid(901)])
    assert not res.ok and pid(901) in res.payload["unknown_ids"] and not ctx.evidence.products


def test_get_products_returns_current_full_records_and_records_evidence(db):
    ctx = ctx_for(db)
    res = run(ctx, "get_products", product_ids=[pid(11), pid(12), "not-a-uuid"])
    assert [p["name"] for p in res.payload["products"]] == ["Galaxy A05", "Casio FX-991ES Plus"] and res.payload["unknown_ids"] == ["not-a-uuid"]
    assert set(ctx.evidence.products) == {pid(11), pid(12)}


def test_search_records_everything_it_shows_as_evidence(db):
    ctx = ctx_for(db)
    run(ctx, "search_products", brand="Samsung", limit=3)
    assert len(ctx.evidence.products) == 3


def test_tool_output_never_contains_cost_or_owner_fields(db):
    ctx = ctx_for(db)
    text = run(ctx, "search_products", query="galaxy", limit=20).content() + run(ctx, "get_shop_info").content()
    assert "cost_price" not in text and "owner_id" not in text and "owner-1" not in text


def test_arguments_are_coerced_and_unknown_ones_dropped():
    schema = {"type": "object", "properties": {"max_price_kes": {"type": "number", "minimum": 0}, "condition": {"type": "string", "enum": ["new", "used"]}}}
    clean, errors = validate(schema, {"max_price_kes": "50,000", "condition": "NEW", "made_up": 1})
    assert clean == {"max_price_kes": 50000.0, "condition": "new"} and errors == []
    _, errors = validate(schema, {"condition": "broken"})
    assert errors


def test_invalid_arguments_produce_a_corrective_result_not_an_exception(db):
    res = run(ctx_for(db), "search_products", sort="cheapest-ish")
    assert not res.ok and "sort" in res.payload["error"]
    assert not run(ctx_for(db), "no_such_tool").ok
    bad = ToolRegistry().execute(ctx_for(db), ToolCall(id="c", name="get_products", arguments={}, arguments_error="arguments were not valid JSON"))
    assert not bad.ok


def test_shop_info_exposes_profile_and_states_when_nothing_is_recorded(db):
    ctx = ctx_for(db)
    info = run(ctx, "get_shop_info").payload
    assert "Moi Avenue" in info["owner_written_profile"] and info["shop"]["phone"] == "+254700111222"
    db.tables["businesses"][0]["description"] = None
    empty = run(ctx_for(db), "get_shop_info").payload
    assert empty["owner_written_profile"] is None and "not written a profile" in empty["note"]


def test_escalation_is_recorded_for_this_tenant_only(db):
    ctx = ctx_for(db)
    res = run(ctx, "escalate_to_owner", reason="order_help", summary="Wants 2 x Galaxy A05, pickup tomorrow")
    assert res.payload["handoff_recorded"] is True and ctx.evidence.escalation_recorded
    row = db.tables["escalations"][0]
    assert row["business_id"] == SHOP_A and row["status"] == "open"


def test_failed_escalation_is_never_reported_as_recorded(db):
    db.fail_tables.add("escalations")
    ctx = ctx_for(db)
    res = run(ctx, "escalate_to_owner", reason="unknown_information", summary="Asked about trade-ins")
    assert res.payload["handoff_recorded"] is False and res.payload["owner_contact"]["phone"] == "+254700111222"
    assert not ctx.evidence.escalation_recorded and "could NOT be saved" in res.payload["note"]


def test_database_outage_propagates_instead_of_letting_the_model_guess(db):
    db.fail_tables.add("products")
    with pytest.raises(DataUnavailable):
        run(ctx_for(db), "search_products", query="galaxy")


def test_state_is_read_and_written_only_for_the_owning_business(db):
    conv = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    db.tables["conversations"] = [{"id": conv, "business_id": SHOP_A, "agent_state": {"quantity": 2}}]
    assert SupabaseShopRepository(db, SHOP_A).get_state(conv) == {"quantity": 2}
    assert SupabaseShopRepository(db, SHOP_B).get_state(conv) == {}
    assert SupabaseShopRepository(db, SHOP_B).save_state(conv, {"quantity": 99}) is False
    assert db.tables["conversations"][0]["agent_state"] == {"quantity": 2}
