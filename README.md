# Intelispark AI

**AI sales intelligence for modern commerce.**

Intelispark AI is an independent, database-driven sales intelligence platform designed to help businesses understand customer conversations, use their real business data, recommend products and move conversations toward purchases.

## Current foundation

- FastAPI backend
- Supabase database integration
- Customer and conversation storage
- Independent rule-based sales intelligence layer
- Static Intelispark AI frontend
- No OpenAI API dependency
- Environment variables for Supabase credentials

## Product direction

```text
Customer message
      ↓
Understand intent
      ↓
Retrieve business data
      ↓
Match products / stock / price
      ↓
Sales reasoning
      ↓
Helpful response
      ↓
Conversation memory
      ↓
Order / payment
```

## Next build

1. Add product and inventory data models.
2. Build the product retrieval and matching layer.
3. Replace manual `product_context` with database-backed intelligence.
4. Build the real shop dashboard.
5. Add orders and payment workflow.
6. Connect WhatsApp after the internal sales loop works reliably.

## Run locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the API:

```bash
uvicorn app.main:app --reload
```

Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the local environment. Never commit `.env` or secret credentials.
