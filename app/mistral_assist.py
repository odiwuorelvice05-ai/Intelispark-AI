"""Optional Mistral language layer for Intelispark.

Mistral is deliberately a supplement, not the source of truth. It is only
called for ambiguous/low-confidence messages and returns structured guidance.
Supabase and Intelispark's local retrieval engine remain authoritative.
"""
from __future__ import annotations

import json
import os
from typing import Any

try:
    from mistralai.client import Mistral
except ImportError:  # pragma: no cover
    Mistral = None


class MistralAssist:
    def __init__(self) -> None:
        self.api_key = os.getenv("MISTRAL_API_KEY", "").strip()
        self.model = os.getenv("MISTRAL_MODEL", "mistral-small-latest").strip()
        self.enabled = bool(self.api_key and Mistral)
        self.client = Mistral(api_key=self.api_key) if self.enabled else None

    def should_call(self, analysis: dict[str, Any], message: str) -> bool:
        if not self.enabled:
            return False
        intent = analysis.get("intent")
        confidence = float(analysis.get("confidence") or 0)
        entities = analysis.get("entities") or {}
        text = message.strip()

        # Preserve tokens: straightforward, high-confidence catalog questions
        # stay entirely inside Intelispark's local engine.
        if confidence >= 0.82 and intent in {
            "price", "availability", "purchase", "installment",
            "location", "delivery", "business_info", "greeting",
        } and (
            entities.get("product_type")
            or entities.get("product_mentions")
            or intent in {"location", "delivery", "business_info", "greeting"}
        ):
            return False

        # The model earns its tokens when language is ambiguous, contextual,
        # conversational, or the local classifier is uncertain.
        return confidence < 0.72 or len(text.split()) <= 5 or intent in {"general", "thanks"}

    def understand(
        self,
        message: str,
        context: str,
        business: dict[str, Any],
        products: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        catalog = [
            {
                "name": p.get("name"),
                "brand": p.get("brand"),
                "category": p.get("category"),
                "variant": p.get("variant"),
                "price": p.get("price"),
                "stock_quantity": p.get("stock_quantity"),
                "condition": p.get("condition"),
                "description": p.get("description"),
                "specs": p.get("specs"),
            }
            for p in products[:12]
        ]
        profile = {
            "name": business.get("name"),
            "phone": business.get("phone"),
            "whatsapp_number": business.get("whatsapp_number"),
            "description": business.get("description"),
        }

        system = """You are the language-understanding layer inside Intelispark AI.
Do not invent products, prices, stock, policies, locations, owners, or other
business facts. Supplied catalog/profile data is the only source of truth.
Your job is to understand the customer's meaning and return JSON guidance for
another deterministic engine.

Resolve pronouns and references from the conversation. Understand natural
English, Kenyan English, Swahili and Sheng. Recognize paraphrases you have
never seen before. If the customer asks for a product, create a concise
catalog_query that describes what should be searched. If the message is not a
catalog request, say so.

Return ONLY JSON with:
{
  "intent": "greeting|price|availability|purchase|recommendation|comparison|installment|location|delivery|business_info|identity|owner_contact|general|thanks",
  "catalog_query": "short semantic product search phrase or empty string",
  "product_type": "phone|laptop|tablet|camera|audio|accessory|other|null",
  "budget_max": number|null,
  "brand": "brand or empty string",
  "needs_catalog": true|false,
  "direct_reply": "only for identity/owner_contact/general questions that can be answered safely from supplied data, otherwise empty",
  "confidence": number,
  "exclude_names": ["exact product names to exclude for alternatives/what-else requests"]
}

For 'what else', 'another one', 'anything cheaper', 'that's expensive', and
similar follow-ups, use the conversation to infer what product/category the
customer means. Do not fabricate missing facts. For 'what else' or 'another one', identify products already shown in the conversation and put their exact names in exclude_names. For 'anything cheaper' or a price objection, identify the referenced product and exclude it from alternatives."""
        user = {
            "customer_message": message,
            "conversation": context[-6000:],
            "business_profile": profile,
            "currently_retrieved_products": catalog,
        }

        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=350,
                reasoning_effort="low",
            )
            raw = response.choices[0].message.content
            if isinstance(raw, list):
                raw = "".join(getattr(part, "text", "") for part in raw)
            data = json.loads(raw or "{}")
            return data if isinstance(data, dict) else None
        except Exception:
            # Mistral must never take Intelispark down. Local intelligence remains
            # the fallback whenever the API is unavailable, rate-limited, or malformed.
            return None


mistral_assist = MistralAssist()
