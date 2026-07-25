-- Canonical, database-backed farm projects.
-- Farmer profiles keep a small project index for portable memory, while this
-- table makes ownership, lifecycle state and linked sessions directly visible.

create table if not exists public.farm_project (
  id text primary key,
  farmer_id uuid not null references public.farmer_profile(id) on delete cascade,
  name text not null check (char_length(name) between 2 and 80),
  status text not null default 'draft' check (
    status in ('draft', 'intake', 'planning', 'active', 'archived')
  ),
  access_mode text not null check (access_mode in ('farm', 'guest')),
  intake_session_id text references public.farmer_session(id) on delete set null,
  plan_session_id text references public.farmer_session(id) on delete set null,
  project_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists farm_project_farmer_updated_idx
  on public.farm_project (farmer_id, updated_at desc);
create index if not exists farm_project_status_idx
  on public.farm_project (status);

drop trigger if exists set_farm_project_updated_at on public.farm_project;
create trigger set_farm_project_updated_at
before update on public.farm_project
for each row execute function public.set_updated_at();

alter table public.farm_project enable row level security;
revoke all on table public.farm_project from anon, authenticated;
grant all on table public.farm_project to service_role;
