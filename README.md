# Intelispark AI

**Independent AI sales intelligence for modern commerce.**

Intelispark AI is being built as an independent AI sales employee for phone and electronics businesses. The **customer interacts with the shop through WhatsApp**. Intelispark receives the customer's message, understands it, retrieves the shop's real catalog from Supabase, checks price and stock, reasons about suitable products, and sends a grounded sales response back through WhatsApp.

The **shop owner/admin uses a separate dashboard** to manage products, stock, prices, conversations, customers and sales intelligence. The dashboard is not the customer interface.

## Core product architecture

```text
CUSTOMER
   │
   │ WhatsApp message
   ▼
SHOP WHATSAPP
   │
   ▼
INTELISPARK AI
   │
   ├── Local trained intelligence
   ├── Conversation context
   ├── Shop product catalog (Supabase)
   └── Sales reasoning
   │
   ▼
WhatsApp response
   │
   ▼
CUSTOMER

SHOP OWNER / ADMIN
   │
   ▼
INTELISPARK DASHBOARD
   ├── Products & inventory
   ├── Customers
   ├── Conversations
   ├── Sales pipeline
   └── AI sales intelligence
```

## Step 2 — Intelligence Core

The project contains a local supervised machine-learning model trained on a version-controlled commerce dataset. It requires **no OpenAI or other external AI API key**.

### Intelligence pipeline

```text
Customer WhatsApp message
      ↓
Local trained intent model
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
- Model trains locally when the application starts
- Product facts are grounded in the shop's Supabase catalog
- Conversation history is used as context
- No external generative AI API is required

### Product knowledge layer

Run `database/step2_products.sql` in Supabase to add the product catalog table.

For a complete development test shop, run `database/mock_shop.sql` after the product table exists.

The mock catalog contains new/refurbished phones, prices, stock, specifications and installment availability. It represents a **real test business record and real database data**, not a hard-coded chatbot demo.

## API

- `GET /` — service identity
- `GET /health` — health and intelligence status
- `GET /ai/status` — model/training status
- `POST /sales/reply` — customer message → conversation context → Intelispark intelligence → real product retrieval → grounded sales response

The current `/sales/reply` endpoint is the internal intelligence loop. The next integration layer will receive customer messages from the test shop's WhatsApp number and return the generated response to WhatsApp.

Example request:

```json
{
  "business_id": "11111111-1111-1111-1111-111111111111",
  "customer_id": "31111111-1111-1111-1111-111111111111",
  "customer_message": "How much is the Samsung A15 and is it in stock?"
}
```

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the local environment. Never commit `.env` or secret credentials.

## Product roadmap

1. **Intelligence core** — local understanding, retrieval, reasoning and conversation context.
2. **WhatsApp channel** — connect a real test shop WhatsApp number so real customer messages enter Intelispark and responses return to WhatsApp.
3. **Shop dashboard** — owner/admin workspace for products, inventory, customers, conversations and sales intelligence.
4. **Orders and payments** — turn qualified conversations into real orders and payment workflows.
5. **Learning loop** — use anonymised real conversations and outcomes to improve the local intelligence system.

### Development principle

Build and test the system as a real commerce product: **WhatsApp is the customer interface, the dashboard is the shop-owner interface, Supabase is the business knowledge/data layer, and Intelispark AI is the intelligence layer connecting them.**
