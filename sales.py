   from app.supabase_client import supabase


def detect_intent(message: str) -> str:
    text = message.lower().strip()

    if any(word in text for word in [
        "hello", "hi", "hey", "habari", "mambo",
        "good morning", "good afternoon", "good evening"
    ]):
        return "greeting"

    if any(word in text for word in [
        "price", "cost", "how much", "bei", "ngapi",
        "charges", "expensive", "cheap"
    ]):
        return "price"

    if any(word in text for word in [
        "available", "availability", "stock", "in stock",
        "ipo", "mna"
    ]):
        return "availability"

    if any(word in text for word in [
        "buy", "purchase", "order", "nunua", "nataka",
        "take it", "i'll take", "i want it"
    ]):
        return "purchase"

    if any(word in text for word in [
        "appointment", "book", "booking", "schedule",
        "meeting", "visit"
    ]):
        return "appointment"

    if any(word in text for word in [
        "where", "location", "address", "located", "wapi"
    ]):
        return "location"

    if any(word in text for word in [
        "thank", "thanks", "asante"
    ]):
        return "thanks"

    return "general"


def generate_sales_reply(
    customer_message: str,
    product_context: str = "",
) -> str:
    """
    Forge AI's independent sales intelligence engine.
    No external AI API is required.
    """

    message = customer_message.strip()
    context = product_context.strip()

    if not message:
        return "Hi! 👋 How can I help you today?"

    intent = detect_intent(message)

    if intent == "greeting":
        return "Hi! 👋 Welcome to Forge AI. How can I help you today?"

    if intent == "price":
        if context:
            return (
                f"Sure 👍 Here is the information I have:\n\n"
                f"{context}\n\n"
                "Would you like to proceed?"
            )

        return (
            "Sure 👍 Which product are you asking about? "
            "Send me the product name and I'll help you."
        )

    if intent == "availability":
        if context:
            return f"Let me help with that 👍\n\n{context}"

        return "Sure 👍 Which product would you like to check?"

    if intent == "purchase":
        if context:
            return (
                f"Great choice 👍\n\n"
                f"{context}\n\n"
                "Would you like to place the order?"
            )

        return (
            "Great 👍 Tell me the product you'd like to order "
            "and I'll help you with the next step."
        )

    if intent == "appointment":
        return (
            "Absolutely 👍 What day and time would work best "
            "for your appointment?"
        )

    if intent == "location":
        return "Sure 👍 What location information would you like?"

    if intent == "thanks":
        return "You're welcome! 😊 Let me know if you need anything else."

    return (
        "I'd be happy to help 👍 "
        "Could you tell me a little more about what you need?"
    )
