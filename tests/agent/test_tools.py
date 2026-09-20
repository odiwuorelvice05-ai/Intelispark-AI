import json

from app.agent.repository import SupabaseShopRepository
from app.agent.tools import ToolContext, ToolRegistry, validate_args
from app.agent.types import ToolCall
from tests.agent.fixtures import CONV, SHOP_A, SHOP_B, make_store, _id

REG = ToolRegistry()


def ctx_for(shop=SHOP_A, store=None):
    store = store or make_store()
    return ToolContext(repo=store.repo(shop), conversation_id=CONV), store


def run(ctx, name, **args):
    return REG.execute(ctx, ToolCall(id="t1", name=name, arguments=args))


def names(res):
    return [p["name"] + " " + str(p["variant"]) for p in res.payload["products"]]


def test_search_applies_brand_budget_and_stock_filters():
    ctx, _ = ctx_for()
    res = run(ctx, "search_products", brand="Samsung", max_price_kes=50000, preferences=["camera", "photography"])
    assert res.ok
    got = {p["name"] for p in res.payload["products"]}
    assert got == {"Galaxy A55", "Galaxy A35", "Galaxy A15"}          # S24 too expensive, A16 out of stock
    assert all(p["price_kes"] <= 50000 and p["in_stock"] for p in res.payload["products"])
    assert set(ctx.evidence.products) == {p["id"] for p in res.payload["products"]}


def test_search_tolerates_typos_and_category_synonyms():
    ctx, _ = ctx_for()
    res = run(ctx, "search_products", keywords=["galxy", "a55"], category="smartphone")
    assert names(res)[0].startswith("Galaxy A55")


def test_search_sort_and_limit():
    ctx, _ = ctx_for()
    res = run(ctx, "search_products", category="phone", sort="price_asc", limit=2)
    assert [p["price_kes"] for p in res.payload["products"]] == [14500, 17500]  # cheapest two in stock (A15 refurbished is 17,500)


def test_out_of_stock_only_when_asked():
    ctx, _ = ctx_for()
    res = run(ctx, "search_products", keywords=["a16"], in_stock_only=False)
    assert res.payload["products"][0]["name"] == "Galaxy A16" and res.payload["products"][0]["in_stock"] is False
    res2 = run(ctx, "search_products", keywords=["a16"])
    assert res2.payload["products"] == [] and res2.payload["relaxed_constraint"] == "in_stock_only"


def test_no_exact_match_returns_labelled_alternatives_not_fake_matches():
    ctx, _ = ctx_for()
    res = run(ctx, "search_products", brand="Samsung", max_price_kes=10000)
    assert res.payload["products"] == [] and res.payload["alternatives"]
    assert res.payload["relaxed_constraint"] == "max_price_kes"
    assert "notes" in res.payload


def test_unknown_brand_reports_nothing():
    ctx, _ = ctx_for()
    res = run(ctx, "search_products", brand="Sony")
    assert res.payload["products"] == [] and "alternatives" not in res.payload


def test_missing_price_never_matches_a_price_filter():
    store = make_store()
    store.products[SHOP_A].append(dict(id=_id(50), name="No Price Phone", brand="Samsung", category="phone", price=None, stock_quantity=2, specs={}))
    ctx, _ = ctx_for(store=store)
    res = run(ctx, "search_products", brand="Samsung", max_price_kes=100000)
    assert "No Price Phone" not in {p["name"] for p in res.payload["products"]}


def test_get_product_and_compare():
    ctx, _ = ctx_for()
    p = run(ctx, "get_product", product_id=_id(2))
    assert p.ok and p.payload["product"]["price_kes"] == 48500 and p.payload["product"]["specs"]["camera"] == "50MP OIS"
    cmp_ = run(ctx, "compare_products", product_ids=[_id(2), _id(3)])
    assert cmp_.ok and cmp_.payload["spec_comparison"]["battery"] == {_id(2): "5000mAh", _id(3): "5000mAh"}
    assert not run(ctx, "compare_products", product_ids=[_id(2), _id(2)]).ok      # need two distinct products


def test_policy_lookup_finds_recorded_policy_and_admits_missing():
    ctx, _ = ctx_for()
    d = run(ctx, "get_shop_policy", topic="delivery", question="deliver to Kisumu")
    assert d.payload["found"] and any("Kisumu" in s for s in d.payload["passages"])
    w = run(ctx, "get_shop_policy", topic="warranty")
    assert any("12-month" in s for s in w.payload["passages"])
    ctx_b, _ = ctx_for(SHOP_B)
    miss = run(ctx_b, "get_shop_policy", topic="warranty")
    assert miss.payload["found"] is False and "not guess" in miss.payload["note"].lower() or "do not guess" in miss.payload["note"].lower()


# ---------------------------------------------------------------- tenant isolation
def test_other_shops_products_are_invisible():
    ctx, _ = ctx_for(SHOP_A)
    assert not run(ctx, "get_product", product_id=_id(901)).ok
    assert "Secret Fold Z" not in json.dumps(run(ctx, "search_products", brand="Samsung", in_stock_only=False).payload)
    assert not run(ctx, "compare_products", product_ids=[_id(901), _id(2)]).ok


def test_model_supplied_business_id_is_ignored_and_flagged():
    ctx, _ = ctx_for(SHOP_A)
    res = run(ctx, "search_products", brand="Samsung", business_id=SHOP_B, owner_id="x")
    assert res.ok and "Secret Fold Z" not in json.dumps(res.payload)
    assert any("business_id" in e for e in ctx.security_events) and any("owner_id" in e for e in ctx.security_events)


def test_state_rejects_foreign_product_ids_and_is_tenant_scoped():
    ctx, store = ctx_for(SHOP_A)
    assert not run(ctx, "save_conversation_state", selected_product_ids=[_id(901)]).ok
    ok = run(ctx, "save_conversation_state", selected_product_ids=[_id(2)], quantity=2, stage="product_selected")
    assert ok.ok and ok.payload["persisted"]
    assert store.repo(SHOP_B).get_state(CONV) == {}          # same conversation id, other tenant: nothing
    assert store.repo(SHOP_A).get_state(CONV)["quantity"] == 2


def test_supabase_repository_always_filters_by_business_id():
    class Q:
        def __init__(self, log, table): self.log, self.table = log, table
        def select(self, *_): return self
        def eq(self, col, val): self.log.append((self.table, col, val)); return self
        def limit(self, *_): return self
        def execute(self):
            class R: data = []
            return R()
    log = []
    class DB:
        def table(self, name): return Q(log, name)
    repo = SupabaseShopRepository(DB(), SHOP_A)
    repo.list_products(); repo.get_business(); repo.get_state(CONV)
    assert ("products", "business_id", SHOP_A) in log
    assert ("businesses", "id", SHOP_A) in log
    assert ("conversations", "business_id", SHOP_A) in log


# ---------------------------------------------------------------- validation & robustness
def test_argument_validation_and_coercion():
    schema = next(t for t in REG.specs() if t["name"] == "search_products")["parameters"]
    clean, errs = validate_args(schema, {"max_price_kes": "50,000", "brand": "Samsung", "limit": "3"})
    assert not errs and clean == {"max_price_kes": 50000, "brand": "Samsung", "limit": 3}
    _, errs = validate_args(schema, {"condition": "broken"})
    assert errs
    _, errs = validate_args(schema, {"sql": "drop table"})
    assert errs and "unknown argument" in errs[0]


def test_bad_calls_return_errors_instead_of_raising():
    ctx, _ = ctx_for()
    assert not run(ctx, "get_product", product_id="1; drop table products").ok
    assert not run(ctx, "delete_everything").ok
    assert not REG.execute(ctx, ToolCall(id="x", name="search_products", arguments={}, arguments_error="arguments were not valid JSON")).ok


def test_escalation_records_and_reports_failure_honestly():
    ctx, store = ctx_for()
    res = run(ctx, "escalate_to_owner", reason="order_help", summary="Wants 2x Galaxy A55 delivered to Kisumu", urgency="high")
    assert res.payload["handoff_recorded"] and store.escalations[0]["business_id"] == SHOP_A
    assert res.payload["owner_contact"]["phone"] == "+254700111222"

    class BrokenRepo(type(ctx.repo)):
        def create_escalation(self, *a, **k): return {"recorded": False, "id": None}
    ctx2 = ToolContext(repo=BrokenRepo(store, SHOP_A), conversation_id=CONV)
    res2 = run(ctx2, "escalate_to_owner", reason="complaint", summary="x")
    assert res2.payload["handoff_recorded"] is False and "could not" in res2.payload["note"].lower()
