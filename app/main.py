from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.intelligence import engine
from app.supabase_client import supabase


app = FastAPI(
    title=settings.app_name,
    description="Independent AI sales intelligence platform",
    version="0.2.0",
)


class SalesRequest(BaseModel):
    business_id: str
    customer_id: str
    customer_message: str


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "status": "online",
        "version": "0.2.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "environment": settings.environment,
        "intelligence": "trained-local-model",
    }


@app.get("/ai/status")
def ai_status():
    return {
        "name": "Intelispark Sales Intelligence Engine",
        "status": "trained",
        "training_examples": engine.training_examples,
        "intent_classes": engine.intent_classes,
        "external_ai_api": False,
        "knowledge_source": "Supabase product catalog",
    }


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

        products = engine.retrieve_products(request.business_id, request.customer_message)
        reply = engine.generate_reply(
            message=request.customer_message,
            products=products,
            business_name=business_name,
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
        (
            supabase.table("conversations")
            .update({"last_message_at": now, "updated_at": now})
            .eq("id", conversation_id)
            .execute()
        )

        intent, confidence = engine.predict_intent(request.customer_message)
        return {
            "success": True,
            "conversation_id": conversation_id,
            "reply": reply,
            "intelligence": {
                "intent": intent,
                "confidence": round(confidence, 3),
                "products_considered": len(products),
                "model": "local-tfidf-logistic-regression",
            },
        }

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))
