from app.agent.grounding import check_reply
from app.agent.tools import Evidence, ToolContext, ToolRegistry
from app.agent.types import ToolCall
from tests.agent.fixtures import CONV, SHOP_A, make_store, _id


def evidence_after_search(**args):
    ctx = ToolContext(repo=make_store().repo(SHOP_A), conversation_id=CONV)
    ToolRegistry().execute(ctx, ToolCall(id="1", name="search_products", arguments=args))
    ToolRegistry().execute(ctx, ToolCall(id="2", name="get_shop_policy", arguments={"topic": "delivery"}))
    return ctx.evidence


EV = evidence_after_search(brand="Samsung", in_stock_only=False)


def check(reply, customer=("hi",), state=None, **kw):
    return check_reply(reply, EV, list(customer), state or {}, **kw)


def test_correct_price_passes_in_several_formats():
    assert check("The Galaxy A55 is KES 48,500.").ok
    assert check("Galaxy A55: KSh 48500/=").ok
    assert check("48,500 shillings only").ok


def test_wrong_price_is_rejected():
    r = check("The S24 costs KES 75,000.")
    assert not r.ok and "75,000" in r.violations[0]


def test_quantity_totals_sums_and_differences_are_allowed():
    assert check("Two Galaxy A55 come to KES 97,000.").ok
    assert check("A55 plus A35 is KES 87,000 in total.").ok
    assert check("The A55 is KES 10,000 cheaper than the S24.").ok
    assert not check("Two A55 come to KES 96,000.").ok


def test_totals_with_delivery_fee_from_policy():
    assert check("Two A55 plus courier KES 500 = KES 97,500.").ok


def test_customer_budget_can_be_echoed():
    assert check("Within your KES 50,000 budget I have the A55.", customer=("around 50k",)).ok
    assert check("Within your 50,000 budget...", customer=("budget ni 50,000",)).ok


def test_approximate_k_amounts():
    assert check("The A55 is around 48k.").ok
    assert not check("The A55 is around 30k.").ok


def test_non_money_numbers_are_ignored():
    assert check("It has 8GB RAM, a 5000mAh battery, 120Hz display and 50MP camera. Call 0700111222.").ok


def test_stock_statements_must_match_retrieved_stock():
    assert check("We have the A55 in stock, only 5 left.").ok
    assert not check("Only 9 left!").ok


def test_uncited_product_ids_rejected():
    assert not check("Try this one.", cited_product_ids=[_id(901)]).ok
    assert check("Try this one.", cited_product_ids=[_id(2)]).ok


def test_order_success_claims_are_blocked_unless_backend_confirmed():
    for claim in ("Your order has been placed.", "I've placed the order for you.", "Order is confirmed!"):
        assert not check(claim).ok
    assert not check("All done.", claims_order_confirmed=True).ok
    ev = Evidence(order_confirmed=True)
    assert check_reply("Your order has been placed.", ev, ["x"], {}).ok


def test_swahili_reply_with_correct_price_passes():
    assert check("Galaxy A55 iko KES 48,500, ina camera ya 50MP.").ok
