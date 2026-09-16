-- Intelispark AI — account ownership for the account-first onboarding flow.
-- Run once in the Supabase SQL editor before creating real workspaces.

alter table public.businesses
  add column if not exists owner_id uuid references auth.users(id) on delete cascade;

create index if not exists businesses_owner_id_idx
  on public.businesses(owner_id);

-- Existing mock/test businesses can remain ownerless. New authenticated
-- workspaces created by the frontend always receive the signed-in user's id.
-- RLS policies are intentionally not enabled here because the existing
-- product/customer policies should be audited together before production use.
