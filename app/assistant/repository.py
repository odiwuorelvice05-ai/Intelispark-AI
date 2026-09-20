"""Tenant-scoped data access: the ONLY place the assistant touches the database.

A repository instance is bound to one business id, chosen by the backend from the
authenticated request. No method takes a business id, so nothing the model says can
widen access. Only whitelisted columns are ever read, so fields the owner never meant
to expose (costs, internal notes, owner ids) cannot reach the model.
"""
from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger("intelispark.assistant")

PRODUCT_COLUMNS = "id,name,brand,category,variant,condition,price,stock_quantity,description,specs,installment_available"
BUSINESS_FIELDS = ("name", "industry", "phone", "whatsapp_number", "email", "timezone", "description")
CATALOG_LIMIT = 500
_STATE_RETRY_AFTER_S = 300


class DataUnavailable(Exception):
    """Shop data (catalog / profile) could not be read. The assistant must not guess."""


def is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class ShopRepository(ABC):
    business_id: str

    @abstractmethod
    def get_business(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_products(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_state(self, conversation_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def save_state(self, conversation_id: str, state: dict[str, Any]) -> bool:
        """True only if the state was durably stored."""

    @abstractmethod
    def create_escalation(self, conversation_id: str, customer_id: str | None, reason: str, summary: str, urgency: str) -> bool:
        """True only if a handoff row was durably stored. Must not raise."""

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        return next((p for p in self.list_products() if str(p.get("id")) == str(product_id)), None)


class SupabaseShopRepository(ShopRepository):
    # Durable state / escalations need database/proposed/assistant_state.sql. If it has not been
    # applied the assistant degrades to chat-history-only memory; we re-probe every few minutes so
    # applying the SQL takes effect without a redeploy.
    _state_disabled_until = 0.0

    def __init__(self, db: Any, business_id: str, business_row: dict[str, Any] | None = None) -> None:
        self._db = db
        self.business_id = business_id
        self._business = self._whitelist(business_row) if business_row else None
        self._products: list[dict[str, Any]] | None = None

    @staticmethod
    def _whitelist(row: dict[str, Any]) -> dict[str, Any]:
        return {k: row.get(k) for k in BUSINESS_FIELDS}

    def get_business(self) -> dict[str, Any]:
        if self._business is None:
            try:
                res = self._db.table("businesses").select("*").eq("id", self.business_id).limit(1).execute()
            except Exception as exc:
                raise DataUnavailable(f"business profile unavailable: {type(exc).__name__}") from exc
            if not res.data:
                raise DataUnavailable("business not found")
            self._business = self._whitelist(res.data[0])
        return self._business

    def list_products(self) -> list[dict[str, Any]]:
        if self._products is None:
            try:
                res = self._db.table("products").select(PRODUCT_COLUMNS).eq("business_id", self.business_id).limit(CATALOG_LIMIT).execute()
            except Exception as exc:
                raise DataUnavailable(f"catalog unavailable: {type(exc).__name__}") from exc
            self._products = res.data or []
            if len(self._products) >= CATALOG_LIMIT:
                log.warning("catalog_truncated business=%s limit=%d", self.business_id, CATALOG_LIMIT)
        return self._products

    # ---- optional durable state ---------------------------------------------------------
    @classmethod
    def _note_schema_error(cls, exc: Exception) -> None:
        if "agent_state" in str(exc) or "escalations" in str(exc) or "column" in str(exc).lower() or "relation" in str(exc).lower():
            cls._state_disabled_until = time.monotonic() + _STATE_RETRY_AFTER_S

    @classmethod
    def _state_enabled(cls) -> bool:
        return time.monotonic() >= cls._state_disabled_until

    def get_state(self, conversation_id: str) -> dict[str, Any]:
        if not self._state_enabled() or not is_uuid(conversation_id):
            return {}
        try:
            res = (self._db.table("conversations").select("agent_state").eq("id", conversation_id)
                   .eq("business_id", self.business_id).limit(1).execute())
            state = ((res.data or [{}])[0] or {}).get("agent_state")
            return state if isinstance(state, dict) else {}
        except Exception as exc:
            self._note_schema_error(exc)
            return {}

    def save_state(self, conversation_id: str, state: dict[str, Any]) -> bool:
        if not self._state_enabled() or not is_uuid(conversation_id):
            return False
        try:
            res = (self._db.table("conversations").update({"agent_state": state}).eq("id", conversation_id)
                   .eq("business_id", self.business_id).execute())
            return bool(res.data)
        except Exception as exc:
            self._note_schema_error(exc)
            return False

    def create_escalation(self, conversation_id, customer_id, reason, summary, urgency) -> bool:
        try:
            row = {"business_id": self.business_id, "conversation_id": conversation_id, "customer_id": customer_id,
                   "reason": reason, "summary": summary, "urgency": urgency, "status": "open"}
            return bool(self._db.table("escalations").insert(row).execute().data)
        except Exception as exc:
            log.warning("escalation_not_recorded business=%s error=%s", self.business_id, type(exc).__name__)
            return False
