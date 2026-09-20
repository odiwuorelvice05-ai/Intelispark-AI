# Intelispark AI

**Independent AI sales intelligence for modern commerce.**

Intelispark AI is being built as an independent AI sales employee for phone and electronics businesses. The **customer interacts with the shop through WhatsApp**. Intelispark receives the customer's message, understands it, retrieves the shop's real catalog from Supabase, checks price and stock, reasons about suitable products, and sends a grounded sales response back through WhatsApp.

The **shop owner/admin uses a separate dashboard** to manage the business. The dashboard is not the customer interface.

## Core product architecture

```text
SHOP OWNER
   │
   ▼
INTELISPARK DASHBOARD
   │
   ├── Auth / account
   ├── Business profile
   ├── Products & inventory
   ├── Product media (Supabase Storage)
   ├── Customers
   ├── Conversations
   ├── Sales pipeline
   └── AI sales intelligence
   │
   ▼
SUPABASE
   │
   ├── Business data
   ├── Product/catalog data
   ├── Customer/conversation data
   └── Uploaded business media
   │
   ▼
INTELISPARK AI BRAIN
   │
   ▼
SHOP WHATSAPP
   │
   ▼
CUSTOMER
```

## Intelligence Core

The customer-facing intelligence lives in `app/assistant/` and is described in [`docs/INTELLIGENCE.md`](docs/INTELLIGENCE.md).
A foundation model (behind a replaceable provider interface) understands the customer's message in any language, decides what
it needs, and calls tenant-bound tools that read the shop's real catalog and profile from Supabase. A grounding check refuses
any reply whose prices, stock or order claims contradict those facts, and the application owns structured conversation state.
Supabase is the only source of truth for business and product facts; the assistant never creates orders, it hands them to the owner.

```text
Customer message -> owner-authenticated tenant -> conversation + history
      -> model <-> tools (search_products / get_products / get_shop_info / escalate_to_owner)
      -> grounded reply (or a controlled "temporarily unavailable")
      -> stored in Supabase with validated conversation state
```

Requires `LLM_API_KEY` (see `.env.example`). Without it the API returns a controlled 503 for `/sales/reply`; the rest of the app is unaffected.

### Product knowledge layer

Run `database/step2_products.sql` in Supabase to add the product catalog table.

For a complete development test shop, `database/mock_shop.sql` provides temporary test data. It is not part of the final shop onboarding architecture.

The product catalog contains new/refurbished phones, prices, stock, specifications and installment availability.

## API

- `GET /` — service identity
- `GET /health` — service health
- `GET /ai/status` — whether the assistant is configured and which model
- `POST /sales/reply` — customer message → conversation context → assistant → tenant-scoped catalog tools → grounded sales response

The current `/sales/reply` endpoint is the **internal intelligence loop**. It is not yet the real WhatsApp webhook/API integration.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the local environment. Configure `LLM_API_KEY` (and optionally `LLM_BASE_URL`, `LLM_MODEL`) for the assistant. Never commit `.env` or secret credentials.

## Product roadmap

1. **Intelligence core** — model-based understanding, tenant-scoped retrieval, grounding and structured conversation state. **Foundation in place; measure it with `scripts/live_eval.py`.**
2. **Shop onboarding + dashboard** — owner account, business creation, product management, inventory, product images via Supabase Storage, and shop-scoped data access. **Next build milestone.**
3. **WhatsApp channel** — connect each shop's real WhatsApp number so customer messages enter Intelispark and responses return to the same shop/customer.
4. **Live dashboard activity** — real-time conversations, AI activity, inventory changes and sales signals.
5. **Orders and payments** — turn qualified conversations into real orders and payment workflows.
6. **Learning loop** — use anonymised real conversations and outcomes to improve prompts, tools and evaluation.

### Development principle

Build and test the system as a real multi-tenant commerce product: **WhatsApp is the customer interface, the dashboard is the shop-owner interface, Supabase Database is the structured business knowledge/data layer, Supabase Storage is the business media layer, and Intelispark AI is the intelligence layer connecting them.**

