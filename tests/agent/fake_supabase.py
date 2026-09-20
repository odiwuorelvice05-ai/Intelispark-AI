"""Minimal in-memory stand-in for the supabase-py client (only what sales_reply needs)."""
from __future__ import annotations

import itertools
from types import SimpleNamespace as NS

_ids = itertools.count(1)


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self._op, self._payload, self._limit, self._order = db, name, [], "select", None, None, None

    def select(self, *_): self._op = "select"; return self
    def eq(self, col, val): self.filters.append((col, val)); return self
    def limit(self, n): self._limit = n; return self
    def order(self, col, desc=False): self._order = (col, desc); return self
    def insert(self, row): self._op, self._payload = "insert", row; return self
    def update(self, row): self._op, self._payload = "update", row; return self
    def delete(self): self._op = "delete"; return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        match = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        if self._op == "insert":
            row = {"id": f"{next(_ids):08d}-0000-0000-0000-000000000000", "created_at": f"2026-01-01T00:00:{next(_ids):02d}", **self._payload}
            rows.append(row); return NS(data=[row])
        if self._op == "update":
            for r in match: r.update(self._payload)
            return NS(data=match)
        if self._op == "delete":
            for r in match: rows.remove(r)
            return NS(data=match)
        out = list(match)
        if self._order: out.sort(key=lambda r: r.get(self._order[0], ""), reverse=self._order[1])
        return NS(data=out[: self._limit] if self._limit else out)


class FakeSupabase:
    def __init__(self, user_id="owner-1"):
        self.tables, self.user_id = {}, user_id
        self.auth = NS(get_user=lambda token: NS(user=NS(id=self.user_id) if token == "good-token" else None))

    def table(self, name): return Query(self, name)
