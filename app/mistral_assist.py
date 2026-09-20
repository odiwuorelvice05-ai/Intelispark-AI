"""Optional Mistral language layer for Intelispark.

Mistral is the primary language-understanding layer, not the source of truth.
It interprets customer language and conversation; Intelispark performs grounded
retrieval and response generation from Supabase.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    from mistralai.client import Mistral
except ImportError:  # pragma: no cover
    Mistral = None


def _describe_error(exc: Exception) -> str:
    """One-line, log-safe summary of a provider failure.

    Never includes the request payload, the API key or any token. Redaction runs on the full text
    BEFORE truncation so a key cannot survive as a fragment.
    """
    text = re.sub(r"\s+", " ", f"{exc} {getattr(exc, 'body', '') or ''}")
    key = os.getenv("MISTRAL_API_KEY", "").strip()
    if key:
        text = text.replace(key, "[redacted]")
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+){0,2}", "[jwt]", text)
    return (f"{type(exc).__name__} status={getattr(exc, 'status_code', None)} "
            f"reasoning_effort_in_error={'reasoning_effort' in text} detail={text[:200]!r}")


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

        # Keep truly standalone greetings and exact high-confidence business
        # lookups local. Do not skip Mistral merely because the cheap classifier
        # called something a greeting: brand/product questions such as
        # "is Vitron a good brand?" still need semantic interpretation.
        lower = text.lower()
        has_catalog_signal = (
            bool(entities.get("product_type"))
            or bool(entities.get("brands"))
            or any(word in lower for word in (
                "price", "cost", "how much", "available", "in stock",
                "buy", "need", "looking for", "good brand", "worth",
                "recommend", "compare", "cheaper", "another", "what else",
                "woofer", "speaker", "charger", "mouse", "keyboard",
            ))
        )
        if confidence >= 0.88 and intent in {
            "greeting", "location", "delivery", "business_info"
        } and not has_catalog_signal:
            return False

        # Catalog and conversational requests benefit from semantic understanding,
        # especially short follow-ups such as "what else?".
        return True

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
            for p in products[:200]
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
catalog request, say so. For broad requests such as "what do you have", "what is for sale", or "what is in stock", set catalog_scope to "all". For "what else", "another one", or cheaper alternatives, set catalog_scope to "alternatives".

Return ONLY JSON with:
{
  "intent": "greeting|price|availability|purchase|recommendation|comparison|installment|location|delivery|business_info|identity|owner_contact|general|thanks",
  "catalog_query": "short semantic product search phrase or empty string",
  "catalog_scope": "all|filtered|alternatives|none",
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
            "catalog": catalog,
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
        except Exception as exc:
            # Mistral must never take Intelispark down. Local intelligence remains
            # the fallback whenever the API is unavailable, rate-limited, or malformed.
            try:  # logging must never be able to break the request
                print(f"[Intelispark assist] guidance unavailable: model={self.model} {_describe_error(exc)}")
            except Exception:
                pass
            return None


mistral_assist = MistralAssist()
