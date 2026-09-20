"""Agent evaluation: run unseen customer messages through the REAL agent loop and score
tool choice, tool arguments, retrieval, decision, answer content and groundedness.

    MISTRAL_API_KEY=... python -m tests.agent.eval_live                # all cases
    python -m tests.agent.eval_live --tags sheng,multi-turn --verbose
    python -m tests.agent.eval_live --model mistral-medium-latest --out report_medium.json

The cases in eval_cases.jsonl are NEVER shown to the model as examples: they are only
inputs to be judged. Content checks are coarse on purpose (a human should still read the
--verbose transcript); the point is comparing models/prompts/tools over time.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from tests.agent.harness import TurnRecord, describe_turn, run_conversation

CASES = Path(__file__).with_name("eval_cases.jsonl")
DIMS = ["answered", "tool_selection", "tool_args", "retrieval", "action", "content", "grounded"]


def load_cases(path: Path = CASES, tags: set[str] | None = None, ids: set[str] | None = None) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if tags:
        cases = [c for c in cases if tags & set(c["tags"])]
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    return cases


def _search_args(rec: TurnRecord) -> list[dict[str, Any]]:
    return [s["arguments"] for s in rec.result.trace.steps if s.get("tool") == "search_products" and s.get("ok")]


def _call_matches(a: dict[str, Any], want: dict[str, Any]) -> bool:
    for k, v in want.items():
        if k == "brand":
            hay = ((a.get("brand") or "") + " " + " ".join(a.get("keywords") or [])).lower()
            ok = str(v).lower() in hay
        elif k == "max_price_kes":
            got = a.get("max_price_kes")
            ok = got is not None and abs(float(got) - float(v)) <= 0.01 * float(v)
        elif k == "preferences_any":
            hay = " ".join((a.get("preferences") or []) + (a.get("keywords") or [])).lower()
            ok = any(str(x).lower() in hay for x in v)
        elif k == "category_in":
            ok = any(str(x).lower() in str(a.get("category") or "").lower() for x in v)
        elif k == "keywords_any":
            hay = " ".join(a.get("keywords") or []).lower()
            ok = any(str(x).lower() in hay for x in v)
        else:
            ok = False
        if not ok:
            return False
    return True


def score_turn(expect: dict[str, Any], rec: TurnRecord) -> dict[str, bool | None]:
    r, t = rec.result, rec.result.trace
    reply = (rec.reply or "").lower()
    called = set(t.tools_called)
    s: dict[str, bool | None] = {d: None for d in DIMS}
    s["answered"] = r.status == "answered"
    s["grounded"] = r.status == "answered" and t.grounding["first_pass_ok"] is not False
    if r.status != "answered":
        return {**s, **{d: False for d in DIMS if s[d] is None and any(k in expect for k in _DIM_KEYS[d])}}
    sel = []
    if "tools_include" in expect: sel.append(set(expect["tools_include"]) <= called)
    if "tools_include_any" in expect: sel.append(bool(set(expect["tools_include_any"]) & called))
    if "tools_exclude" in expect: sel.append(not (set(expect["tools_exclude"]) & called))
    if "if_answer_tools_include" in expect and t.action == "answer": sel.append(set(expect["if_answer_tools_include"]) <= called)
    if sel: s["tool_selection"] = all(sel)
    if "search_args" in expect: s["tool_args"] = any(_call_matches(a, expect["search_args"]) for a in _search_args(rec))
    if "evidence_names_any" in expect:
        names = {str(p.get("name")) for p in r.ctx.evidence.products.values()}
        s["retrieval"] = bool(names & set(expect["evidence_names_any"]))
    if "action_in" in expect: s["action"] = t.action in expect["action_in"]
    content = []
    if "must_mention_any" in expect: content.append(any(x.lower() in reply for x in expect["must_mention_any"]))
    if "mention_all" in expect: content.append(all(x.lower() in reply for x in expect["mention_all"]) or t.action == expect.get("or_action"))
    if "must_not_mention" in expect: content.append(not any(x.lower() in reply for x in expect["must_not_mention"]))
    if content: s["content"] = all(content)
    return s


_DIM_KEYS = {"tool_selection": ("tools_include", "tools_include_any", "tools_exclude", "if_answer_tools_include"), "tool_args": ("search_args",),
             "retrieval": ("evidence_names_any",), "action": ("action_in",), "content": ("must_mention_any", "mention_all", "must_not_mention")}


def evaluate(provider: Any, cases: list[dict[str, Any]], verbose: bool = False) -> dict[str, Any]:
    dim_totals: dict[str, list[bool]] = defaultdict(list)
    details, single_pass, multi_pass, multi_n, single_n = [], 0, 0, 0, 0
    tokens, latency_calls = 0, 0
    for case in cases:
        recs = run_conversation(provider, [t["user"] for t in case["turns"]])
        turn_scores = [score_turn(t["expect"], rec) for t, rec in zip(case["turns"], recs)]
        case_ok = all(v for sc in turn_scores for v in sc.values() if v is not None)
        for sc in turn_scores:
            for d, v in sc.items():
                if v is not None:
                    dim_totals[d].append(v)
        for rec in recs:
            tokens += rec.result.trace.prompt_tokens + rec.result.trace.completion_tokens
            latency_calls += rec.result.trace.model_calls
        if len(case["turns"]) > 1:
            multi_n += 1; multi_pass += case_ok
        else:
            single_n += 1; single_pass += case_ok
        details.append({"id": case["id"], "passed": case_ok, "turns": [{"user": r.user, "reply": r.reply, "scores": sc, "trace": r.result.trace.to_dict()} for r, sc in zip(recs, turn_scores)]})
        print(("PASS " if case_ok else "FAIL ") + case["id"])
        if verbose or not case_ok:
            for rec, sc in zip(recs, turn_scores):
                print("   " + describe_turn(rec).replace("\n", "\n   "))
                bad = [d for d, v in sc.items() if v is False]
                if bad: print("   >> failed:", ", ".join(bad))
    metrics = {d: (sum(v) / len(v) if v else None) for d, v in dim_totals.items()}
    hall = 1 - metrics["grounded"] if metrics.get("grounded") is not None else None
    summary = {"cases": len(cases), "passed": sum(d["passed"] for d in details), "single_turn": f"{single_pass}/{single_n}", "multi_turn_success": f"{multi_pass}/{multi_n}",
               "dimension_accuracy": metrics, "ungrounded_first_draft_rate": hall, "total_tokens": tokens, "model_calls": latency_calls}
    return {"summary": summary, "details": details}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", default=""); ap.add_argument("--ids", default=""); ap.add_argument("--model", default=""); ap.add_argument("--out", default="")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    from app.agent.providers import get_provider
    from app.config import settings
    provider = get_provider(settings.ai_provider, api_key=settings.mistral_api_key, model=a.model or settings.agent_model, reasoning_effort=settings.agent_reasoning_effort or None)
    if not provider.enabled:
        print("No model configured. Set MISTRAL_API_KEY (and optionally AGENT_MODEL) and run again.")
        return 2
    cases = load_cases(tags=set(filter(None, a.tags.split(","))), ids=set(filter(None, a.ids.split(","))))
    report = evaluate(provider, cases, a.verbose)
    print("\n" + json.dumps(report["summary"], indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
