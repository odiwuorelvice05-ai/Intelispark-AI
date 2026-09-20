"""Tenant-scoped data access for agent tools.

The agent never touches Supabase directly. Each repository instance is BOUND to one
business_id chosen by the backend from the authenticated request; no method accepts a
business id, so a model-supplied id cannot widen access. Every query filters on it.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

PRODUCT_COLUMNS = "id,name,brand,category,variant,condition,price,stock_quantity,description,specs,installment_available"
BUSINESS_COLUMNS = "name,phone,email,industry,description,whatsapp_number,timezone"


def is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class ShopRepository(ABC):
    business_id: str

    @abstractmethod
    def list_products(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_business(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_state(self, conversation_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def save_state(self, conversation_id: str, state: dict[str, Any]) -> bool:
        """True only if the state was durably persisted."""

    @abstractmethod
    def create_escalation(self, conversation_id: str, customer_id: str | None, reason: str, summary: str, urgency: str) -> dict[str, Any]:
        """Return {"recorded": bool, "id": str | None}. Must not raise."""

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        for p in self.list_products():
            if str(p.get("id")) == str(product_id):
                return p
        return None


class SupabaseShopRepository(ShopRepository):
    _state_column_available = True  # shared: once the column is known to be missing, stop probing on every request

    def __init__(self, db: Any, business_id: str) -> None:
        self._db = db
        self.business_id = business_id
        self._products: list[dict[str, Any]] | None = None
        self._business: dict[str, Any] | None = None

    def list_products(self) -> list[dict[str, Any]]:
        if self._products is None:
            res = self._db.table("products").select(PRODUCT_COLUMNS).eq("business_id", self.business_id).limit(500).execute()
            self._products = res.data or []
        return self._products

    def get_business(self) -> dict[str, Any]:
        if self._business is None:
            res = self._db.table("businesses").select(BUSINESS_COLUMNS).eq("id", self.business_id).limit(1).execute()
            self._business = (res.data or [{}])[0]
        return self._business

    @staticmethod
    def _note_state_error(exc: Exception) -> None:
        # Only a missing column disables durable state; a transient network error must not.
        if "agent_state" in str(exc) or "column" in str(exc).lower():
            SupabaseShopRepository._state_column_available = False

    def get_state(self, conversation_id: str) -> dict[str, Any]:
        if not SupabaseShopRepository._state_column_available or not is_uuid(conversation_id):
            return {}
        try:  # needs conversations.agent_state (database/proposed/agent_phase2.sql); degrade if absent
            res = (self._db.table("conversations").select("agent_state").eq("id", conversation_id)
                   .eq("business_id", self.business_id).limit(1).execute())
            state = ((res.data or [{}])[0] or {}).get("agent_state")
            return state if isinstance(state, dict) else {}
        except Exception as exc:
            self._note_state_error(exc)
            return {}

    def save_state(self, conversation_id: str, state: dict[str, Any]) -> bool:
        if not SupabaseShopRepository._state_column_available or not is_uuid(conversation_id):
            return False
        try:
            res = (self._db.table("conversations").update({"agent_state": state}).eq("id", conversation_id)
                   .eq("business_id", self.business_id).execute())
            return bool(res.data)
        except Exception as exc:
            self._note_state_error(exc)
            return False

    def create_escalation(self, conversation_id, customer_id, reason, summary, urgency) -> dict[str, Any]:
        try:  # needs the escalations table (database/proposed/agent_phase2.sql)
            row = {"business_id": self.business_id, "conversation_id": conversation_id, "customer_id": customer_id,
                   "reason": reason, "summary": summary, "urgency": urgency, "status": "open"}
            res = self._db.table("escalations").insert(row).execute()
            return {"recorded": bool(res.data), "id": (res.data or [{}])[0].get("id")}
        except Exception:
            return {"recorded": False, "id": None}


class InMemoryStore:
    """Multi-tenant in-memory backing store: tests, evals and the offline demo."""

    def __init__(self) -> None:
        self.businesses: dict[str, dict[str, Any]] = {}
        self.products: dict[str, list[dict[str, Any]]] = {}
        self.states: dict[tuple[str, str], dict[str, Any]] = {}
        self.escalations: list[dict[str, Any]] = []

    def add_business(self, business_id: str, business: dict[str, Any], products: list[dict[str, Any]]) -> None:
        self.businesses[business_id] = business
        self.products[business_id] = products

    def repo(self, business_id: str) -> "InMemoryShopRepository":
        return InMemoryShopRepository(self, business_id)


class InMemoryShopRepository(ShopRepository):
    def __init__(self, store: InMemoryStore, business_id: str) -> None:
        self._s, self.business_id = store, business_id

    def list_products(self) -> list[dict[str, Any]]:
        return [dict(p) for p in self._s.products.get(self.business_id, [])]

    def get_business(self) -> dict[str, Any]:
        return dict(self._s.businesses.get(self.business_id, {}))

    def get_state(self, conversation_id: str) -> dict[str, Any]:
        return dict(self._s.states.get((self.business_id, conversation_id), {}))

    def save_state(self, conversation_id: str, state: dict[str, Any]) -> bool:
        self._s.states[(self.business_id, conversation_id)] = dict(state)
        return True

    def create_escalation(self, conversation_id, customer_id, reason, summary, urgency) -> dict[str, Any]:
        rec = {"id": f"esc-{len(self._s.escalations) + 1}", "business_id": self.business_id, "conversation_id": conversation_id,
               "customer_id": customer_id, "reason": reason, "summary": summary, "urgency": urgency}
        self._s.escalations.append(rec)
        return {"recorded": True, "id": rec["id"]}
