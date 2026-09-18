from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.intelligence import engine
from app.supabase_client import supabase
from app.mistral_assist import mistral_assist

app = FastAPI(title=settings.app_name, description="Independent AI sales intelligence platform", version="0.3.0")

class SalesRequest(BaseModel):
    business_id: str
    customer_id: str | None = None
    customer_message: str

@app.get("/")
def root():
    return {"name": settings.app_name, "status": "online", "version": "0.3.0"}

@app.get("/health")
def health():
    return {"status": "healthy", "environment": settings.environment, "intelligence": "trained-local-reasoning-engine-v0.3"}

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
            "business_profile_grounding",
            "policy_and_contact_lookup",
            "optional_mistral_language_understanding",
        ],
        "external_ai_api": mistral_assist.enabled,
        "mistral_model": mistral_assist.model if mistral_assist.enabled else None,
        "knowledge_source": "Supabase product catalog + business profile",
    }

def _conversation_context(conversation_id: str) -> str:
    result=(supabase.table("messages").select("sender_type,message_text,created_at").eq("conversation_id",conversation_id).order("created_at",desc=True).limit(8).execute())
    messages=result.data or []; messages.reverse()
    return "\n".join(f"{item.get('sender_type','unknown')}: {item.get('message_text','')}" for item in messages if item.get("message_text"))

def _require_owner(business_id: str, authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    token=authorization.split(" ",1)[1].strip()
    if not token: raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        user_result=supabase.auth.get_user(token); user=getattr(user_result,"user",None); user_id=getattr(user,"id",None)
    except Exception: user_id=None
    if not user_id: raise HTTPException(status_code=401, detail="Invalid or expired session.")
    result=supabase.table("businesses").select("id,name,owner_id").eq("id",business_id).limit(1).execute()
    if not result.data: raise HTTPException(status_code=404, detail="Business not found.")
    business=result.data[0]
    if business.get("owner_id") != user_id: raise HTTPException(status_code=403, detail="You do not have access to this business.")
    return business

@app.post("/sales/reply")
def sales_reply(request: SalesRequest, authorization: str | None = Header(default=None)):
    try:
        business=_require_owner(request.business_id,authorization); business_name=business.get("name","the shop")
        customer_id=request.customer_id
        if customer_id:
            customer_result=(supabase.table("customers").select("id,name,phone").eq("id",customer_id).eq("business_id",request.business_id).limit(1).execute())
            if not customer_result.data: raise HTTPException(status_code=404, detail="Customer not found for this business.")
        else:
            customer_result=(supabase.table("customers").select("id,name,phone").eq("business_id",request.business_id).eq("name","Intelispark Test Customer").limit(1).execute())
            if customer_result.data: customer_id=customer_result.data[0]["id"]
            else:
                created=(supabase.table("customers").insert({"business_id":request.business_id,"name":"Intelispark Test Customer","phone":"+254700000000"}).execute())
                if not created.data: raise RuntimeError("Could not create test customer.")
                customer_id=created.data[0]["id"]
        conversation_result=(supabase.table("conversations").select("id").eq("business_id",request.business_id).eq("customer_id",customer_id).eq("channel","whatsapp").eq("status","open").limit(1).execute())
        if conversation_result.data: conversation_id=conversation_result.data[0]["id"]
        else:
            new_conversation=(supabase.table("conversations").insert({"business_id":request.business_id,"customer_id":customer_id,"channel":"whatsapp","status":"open"}).execute())
            if not new_conversation.data: raise RuntimeError("Could not create conversation.")
            conversation_id=new_conversation.data[0]["id"]
        context=_conversation_context(conversation_id)
        saved=(supabase.table("messages").insert({"conversation_id":conversation_id,"sender_type":"customer","message_text":request.customer_message,"channel":"whatsapp"}).execute())
        if not saved.data: raise RuntimeError("Could not save customer message.")
        local_analysis = engine.understand(request.customer_message, context)
        products = engine.retrieve_products(request.business_id, request.customer_message, context)
        business_knowledge = engine.get_business_knowledge(request.business_id)

        # Mistral is a selective language-understanding supplement. It is not
        # the catalog authority and is never required for ordinary requests.
        ai_guidance = None
        if mistral_assist.should_call(local_analysis, request.customer_message):
            # Mistral gets the full catalog for semantic understanding, while
            # Supabase remains the authoritative source of every product fact.
            catalog_result = (
                supabase.table("products")
                .select("id,name,brand,category,variant,condition,price,stock_quantity,description,specs,installment_available")
                .eq("business_id", request.business_id)
                .limit(200)
                .execute()
            )
            catalog_for_ai = catalog_result.data or []
            ai_guidance = mistral_assist.understand(
                request.customer_message,
                context,
                business_knowledge,
                catalog_for_ai,
            )

        search_message = request.customer_message
        analysis_for_reply = local_analysis

        if ai_guidance:
            # Mistral is the primary language-understanding layer. It determines
            # what the customer means; Intelispark still retrieves only verified
            # products from this shop's Supabase catalog.
            guided_intent = str(ai_guidance.get("intent") or "").strip()
            valid_intents = set(engine.intent_classes) | {
                "identity", "owner_contact", "general", "thanks"
            }
            analysis_for_reply = dict(local_analysis)
            if guided_intent in valid_intents:
                analysis_for_reply["intent"] = guided_intent
            analysis_for_reply["confidence"] = max(
                float(local_analysis.get("confidence") or 0),
                float(ai_guidance.get("confidence") or 0),
            )

            guided_entities = dict(local_analysis.get("entities") or {})
            product_type = ai_guidance.get("product_type")
            brand = str(ai_guidance.get("brand") or "").strip().lower()
            budget = ai_guidance.get("budget_max")
            if product_type in {"phone", "laptop", "tablet", "camera", "audio", "accessory"}:
                guided_entities["product_type"] = product_type
            if brand:
                guided_entities["brands"] = [brand]
            if budget is not None:
                guided_entities["budget_max"] = budget
            analysis_for_reply["entities"] = guided_entities

            if ai_guidance.get("catalog_query") or ai_guidance.get("needs_catalog"):
                search_message = str(
                    ai_guidance.get("catalog_query") or request.customer_message
                )
                products = engine.retrieve_products(
                    request.business_id,
                    search_message,
                    context,
                    analysis_override=analysis_for_reply,
                )

            excluded = {
                str(name).strip().lower()
                for name in (ai_guidance.get("exclude_names") or [])
                if str(name).strip()
            }
            if excluded:
                products = [
                    p for p in products
                    if str(p.get("name") or "").strip().lower() not in excluded
                ]
                products = [
                    p for p in products
                    if int(p.get("stock_quantity") or 0) > 0
                ]

        reply = engine.generate_reply(
            message=request.customer_message,
            products=products,
            business_name=business_name,
            context=context,
            business=business_knowledge,
            analysis_override=analysis_for_reply,
        )

        # Mistral may provide a conversational direct response when it does not
        # require catalog facts. Catalog/business facts still come from Intelispark.
        if ai_guidance:
            direct = str(ai_guidance.get("direct_reply") or "").strip()
            intent = str(ai_guidance.get("intent") or "")
            if direct and intent in {"identity", "owner_contact", "general"}:
                reply = direct
        saved_ai=(supabase.table("messages").insert({"conversation_id":conversation_id,"sender_type":"ai","message_text":reply,"channel":"whatsapp"}).execute())
        if not saved_ai.data: raise RuntimeError("Could not save Intelispark response.")
        now=datetime.now(timezone.utc).isoformat(); supabase.table("conversations").update({"last_message_at":now,"updated_at":now}).eq("id",conversation_id).execute()
        analysis = engine.understand(request.customer_message, context)
        analysis["mistral_assist"] = {
            "used": bool(ai_guidance),
            "model": mistral_assist.model if ai_guidance else None,
        }
        return {
            "success": True,
            "conversation_id": conversation_id,
            "reply": reply,
            "intelligence": {
                **analysis,
                "products_considered": len(products),
                "model": "local-intent-reasoning + selective-mistral",
            },
        }
    except HTTPException: raise
    except Exception as error: raise HTTPException(status_code=500,detail=str(error))

app.add_api_route("/api/health",health,methods=["GET"])
app.add_api_route("/api/ai/status",ai_status,methods=["GET"])
app.add_api_route("/api/sales/reply",sales_reply,methods=["POST"])
