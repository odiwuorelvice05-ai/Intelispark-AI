-- Intelispark AI — canonical tenant RLS reconciliation.
-- Replaces the duplicated/stale permissive policy set with one consistent
-- owner-or-explicit-user-membership model.
--
-- IMPORTANT:
-- * This migration does not delete data or change table structure.
-- * The Python backend uses service_role and is intentionally unaffected.
-- * The browser uses the authenticated user's session, so these policies are
--   the security boundary for direct Supabase access.
-- * Existing ownerless demo/test businesses remain inaccessible to browser
--   users unless they are later assigned an owner/member. service_role access
--   remains available to the backend.
--
-- Access model:
--   owner = businesses.owner_id = auth.uid()
--   member = business_members.user_id = auth.uid()
--
-- Email-only membership is deliberately NOT treated as authorization. An
-- invitation should be linked to a real auth user before that user gets access.

begin;

-- Remove all previously-defined policy families so permissive policies cannot
-- silently widen access through OR semantics.

drop policy if exists businesses_select_own_or_member on public.businesses;
drop policy if exists businesses_select_own on public.businesses;
drop policy if exists businesses_insert_self_owned on public.businesses;
drop policy if exists businesses_insert_own on public.businesses;
drop policy if exists businesses_update_owner_only on public.businesses;
drop policy if exists businesses_update_own on public.businesses;
drop policy if exists businesses_delete_owner_only on public.businesses;

drop policy if exists members_select_same_business on public.business_members;
drop policy if exists members_insert_owner on public.business_members;
drop policy if exists members_update_owner on public.business_members;
drop policy if exists members_delete_owner on public.business_members;

drop policy if exists products_select_same_business on public.products;
drop policy if exists products_select_tenant on public.products;
drop policy if exists products_select_own on public.products;
drop policy if exists products_insert_same_business on public.products;
drop policy if exists products_insert_tenant on public.products;
drop policy if exists products_insert_own on public.products;
drop policy if exists products_update_same_business on public.products;
drop policy if exists products_update_tenant on public.products;
drop policy if exists products_update_own on public.products;
drop policy if exists products_delete_same_business on public.products;
drop policy if exists products_delete_tenant on public.products;
drop policy if exists products_delete_own on public.products;

drop policy if exists customers_select_same_business on public.customers;
drop policy if exists customers_select_tenant on public.customers;
drop policy if exists customers_select_own on public.customers;
drop policy if exists customers_insert_same_business on public.customers;
drop policy if exists customers_insert_tenant on public.customers;
drop policy if exists customers_insert_own on public.customers;
drop policy if exists customers_update_same_business on public.customers;
drop policy if exists customers_update_tenant on public.customers;
drop policy if exists customers_update_own on public.customers;
drop policy if exists customers_delete_same_business on public.customers;
drop policy if exists customers_delete_tenant on public.customers;
drop policy if exists customers_delete_own on public.customers;

drop policy if exists conversations_select_same_business on public.conversations;
drop policy if exists conversations_select_tenant on public.conversations;
drop policy if exists conversations_select_own on public.conversations;
drop policy if exists conversations_insert_same_business on public.conversations;
drop policy if exists conversations_insert_tenant on public.conversations;
drop policy if exists conversations_insert_own on public.conversations;
drop policy if exists conversations_update_same_business on public.conversations;
drop policy if exists conversations_update_tenant on public.conversations;
drop policy if exists conversations_update_own on public.conversations;
drop policy if exists conversations_delete_same_business on public.conversations;
drop policy if exists conversations_delete_tenant on public.conversations;
drop policy if exists conversations_delete_own on public.conversations;

drop policy if exists messages_select_same_business on public.messages;
drop policy if exists messages_select_tenant on public.messages;
drop policy if exists messages_select_own on public.messages;
drop policy if exists messages_insert_same_business on public.messages;
drop policy if exists messages_insert_tenant on public.messages;
drop policy if exists messages_insert_own on public.messages;
drop policy if exists messages_update_same_business on public.messages;
drop policy if exists messages_update_tenant on public.messages;
drop policy if exists messages_update_own on public.messages;
drop policy if exists messages_delete_same_business on public.messages;
drop policy if exists messages_delete_tenant on public.messages;
drop policy if exists messages_delete_own on public.messages;

drop policy if exists appointments_select_same_business on public.appointments;
drop policy if exists appointments_select_tenant on public.appointments;
drop policy if exists appointments_insert_same_business on public.appointments;
drop policy if exists appointments_insert_tenant on public.appointments;
drop policy if exists appointments_update_same_business on public.appointments;
drop policy if exists appointments_update_tenant on public.appointments;
drop policy if exists appointments_delete_same_business on public.appointments;
drop policy if exists appointments_delete_tenant on public.appointments;

alter table public.businesses enable row level security;
alter table public.business_members enable row level security;
alter table public.products enable row level security;
alter table public.customers enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.appointments enable row level security;

create policy businesses_select_owner_or_member
on public.businesses for select to authenticated
using (private.is_business_user(id));

create policy businesses_insert_owner
on public.businesses for insert to authenticated
with check (owner_id = auth.uid());

create policy businesses_update_owner
on public.businesses for update to authenticated
using (owner_id = auth.uid())
with check (owner_id = auth.uid());

create policy businesses_delete_owner
on public.businesses for delete to authenticated
using (owner_id = auth.uid());

create policy members_select_business_user
on public.business_members for select to authenticated
using (private.is_business_user(business_id));

create policy members_insert_owner
on public.business_members for insert to authenticated
with check (exists (
  select 1 from public.businesses b
  where b.id = business_members.business_id and b.owner_id = auth.uid()
));

create policy members_update_owner
on public.business_members for update to authenticated
using (exists (
  select 1 from public.businesses b
  where b.id = business_members.business_id and b.owner_id = auth.uid()
))
with check (exists (
  select 1 from public.businesses b
  where b.id = business_members.business_id and b.owner_id = auth.uid()
));

create policy members_delete_owner
on public.business_members for delete to authenticated
using (exists (
  select 1 from public.businesses b
  where b.id = business_members.business_id and b.owner_id = auth.uid()
));

create policy products_select_business_user
on public.products for select to authenticated
using (private.is_business_user(business_id));

create policy products_insert_business_user
on public.products for insert to authenticated
with check (private.is_business_user(business_id));

create policy products_update_business_user
on public.products for update to authenticated
using (private.is_business_user(business_id))
with check (private.is_business_user(business_id));

create policy products_delete_business_user
on public.products for delete to authenticated
using (private.is_business_user(business_id));

create policy customers_select_business_user
on public.customers for select to authenticated
using (private.is_business_user(business_id));

create policy conversations_select_business_user
on public.conversations for select to authenticated
using (private.is_business_user(business_id));

create policy conversations_delete_business_user
on public.conversations for delete to authenticated
using (private.is_business_user(business_id));

create policy messages_select_business_user
on public.messages for select to authenticated
using (exists (
  select 1 from public.conversations c
  where c.id = messages.conversation_id
    and private.is_business_user(c.business_id)
));

create policy appointments_select_business_user
on public.appointments for select to authenticated
using (private.is_business_user(business_id));

create policy appointments_insert_business_user
on public.appointments for insert to authenticated
with check (private.is_business_user(business_id));

create policy appointments_update_business_user
on public.appointments for update to authenticated
using (private.is_business_user(business_id))
with check (private.is_business_user(business_id));

create policy appointments_delete_business_user
on public.appointments for delete to authenticated
using (private.is_business_user(business_id));

commit;
