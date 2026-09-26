-- Intelispark AI — RLS hardening for tenant isolation (Task 3 of the intelligence-layer reset).
-- Run once in the Supabase SQL editor. Read the whole comment block before running it.
--
-- WHY THIS MATTERS
-- The Python backend (app/agent/*, app/main.py) already enforces tenant isolation entirely in
-- application code, and it always connects with the Supabase SERVICE-ROLE key, which bypasses
-- RLS by design (Supabase's service_role Postgres role has BYPASSRLS). This migration changes
-- NOTHING about that path -- it will keep working exactly as it does today.
--
-- The DASHBOARD, however, talks to Supabase DIRECTLY from the browser using the anon key plus
-- the signed-in user's own session (see APP.supabase.from(...) calls in frontend/script.js,
-- onboarding.js, conversation-ui.js, product-delete.js). Every one of those calls currently
-- relies on a client-side .eq('business_id', ...) / .eq('owner_id', ...) filter for isolation --
-- that is NOT a security boundary. Any authenticated user can open devtools and query these
-- tables directly with no filter, or with a different business_id, and get another shop's data.
-- database/step3_account_ownership.sql says outright that RLS was never enabled here. If that
-- still matches production, this is the one real gap that lets a signed-in shop owner read or
-- write another shop's products, customers, conversations and messages.
--
-- WHAT THIS DOES
-- Enables RLS on the five tables the dashboard queries directly (businesses, products,
-- customers, conversations, messages), with policies that allow exactly the operations the
-- current frontend performs -- nothing more, nothing less -- scoped to owner_id = auth.uid()
-- on businesses, and via a join back to businesses for every table that only carries
-- business_id (or, for messages, only conversation_id).
--
-- WHAT THIS DOES NOT DO
-- Touch table structure, drop or rename a single column, delete a single row, reset any table,
-- or change how the Python backend talks to Supabase.
--
-- BEFORE RUNNING IN PRODUCTION
--   1. businesses/customers/conversations/messages have no schema file checked into this repo
--      (unlike products -- see step2_products.sql), so the column names below (owner_id,
--      business_id, conversation_id) are inferred from every query site in frontend/*.js and
--      app/*.py. Confirm they match the Supabase Table Editor before running this.
--   2. Run this in a staging/dev project first, or wrapped in a transaction you can roll back
--      (it already is, below), then click through the dashboard end-to-end -- sign in, view
--      products, add/edit/delete a product, edit business info, open a conversation, delete
--      a conversation -- before trusting it in production. Enabling RLS with a missing policy
--      denies that operation outright rather than raising a loud error, so a gap here reads as
--      "nothing loads", not a clear failure.
--   3. Independent of database/proposed/agent_phase2.sql (escalations/agent_state) -- run this
--      whether or not that one has been applied. Once escalations exists, give it the same
--      treatment (a starting policy is already sketched in that file's own comment).
--
begin;

-- ── businesses ───────────────────────────────────────────────────────────
alter table public.businesses enable row level security;

drop policy if exists businesses_select_own on public.businesses;
create policy businesses_select_own on public.businesses
  for select to authenticated
  using (owner_id = auth.uid());

drop policy if exists businesses_insert_own on public.businesses;
create policy businesses_insert_own on public.businesses
  for insert to authenticated
  with check (owner_id = auth.uid());

drop policy if exists businesses_update_own on public.businesses;
create policy businesses_update_own on public.businesses
  for update to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

-- No delete policy: the dashboard has no "delete business" action today.
-- Omitting the policy denies the operation outright -- matches current behaviour.

-- ── products ─────────────────────────────────────────────────────────────
alter table public.products enable row level security;

drop policy if exists products_select_own on public.products;
create policy products_select_own on public.products
  for select to authenticated
  using (exists (select 1 from public.businesses b where b.id = products.business_id and b.owner_id = auth.uid()));

drop policy if exists products_insert_own on public.products;
create policy products_insert_own on public.products
  for insert to authenticated
  with check (exists (select 1 from public.businesses b where b.id = products.business_id and b.owner_id = auth.uid()));

drop policy if exists products_update_own on public.products;
create policy products_update_own on public.products
  for update to authenticated
  using (exists (select 1 from public.businesses b where b.id = products.business_id and b.owner_id = auth.uid()))
  with check (exists (select 1 from public.businesses b where b.id = products.business_id and b.owner_id = auth.uid()));

drop policy if exists products_delete_own on public.products;
create policy products_delete_own on public.products
  for delete to authenticated
  using (exists (select 1 from public.businesses b where b.id = products.business_id and b.owner_id = auth.uid()));

-- ── customers ────────────────────────────────────────────────────────────
-- The dashboard only ever reads customers directly; creation happens through the backend
-- (service-role key) when a WhatsApp/test conversation starts. Only a select policy is added,
-- matching current behaviour -- insert/update/delete stay denied on the anon-key path.
alter table public.customers enable row level security;

drop policy if exists customers_select_own on public.customers;
create policy customers_select_own on public.customers
  for select to authenticated
  using (exists (select 1 from public.businesses b where b.id = customers.business_id and b.owner_id = auth.uid()));

-- ── conversations ────────────────────────────────────────────────────────
alter table public.conversations enable row level security;

drop policy if exists conversations_select_own on public.conversations;
create policy conversations_select_own on public.conversations
  for select to authenticated
  using (exists (select 1 from public.businesses b where b.id = conversations.business_id and b.owner_id = auth.uid()));

drop policy if exists conversations_delete_own on public.conversations;
create policy conversations_delete_own on public.conversations
  for delete to authenticated
  using (exists (select 1 from public.businesses b where b.id = conversations.business_id and b.owner_id = auth.uid()));

-- No insert/update policy: conversations are only ever created/updated by the backend.

-- ── messages ─────────────────────────────────────────────────────────────
-- messages carries only conversation_id, not business_id -- ownership is checked by joining
-- through conversations -> businesses. Read-only from the dashboard; all writes come from the
-- backend (service-role key).
alter table public.messages enable row level security;

drop policy if exists messages_select_own on public.messages;
create policy messages_select_own on public.messages
  for select to authenticated
  using (exists (
    select 1 from public.conversations c
    join public.businesses b on b.id = c.business_id
    where c.id = messages.conversation_id and b.owner_id = auth.uid()
  ));

commit;
