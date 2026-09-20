import os

# The API module builds a Supabase client at import time; tests replace it with a fake before any request.
os.environ.setdefault("SUPABASE_URL", "https://abc.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.x")
