-- OPTIONAL and ADDITIVE. Not applied by the migration. Review, then run once in the Supabase SQL editor.
-- The assistant works without it: conversation memory falls back to chat history, and escalations
-- are reported honestly as "not recorded" (the assistant then gives the shop's phone number instead).
-- Nothing here alters or deletes existing data.

-- 1) Durable structured conversation memory (product ids in focus, quantity, budget, delivery place).
alter table public.conversations
  add column if not exists agent_state jsonb not null default '{}'::jsonb;

-- 2) Owner handoffs written by the assistant (unknown information, complaints, negotiation, orders/reservations to confirm).
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

-- RLS: the backend uses the service-role key (bypasses RLS). If the dashboard will read this table
-- directly with the user's JWT, enable RLS first, e.g.:
--   alter table public.escalations enable row level security;
--   create policy escalations_owner_read on public.escalations for select
--     using (exists (select 1 from public.businesses b where b.id = escalations.business_id and b.owner_id = auth.uid()));
