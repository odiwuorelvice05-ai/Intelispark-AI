"""Checks the evaluation tooling itself (so a scoring bug cannot hide an agent bug)."""
from tests.agent.eval_live import DIMS, evaluate, load_cases, score_turn
from tests.agent.fixtures import PRODUCTS_A, _id
from tests.agent.harness import run_conversation
from tests.agent.scripted import ScriptedProvider, call, say


def test_case_file_is_well_formed_and_covers_the_required_categories():
    cases = load_cases()
    assert len(cases) >= 30 and len({c["id"] for c in cases}) == len(cases)
    tags = {t for c in cases for t in c["tags"]}
    for needed in ("english", "swahili", "sheng", "mixed", "typo", "vague", "comparison", "recommendation", "multi-turn", "impossible",
                   "unavailable", "ambiguity", "delivery", "warranty", "payment", "security", "negotiation", "quantity"):
        assert needed in tags, needed
    names = {p["name"] for p in PRODUCTS_A}
    for c in cases:
        for turn in c["turns"]:
            assert turn["user"].strip() and set(turn["expect"]) <= {"tools_include", "tools_include_any", "tools_exclude", "if_answer_tools_include", "search_args",
                "evidence_names_any", "action_in", "must_mention_any", "mention_all", "or_action", "must_not_mention"}, (c["id"], turn["expect"].keys())
            assert set(turn["expect"].get("evidence_names_any", [])) <= names, c["id"]


def test_scoring_marks_good_and_bad_turns_correctly():
    good = run_conversation(ScriptedProvider([call("search_products", brand="Samsung", max_price_kes=50000, preferences=["camera"]),
                                              say("Nina Galaxy A55 KES 48,500.", evidence_product_ids=[_id(2)])]), ["x"])[0]
    bad = run_conversation(ScriptedProvider([say("Karibu, tuna simu nyingi.", action="answer")]), ["x"])[0]
    expect = {"tools_include": ["search_products"], "search_args": {"brand": "samsung", "max_price_kes": 50000, "preferences_any": ["camera"]},
              "evidence_names_any": ["Galaxy A55"], "action_in": ["answer"], "must_mention_any": ["48,500"], "must_not_mention": ["S24"]}
    g, b = score_turn(expect, good), score_turn(expect, bad)
    assert all(v is True for v in g.values()), g
    assert b["tool_selection"] is False and b["tool_args"] is False and b["retrieval"] is False and b["content"] is False


def test_evaluate_reports_summary_metrics():
    cases = [c for c in load_cases() if c["id"] == "rec-sheng"]
    prov = ScriptedProvider([call("search_products", brand="Samsung", max_price_kes=50000, preferences=["camera"]), say("Galaxy A55 iko KES 48,500.", evidence_product_ids=[_id(2)])])
    rep = evaluate(prov, cases)
    assert rep["summary"]["passed"] == 1 and rep["summary"]["ungrounded_first_draft_rate"] == 0
    assert set(rep["summary"]["dimension_accuracy"]) <= set(DIMS)
