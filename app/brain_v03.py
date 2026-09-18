"""Intelispark Brain v0.3: local understanding, memory-aware ranking and sales reasoning."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.supabase_client import supabase
from app.training_data import TRAINING_EXAMPLES


class IntelisparkEngine:
    BRANDS = ("samsung", "iphone", "apple", "xiaomi", "redmi", "tecno", "itel", "infinix", "nokia", "oppo", "vivo", "honor", "google", "oneplus")
    PRODUCT_TYPES = {
        "audio": ("woofer", "woofers", "speaker", "speakers", "sound system", "home theater", "home theatre", "subwoofer", "sub woofer", "subwoofer"),
        "phone": ("phone", "smartphone", "mobile", "handset", "iphone", "galaxy", "redmi", "tecno", "itel", "infinix", "nokia", "oppo", "vivo", "honor", "oneplus"),
        "laptop": ("laptop", "notebook", "macbook", "thinkpad", "ideapad", "pavilion", "latitude", "elitebook"),
        "tablet": ("tablet", "ipad"),
        "camera": ("camera", "dslr", "mirrorless", "canon", "nikon", "sony alpha"),
        "accessory": ("charger", "cable", "earphones", "earbuds", "headphones", "power bank", "case", "cover"),
    }
    PRIORITIES = {
        "camera": ("camera", "photo", "selfie"),
        "battery": ("battery", "power", "lasting"),
        "gaming": ("gaming", "game", "performance"),
        "storage": ("storage", "memory", "gb", "space"),
        "display": ("display", "screen", "amoled", "refresh"),
    }

    def __init__(self) -> None:
        texts = [x[0] for x in TRAINING_EXAMPLES]
        labels = [x[1] for x in TRAINING_EXAMPLES]
        self.model = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True)),
            ("classifier", LogisticRegression(max_iter=1000)),
        ])
        self.model.fit(texts, labels)
        self.training_examples = len(texts)
        self.intent_classes = sorted(set(labels))

    def predict_intent(self, message: str, context: str = "") -> tuple[str, float]:
        normalized = message.strip().lower()
        if "pickup or delivery" in context.lower() and any(x in normalized for x in ("pickup", "pick up", "collect", "delivery")):
            return "delivery", 1.0
        if normalized in {"yes", "yeah", "yep", "sure", "okay", "ok"} and "pickup or delivery" in context.lower():
            return "delivery", 1.0
        probabilities = self.model.predict_proba([message])[0]
        i = probabilities.argmax()
        return self.model.classes_[i], float(probabilities[i])

    def understand(self, message: str, context: str = "") -> dict[str, Any]:
        intent, confidence = self.predict_intent(message, context)
        current = message.lower()
        text = f"{context} {message}".lower()
        explicit_types = [k for k, words in self.PRODUCT_TYPES.items() if any(re.search(rf"\b{re.escape(w)}\b", current) for w in words)]
        product_type = explicit_types[0] if explicit_types else None
        return {
            "intent": intent,
            "confidence": round(confidence, 3),
            "entities": {
                "brands": [b for b in self.BRANDS if re.search(rf"\b{re.escape(b)}\b", current) and not re.search(rf"\b(?:not|no|without)\s+(?:the\s+)?{re.escape(b)}\b", current)],
                "product_mentions": self._product_mentions(current),
                "product_type": product_type,
                "budget_max": self._budget(current),
                "condition": self._condition(text),
                "priorities": [k for k, words in self.PRIORITIES.items() if any(w in text for w in words)],
            },
            "sales_signal": {
                "purchase_intent": intent == "purchase" or any(p in text for p in ("i'll take", "i will take", "nataka kununua", "nitachukua", "send me", "place an order")),
                "objection": "price" if any(p in text for p in ("expensive", "too much", "costly", "ghali", "pricey")) else None,
            },
        }

    def get_business_knowledge(self, business_id: str) -> dict[str, Any]:
        result = (supabase.table("businesses")
                  .select("name,phone,email,industry,description,whatsapp_number,timezone")
                  .eq("id", business_id).limit(1).execute())
        return result.data[0] if result.data else {}

    def retrieve_products(self, business_id: str, message: str, context: str = "", analysis_override: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = (supabase.table("products")
                  .select("id,name,brand,category,variant,condition,price,stock_quantity,description,specs,installment_available")
                  .eq("business_id", business_id).limit(200).execute())
        products = result.data or []
        if not products:
            return []
        analysis = analysis_override or self.understand(message, context)
        e = dict(analysis.get("entities") or {})
        analysis = dict(analysis)
        analysis["entities"] = e
        # Older preferences are inherited only for short follow-ups.
        context_analysis = self.understand(context, "") if context.strip() else {"entities": {}}
        context_e = context_analysis.get("entities", {})
        if not e.get("product_type") and self._is_short_followup(message):
            e["product_type"] = context_e.get("product_type")
        if not e.get("brands") and self._is_short_followup(message):
            e["brands"] = context_e.get("brands", [])
        if e.get("budget_max") is None and self._is_short_followup(message):
            e["budget_max"] = context_e.get("budget_max")
        if not e.get("condition") and self._is_short_followup(message):
            e["condition"] = context_e.get("condition")
        if not e.get("priorities") and self._is_short_followup(message):
            e["priorities"] = context_e.get("priorities", [])
        terms = set(self._tokens(message))
        ranked = []
        for p in products:
            text = " ".join(str(p.get(k) or "") for k in ("name", "brand", "category", "variant", "condition", "description", "specs")).lower()
            score = float(len(terms & set(self._tokens(text))))
            name, brand = str(p.get("name") or "").lower(), str(p.get("brand") or "").lower()
            price = self._number(p.get("price"))
            stock = int(p.get("stock_quantity") or 0)
            for b in e["brands"]:
                score += 6 if b in brand or b in name else -3
            if e["budget_max"] is not None:
                score += 7 if price <= e["budget_max"] else -12
            if e.get("product_type"):
                type_words = self.PRODUCT_TYPES[e["product_type"]]
                score += 12 if any(re.search(rf"\b{re.escape(w)}\b", text) for w in type_words) else -15
            if e["condition"]:
                score += 5 if e["condition"] in str(p.get("condition") or "").lower() else -4
            for priority in e["priorities"]:
                if priority in text:
                    score += 2.5
            if stock > 0 and analysis["intent"] in {"availability", "purchase", "recommendation", "comparison"}:
                score += 1.5
            for mention in e["product_mentions"]:
                score += SequenceMatcher(None, mention, name).ratio() * 3
            ranked.append((score, p))
        ranked.sort(key=lambda x: x[0], reverse=True)
        filtered = ranked
        if e.get("product_type"):
            words = self.PRODUCT_TYPES[e["product_type"]]
            typed = [(score, p) for score, p in ranked if any(re.search(rf"\b{re.escape(w)}\b", " ".join(str(p.get(k) or "") for k in ("name","brand","category","variant","description","specs")).lower()) for w in words)]
            if typed:
                filtered = typed
        if e.get("budget_max") is not None:
            within_budget = [(score, p) for score, p in filtered if self._number(p.get("price")) <= e["budget_max"]]
            if within_budget:
                filtered = within_budget
            else:
                return []
        positive = [p for score, p in filtered if score > 0]
        return [p for score, p in filtered[:5]] if not positive else positive[:5]

    def generate_reply(self, message: str, products: list[dict[str, Any]], business_name: str = "the shop", context: str = "", business: dict[str, Any] | None = None, analysis_override: dict[str, Any] | None = None) -> str:
        a = analysis_override or self.understand(message, context)
        intent, confidence, e = a["intent"], a["confidence"], a["entities"]
        business = business or {}
        description = str(business.get("description") or "").strip()
        top = products[0] if products else None
        # Generic catalog questions should return a useful catalog slice rather than
        # whichever product happened to score highest. The catalog remains the source of truth.
        normalized_message = message.lower().strip()
        catalog_overview = any(phrase in normalized_message for phrase in (
            "what do you have in stock",
            "what is in stock",
            "what's in stock",
            "what do you have",
            "what products do you have",
            "what products are available",
            "what is available",
        ))
        if catalog_overview and products:
            available = [p for p in products if int(p.get("stock_quantity") or 0) > 0]
            if available:
                return "Here's what is currently in stock:\n\n" + "\n\n".join(self._card(p) for p in available[:5])
            return "I don't see any products currently marked as in stock in the shop catalog."

        if intent == "business_info":
            if description:
                q = message.lower()
                groups = {
                    "hours": ("hour", "open", "close", "opening"),
                    "warranty": ("warranty", "guarantee"),
                    "returns": ("return", "refund", "exchange"),
                    "payment": ("payment", "pay", "mpesa", "m-pesa", "cash", "installment"),
                    "contact": ("contact", "phone number", "call"),
                }
                wanted = next((terms for key, terms in groups.items() if any(x in q for x in terms)), ())
                relevant = [x.strip() for x in re.split(r"[\n.;]+", description) if any(k in x.lower() for k in wanted)]
                if relevant:
                    return "Here is the business information from the shop profile: " + " ".join(relevant[:4])
            if any(x in message.lower() for x in ("contact", "phone number", "call")) and (business.get("phone") or business.get("whatsapp_number")):
                return f"You can contact the shop at {business.get('phone') or business.get('whatsapp_number')}."
            return "I don't see that information in the business profile yet, so I don't want to invent it. The owner can add it to Business knowledge in Settings."

        if intent == "location":
            if description:
                relevant = [x.strip() for x in re.split(r"[\n.;]+", description) if any(k in x.lower() for k in ("location","address","located","shop","branch","pickup","collect"))]
                if relevant:
                    return "Here is the shop information from its business profile: " + " ".join(relevant[:3])
            if business.get("phone") or business.get("whatsapp_number"):
                return f"I don't have the full shop address in the profile yet. You can contact the shop at {business.get('phone') or business.get('whatsapp_number')} to confirm the exact location."
            return "I don't have a full shop address in the business profile yet, so I don't want to invent one. The owner can add it to Business knowledge in Settings."
        if intent == "delivery":
            if description:
                relevant = [x.strip() for x in re.split(r"[\n.;]+", description) if any(k in x.lower() for k in ("delivery","deliver","shipping","courier","fee"))]
                if relevant:
                    return "Here is the delivery information from the business profile: " + " ".join(relevant[:3])
            return "I don't see a delivery policy or fee in the business profile yet. The shop owner can add those details to Business knowledge in Settings."
        if intent == "greeting" and not e.get("product_type") and not any(x in message.lower() for x in ("power adapter", "adapter", "charger", "cable", "earphones", "earbuds", "headphones", "power bank", "case", "cover", "woofer", "speaker", "subwoofer", "sound system", "home theater", "home theatre", "laptop", "camera", "tablet", "ipad", "macbook", "phone", "smartphone", "mobile")):
            return f"Hi! 👋 Welcome to {business_name}. What phone or device are you looking for?"
        if not products:
            requested = e.get("product_type")
            if requested:
                return f"I couldn't find a {requested} matching that request in the shop's current catalog. I don't want to invent stock that isn't there. If you'd like, give me a different model, brand or budget and I'll check again."
            return "I couldn't find a matching product in the shop catalog. Give me the model, brand or budget and I'll check again."
        if intent == "price":
            return f"{self._card(top)}\n\nWould you like me to find another option?"
        if intent == "availability":
            return f"{top.get('name', 'That product')} is {'in stock' if int(top.get('stock_quantity') or 0) > 0 else 'currently out of stock'}. {self._card(top)}"
        if intent == "delivery":
            return "Absolutely 👍 Would you prefer pickup from the shop or delivery? If you choose delivery, tell me your location and the shop can confirm the available option and fee."
        if intent == "purchase":
            if int(top.get("stock_quantity") or 0) <= 0:
                alternatives = [p for p in products[1:] if int(p.get("stock_quantity") or 0) > 0]
                return f"{top.get('name', 'That product')} is currently out of stock. I found an available alternative: {self._card(alternatives[0])}" if alternatives else f"{top.get('name', 'That product')} is currently out of stock. I can help you find another option."
            return f"Great choice 👍 {self._card(top)}\n\nWould you like pickup or delivery?"
        if intent == "recommendation":
            reason = []
            if e["budget_max"] is not None: reason.append(f"budget up to {self._money(e['budget_max'])}")
            if e["brands"]: reason.append("preferred " + "/".join(e["brands"]))
            if e["condition"]: reason.append(e["condition"] + " condition")
            if e["priorities"]: reason.append("focus on " + ", ".join(e["priorities"][:3]))
            why = ", ".join(reason) if reason else "your request"
            return f"Based on {why}, these are the strongest matches in the current catalog:\n\n" + "\n\n".join(self._card(p) for p in products[:3])
        if intent == "comparison" and len(products) >= 2:
            return "Here are the closest matches from the real catalog:\n\n" + "\n\n".join(self._card(p) for p in products[:2])
        if intent == "installment":
            available = [p for p in products if p.get("installment_available")]
            return f"Installments are marked as available for {available[0].get('name')}. {self._card(available[0])}\n\nThe shop can confirm the exact terms before checkout." if available else "I don't see installments marked as available for the matching products. The shop can confirm whether another payment plan exists."
        if e.get("priorities") and intent == "general":
            return f"I can help you choose based on {', '.join(e['priorities'])}. Tell me your budget and preferred brand."
        if a["sales_signal"].get("objection") == "price":
            cheaper = [p for p in products if self._number(p.get("price")) < self._number(top.get("price"))]
            if cheaper: return f"I understand 👍 If the price is the concern, this lower-priced option is available: {self._card(cheaper[0])}"
        if confidence < 0.40:
            return "I want to make sure I understand you correctly. Are you looking for a price, availability, recommendation, comparison or purchase?"
        return f"I found {top.get('name')} in the shop catalog. {self._card(top)}\n\nHow would you like to proceed?"

    @staticmethod
    def _is_short_followup(text: str) -> bool:
        return len(re.sub(r"[^a-z0-9]+", " ", text.lower()).split()) <= 5

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [x for x in re.sub(r"[^a-z0-9]+", " ", text.lower()).split() if len(x) > 1]

    @staticmethod
    def _budget(text: str) -> float | None:
        m = re.search(r"(?:under|below|less than|budget(?: of)?|around|about|kes|ksh)\s*([\d,]+(?:\.\d+)?)\s*(k)?", text)
        if not m: m = re.search(r"\b([\d,]+)\s*k\b", text)
        if not m: return None
        value = float(m.group(1).replace(",", ""))
        if m.group(2) == "k" or (value < 1000 and "k" in m.group(0)): value *= 1000
        return value

    @staticmethod
    def _condition(text: str) -> str | None:
        if any(x in text for x in ("refurb", "renewed", "used", "second hand", "second-hand")): return "refurbished"
        if any(x in text for x in ("brand new", "new phone", "new device", "sealed")): return "new"
        return None

    @staticmethod
    def _product_mentions(text: str) -> list[str]:
        pattern = r"\b(?:iphone|samsung|galaxy|redmi|tecno|itel|infinix|nokia|oppo|vivo|honor|oneplus)\s*[a-z0-9-]+(?:\s*[a-z0-9-]+)?\b"
        return list(dict.fromkeys(x.lower() for x in re.findall(pattern, text)))

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value)
        except (TypeError, ValueError): return 0.0

    @classmethod
    def _money(cls, value: Any) -> str:
        try: return f"KES {float(value):,.0f}"
        except (TypeError, ValueError): return "price unavailable"

    @classmethod
    def _card(cls, p: dict[str, Any]) -> str:
        stock = int(p.get("stock_quantity") or 0)
        return f"📱 {(str(p.get('brand') or '') + ' ' + str(p.get('name') or 'Product')).strip()} — {cls._money(p.get('price'))} — {p.get('condition') or 'unspecified'} — {'In stock' if stock > 0 else 'Out of stock'}"


engine = IntelisparkEngine()
