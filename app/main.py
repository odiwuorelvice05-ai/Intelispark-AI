import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app import assistant
from app.config import settings
from app.supabase_client import supabase

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("intelispark.api")

app = FastAPI(title=settings.app_name, description="Independent AI sales intelligence platform", version="0.4.0")

TEST_CUSTOMER_NAME = "Intelispark Test Customer"
UNAVAILABLE_DETAIL = "The assistant is temporarily unavailable. Your message was saved; please try again in a moment."


class SalesRequest(BaseModel):
    business_id: str
    customer_id: str | None = None
    customer_message: str


@app.get("/")
def root():
    return {"name": settings.app_name, "status": "online", "version": app.version}


@app.get("/health")
def health():
    return {"status": "healthy", "environment": settings.environment}


@app.get("/ai/status")
def ai_status():
    return {"name": "Intelispark Sales Assistant", "knowledge_source": "Supabase product catalog + business profile", "assistant": assistant.status()}


def _require_owner(business_id: str, authorization: str | None) -> dict:
    """Authenticate the caller and prove they own `business_id`. This is where the tenant is established."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        user_id = getattr(getattr(supabase.auth.get_user(token), "user", None), "id", None)
    except Exception:
        user_id = None
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    result = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Business not found.")
    business = result.data[0]
    if business.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this business.")
    return business


def _customer_id(business_id: str, requested: str | None) -> str:
    if requested:
        found = supabase.table("customers").select("id").eq("id", requested).eq("business_id", business_id).limit(1).execute()
        if not found.data:
            raise HTTPException(status_code=404, detail="Customer not found for this business.")
        return requested
    found = supabase.table("customers").select("id").eq("business_id", business_id).eq("name", TEST_CUSTOMER_NAME).limit(1).execute()
    if found.data:
        return found.data[0]["id"]
    created = supabase.table("customers").insert({"business_id": business_id, "name": TEST_CUSTOMER_NAME, "phone": "+254700000000"}).execute()
    if not created.data:
        raise RuntimeError("Could not create test customer.")
    return created.data[0]["id"]


def _open_conversation(business_id: str, customer_id: str) -> str:
    found = (supabase.table("conversations").select("id").eq("business_id", business_id).eq("customer_id", customer_id)
             .eq("channel", "whatsapp").eq("status", "open").limit(1).execute())
    if found.data:
        return found.data[0]["id"]
    created = supabase.table("conversations").insert({"business_id": business_id, "customer_id": customer_id, "channel": "whatsapp", "status": "open"}).execute()
    if not created.data:
        raise RuntimeError("Could not create conversation.")
    return created.data[0]["id"]


def _history_rows(conversation_id: str) -> list[dict]:
    """Recent messages for context. Never authoritative, and never a reason to fail the request."""
    try:
        res = (supabase.table("messages").select("sender_type,message_text,created_at").eq("conversation_id", conversation_id)
               .order("created_at", desc=True).limit(settings.assistant_history_messages).execute())
        return list(reversed(res.data or []))
    except Exception as exc:
        log.warning("history_unavailable conversation=%s error=%s", conversation_id, type(exc).__name__)
        return []


def _save_message(conversation_id: str, sender_type: str, text: str) -> None:
    saved = supabase.table("messages").insert({"conversation_id": conversation_id, "sender_type": sender_type, "message_text": text, "channel": "whatsapp"}).execute()
    if not saved.data:
        raise RuntimeError(f"Could not save {sender_type} message.")


@app.post("/sales/reply")
def sales_reply(request: SalesRequest, authorization: str | None = Header(default=None)):
    try:
        business = _require_owner(request.business_id, authorization)
        customer_id = _customer_id(request.business_id, request.customer_id)
        conversation_id = _open_conversation(request.business_id, customer_id)
        history_rows = _history_rows(conversation_id)  # read before the current message is stored
        _save_message(conversation_id, "customer", request.customer_message)

        outcome = assistant.respond(db=supabase, business=business, conversation_id=conversation_id, customer_id=customer_id,
                                    customer_message=request.customer_message, history_rows=history_rows)
        if outcome.status != "answered":
            raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)

        _save_message(conversation_id, "ai", outcome.reply)
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("conversations").update({"last_message_at": now, "updated_at": now}).eq("id", conversation_id).execute()
        return {"success": True, "conversation_id": conversation_id, "reply": outcome.reply, "intelligence": outcome.intelligence}
    except HTTPException:
        raise
    except Exception as error:
        log.error("sales_reply_failed error=%r", error)
        raise HTTPException(status_code=500, detail="Intelligence service error. Please try again.")


app.add_api_route("/api/health", health, methods=["GET"])
app.add_api_route("/api/ai/status", ai_status, methods=["GET"])
app.add_api_route("/api/sales/reply", sales_reply, methods=["POST"])
