"""Measure the REAL model on realistic customer conversations, through the real application path.

    LLM_API_KEY=... python -m scripts.live_eval [--model NAME] [--verbose]

Runs each conversation in scripts/eval_cases.json against two fictional shops held in an in-memory
Supabase stand-in (tests/fixtures.py). Prints tools used, reply, latency and tokens, and applies simple
automatic checks. The checks are a smoke test: READ the transcripts before trusting a model with customers.
The unit tests use a scripted model and cannot tell you whether a real model understands customers; this can.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import os  # noqa: E402

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "unused-in-eval")

from app.assistant import service  # noqa: E402
from app.assistant.provider import get_provider  # noqa: E402
from app.config import settings  # noqa: E402
from tests.fakes import FakeSupabase  # noqa: E402
from tests.fixtures import SHOP_A, seed  # noqa: E402

CONV = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if args.model:
        settings.llm_model = args.model
    provider = get_provider()
    if provider is None:
        print("Set LLM_API_KEY (and optionally LLM_BASE_URL / LLM_MODEL) first.")
        return 2
    cases = json.loads((pathlib.Path(__file__).parent / "eval_cases.json").read_text(encoding="utf-8"))
    passed = total = tokens = 0
    for case in cases:
        db = FakeSupabase()
        seed(db)
        db.tables["conversations"] = [{"id": CONV, "business_id": SHOP_A}]
        business = db.tables["businesses"][0]
        history: list[dict] = []
        print(f"\n== {case['name']}")
        for t in case["turns"]:
            started = time.time()
            out = service.respond(db=db, business=business, conversation_id=CONV, customer_id=None, customer_message=t["say"], history_rows=list(history))
            reply = out.reply or f"<{out.status}: {out.failure}>"
            history += [{"sender_type": "customer", "message_text": t["say"]}, {"sender_type": "ai", "message_text": reply}]
            trace = out.intelligence.get("trace", {})
            used = trace.get("tools_called", [])
            tokens += sum(trace.get("tokens", {}).values())
            problems = []
            if out.status != "answered":
                problems.append(f"no answer ({out.failure})")
            problems += [f"expected tool {n}" for n in t.get("tools", []) if n not in used]
            low = reply.lower()
            if t.get("includes_any") and not any(s.lower() in low for s in t["includes_any"]):
                problems.append(f"expected one of {t['includes_any']}")
            problems += [f"must not contain {s!r}" for s in t.get("excludes", []) if s.lower() in low]
            total += 1
            passed += not problems
            print(f"  customer: {t['say']}\n  assistant: {reply}")
            print(f"  [{'PASS' if not problems else 'FAIL: ' + '; '.join(problems)}] tools={used} calls={trace.get('model_calls')} {int((time.time() - started) * 1000)}ms retried={trace.get('grounding_retried')}")
            if args.verbose:
                print("  trace:", json.dumps(trace))
    print(f"\n{passed}/{total} turns passed automatic checks; {tokens} tokens; model={provider.model}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
