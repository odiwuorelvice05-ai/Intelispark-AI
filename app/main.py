from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.supabase_client import supabase
from app.agent.repository import SupabaseShopRepository
from app.agent.service import agent_enabled, run_agent_turn, status as agent_status

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
    return {"status": "healthy", "environment": settings.environment, "intelligence": "agent" if agent_enabled() else "handoff-only"}

@app.get("/ai/status")
def ai_status():
    return {
        "name": "Intelispark Sales Intelligence Engine",
        "knowledge_source": "Supabase product catalog + business profile",
        "agent": agent_status(),
    }

def _safe_fallback_reply(business_id: str, business_name: str, conversation_id: str, customer_id: str | None, customer_message: str) -> tuple[str, dict]:
    """No AI reply is available this turn (agent disabled, unavailable, or it could not produce a
    grounded answer). Never let anything here guess at a fact: hand the conversation to the shop
    owner and tell the customer honestly that a person will follow up, using only real, retrieved
    business data (never an invented phone number or promise)."""
    phone = None
    handoff_recorded = False
    try:
        repo = SupabaseShopRepository(supabase, business_id)
        biz = repo.get_business()
        phone = biz.get("whatsapp_number") or biz.get("phone")
        result = repo.create_escalation(
            conversation_id, customer_id, "other",
            f"Could not be answered automatically: {customer_message[:300]}", "normal",
        )
        handoff_recorded = bool(result.get("recorded"))
    except Exception as exc:
        print(f"[Intelispark fallback] could not record handoff: {exc!r}")

    reply = f"Thanks for reaching out to {business_name}! I've passed your message to the team and someone will get back to you shortly."
    if phone:
        reply += f" If it's urgent, you can reach them directly at {phone}."
    return reply, {"intent": "handoff", "handoff_recorded": handoff_recorded, "model": "safe-template-fallback"}

def _history_rows(conversation_id: str, limit: int = 12) -> list[dict]:
    result=(supabase.table("messages").select("sender_type,message_text,created_at").eq("conversation_id",conversation_id).order("created_at",desc=True).limit(limit).execute())
    rows=result.data or []
    rows.reverse()
    return rows

def _require_owner(business_id: str, authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    token=authorization.split(" ",1)[1].strip()
    if not token: raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        user_result=supabase.auth.get_user(token)
        user=getattr(user_result,"user",None)
        user_id=getattr(user,"id",None)
    except Exception:
        user_id=None
    if not user_id: raise HTTPException(status_code=401, detail="Invalid or expired session.")
    result=supabase.table("businesses").select("id,name,owner_id").eq("id",business_id).limit(1).execute()
    if not result.data: raise HTTPException(status_code=404, detail="Business not found.")
    business=result.data[0]
    if business.get("owner_id") != user_id: raise HTTPException(status_code=403, detail="You do not have access to this business.")
    return business

@app.post("/sales/reply")
def sales_reply(request: SalesRequest, authorization: str | None = Header(default=None)):
    try:
        business=_require_owner(request.business_id,authorization)
        business_name=business.get("name","the shop")
        customer_id=request.customer_id
        if customer_id:
            customer_result=(supabase.table("customers").select("id,name,phone").eq("id",customer_id).eq("business_id",request.business_id).limit(1).execute())
            if not customer_result.data: raise HTTPException(status_code=404, detail="Customer not found for this business.")
        else:
            customer_result=(supabase.table("customers").select("id,name,phone").eq("business_id",request.business_id).eq("name","Intelispark Test Customer").limit(1).execute())
            if customer_result.data:
                customer_id=customer_result.data[0]["id"]
            else:
                created=(supabase.table("customers").insert({"business_id":request.business_id,"name":"Intelispark Test Customer","phone":"+254700000000"}).execute())
                if not created.data: raise RuntimeError("Could not create test customer.")
                customer_id=created.data[0]["id"]

        conversation_result=(supabase.table("conversations").select("id").eq("business_id",request.business_id).eq("customer_id",customer_id).eq("channel","whatsapp").eq("status","open").limit(1).execute())
        if conversation_result.data:
            conversation_id=conversation_result.data[0]["id"]
        else:
            new_conversation=(supabase.table("conversations").insert({"business_id":request.business_id,"customer_id":customer_id,"channel":"whatsapp","status":"open"}).execute())
            if not new_conversation.data: raise RuntimeError("Could not create conversation.")
            conversation_id=new_conversation.data[0]["id"]

        history_rows=[]
        try:
            history_rows=_history_rows(conversation_id)
        except Exception as exc:
            print(f"[Intelispark] history unavailable; continuing without it: {exc!r}")
            history_rows=[]

        saved=(supabase.table("messages").insert({"conversation_id":conversation_id,"sender_type":"customer","message_text":request.customer_message,"channel":"whatsapp"}).execute())
        if not saved.data: raise RuntimeError("Could not save customer message.")

        reply=None
        intelligence: dict={}
        if agent_enabled():
            outcome = run_agent_turn(
                db=supabase, business=business, conversation_id=conversation_id,
                customer_id=customer_id, customer_message=request.customer_message,
                history_rows=history_rows,
            )
            if outcome is not None:
                reply=outcome.reply
                intelligence=outcome.intelligence

        if reply is None:
            reply, intelligence = _safe_fallback_reply(business["id"], business_name, conversation_id, customer_id, request.customer_message)

        saved_ai=(supabase.table("messages").insert({"conversation_id":conversation_id,"sender_type":"ai","message_text":outcome.reply,"channel":"whatsapp"}).execute())
                if not saved_ai.data: raise RuntimeError("Could not save Intelispark response.")
                now=datetime.now(timezone.utc).isoformat()
                supabase.table("conversations").update({"last_message_at":now,"updated_at":now}).eq("id",conversation_id).execute()
                return {"success": True, "conversation_id": conversation_id, "reply": outcome.reply, "intelligence": outcome.intelligence}

        if reply is None:
            reply, intelligence = _safe_fallback_reply(business["id"], business_name, conversation_id, customer_id, request.customer_message)

        saved_ai=(supabase.table("messages").insert({"conversation_id":conversation_id,"sender_type":"ai","message_text":reply,"channel":"whatsapp"}).execute())
        if not saved_ai.data: raise RuntimeError("Could not save Intelispark response.")
        now=datetime.now(timezone.utc).isoformat()
        supabase.table("conversations").update({"last_message_at":now,"updated_at":now}).eq("id",conversation_id).execute()
        return {"success": True, "conversation_id": conversation_id, "reply": reply, "intelligence": intelligence}
    except HTTPException:
        raise
    except Exception as error:
        print(f"[Intelispark sales reply] {error!r}")
        raise HTTPException(status_code=500, detail="Intelligence service error. Please try again.")

app.add_api_route("/api/health",health,methods=["GET"])
app.add_api_route("/api/ai/status",ai_status,methods=["GET"])
app.add_api_route("/api/sales/reply",sales_reply,methods=["POST"])
