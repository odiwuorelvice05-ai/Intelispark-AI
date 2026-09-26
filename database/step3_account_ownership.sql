-- Intelispark AI — account ownership for the account-first onboarding flow.
-- Run once in the Supabase SQL editor before creating real workspaces.

alter table public.businesses
  add column if not exists owner_id uuid references auth.users(id) on delete cascade;

create index if not exists businesses_owner_id_idx
  on public.businesses(owner_id);

-- Existing mock/test businesses can remain ownerless. New authenticated
-- workspaces created by the frontend always receive the signed-in user's id.
-- RLS hardening for this and every other tenant-scoped table the dashboard
-- queries directly now lives in database/step4_rls_hardening.sql -- run it
-- (after reading its own review notes) before trusting this in production.
