# AgriSense Tier 0 Gap Analysis

Audit date: 2026-07-25

## Audit basis

This report compares:

1. Tier 0 on page 3 of
   `docs/Agentic_AI_Hackathon_Final_Question.pdf`;
2. the target and implemented-checkpoint claims in
   `docs/ARCHITECTURE.md`; and
3. the current backend, frontend, curated data, migrations and tests.

The PDF defines Tier 0 as one complete path:

> From a short conversation, produce a grounded, explained, costed season plan
> for one farm. All eight capabilities must work end to end.

Status meanings:

- **PASS** - the current application meets the PDF's "done when" condition.
- **PARTIAL** - working components exist, but the strict end-to-end condition is
  not met.
- **MISSING** - the required result is not produced.

## Executive verdict

**AgriSense is not Tier-0 complete yet.**

The current repository is a strong, fail-closed foundation with working intake,
real weather retrieval, curated Supabase tables, financial formulas, limited
season events, RAG retrieval, persistence and a visible trace UI. However, it
does not yet produce the single output Tier 0 requires:

- at least three same-season crops ranked using actual weather values;
- one chosen crop;
- a complete dated land-preparation-to-harvest plan;
- a costed plan by default or after an integrated conversation step;
- per-recommendation explanations grounded in retrieved facts; and
- raw-enough trace evidence that lets a judge reproduce every displayed number.

Strict status at first audit: **1 PASS, 6 PARTIAL, 1 MISSING**.

## Progress update — 2026-07-25

Several decisive Tier-0 blockers have since been closed. The changes are additive
and every existing fail-closed gate is preserved; `python -m kb.validate` returns
zero errors/warnings and the full backend test suite (including new ranking and
ranking-endpoint tests) passes.

- **Three comparable Rabi crops (was the sole MISSING).** Wheat is now curated
  across `crop_calendar`, `crop_soil_suitability`, `crop_water_stage`,
  `fertilizer_recommendation`, `yield_baseline`, `cost_baseline` and
  `rag_chunks`, sourced from the local datasets (FRG 2024 page 75 fertilizer;
  BBS 2024 wheat estimates for yield; AIS calendar + BBS page 39 for the sowing
  and harvest window; WHEAT.CRO for Kc/root seeds). Rabi now offers maize,
  lentil and wheat as genuine same-season candidates.
- **Real weather is now used as weather.** `tools/agro_score.py` reduces the live
  Open-Meteo daily series to the exact values used and builds a daily
  `ETc = Kc x ET0` series from the curated stage coefficients.
- **The FAO-56 water balance feeds the ranking.** For non-paddy crops the daily
  balance consumes real ET0/rain plus explicit starting depletion and irrigation
  inputs (curated per-crop critical depletion `p` from the CROPWAT seeds) and
  returns an S1-N water class. Paddy rice stays unassessed.
- **Deterministic ranking exists.** `tools/ranking.py` orders crops by a
  documented composite (soil 0.40, water 0.40, profit 0.20), returns a chosen
  crop, and still refuses to rank any crop missing a limiting factor. The new
  `POST /plan/rank` endpoint returns a costed, weather-grounded top list with
  reproducible evidence (weather window, water totals, financial assumptions,
  temperature-risk flags with the observed temperatures that triggered them).

The `/plan/rank` path now also:

- **builds a full dated plan for the chosen crop** (`chosen_plan`) — land
  preparation, sowing, CROPWAT stage transitions, irrigation/weed/pest scouting
  checkpoints and a computed harvest date, each with source provenance;
- **carries budget** into the ranking as a per-crop `fits_budget` flag and costs
  every crop by default (editable via the existing `/financials` overrides); and
- **grounds the chosen-crop advice in retrieved RAG chunks** with a relevance
  threshold that withholds prose advice when retrieval is weak.

Separately, the `/plan/preview` trace now records distinct trace types
(`external_api`, `structured_retrieval`, `computation`) and stores the **raw
weather values** (rain, temperature, ET0) a judge must inspect.

The intake conversation and the plan are now **one path**: `POST
/plan/from-conversation` reads the collected profile from the intake session and
feeds it straight into the ranking, failing closed (HTTP 409 with the missing
fields) when the conversation has not yet gathered every minimum field. The
ranking path (`/plan/rank` and `/plan/from-conversation`) also now records a full
tool trace — structured retrieval, the external weather call with raw values, a
per-crop water-balance computation, the ranking computation, the season plan and
the RAG retrieval — retrievable at `/plan/preview/{session_id}/traces`, so every
displayed number is backed by a visible call (capability 8).

Remaining open work: a dedicated per-output `ProvenanceRecord`/`based_on`
renderer (capability 6 is served today by the per-crop `evidence` object rather
than a formal renderer) and replacing the deterministic demo embeddings with a
production semantic model (capability 7). Neither changes the fail-closed
contract.

## Tier 0 capability matrix

| # | PDF requirement | Current implementation | Status | What is still required |
|---|---|---|---|---|
| 1 | Conversational intake collects location, farm size, soil, water, budget and season; asks only for missing fields | Gemini structured extraction, evidence quotes, controlled enums, progressive clarification, live location/Maps, and Supabase turn context are implemented | **PASS** | Carry the collected budget into planning; link intake and plan sessions; optionally collect water reliability/capacity promised by the architecture |
| 2 | Real weather API values are used in recommendations | Open-Meteo returns temperature, rainfall and ET0 and the UI displays them | **PARTIAL** | The recommender currently receives only `weather_available: bool`; it does not consume the returned rainfall or temperature values. Add weather scores, risks and task overlays derived from the actual daily series |
| 3 | Rank at least 3 crops for profile, season and weather, each with suitability, water need, risk and rough profit | `POST /plan/rank` ranks the three Rabi crops (maize, lentil, wheat) by a documented soil/water/profit composite, with a chosen crop and reproducible per-crop evidence; still fail-closed when a factor is missing | **PASS (via /plan/rank)** | Fold the ranking into the conversational preview path and extend beyond the Rabi slice |
| 4 | Chosen crop gets a dated calendar from land preparation through harvest, including fertilizer, irrigation, weed and pest checkpoints | Cited sow/harvest month windows and fertilizer events exist; only maize has two reviewed DAS ranges converted to dates | **PARTIAL** | Add chosen-crop flow, structured operation rows, complete dated events, irrigation, weed/pest checkpoints, harvest date, and weather-aware shifts |
| 5 | Itemized costs, yield, revenue, net profit, ROI and break-even; inputs react correctly | Decimal-based calculations and all required metrics exist, with tests and explicit assumption labels | **PARTIAL** | Finance is off by default, budget is unused, frontend line items are not actually editable, and zero-candidate seasons have no finance. Integrate consent/editing into the conversation-to-plan path |
| 6 | Every recommendation states the farm inputs and retrieved data behind it | The UI shows farm evidence, source lines, missing inputs and unassessed factors | **PARTIAL** | There is no ranked recommendation and no per-output provenance object linking soil, weather, water, source and formula. Implement the architecture's `based_on`/provenance renderer |
| 7 | Public agronomic data is in a KB with RAG, and retrieved content feeds crop, fertilizer and season advice | Structured Supabase KB and five cited RAG chunks work; bilingual retrieval tests pass | **PARTIAL** | `/plan/preview` never performs RAG retrieval and never consumes intake retrieval. Current deterministic hashed vectors are not production semantic embeddings. Trace the retrieved chunks used by advice |
| 8 | UI shows every tool call, parameters and raw returned values so numbers can be verified | A trace page displays saved parameters and compact output summaries | **PARTIAL** | All traces are labelled `computation`; raw weather values are not shown in the trace; RAG/intake/standalone tools are not traced; duration, failures, hashes and one-to-one output-to-trace links are absent |

## The decisive Tier 0 blockers

### P0. One season does not have three comparable crops

Current curated calendar coverage:

| Season | Curated candidates |
|---|---|
| Boro | Boro rice only |
| Rabi | Maize and lentil |
| Kharif 1 | None |
| Kharif 2 | None |

This is why a Kharif 2 farm in Gazipur produces zero assessments. It also means
the current code cannot satisfy Tier 0 capability 3 for any selected season.

Shortest safe path: declare **Rabi** as the demo season and curate one additional
Rabi crop, such as wheat, across the same required tables. The repository already
has a provisional CROPWAT wheat file, but local soil/agronomy, calendar, yield,
cost and operation rows still require review before use.

Evidence:

- `backend/kb/curated/crop_calendar.csv` has only three rows;
- `backend/tools/recommend.py:11` limits the catalog to Boro rice, maize and
  lentil; and
- `backend/tools/recommend.py:59-67` removes crops that do not match the selected
  season.

### P0. Weather is fetched but not used as weather

`backend/agent/controller.py:238` fetches seven daily weather records. At
`backend/agent/controller.py:287`, the recommender receives only whether the
weather request succeeded. Rainfall and temperature values never enter a crop
score, risk label, sowing decision or operation date.

Required:

- pass the daily weather series into the recommendation engine;
- calculate sourced temperature/rain risk flags per crop;
- use actual rainfall/ET0 in water need or explicitly mark the factor missing;
- use forecast values to shift only near-term events whose threshold rules are
  curated; and
- cite the exact weather dates/values used in each result.

### P0. There is no crop ranking

Every assessment currently returns:

`not_ranked_until_all_limiting_factors_are_available`.

The code does not return:

- rank position;
- combined suitability;
- weather suitability;
- water need;
- risk level;
- rough profit in the default assessment response; or
- a winner/chosen crop.

Fail-closed behavior is correct for safety, but it does not satisfy the
hackathon's Tier 0 "done when" condition. The remedy is to complete a narrow,
reviewed same-season slice rather than remove the safety gate.

### P0. The season plan is neither complete nor fully dated

`backend/tools/season_plan.py` currently creates:

- a provisional sow/transplant month window;
- a provisional harvest month window;
- fertilizer events; and
- two maize nitrogen date ranges when a sowing date is supplied.

Missing Tier 0 operations:

- land preparation;
- a dated sow/transplant action;
- irrigation quantity/timing;
- weed checkpoints;
- pest checkpoints;
- crop-stage transitions; and
- a dated harvest action.

The current controller also builds plans for every assessed crop, not only a
farmer-confirmed chosen crop.

### P0. The core path is not costed by default

The financial engine itself is sound and tested, but `/plan/preview` blocks
financials unless `allow_assumptions=true`. The conversation collects
`budget_bdt`, but `PlanPreviewRequest` has no budget field and the frontend does
not send the budget into planning.

Required:

- ask the farmer to accept/edit the seeded assumptions during intake;
- pass budget into the plan;
- show whether each crop fits the budget;
- make cost, yield and sale-price fields actually editable;
- recalculate through the same backend function; and
- generate finance only for the farmer's chosen crop in the final plan.

### P0. RAG is visible but does not ground the plan

`POST /intake/chat` performs RAG retrieval and returns up to three chunks.
`POST /plan/preview` loads structured tables but never calls
`SupabaseVectorStore.search`.

Therefore, the RAG results shown in capability 7 are not inputs to crop,
fertilizer or season-plan advice. Tier 0 explicitly requires retrieved content
to feed the advice.

Safe integration:

1. use structured tables for exact dates, rates, yields and costs;
2. retrieve RAG chunks for explanatory crop/fertilizer/operation guidance;
3. attach selected chunk IDs and source locators to the generated advice;
4. return no prose advice when retrieval is below a relevance threshold; and
5. trace the query, filters, selected chunks and scores.

### P0. Trace summaries are not the raw evidence required by the PDF

The trace UI is implemented, but `weather_trace_output` keeps only:

- source;
- timezone;
- forecast day count;
- field names; and
- first date.

It omits the actual rainfall, temperature and ET0 values that the judge must
inspect. Every record is also stored as `trace_type="computation"`, including the
external weather call and structured retrieval.

Required:

- distinct `external_api`, `rag_retrieval` and `computation` types;
- sanitized request parameters;
- the exact bounded values used downstream;
- formula ID/version and inputs for computed numbers;
- success/failure, duration and freshness;
- source/chunk/table locators; and
- a trace ID on each displayed recommendation, event and financial metric.

## Architecture commitments not implemented

The following items appear as target design or promised data structures in
`docs/ARCHITECTURE.md`, but are not present in the current end-to-end runtime.

### Agent and session flow

- A tool-selecting agent loop. Gemini currently extracts intake fields only; the
  plan controller follows a hard-coded sequence.
- One shared session across intake, weather, recommendation, chosen crop, plan
  and finance. Intake and plan currently use separate sessions without a parent
  link.
- Stored farmer identity/authentication and consented ownership. Tables and RLS
  exist, but runtime writes use no authenticated `user_id`.
- Conversation/message persistence. Compact recognized state is stored, not the
  architecture's farmer/messages/plan history.
- Streaming FastAPI turns. The current endpoints return normal JSON responses.

### Intake model

- Water reliability (`year-round`, `seasonal`, `scarce`).
- Numeric irrigation capacity in mm/week or converted pump/discharge units.
- Budget basis (`total_season` versus `per_acre`).
- Preservation of the farmer's original area unit and reviewed local bigha
  conversion.
- Current-month season prefill followed by confirmation.
- Automatic ambiguous text-location geocoding and farmer selection. Location is
  currently browser geolocation or a Google Maps pin.

### Weather model

- Sixteen-day forecast in the main preview; current preview requests seven days.
- Historical 1991-2020 baseline/archive call.
- Effective rainfall feature in the preview.
- GDD/heat-unit features and crop threshold flags.
- `fetched_at`, expiry/freshness and model metadata.
- Coordinate/time-window cache.
- Explicit bounded retry logic for Open-Meteo.
- Downstream use by ranking and season scheduling.

### Geospatial and soil model

- Licensed point-resolvable AEZ polygons.
- Broad reviewed ADM3-to-AEZ coverage. Only Bogura Sadar is curated.
- Plot-level or reviewed local soil evidence.
- `crop_temp_tolerance`.
- Complete crop-soil/AEZ suitability for the demo crops. Boro has no soil
  suitability row.

### Water and ranking model

- Integration of the existing FAO-56 daily water-balance function into
  `/plan/preview`.
- Initial root-zone depletion or a safe farmer input for it.
- Irrigation amount, timing and efficiency in the plan request.
- Locally reviewed crop Kc/root-depth parameters.
- Paddy land-preparation, ponding, percolation/seepage and field-loss inputs.
- Limiting-factor S1/S2/S3/N score.
- Weather and season scores.
- At least three same-window candidates.
- Profit/risk tie-breaker and UI preference sliders.

### Season-plan engine

- Structured `crop_operation`/phenology table with DAS ranges.
- Farmer-confirmed chosen crop before plan generation.
- Sowing-date anchor selection.
- Full DAS date engine.
- GDD updates using observations/historical baseline.
- Forecast threshold overlay.
- Land preparation, irrigation, weed and pest operations.
- Complete dated harvest.

### Financial model and UI

- Budget integration.
- Editable quantities, unit prices, yield and farmgate price in the frontend.
- Per-acre versus total basis controls.
- Input-level formula trace.
- Dated observed input/farmgate price records. Current values are assumptions.

### Explanation and provenance

- The architecture's `ProvenanceRecord` model.
- An output path and `based_on` record for every recommendation.
- Narrative/template rendering constrained to the provenance record.
- Confidence and assumption labels attached to every output, not only general
  warnings.

### RAG and ingestion

- A tested multilingual semantic embedding model. Current vectors are
  deterministic demo hashes.
- A relevance/no-answer threshold.
- RAG retrieval inside the plan controller.
- RAG trace records.
- A larger reviewed corpus beyond five chunks and two topics.
- Safely curated BARI legacy-Bengali content.
- Broader reviewed BRRI/AIS material.

### Trace implementation

- Automatic wrapper around every external call, retrieval and computation.
- Trace coverage for Gemini intake and its failures/retries.
- Trace coverage for RAG search.
- Trace coverage for standalone geo/water/financial endpoints.
- Raw-output hash/reference storage.
- Duration, parent/child step structure, redaction list and failure records.
- One-to-one trace coverage test for every displayed number.

### Acceptance gates

The architecture lists these as required before full Tier 0, but current
validation does not block the build on them:

- weather date/unit/freshness validation;
- three fully assessable same-window crops;
- complete fertilizer geographic context;
- complete season-plan operations; and
- one-to-one provenance/trace coverage.

## Documentation mismatches to correct

### `docs/ARCHITECTURE.md`

- Correctly admits that full Tier 0 is not met, but mixes target-state diagrams
  with implemented behavior. Add a per-capability status table near the top.
- Says a browser trace panel is "still next" even though the Next.js trace panel
  now exists.
- Uses a Kharif 2 session example although the curated catalog has no Kharif 2
  crop.
- Describes 16-day plus historical weather while the current preview uses seven
  forecast days and no archive baseline.
- Describes an editable finance dashboard, but the frontend currently exposes
  only an assumption checkbox.

### `README.md`

The submission PDF requires a README that states setup, tools/APIs, tier reached,
and real versus mock data. The README has setup and honest boundaries, but needs:

- an explicit Tier 0 capability/status matrix;
- a clear statement that only conversational intake currently passes strictly;
- a table listing real API data, reviewed local data, provisional seeds and mock
  assumptions;
- a warning that no selected season currently has three candidates; and
- the exact judge-ready supported scenario.

### `docs/DEMO_RUNBOOK.md`

- Uses the old FastAPI form demo rather than the required short-conversation
  path.
- Says weather is missing even though `/plan/preview` now fetches live weather.
- Expected trace counts are stale: the integrated preview now normally produces
  seven traces without finance and eight with finance for the unfiltered
  three-crop scenario.
- Its sample payload omits water availability and target season.
- It demonstrates "no fabricated ranking", which is honest but also proves that
  Tier 0 capability 3 is not complete.

### Frontend labels

The UI always says "3 candidates" and "Three transparent crop candidates" even
when the selected season returns zero, one or two. It also leaves maize selected
when Kharif returns zero candidates, causing misleading "no operations" and "no
financial row" messages.

Use a coverage-aware empty state:

- "This season is not yet supported by the reviewed demo corpus";
- show the supported season/crop combinations;
- hide crop-specific timeline/finance panels when there is no candidate; and
- display the backend's zero-candidate warning instead of the generic
  ranking-paused notice.

## What is already implemented well

Do not spend remaining time rebuilding these:

- evidence-checked Gemini intake and targeted clarification;
- browser/map location capture;
- HDX coordinate-to-ADM3 lookup;
- live Open-Meteo call;
- Supabase Postgres/pgvector migration and seed;
- source registry, hashes, quarantine and curation validation;
- structured fertilizer/yield/cost/calendar tables;
- financial formula engine and tests;
- fail-closed paddy and irrigation assumptions;
- compact session persistence;
- cited RAG search;
- trace persistence and a usable trace-panel skeleton;
- broad backend unit/integration coverage; and
- frontend TypeScript correctness.

At audit time:

- all backend tests pass;
- `python -m kb.validate` returns zero errors and warnings; and
- frontend `tsc --noEmit` passes.

## Shortest Tier-0 completion order

1. **Freeze the demo to Rabi and one golden farm.**
2. **Curate one additional Rabi crop** across calendar, soil, water, yield, cost,
   fertilizer and operations so three crops are comparable.
3. **Feed real daily weather values into each crop assessment**, returning
   weather suitability and risk with exact evidence.
4. **Integrate the water balance** for non-paddy crops using explicit initial
   depletion/irrigation inputs; keep unsupported paddy scoring closed.
5. **Return a deterministic top-three ranking** with suitability, water need,
   risk and rough profit.
6. **Ask the farmer to choose a crop.**
7. **Build one complete dated operation template** for that chosen crop.
8. **Carry finance consent, budget and editable assumptions into the chosen-crop
   plan.**
9. **Retrieve and attach RAG guidance** to crop/fertilizer/season explanations.
10. **Upgrade trace records** so every displayed number has exact parameters,
    values, formula/source and trace ID.
11. **Update README, architecture status and demo runbook**, then rehearse the
    four-minute conversation-to-plan path.

## Tier-0 completion acceptance test

A judge should be able to perform one flow and observe all of the following:

1. Start with a vague farmer message.
2. Answer only targeted questions for the remaining minimum fields.
3. See a real forecast retrieved for the selected farm.
4. See at least three crops ranked for the same season.
5. Inspect suitability, water need, risk and rough profit for each crop.
6. Choose one crop.
7. Receive a complete dated plan from land preparation to harvest.
8. Inspect itemized cost, expected yield, revenue, profit, ROI and break-even.
9. Read an explanation that names farm inputs, weather values and cited
   agronomic sources.
10. Expand trace rows and reproduce every displayed number from the exact tool
    values or formula inputs.

Until that flow passes, label the application a **partial Tier-0 prototype**, not
a completed Tier-0 submission.
