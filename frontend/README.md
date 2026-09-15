# Intelispark AI Frontend

The frontend is a lightweight responsive static application with three layers:

- Landing page — public Intelispark AI product experience.
- Auth — Supabase email/password sign-in and account creation.
- Workspace — business dashboard for profile, products, inventory, customers, conversations and AI testing.

## Data flow

`Dashboard → Supabase → Intelispark intelligence`

Business profile and product records are written to the existing `businesses` and `products` tables. Product fields include price, stock, condition, variant, specifications, description and installment availability so the intelligence layer can ground answers in real catalog facts.

## First connection

The browser must use a Supabase **publishable/anon key**, never the service-role key. The connection is stored in browser local storage for the current prototype. The backend URL is also configured in Settings for the AI Lab.

The `products` table must exist. Run `database/step2_products.sql` once in the Supabase SQL editor if it has not already been created.

## Static hosting

This frontend has no Node build step. The root `index.html` redirects to `frontend/`, so it can be served by any static host. For production, move the Supabase connection to a proper environment/build configuration and add RLS policies before onboarding real businesses.
