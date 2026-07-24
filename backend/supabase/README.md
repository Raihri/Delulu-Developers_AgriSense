# Supabase setup

1. Create a Supabase project.
2. Copy `.env.example` to `.env` and set the backend-only
   `SUPABASE_DB_URL`.
3. Install dependencies, migrate, seed and verify the reviewed data:

   ```bash
   cd backend
   cp .env.example .env
   pip install -r requirements-dev.txt
   python -m kb.validate
   python -m kb.migrate
   python -m kb.build
   python -m kb.verify
   uvicorn app:app --reload
   ```

As an alternative, apply `migrations/202607240001_agrisense.sql` in the SQL
editor or with `supabase db push`, then configure `SUPABASE_URL` plus a
backend-only `SUPABASE_SECRET_KEY` for seed/runtime calls. A legacy
`SUPABASE_SERVICE_ROLE_KEY` is also accepted.

Direct `db.<project-ref>.supabase.co` hosts are IPv6 by default. If the machine
running these commands is IPv4-only, copy the exact **Session pooler** URL
(port 5432) from Dashboard → Connect and use that as `SUPABASE_DB_URL`.
Alternatively, retain the direct URL and set `SUPABASE_DB_POOLER_HOST` to the
exact Session pooler hostname. It is non-secret; the backend derives the pooled
username and keeps the password solely in the original URL.

The migration enables pgvector, defines the curated/reference, session and trace
tables, installs the `match_rag_chunks` RPC, enables RLS and denies direct
anonymous access. Direct database URLs and secret/service keys are server-only;
never expose or commit them.
