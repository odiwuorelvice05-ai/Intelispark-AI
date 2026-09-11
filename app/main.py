from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.sales import generate_sales_reply
from app.supabase_client import supabase


app = FastAPI(
    title=settings.app_name,
    description="Independent AI sales automation platform",
    version="0.1.0",
)


class SalesRequest(BaseModel):
    business_id: str
    customer_id: str
    customer_message: str
    product_context: str = ""


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "status": "online",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "environment": settings.environment,
    }


@app.post("/sales/reply")
def sales_reply(request: SalesRequest):
    try:
        # 1. Confirm the business exists.
        business_result = (
            supabase
            .table("businesses")
            .select("id, name")
            .eq("id", request.business_id)
            .limit(1)
            .execute()
        )

        if not business_result.data:
            raise HTTPException(
                status_code=404,
                detail="Business not found.",
            )

        # 2. Confirm the customer belongs to this business.
        customer_result = (
            supabase
            .table("customers")
            .select("id, name, phone")
            .eq("id", request.customer_id)
            .eq("business_id", request.business_id)
            .limit(1)
            .execute()
        )

        if not customer_result.data:
            raise HTTPException(
                status_code=404,
                detail="Customer not found for this business.",
            )

        # 3. Find an existing open WhatsApp conversation.
        conversation_result = (
            supabase
            .table("conversations")
            .select("id")
            .eq("business_id", request.business_id)
            .eq("customer_id", request.customer_id)
            .eq("channel", "whatsapp")
            .eq("status", "open")
            .limit(1)
            .execute()
        )

        if conversation_result.data:
            conversation_id = conversation_result.data[0]["id"]

        else:
            # 4. Create a new conversation.
            new_conversation = (
                supabase
                .table("conversations")
                .insert({
                    "business_id": request.business_id,
                    "customer_id": request.customer_id,
                    "channel": "whatsapp",
                    "status": "open",
                })
                .execute()
            )

            if not new_conversation.data:
                raise RuntimeError(
                    "Could not create conversation."
                )

            conversation_id = new_conversation.data[0]["id"]

        # 5. Save the customer's message.
        saved_customer_message = (
            supabase
            .table("messages")
            .insert({
                "conversation_id": conversation_id,
                "sender_type": "customer",
                "message_text": request.customer_message,
                "channel": "whatsapp",
            })
            .execute()
        )

        if not saved_customer_message.data:
            raise RuntimeError(
                "Could not save customer message."
            )

        # 6. Run Forge's independent intelligence engine.
        reply = generate_sales_reply(
            customer_message=request.customer_message,
            product_context=request.product_context,
        )

        # 7. Save Forge's response.
        saved_ai_message = (
            supabase
            .table("messages")
            .insert({
                "conversation_id": conversation_id,
                "sender_type": "ai",
                "message_text": reply,
                "channel": "whatsapp",
            })
            .execute()
        )

        if not saved_ai_message.data:
            raise RuntimeError(
                "Could not save Forge response."
            )

        # 8. Update conversation activity.
        now = datetime.now(timezone.utc).isoformat()

        supabase \
            .table("conversations") \
            .update({
                "last_message_at": now,
                "updated_at": now,
            }) \
            .eq("id", conversation_id) \
            .execute()

        # 9. Return the result.
        return {
            "success": True,
            "conversation_id": conversation_id,
            "reply": reply,
        }

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )
