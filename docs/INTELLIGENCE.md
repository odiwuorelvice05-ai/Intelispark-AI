# Intelispark intelligence layer

One architecture, in `app/assistant/`. A foundation model understands the customer and decides what it
needs; tenant-bound tools fetch authoritative facts from Supabase; a grounding check refuses replies that
contradict those facts; the application (not the model) owns conversation state.

## Flow

```
POST /sales/reply  (owner auth + business ownership check: the tenant is established here)
  -> conversation/customer resolved for that business, recent history read, customer message stored
  -> assistant.respond(business=<authenticated business>)
       repository bound to that one business id            (no tool or model input can change it)
       system prompt = rules + coarse catalog shape + structured state (ids/names, never prices)
       Agent loop:  model -> data tools (validated, tenant-scoped) -> ... -> reply_to_customer
       grounding check -> one retry with the reasons -> answer | controlled failure
       validated state update stored in conversations.agent_state
  -> answer stored in `messages`; response shape the dashboard already reads
  -> any failure => HTTP 503 with a safe message, customer message kept, no fake reply stored
```

## Components

| Module | Job |
|---|---|
| `provider.py` | `LLMProvider.chat` boundary; one OpenAI-compatible implementation (Mistral, OpenAI, Groq, Gemini-compat, vLLM, Ollama...). Vendor change = env vars. |
| `repository.py` | Only place that touches the database. Bound to one business id; whitelisted columns (no cost/owner fields); `DataUnavailable` on outage. |
| `catalog.py` | Deterministic search over one shop's rows: exact/partial match reporting, typo tolerance for words (never model codes), sold-out and over-budget items reported instead of hidden. No customer phrases. |
| `tools.py` | Four capabilities: `search_products`, `get_products`, `get_shop_info`, `escalate_to_owner`. Everything returned is recorded as evidence. |
| `agent.py` | Bounded loop (model calls, tool calls, tokens, wall clock); `tool_choice=required`; final `reply_to_customer` carries structured claims and a state update. |
| `grounding.py` | Narrow deterministic backstop: amounts, stock counts, declared availability/price claims, order/reservation claims. |
| `state.py` | Structured memory: focus product ids, quantity, budget, fulfilment, delivery place. Validated against the catalog; never stores prices or stock. |
| `service.py` | `respond()`: fixes the tenant, runs the agent, applies state, never raises. |

## Guarantees (each has tests)

* **Tenant isolation.** Repository is bound to the authenticated business. Tool schemas have no tenant argument; one the model invents is dropped and logged. Product ids from another shop resolve to "not found". State reads/writes filter on business id. History comes from a conversation resolved for that business.
* **Database is the source of truth.** Prices/stock/specs/policies exist only in tool results fetched this turn; state holds ids and customer wishes, not facts.
* **No false claims.** Amounts must match returned prices (or simple multiples/sums, shop-stated figures, or the recorded customer budget). A number only the customer wrote is not accepted. Declared availability/price claims must match the record. "Order/reservation placed" is always rejected: the application cannot create either, so purchases go to `escalate_to_owner`.
* **Graceful failure.** Provider error/timeout, malformed output, grounding failure, database outage or an unexpected exception -> 503 `The assistant is temporarily unavailable...`; the dashboard, products and auth are unaffected. Transient provider errors are retried once inside the time budget.
* **No secrets in logs or responses.** The provider scrubs the key from errors; logs carry ids, counts, tool names and latency, not message bodies.

## Configuration

| Variable | Required | Meaning |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | yes | unchanged |
| `LLM_API_KEY` | yes for answers | key for the model API (`MISTRAL_API_KEY` still accepted as a fallback) |
| `LLM_BASE_URL` | no | default `https://api.mistral.ai/v1` |
| `LLM_MODEL` | no | default `mistral-small-latest` |
| `ASSISTANT_DEADLINE_S` | no | whole-turn budget, default 7 (keep below the Vercel function timeout) |
| `ASSISTANT_HISTORY_MESSAGES` | no | prior messages shown to the model, default 10 |

## Database

No required changes. Optional, additive: `database/proposed/assistant_state.sql` adds `conversations.agent_state`
(durable memory) and an `escalations` table (owner handoffs). Without them memory falls back to chat history and
the assistant tells customers the shop's number instead of promising a handoff.

## Verifying with a real model

```
pip install -r requirements-dev.txt
pytest                                                    # application tests, no key needed
LLM_API_KEY=... python -m scripts.live_eval --verbose     # real-model conversations through the real path
LLM_API_KEY=... python -m scripts.live_eval --model mistral-medium-latest
```

The unit/API tests use a scripted model: they prove the application is safe and correct given what a model does,
not that a model understands customers. Run the live eval and read the transcripts before enabling for real customers.

## Known limits

1. Real-model quality is unmeasured until the live eval is run with your key.
2. Policy statements (delivery zones, hours, warranty) come from the owner's free-text profile and cannot be verified
   by code beyond amounts; structured policy fields would be more reliable.
3. Catalog search loads up to 500 products per turn in memory; beyond that use database-side search (pg_trgm/embeddings).
4. Each turn is 2-3 sequential model calls; measure tokens with the live eval before setting plan prices.
5. `/sales/reply` is the owner's simulator. A real WhatsApp webhook must resolve the tenant from the connected number, never from message content.
6. Orders/payments do not exist; the assistant hands them to the owner. Add a deterministic `create_order` tool with its own tests before allowing any "order placed" wording.
