-- Intelispark AI — Step 2 product knowledge layer
-- Run this once in the Supabase SQL editor.

create table if not exists public.products (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null,
  brand text,
  category text not null default 'phone',
  variant text,
  condition text not null default 'new',
  price numeric(12,2),
  stock_quantity integer not null default 0 check (stock_quantity >= 0),
  description text,
  specs jsonb not null default '{}'::jsonb,
  installment_available boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists products_business_idx on public.products(business_id);
create index if not exists products_name_idx on public.products using gin (to_tsvector('simple', coalesce(name, '')));

-- Optional trigger keeps updated_at current.
create or replace function public.set_products_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists products_updated_at on public.products;
create trigger products_updated_at
before update on public.products
for each row execute function public.set_products_updated_at();
