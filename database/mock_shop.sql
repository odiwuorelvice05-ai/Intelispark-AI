-- Intelispark AI mock electronics shop for Step 2 testing.
-- Run step2_products.sql first.
-- Safe to use only in a development/test Supabase project.

insert into public.businesses (id, name, industry, description, timezone)
values (
  '11111111-1111-1111-1111-111111111111',
  'Nairobi Mobile Hub',
  'phone_electronics',
  'Mock electronics shop used to test Intelispark AI product intelligence.',
  'Africa/Nairobi'
)
on conflict (id) do update set
  name = excluded.name,
  industry = excluded.industry,
  description = excluded.description,
  timezone = excluded.timezone;

insert into public.products
  (id, business_id, name, brand, category, variant, condition, price, stock_quantity, description, specs, installment_available)
values
  ('21111111-1111-1111-1111-111111111111', '11111111-1111-1111-1111-111111111111', 'Galaxy A15', 'Samsung', 'phone', '8GB/256GB', 'new', 24500, 8, 'Affordable Samsung phone with strong battery and AMOLED display.', '{"ram":"8GB","storage":"256GB","camera":"50MP","battery":"5000mAh","display":"6.5 AMOLED"}', true),
  ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'Galaxy A15', 'Samsung', 'phone', '4GB/128GB', 'refurbished', 17500, 3, 'Test refurbished option for customers seeking a lower price.', '{"ram":"4GB","storage":"128GB","camera":"50MP","battery":"5000mAh","display":"6.5 AMOLED"}', true),
  ('23333333-3333-3333-3333-333333333333', '11111111-1111-1111-1111-111111111111', 'iPhone 13', 'Apple', 'phone', '128GB', 'new', 68000, 4, 'Apple smartphone with strong camera performance and premium build.', '{"storage":"128GB","camera":"12MP dual","battery":"all-day","display":"6.1 OLED"}', false),
  ('24444444-4444-4444-4444-444444444444', '11111111-1111-1111-1111-111111111111', 'Redmi Note 13', 'Xiaomi', 'phone', '8GB/256GB', 'new', 28500, 6, 'High-value Android phone with a high-resolution display and large storage.', '{"ram":"8GB","storage":"256GB","camera":"108MP","battery":"5000mAh","display":"6.67 AMOLED"}', true),
  ('25555555-5555-5555-5555-555555555555', '11111111-1111-1111-1111-111111111111', 'Nokia C32', 'Nokia', 'phone', '4GB/128GB', 'new', 14500, 10, 'Budget phone for customers prioritising affordability and battery life.', '{"ram":"4GB","storage":"128GB","camera":"50MP","battery":"5000mAh","display":"6.5"}', true)
on conflict (id) do update set
  price = excluded.price,
  stock_quantity = excluded.stock_quantity,
  condition = excluded.condition,
  specs = excluded.specs,
  installment_available = excluded.installment_available,
  updated_at = now();

-- Mock customer. If your existing customers table has additional required fields,
-- add them here before running this seed.
insert into public.customers (id, business_id, name, phone)
values (
  '31111111-1111-1111-1111-111111111111',
  '11111111-1111-1111-1111-111111111111',
  'Test Customer',
  '+254700000000'
)
on conflict (id) do update set name = excluded.name, phone = excluded.phone;
