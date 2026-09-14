"""Compatibility entry point for Intelispark's sales engine.

The real intelligence now lives in app.intelligence and is database-backed.
"""

from app.intelligence import engine


def detect_intent(message: str) -> str:
    """Return the intent predicted by Intelispark's trained local model."""
    return engine.predict_intent(message)[0]


def generate_sales_reply(customer_message: str, product_context: str = "") -> str:
    """Legacy wrapper kept for compatibility with older integrations.

    New production code should call app.intelligence.engine and provide a
    business_id so product facts can come directly from Supabase.
    """
    products = []
    if product_context.strip():
        return engine.generate_reply(customer_message, products, "the shop")
    return engine.generate_reply(customer_message, products, "the shop")
