"""Intelispark's independent sales intelligence core.

No external AI API is used. A local supervised classifier is trained from the
version-controlled domain dataset, while product facts come only from Supabase.
"""

from __future__ import annotations

from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.training_data import TRAINING_EXAMPLES
from app.supabase_client import supabase


class IntelisparkEngine:
    """Train and run the local commerce-intelligence model."""

    def __init__(self) -> None:
        texts = [item[0] for item in TRAINING_EXAMPLES]
        labels = [item[1] for item in TRAINING_EXAMPLES]
        self.model = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True)),
            ("classifier", LogisticRegression(max_iter=1000)),
        ])
        self.model.fit(texts, labels)
        self.training_examples = len(texts)
        self.intent_classes = sorted(set(labels))

    def predict_intent(self, message: str) -> tuple[str, float]:
        probabilities = self.model.predict_proba([message])[0]
        best_index = probabilities.argmax()
        label = self.model.classes_[best_index]
        return label, float(probabilities[best_index])

    def retrieve_products(self, business_id: str, message: str) -> list[dict[str, Any]]:
        """Retrieve real products for the business; never invent product facts."""
        result = (
            supabase.table("products")
            .select(
                "id,name,brand,category,variant,condition,price,stock_quantity,"
                "description,specs,installment_available"
            )
            .eq("business_id", business_id)
            .limit(100)
            .execute()
        )
        products = result.data or []
        if not products:
            return []

        query_terms = set(self._tokens(message))
        scored: list[tuple[float, dict[str, Any]]] = []

        for product in products:
            searchable = " ".join(
                str(product.get(field) or "")
                for field in ("name", "brand", "category", "variant", "condition", "description")
            ).lower()
            product_terms = set(self._tokens(searchable))
            overlap = len(query_terms & product_terms)
            exact_name_bonus = 3 if str(product.get("name", "")).lower() in message.lower() else 0
            score = overlap + exact_name_bonus
            scored.append((score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        matches = [product for score, product in scored if score > 0]
        return matches[:5] if matches else products[:5]

    @staticmethod
    def _tokens(text: str) -> list[str]:
        cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
        return [token for token in cleaned.split() if len(token) > 1]

    @staticmethod
    def _money(value: Any) -> str:
        try:
            return f"KES {float(value):,.0f}"
        except (TypeError, ValueError):
            return "price unavailable"

    def generate_reply(
        self,
        message: str,
        products: list[dict[str, Any]],
        business_name: str = "the shop",
    ) -> str:
        intent, confidence = self.predict_intent(message)
        top = products[0] if products else None

        if intent == "greeting":
            return f"Hi! 👋 Welcome to {business_name}. What phone or device are you looking for?"

        if not products:
            if intent in {"price", "availability", "recommendation", "comparison"}:
                return "I can help with that 👍 Tell me the exact phone or budget you have in mind, and I'll check the shop's product data."
            if intent == "purchase":
                return "Absolutely 👍 Tell me the product you'd like to order and I'll check availability first."
            if intent == "location":
                return "I can help with the shop details. Which location information do you need?"
            if intent == "delivery":
                return "Yes, I can help with delivery. Tell me your location so the shop can confirm the delivery option."
            if intent == "installment":
                return "I can check installment options once you tell me which product you're interested in."
            if intent == "thanks":
                return "You're welcome! 😊"
            return "I'd be happy to help. Tell me what phone or device you're interested in."

        if intent == "price":
            return self._product_card(top) + "\n\nWould you like me to check another option?"

        if intent == "availability":
            stock = int(top.get("stock_quantity") or 0)
            status = "in stock" if stock > 0 else "currently out of stock"
            return f"{top.get('name', 'That product')} is {status}. " + self._product_card(top)

        if intent == "purchase":
            stock = int(top.get("stock_quantity") or 0)
            if stock <= 0:
                return f"{top.get('name', 'That product')} is currently out of stock. I can help you find a similar available option."
            return f"Great choice 👍 {self._product_card(top)}\n\nWould you like to proceed with the order?"

        if intent == "recommendation":
            choices = "\n".join(self._product_card(item) for item in products[:3])
            return f"Based on the shop's current catalog, here are good options:\n\n{choices}\n\nTell me your priority (camera, battery, gaming, storage or budget) and I'll narrow it down."

        if intent == "comparison" and len(products) >= 2:
            return "Here are the closest matches I found:\n\n" + "\n\n".join(self._product_card(item) for item in products[:2])

        if intent == "installment":
            available = [p for p in products if p.get("installment_available")]
            if available:
                return f"Installment payment is marked as available for {available[0].get('name')}. {self._product_card(available[0])}\n\nThe shop can confirm the exact installment terms before checkout."
            return "I don't see an installment option marked for the matching products. The shop can confirm whether another payment plan is available."

        if intent == "delivery":
            return f"I found {top.get('name')} in the catalog. {self._product_card(top)}\n\nTell me your delivery location and I'll help with the next step."

        if intent == "thanks":
            return "You're welcome! 😊 Let me know if you'd like another recommendation."

        if confidence < 0.40:
            return "I want to make sure I understand you correctly. Are you looking for a price, availability, recommendation, comparison or purchase?"

        return f"I found {top.get('name')} in the shop catalog. {self._product_card(top)}\n\nHow would you like to proceed?"

    def _product_card(self, product: dict[str, Any]) -> str:
        stock = int(product.get("stock_quantity") or 0)
        condition = product.get("condition") or "unspecified condition"
        brand = product.get("brand") or ""
        name = product.get("name") or "Product"
        prefix = f"{brand} {name}".strip()
        return f"📱 {prefix} — {self._money(product.get('price'))} — {condition} — {'In stock' if stock > 0 else 'Out of stock'}"


engine = IntelisparkEngine()
