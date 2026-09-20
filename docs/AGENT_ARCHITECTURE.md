# Intelispark agent (Phase 1)

## Gap analysis: what existed vs. the target

| Target | Before this change | Phase 1 |
|---|---|---|
| Model does the language understanding | TF-IDF/LogReg classifier on hand-written examples + regex brand/type/budget lists (`brain_v03.py`); Mistral only produced "guidance" JSON that was merged back into that pipeline | Foundation model reads the raw message and chooses tools/arguments |
| Model chooses tools | none; fixed pipeline | native function calling, 8 tools + a structured final tool |
| Retrieval on demand | whole catalog (200 rows) serialized into every Mistral call | `search_products` returns only matching rows |
| Provider-neutral | `mistral_assist.py` hard-wired to Mistral | `AIProvider` interface; Mistral is one implementation |
| Evidence over eloquence | database facts rendered by Python templates | model writes the reply; `grounding.py` rejects any price/stock/order claim tools did not support |
| Conversation memory | last 8 messages as text | history + structured state (`save_conversation_state`), durable once the proposed column exists |
| Escalation | none | `escalate_to_owner` (durable once the proposed table exists; otherwise the agent gives the shop's phone number) |
| Evaluation | none | 31 unseen-wording cases scored on tool choice/args/retrieval/decision/groundedness |
| Orders | none | deliberately absent: the agent hands purchases to the owner and can never claim an order exists |

## Flow

```
customer message -> POST /sales/reply (owner auth + business ownership check, unchanged)
  -> run_agent_turn(business=<authenticated business>)          # tenant fixed here
       AgentRunner: model <-> tools (validated, tenant-scoped) ... -> respond_to_customer
       grounding check -> (one retry with the violations) -> answer
  -> answer saved to `messages`, same response shape the dashboard already reads
  -> any failure (no key, provider error, timeout, grounding failed twice) => legacy engine answers as before
```

`INTELISPARK_AGENT` defaults to `off`: deploying this code changes nothing until you set it to `on`.

## Safety properties (each has a test)

* The model never supplies a tenant. Tool schemas have no business id; a model-invented `business_id`/`owner_id` is dropped and logged (`security_events`). Every query is bound to the authenticated business (`repository.py`).
* No database credential ever reaches the model; it only sees tool JSON.
* Money amounts, stock counts, cited product ids and "order placed" claims in the final reply must match tool evidence from the same turn, or the reply is rejected and retried once, then discarded in favour of the legacy engine.
* Purchases are escalated to the owner; success is never claimed.
* Bounded: model calls (6), tool calls (8), tokens (24k), wall clock (`AGENT_DEADLINE_S`, default 20 s).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `INTELISPARK_AGENT` | `off` | `on` enables the agent |
| `AI_PROVIDER` | `mistral` | provider factory key |
| `MISTRAL_API_KEY` | – | required for the agent |
| `AGENT_MODEL` | `MISTRAL_MODEL` or `mistral-small-latest` | change to compare models |
| `AGENT_DEADLINE_S` | `20` | total time budget per customer message |
| `AGENT_HISTORY_MESSAGES` | `12` | chat history given to the model |

## Verifying with a real model (not possible in the build sandbox)

```
pip install -r requirements-dev.txt
MISTRAL_API_KEY=... python -m scripts.agent_demo                 # the brief's conversation, every decision printed
MISTRAL_API_KEY=... python -m tests.agent.eval_live --verbose --out report.json
MISTRAL_API_KEY=... python -m tests.agent.eval_live --model mistral-medium-latest   # compare models
pytest                                                            # machinery tests, no key needed
```

## Known limits / next steps

1. **Real-model quality is unmeasured.** Run the two commands above and read the transcripts before enabling for customers.
2. **Customer-stated numbers are allowed in replies** (so "within your KES 50,000 budget" passes). A model could therefore echo a customer's discount request as if agreed. The prompt forbids it and an eval case probes it; the robust fix is to make the final tool declare `quoted_prices` and verify each against the database.
3. **Vercel duration**: each customer message can take several sequential model calls. Check the function `maxDuration` for your plan (`vercel.json` untouched here) or lower `AGENT_DEADLINE_S`; on timeout the legacy engine answers.
4. **Durable memory/escalation** need `database/proposed/agent_phase2.sql` (not applied). Until then state lives only in chat history and escalations are not saved.
5. **Shop policies** are read from the owner's free-text profile. Structured policies (delivery zones, fees) would be more reliable, and embeddings only become worthwhile once shops write long knowledge bases.
6. **Orders** (`create_order`) need the Phase 3 schema and a deterministic state machine.
7. **Cost**: roughly 2-4 model calls of a few thousand tokens per message; measure with the eval's token totals before pricing plans.
8. The dashboard inspector shows the mapped intent/entities; the full tool trace is in `intelligence.agent` of the API response (UI unchanged).
