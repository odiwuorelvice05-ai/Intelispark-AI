from app.assistant import catalog
from app.assistant.grounding import check_reply
from app.assistant.tools import Evidence
from tests.fixtures import BUSINESS_A, PRODUCTS_A, pid


def evidence(*ids, profile=True):
    ev = Evidence()
    for p in PRODUCTS_A:
        if int(p["id"][-12:]) in ids:
            ev.products[p["id"]] = catalog.compact(p, full=True)
    if profile:
        ev.texts.append(BUSINESS_A["description"])
    return ev


def check(reply, ev, state=None, claims=None, order=False):
    return check_reply(reply, ev, state or {}, claims, order)


def test_a_price_returned_by_tools_is_allowed():
    assert check("The Galaxy A55 is KES 48,500.", evidence(2)) == []


def test_an_invented_price_is_rejected():
    assert check("The Galaxy A55 is KES 45,000.", evidence(2))


def test_a_price_with_no_evidence_at_all_is_rejected():
    assert check("It costs 30,000/=", Evidence())


def test_multiples_and_sums_of_real_prices_are_allowed():
    assert check("Two Galaxy A05 come to KES 25,000.", evidence(11), state={"quantity": 2}) == []
    assert check("A05 KES 12,500 plus A15 KES 24,500 is KES 37,000.", evidence(11, 4)) == []


def test_price_plus_a_shop_stated_delivery_fee_is_allowed():
    assert check("A05 with courier to Kisumu: KES 13,000 (KES 500 delivery).", evidence(11)) == []


def test_shop_policy_figures_are_allowed_but_others_are_not():
    assert check("Delivery to Kisumu is KES 500 to KES 800.", evidence()) == []
    assert check("Delivery to Kisumu is KES 300.", evidence())


def test_the_customers_recorded_budget_may_be_echoed_but_other_customer_numbers_may_not():
    reply = "Within your KES 50,000 budget I have the A55 at KES 48,500."
    assert check(reply, evidence(2), state={"budget_max_kes": 50000}) == []
    assert check(reply, evidence(2))                                   # budget not recorded -> not a shop figure
    assert check("Yes, KES 30,000 as the owner told you.", evidence(2), state={"budget_max_kes": 50000})


def test_approximate_k_amounts_must_be_near_a_real_price():
    assert check("The A55 is about 48k.", evidence(2)) == []
    assert check("The A55 is about 30k.", evidence(2))


def test_specs_and_phone_numbers_are_not_mistaken_for_money():
    ev = evidence(2)
    assert check("It has 8GB RAM, 256GB storage and a 5000mAh battery. Call +254700111222.", ev) == []


def test_stock_counts_must_match_the_database():
    assert check("We have only 5 left.", evidence(2)) == []
    assert check("We have only 9 left.", evidence(2))
    assert check("We have 9 in stock.", evidence(2), state={"quantity": 9})   # wanting 9 does not make 9 available


def test_availability_claim_contradicting_stock_is_rejected():
    ev = evidence(5)
    v = check("Yes, the Galaxy A16 is available.", ev, claims=[{"product_id": pid(5), "availability": "in_stock"}])
    assert v and "stock_quantity is 0" in v[0]
    assert check("Sorry, the A16 is sold out.", ev, claims=[{"product_id": pid(5), "availability": "out_of_stock"}]) == []


def test_out_of_stock_claim_for_an_in_stock_product_is_rejected():
    assert check("The A55 is sold out.", evidence(2), claims=[{"product_id": pid(2), "availability": "out_of_stock"}])


def test_declared_price_must_equal_the_record():
    assert check("A55: KES 48,500", evidence(2), claims=[{"product_id": pid(2), "price_kes": 48500}]) == []
    assert check("A55: KES 48,500", evidence(2), claims=[{"product_id": pid(2), "price_kes": 45000}])


def test_claims_about_products_never_retrieved_are_rejected():
    assert check("Fine.", evidence(2), claims=[{"product_id": pid(901), "availability": "in_stock"}])


def test_order_confirmation_is_always_rejected():
    ev = evidence(2)
    for reply in ["Your order has been placed!", "I've placed your order.", "Your reservation is confirmed.", "I have reserved it for you."]:
        assert check(reply, ev), reply
    assert check("Done.", ev, order=True)


def test_handing_over_to_the_shop_is_not_an_order_claim():
    assert check("I've passed your request to the shop. They will confirm availability and payment.", evidence(2)) == []
