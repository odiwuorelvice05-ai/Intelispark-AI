"""Product understanding, retrieval half: given the query/filters a model produces, is the right
record found, and is a non-match reported honestly? (No model involved.)"""
from app.assistant import catalog
from tests.fixtures import PRODUCTS_A, pid


def search(**f):
    payload, _ = catalog.search(PRODUCTS_A, f)
    return payload


def names(payload, key="products"):
    return [p["name"] for p in payload.get(key, [])]


def test_exact_product_lookup_ranks_the_named_model_first_and_marks_it_exact():
    r = search(query="galaxy a05")
    assert r["products"][0]["name"] == "Galaxy A05" and r["products"][0]["match"] == "exact"
    assert r["products"][0]["price_kes"] == 12500 and r["products"][0]["in_stock"] is True


def test_partial_lookup_reports_the_words_that_did_not_match():
    r = search(query="samsung a05 128gb")
    a05 = next(p for p in r["products"] if p["name"] == "Galaxy A05")
    assert a05["match"] == "partial" and a05["unmatched_terms"] == ["128gb"]  # A05 exists, just not in 128GB


def test_model_codes_are_never_fuzzy_matched():
    assert "Galaxy A15" not in names(search(query="a05"))   # a05 must not match a15
    assert "Galaxy A05" in names(search(query="a05"))


def test_typos_in_words_are_tolerated():
    assert {"Galaxy A15"} <= set(names(search(query="samsng galaxy a15")))


def test_brand_browse_lists_only_that_brand_and_only_stock_when_asked():
    r = search(brand="Samsung", limit=20, in_stock_only=True)
    assert r["total_matches"] == len(r["products"]) == 6
    assert all(p["brand"] == "Samsung" and p["in_stock"] for p in r["products"])


def test_category_query_finds_the_calculator_and_ranks_the_in_stock_one_first():
    r = search(category="calculator")
    assert names(r) == ["Casio FX-991ES Plus", "Casio Desk Calculator DJ-120"] and r["products"][1]["in_stock"] is False
    assert names(search(category="calculator", in_stock_only=True)) == ["Casio FX-991ES Plus"]


def test_plural_category_words_and_variant_numbers_match():
    assert "Galaxy A55" in names(search(query="phones 256"))     # 'phones' ~ category phone, '256' ~ 256GB
    assert set(names(search(query="256gb", category="phone"))) >= {"Galaxy S24", "Redmi Note 13"}


def test_budget_filter_is_a_hard_limit():
    r = search(category="phone", max_price_kes=15000)
    assert names(r) == ["Galaxy A05"]
    assert all(p["price_kes"] <= 15000 for p in r["products"])


def test_condition_and_installment_filters():
    assert names(search(query="galaxy a15", condition="refurbished")) == ["Galaxy A15"]
    assert all(p["installment_available"] for p in search(installment_only=True, limit=20)["products"])


def test_variant_queries_distinguish_variants_of_the_same_model():
    r = search(query="galaxy a15", limit=10)
    exact = [p for p in r["products"] if p["match"] == "exact"]
    assert {p["variant"] for p in exact} == {"8GB/256GB", "4GB/128GB"} and r["products"][:2] == exact


def test_a_sold_out_item_is_found_and_reported_as_sold_out_not_as_missing():
    top = search(query="galaxy a16")["products"][0]
    assert top["name"] == "Galaxy A16" and top["match"] == "exact" and top["in_stock"] is False and top["stock_quantity"] == 0


def test_when_stock_is_required_the_sold_out_exact_item_is_flagged_as_blocked():
    r = search(query="galaxy a16", in_stock_only=True)
    assert r["exact_match_blocked_by"]["constraint"] == "in_stock_only"
    assert r["exact_match_blocked_by"]["products"][0]["name"] == "Galaxy A16"


def test_unknown_product_returns_nothing_and_says_so():
    r = search(query="pixel 9 pro")
    assert r["total_matches"] == 0 and r["products"] == [] and "alternatives" not in r
    assert "Nothing in this shop matches" in r["note"]


def test_over_budget_request_says_the_exact_item_exists_but_is_above_budget():
    r = search(category="phone", query="galaxy s24", max_price_kes=30000)
    assert all(p["match"] == "partial" for p in r["products"])          # only look-alikes fit the budget
    blocked = r["exact_match_blocked_by"]
    assert blocked["constraint"] == "max_price_kes" and blocked["products"][0]["name"] == "Galaxy S24"


def test_zero_hits_with_a_binding_filter_offers_labelled_alternatives():
    r = search(category="laptop", max_price_kes=10000)
    assert r["total_matches"] == 0 and r["relaxed_constraint"] == "max_price_kes"
    assert r["alternatives"][0]["name"] == "HP 15 Laptop" and "never present them as exact" in r["note"]


def test_what_else_excludes_ids_already_shown():
    first = search(brand="Samsung", limit=2)["products"]
    more = search(brand="Samsung", limit=20, exclude_product_ids=[p["id"] for p in first])
    assert not {p["id"] for p in first} & {p["id"] for p in more["products"]}


def test_price_sorting():
    prices = [p["price_kes"] for p in search(category="phone", sort="price_asc", limit=20)["products"]]
    assert prices == sorted(prices)


def test_compact_record_never_contains_columns_outside_the_whitelist():
    rec = catalog.compact(PRODUCTS_A[0], full=True)
    assert "cost_price" not in rec and rec["id"] == pid(1)


def test_empty_catalog_is_reported():
    payload, _ = catalog.search([], {"query": "anything"})
    assert payload["note"] == "This shop has no products recorded."
