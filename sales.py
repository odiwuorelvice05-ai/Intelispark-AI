import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


SYSTEM_PROMPT = """
You are Forge AI, a professional WhatsApp sales assistant for
phone and electronics shops.

Your job is to help turn customer conversations into sales.

Rules:
- Be friendly, natural, concise, and persuasive.
- Never invent a product, price, specification, or stock status.
- If product information is provided, use only that information.
- If important information is missing, ask the customer a useful question.
- Do not sound robotic.
- Do not pressure the customer.
- Keep WhatsApp replies short and easy to read.
"""


def generate_sales_reply(
    customer_message: str,
    product_context: str = "",
) -> str:
    """
    Generate a sales reply to a customer's message.
    """

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=api_key)

    context = product_context.strip()

    prompt = f"""
Customer message:
{customer_message}

Available product information:
{context if context else "No product information has been provided."}

Write the best possible WhatsApp sales response.
"""

    response = client.responses.create(
        model="gpt-5.6-luna",
        instructions=SYSTEM_PROMPT,
        input=prompt,
    )

    return response.output_text.strip()
