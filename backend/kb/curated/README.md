# Curated demo slice

This directory contains the reviewed, machine-readable facts allowed to drive the
AgriSense demo. The supported slice is deliberately narrow:

- Boro rice: BRRI dhan28, dhan29 and dhan97 variety facts; medium-soil-test
  fertilizer rows for dhan28 and dhan29.
- Rabi maize: national calendar, soil guidance, provisional CROPWAT stage
  parameters, medium-soil-test fertilizer rows and a national yield baseline.
- Rabi lentil: national calendar, soil guidance, a provisional CROPWAT Pulses
  proxy, medium-soil-test fertilizer rows and a national yield baseline.

Every agronomic row has a registered `source_id` and a page, table, section or
asset locator. `curation_status=human_reviewed` is required before a row can enter
the build. Missing facts remain missing; they are not filled from model memory.

Important boundaries:

- CROPWAT crop files are parameter seeds, not Bangladesh observations.
- `soil_water_profile.csv` contains generic CROPWAT soil hydraulic seeds. These
  are used only to check whether a non-paddy assessment has the minimum profile
  inputs; they are not local soil-test results or calibrated Bangladesh values.
- The generic Pulses file is only a provisional lentil proxy.
- The CROPWAT rice file uses a paddy-specific format. Rice water suitability is
  therefore `unassessed` until land preparation, ponding, percolation and local
  irrigation inputs are curated.
- The Bogura Sadar AEZ crosswalk returns candidates 3, 25 and 27 at ADM3
  resolution. It cannot resolve a farm point to one AEZ.
- Financial rows are editable demo assumptions. The API refuses to use them
  unless `allow_assumptions=true`.
- BBS 2024 carrot Table 3.9.29 is quarantined and excluded from every build.

Run `python -m kb.validate` to verify source hashes, registry fields,
curated schemas, provenance and quarantine rules. Run
`python -m kb.build` to upsert the reviewed slice into the migrated
Supabase Postgres/pgvector project configured in `.env`.

Crop calendars, fertilizer rates, yields, costs, crop-stage values, soil
hydraulic profiles and administrative mappings remain structured data. RAG is
reserved for cited explanatory text rather than exact numeric facts.
