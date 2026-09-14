# Intelispark AI

**Independent AI sales intelligence for modern commerce.**

Intelispark AI is being built as an independent sales employee for phone and electronics businesses. It learns how customers ask for products, retrieves the shop's real catalog from Supabase, checks price and stock, and uses sales reasoning to move the conversation toward a purchase.

## Step 2 — Intelligence Core

The project now contains a local supervised machine-learning model trained on a version-controlled commerce dataset. It requires **no OpenAI or other external AI API key**.

### Intelligence pipeline

```text
Customer message
      ↓
Local trained intent model
      ↓
Product/catalog retrieval from Supabase
      ↓
Product matching
      ↓
Stock + price + condition reasoning
      ↓
Recommendation / comparison / purchase strategy
      ↓
Sales response
      ↓
Conversation stored in Supabase
```

### Current model

- TF-IDF text representation
- Logistic Regression intent classifier
- Domain training dataset focused on electronics commerce and Kenyan/WhatsApp language
- Intent classes: greeting, price, availability, purchase, recommendation, comparison, installment, location, delivery, appointment, thanks, general
- Model trains locally when the application starts
- Product facts are never invented: they come from the shop's Supabase catalog

### Product knowledge layer

Run `database/step2_products.sql` in Supabase to add the product catalog table.

For a complete development test shop, then run `database/mock_shop.sql`.

The mock catalog contains new/refurbished phones, prices, stock, specifications and installment availability.

## API

- `GET /` — service identity
- `GET /health` — health and intelligence status
- `GET /ai/status` — model/training status
- `POST /sales/reply` — full customer → intelligence → product retrieval → sales response loop

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

## Next

1. Expand the training dataset using real anonymised shop conversations.
2. Add stronger entity extraction for model names, budgets and specifications.
3. Add product comparison and recommendation scoring.
4. Build the real shop dashboard.
5. Add orders and payment workflow.
6. Connect WhatsApp after the internal sales loop is reliable.
