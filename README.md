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

The tool-calling agent uses **Google Gemini** for natural-language understanding, tool selection, and grounded reply drafting. Gemini is not the source of truth: Supabase remains authoritative for business and product facts, and every model-proposed tool call is validated and tenant-scoped before execution.

Configure `GEMINI_API_KEY` and `GEMINI_MODEL` to enable the agent. API access may be available on Google's free tier subject to current eligibility and usage limits. If the provider is unavailable or a reply fails grounding checks, the existing safe handoff path remains in place.

### Intelligence pipeline

```text
Customer WhatsApp message
      ↓
Local trained intent model
      ↓
Gemini tool-calling agent
      ↓
Conversation context
      ↓
Product/catalog retrieval from Supabase
      ↓
Product matching and ranking
      ↓
Stock + price + condition reasoning
      ↓
Recommendation / comparison / purchase strategy
      ↓
Grounded sales response
      ↓
Conversation stored in Supabase
```

### Current model

- TF-IDF text representation
- Logistic Regression intent classifier
- Domain training dataset focused on electronics commerce and Kenyan/WhatsApp language
- Intent classes: greeting, price, availability, purchase, recommendation, comparison, installment, location, delivery, appointment, thanks, general
- The lightweight local classifier remains available as a fallback component
- The tool-calling sales agent uses Gemini when `GEMINI_API_KEY` is configured
- Product facts are grounded in the shop's Supabase catalog; model outputs never replace database facts
- Conversation history and structured state are used as context
- If Gemini is unavailable or its reply fails grounding checks, the endpoint uses the existing safe handoff path

### Product knowledge layer

Run `database/step2_products.sql` in Supabase to add the product catalog table.

For a complete development test shop, `database/mock_shop.sql` provides temporary test data. It is not part of the final shop onboarding architecture.

The product catalog contains new/refurbished phones, prices, stock, specifications and installment availability.

## API

- `GET /` — service identity
- `GET /health` — health and intelligence status
- `GET /ai/status` — model/training status
- `POST /sales/reply` — customer message → conversation context → Intelispark intelligence → real product retrieval → grounded sales response

The current `/sales/reply` endpoint is the **internal intelligence loop**. It is not yet the real WhatsApp webhook/API integration.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the local environment. Configure `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`). Never commit `.env` or secret credentials.

## Product roadmap

1. **Intelligence core** — local understanding, retrieval, reasoning and conversation context. **Current foundation complete.**
2. **Shop onboarding + dashboard** — owner account, business creation, product management, inventory, product images via Supabase Storage, and shop-scoped data access. **Next build milestone.**
3. **WhatsApp channel** — connect each shop's real WhatsApp number so customer messages enter Intelispark and responses return to the same shop/customer.
4. **Live dashboard activity** — real-time conversations, AI activity, inventory changes and sales signals.
5. **Orders and payments** — turn qualified conversations into real orders and payment workflows.
6. **Learning loop** — use anonymised real conversations and outcomes to improve the local intelligence system.

### Development principle

Build and test the system as a real multi-tenant commerce product: **WhatsApp is the customer interface, the dashboard is the shop-owner interface, Supabase Database is the structured business knowledge/data layer, Supabase Storage is the business media layer, and Intelispark AI is the intelligence layer connecting them.**


<!-- Production rollback marker: preserved last known-good application code. -->
