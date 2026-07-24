-- Promote the selected CROPWAT soil seeds into an inspectable structured table.
-- These rows remain provisional and are not Bangladesh field observations.

create table if not exists public.soil_water_profile (
  record_id text primary key,
  soil_class text not null,
  profile_name text not null,
  total_available_moisture_mm_per_m numeric not null check (
    total_available_moisture_mm_per_m > 0
  ),
  max_rain_infiltration_mm_per_day numeric not null check (
    max_rain_infiltration_mm_per_day > 0
  ),
  local_observation boolean not null,
  source_id text not null references public.agri_source(id),
  source_locator text not null,
  curation_status text not null,
  safety_status text not null,
  confidence text not null,
  unique (soil_class, profile_name)
);

alter table public.soil_water_profile enable row level security;
revoke all on table public.soil_water_profile from anon, authenticated;
grant all on table public.soil_water_profile to service_role;
