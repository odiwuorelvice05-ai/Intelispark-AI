-- PROPOSAL ONLY: NOT applied, NOT required by Phase 1. Review before running in Supabase.
-- Phase 1 of the agent works without any of this (conversation memory falls back to chat
-- history; escalations report handoff_recorded=false and the agent gives the shop's phone
-- number instead of promising a handoff).

-- 1) Durable structured conversation memory (selected product, quantity, budget, stage...).
alter table public.conversations
  add column if not exists agent_state jsonb not null default '{}'::jsonb;

-- 2) Actionable owner escalations (what escalate_to_owner writes).
create table if not exists public.escalations (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete set null,
  customer_id uuid references public.customers(id) on delete set null,
  reason text not null check (reason in ('unknown_information','complaint','negotiation','order_help','custom_request','other')),
  summary text not null,
  urgency text not null default 'normal' check (urgency in ('low','normal','high')),
  status text not null default 'open' check (status in ('open','resolved')),
  owner_response text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);
create index if not exists escalations_business_status_idx on public.escalations (business_id, status, created_at desc);

-- RLS: the backend uses the service-role key (bypasses RLS). If the dashboard will read this
-- table directly with the user's JWT, enable RLS first, e.g.:
--   alter table public.escalations enable row level security;
--   create policy escalations_owner_read on public.escalations for select
--     using (exists (select 1 from public.businesses b where b.id = escalations.business_id and b.owner_id = auth.uid()));
-- (The repo notes RLS is intentionally unaudited today; do that audit for all tables together.)

-- 3) PHASE 3 SKETCH (orders). The agent must only claim an order exists after a row is
--    committed here by a backend tool (create_order), never because the model said so.
-- create table public.orders (
--   id uuid primary key default gen_random_uuid(),
--   business_id uuid not null references public.businesses(id) on delete cascade,
--   customer_id uuid references public.customers(id),
--   conversation_id uuid references public.conversations(id),
--   status text not null default 'requested' check (status in ('requested','confirmed','cancelled','fulfilled')),
--   fulfilment text check (fulfilment in ('pickup','delivery')),
--   delivery_location text,
--   total_kes numeric(12,2),
--   created_at timestamptz not null default now()
-- );
-- create table public.order_items (
--   id uuid primary key default gen_random_uuid(),
--   order_id uuid not null references public.orders(id) on delete cascade,
--   product_id uuid not null references public.products(id),
--   quantity integer not null check (quantity > 0),
--   unit_price_kes numeric(12,2) not null   -- snapshot taken from products.price by the backend
-- );
