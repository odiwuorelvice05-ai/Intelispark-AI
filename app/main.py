from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.intelligence import engine
from app.supabase_client import supabase


app = FastAPI(
    title=settings.app_name,
    description="Independent AI sales intelligence platform",
    version="0.3.0",
)


class SalesRequest(BaseModel):
    business_id: str
    customer_id: str
    customer_message: str


@app.get("/")
def root():
    return {"name": settings.app_name, "status": "online", "version": "0.3.0"}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "environment": settings.environment,
        "intelligence": "trained-local-reasoning-engine-v0.3",
    }


@app.get("/ai/status")
def ai_status():
    return {
        "name": "Intelispark Sales Intelligence Engine",
        "status": "trained",
        "brain_version": "0.3",
        "training_examples": engine.training_examples,
        "intent_classes": engine.intent_classes,
        "capabilities": [
            "intent_detection",
            "entity_extraction",
            "budget_and_condition_constraints",
            "conversation_context",
            "evidence_grounded_product_ranking",
            "sales_signal_detection",
        ],
        "external_ai_api": False,
        "knowledge_source": "Supabase product catalog",
    }


def _conversation_context(conversation_id: str) -> str:
    result = (
        supabase.table("messages")
        .select("sender_type,message_text,created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(8)
        .execute()
    )
    messages = result.data or []
    messages.reverse()
    return "\n".join(
        f"{item.get('sender_type', 'unknown')}: {item.get('message_text', '')}"
        for item in messages
        if item.get("message_text")
    )


@app.post("/sales/reply")
def sales_reply(request: SalesRequest):
    try:
        business_result = (
            supabase.table("businesses")
            .select("id, name")
            .eq("id", request.business_id)
            .limit(1)
            .execute()
        )
        if not business_result.data:
            raise HTTPException(status_code=404, detail="Business not found.")
        business_name = business_result.data[0].get("name", "the shop")

        customer_result = (
            supabase.table("customers")
            .select("id, name, phone")
            .eq("id", request.customer_id)
            .eq("business_id", request.business_id)
            .limit(1)
            .execute()
        )
        if not customer_result.data:
            raise HTTPException(status_code=404, detail="Customer not found for this business.")

        conversation_result = (
            supabase.table("conversations")
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
            new_conversation = (
                supabase.table("conversations")
                .insert({
                    "business_id": request.business_id,
                    "customer_id": request.customer_id,
                    "channel": "whatsapp",
                    "status": "open",
                })
                .execute()
            )
            if not new_conversation.data:
                raise RuntimeError("Could not create conversation.")
            conversation_id = new_conversation.data[0]["id"]

        context = _conversation_context(conversation_id)

        saved_customer_message = (
            supabase.table("messages")
            .insert({
                "conversation_id": conversation_id,
                "sender_type": "customer",
                "message_text": request.customer_message,
                "channel": "whatsapp",
            })
            .execute()
        )
        if not saved_customer_message.data:
            raise RuntimeError("Could not save customer message.")

        products = engine.retrieve_products(
            request.business_id, request.customer_message, context
        )
        reply = engine.generate_reply(
            message=request.customer_message,
            products=products,
            business_name=business_name,
            context=context,
        )

        saved_ai_message = (
            supabase.table("messages")
            .insert({
                "conversation_id": conversation_id,
                "sender_type": "ai",
                "message_text": reply,
                "channel": "whatsapp",
            })
            .execute()
        )
        if not saved_ai_message.data:
            raise RuntimeError("Could not save Intelispark response.")

        now = datetime.now(timezone.utc).isoformat()
        supabase.table("conversations").update(
            {"last_message_at": now, "updated_at": now}
        ).eq("id", conversation_id).execute()

        analysis = engine.understand(request.customer_message, context)
        return {
            "success": True,
            "conversation_id": conversation_id,
            "reply": reply,
            "intelligence": {
                **analysis,
                "products_considered": len(products),
                "model": "local-tfidf-intent-plus-reasoning-v0.3",
            },
        }

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))
