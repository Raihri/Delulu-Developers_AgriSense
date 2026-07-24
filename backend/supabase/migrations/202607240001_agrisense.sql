-- AgriSense Supabase foundation.
-- Apply with `supabase db push` or paste into the Supabase SQL editor once.

create extension if not exists vector with schema extensions;
create extension if not exists pgcrypto with schema extensions;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create table public.agri_source (
  id text primary key,
  publisher text not null,
  title text not null,
  url text,
  asset_type text not null,
  version text not null,
  accessed_at date not null,
  language text not null,
  geography text not null,
  topics text[] not null default '{}',
  download_status text not null,
  curation_status text not null,
  safety_status text not null,
  licence text not null,
  redistribution_allowed boolean not null,
  machine_readable text not null,
  sha256 text,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default timezone('utc', now()),
  constraint agri_source_download_status check (
    download_status in ('downloaded', 'live_api', 'not_downloaded', 'not_applicable')
  ),
  constraint agri_source_safety_status check (
    safety_status in (
      'approved', 'provisional', 'blocked',
      'approved_with_quarantine', 'licence_restricted'
    )
  )
);

create table public.admin_alias (
  record_id text primary key,
  adm_level text not null,
  pcode text not null,
  canonical_name_en text not null,
  alias text not null,
  language text not null,
  alias_type text not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_status text not null,
  confidence text not null,
  unique (pcode, alias, language)
);

create table public.admin_aez_crosswalk (
  record_id text primary key,
  adm3_pcode text not null,
  adm3_name_en text not null,
  aez_id integer not null,
  resolution text not null,
  review_status text not null,
  coverage_note text not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_status text not null,
  confidence text not null,
  unique (adm3_pcode, aez_id)
);

create table public.crop_variety (
  record_id text primary key,
  crop_id text not null,
  variety_id text not null,
  variety_name text not null,
  season text not null,
  duration_min_days integer,
  duration_base_days integer,
  duration_max_days integer,
  yield_min_t_ha numeric,
  yield_base_t_ha numeric,
  yield_max_t_ha numeric,
  trait text,
  geographic_scope text not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_method text not null,
  curation_status text not null,
  confidence text not null,
  unique (crop_id, variety_id, season)
);

create table public.crop_soil_suitability (
  record_id text primary key,
  crop_id text not null,
  variety_id text not null,
  soil_class text not null,
  drainage_condition text not null,
  suitability_class text not null,
  geographic_scope text not null,
  authority_role text not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_method text not null,
  curation_status text not null,
  confidence text not null,
  unique (crop_id, variety_id, soil_class, drainage_condition)
);

create table public.crop_water_stage (
  record_id text primary key,
  crop_id text not null,
  parameter_basis text not null,
  stage text not null,
  stage_order integer not null,
  duration_days integer not null,
  kc_start numeric not null,
  kc_end numeric not null,
  root_depth_start_m numeric not null,
  root_depth_end_m numeric not null,
  local_observation boolean not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_status text not null,
  safety_status text not null,
  confidence text not null,
  unique (crop_id, parameter_basis, stage)
);

create table public.crop_calendar (
  record_id text primary key,
  crop_id text not null,
  season text not null,
  sow_start_month integer not null,
  sow_end_month integer not null,
  harvest_start_month integer not null,
  harvest_end_month integer not null,
  window_text text not null,
  geographic_scope text not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  precision_source_id text references public.agri_source(id),
  precision_source_locator text,
  curation_method text not null,
  curation_status text not null,
  confidence text not null,
  unique (crop_id, season, geographic_scope)
);

create table public.fertilizer_recommendation (
  record_id text primary key,
  crop_id text not null,
  variety_id text not null,
  soil_test_class text not null,
  yield_target_t_ha numeric not null,
  nutrient text not null,
  rate_min numeric not null,
  rate_max numeric not null,
  canonical_unit text not null,
  application_timing text not null,
  geographic_scope text not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_status text not null,
  confidence text not null,
  unique (
    crop_id, variety_id, soil_test_class, yield_target_t_ha,
    nutrient, canonical_unit
  )
);

create table public.yield_baseline (
  record_id text primary key,
  crop_id text not null,
  variety_id text not null,
  season text not null,
  stat_year text not null,
  geographic_scope text not null,
  area_acres numeric not null,
  production_mt numeric not null,
  canonical_yield_t_ha numeric not null,
  derivation text not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_status text not null,
  confidence text not null,
  unique (crop_id, variety_id, season, stat_year, geographic_scope)
);

create table public.cost_baseline (
  record_id text primary key,
  crop_id text not null,
  item_type text not null,
  item text not null,
  quantity_per_acre numeric not null,
  quantity_unit text not null,
  unit_price_bdt numeric not null,
  cost_per_acre_bdt numeric not null,
  basis_date date not null,
  geographic_scope text not null,
  editable boolean not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_status text not null,
  safety_status text not null,
  unique (crop_id, item_type, item, basis_date, geographic_scope)
);

create table public.rag_chunk (
  chunk_id text primary key,
  content text not null,
  crop text,
  topic text,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  metadata jsonb not null,
  embedding extensions.vector(192) not null,
  updated_at timestamptz not null default timezone('utc', now())
);

create index rag_chunk_embedding_hnsw
  on public.rag_chunk using hnsw (embedding extensions.vector_cosine_ops);
create index rag_chunk_crop_topic_idx on public.rag_chunk (crop, topic);

create table public.build_metadata (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.farmer_profile (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid unique references auth.users(id) on delete cascade,
  profile_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.farmer_session (
  id text primary key,
  user_id uuid references auth.users(id) on delete cascade,
  state_json jsonb not null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.trace_record (
  id uuid primary key default extensions.gen_random_uuid(),
  session_id text references public.farmer_session(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  step text not null,
  tool text not null,
  tool_version text not null,
  trace_type text not null,
  status text not null,
  params_json jsonb not null,
  display_output_json jsonb not null,
  created_at timestamptz not null default timezone('utc', now())
);

create index farmer_session_user_idx on public.farmer_session (user_id);
create index trace_record_session_idx on public.trace_record (session_id, created_at);
create index trace_record_user_idx on public.trace_record (user_id, created_at);

create trigger farmer_profile_set_updated_at
before update on public.farmer_profile
for each row execute function public.set_updated_at();

create trigger farmer_session_set_updated_at
before update on public.farmer_session
for each row execute function public.set_updated_at();

create or replace function public.match_rag_chunks(
  query_embedding extensions.vector(192),
  match_count integer default 5,
  filter_crop text default null,
  filter_topic text default null
)
returns table (
  chunk_id text,
  content text,
  metadata jsonb,
  similarity double precision
)
language sql
stable
set search_path = public, extensions
as $$
  select
    r.chunk_id,
    r.content,
    r.metadata,
    1 - (r.embedding <=> query_embedding) as similarity
  from public.rag_chunk r
  where (filter_crop is null or r.crop = filter_crop)
    and (filter_topic is null or r.topic = filter_topic)
  order by r.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 20);
$$;

-- Reference/KB tables are backend-only. The secret/service key bypasses RLS;
-- it must never be exposed in frontend code.
do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'agri_source',
    'admin_alias',
    'admin_aez_crosswalk',
    'crop_variety',
    'crop_soil_suitability',
    'crop_water_stage',
    'crop_calendar',
    'fertilizer_recommendation',
    'yield_baseline',
    'cost_baseline',
    'rag_chunk',
    'build_metadata'
  ]
  loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('revoke all on table public.%I from anon, authenticated', table_name);
    execute format('grant all on table public.%I to service_role', table_name);
  end loop;
end;
$$;

revoke all on function public.match_rag_chunks(
  extensions.vector, integer, text, text
) from public, anon, authenticated;
grant execute on function public.match_rag_chunks(
  extensions.vector, integer, text, text
) to service_role;

alter table public.farmer_profile enable row level security;
alter table public.farmer_session enable row level security;
alter table public.trace_record enable row level security;

revoke all on public.farmer_profile, public.farmer_session, public.trace_record from anon;
grant select, insert, update, delete
  on public.farmer_profile, public.farmer_session, public.trace_record
  to authenticated;
grant all on public.farmer_profile, public.farmer_session, public.trace_record
  to service_role;

create policy farmer_profile_owner_all
on public.farmer_profile
for all to authenticated
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

create policy farmer_session_owner_all
on public.farmer_session
for all to authenticated
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

create policy trace_record_owner_all
on public.trace_record
for all to authenticated
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));
