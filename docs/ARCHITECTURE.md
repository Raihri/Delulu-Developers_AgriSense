# AgriSense AI — Tier 0 Architecture

> **Status note (2026-07-25):** The Tier-0 contract below is implemented for the
> declared Rabi judge slice. Tier-1 memory, weather alerts, input scheduling,
> conservative pest screening and scenario comparison are also implemented on
> the same saved plan. The detailed current acceptance matrix is in
> `docs/TIER0_GAP_ANALYSIS.md`.

**Team:** Delulu Developers · **Project:** AgriSense AI
**Goal of Tier 0:** From a short conversation, produce a *grounded, explained, costed
season plan* for one farm, with a visible agent trace. A single path that runs end to end.

**Implemented checkpoint (2026-07-25):** A runnable FastAPI/Next.js application,
validated source registry, machine-readable Boro rice/maize/lentil/wheat data,
Supabase Postgres/pgvector adapters, coordinate-to-ADM3 lookup, Bogura Sadar
administrative AEZ candidates, live Open-Meteo weather, FAO-56 daily water
balance, consent-gated editable finance, and automated tests. The maintained
conversation path ranks maize, lentil and wheat for Rabi, chooses a crop, builds
a fully dated land-preparation-to-harvest plan, retrieves crop-specific
agronomic chunks before rendering advice, emits per-recommendation `based_on`
records and persists full bounded tool traces. It also produces Tier-1 memory,
forecast alerts, input schedules, pest screening and budget/rainfall scenarios.
Missing limiting factors, unsupported seasons, unassessed paddy water and weak
RAG retrieval still fail closed. Local environment files are ignored and
excluded from Docker; provider-side rotation and any published-history cleanup
remain repository-owner operations.

---

## 1. Guiding Principles (read first — they explain every later decision)

These eight principles are non-negotiable and shape every module:

1. **The engine decides; the LLM orchestrates and explains.** Recommendations and
   numbers come from deterministic, inspectable functions over retrieved data — never
   from LLM recall. The LLM maps fuzzy input to structured input, chooses which tools to
   call, and narrates results. It does not invent facts, forecasts, or rankings.

2. **Explanation by construction, not by generation.** Every decision emits a structured
   `provenance` record *at the moment it is made*. Human explanations (#6) and the agent
   trace (#8) are two renderings of that same record. We never reconstruct reasoning after
   the fact.

3. **Store the truth compactly; retrieve knowledge on demand.** A small structured
   **session state** is the source of truth passed to the LLM. The knowledge base is
   retrieved fresh per query. Only sanitized, bounded tool summaries are currently retained
   for the trace; neither raw API dumps nor source documents enter the prompt or session.

4. **Two kinds of knowledge, two stores.** Structured numbers (rates, yields, suitability
   ratings, calendar offsets) live in **lookup tables** and are queried exactly. Prose
   guidance lives in a **vector store** and is retrieved semantically. Both are "the
   knowledge base."

5. **No invented numbers, ever.** If a tool fails, degrade gracefully and say so. Every
   number in the final plan must be traceable to either a real tool call or an inspectable
   formula.

6. **Version data before trusting it.** A public homepage is not a dataset. Every source is
   pinned to a document or dataset version, hashed when downloaded, checked for licensing,
   and assigned a stable `source_id`. Every normalized row and RAG chunk keeps a locator back
   to the page, table, section, or API field that produced it.

7. **Units and uncertainty are data, not display details.** Store canonical units, the
   original value/unit, geographic and temporal scope, and confidence. Conversions happen in
   one tested boundary layer. Rounding happens only in the UI.

8. **One authority per fact type.** Source precedence is explicit and machine-readable.
   Similar statements are not blended. A conflict is quarantined for review, not averaged or
   silently corrected.

---

## 2. System Overview & Data Flow

A single farmer request flows through a chain of dependent steps. Each step reads/writes
the shared **session state** and appends to the **trace log**.

```
  Farmer message
        │
        ▼
 ┌───────────────────┐
 │ 1. INTAKE         │  LLM structured-output → fill 7 slots (enums + inference)
 │  (conversational) │  Ask targeted follow-ups only for missing/ambiguous fields
 └─────────┬─────────┘
           │ profile complete
           ▼
 ┌───────────────────┐
 │ 2. WEATHER        │  geocode + P-code → 16-day forecast + historical baseline
 │                   │  → derive daily features, ET₀ and effective rainfall
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 3. CROP REC       │  viability checks → numeric water balance → limiting-factor score
 │                   │  → rank ≥3 crops (suitability, water need, risk, rough profit)
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 4. SEASON PLAN    │  structured phenology template → anchor → DAS/observed-GDD engine
 │                   │  → confirmed near-term + provisional long-term calendar
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 5. FINANCIALS     │  unit-aware editable line-items (rate×area×price) → cost/revenue,
 │  (pure function)  │  net profit, ROI, break-even (yield & price)
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 6. REASONING      │  narrate the provenance records collected by 2–5
 └─────────┬─────────┘
           ▼
        Response  ──────────►  UI renders plan + #8 TRACE panel (sanitized tool evidence)

  Cross-cutting:  #7 KNOWLEDGE BASE (tables + vector RAG) feeds 3/4/5.
                  SOURCE REGISTRY + RAW/NORMALIZED/CURATED layers feed the KB.
                  SESSION STATE (Supabase Postgres) persists everything, keyed by user/session.
                  TRACE LOG records every tool call for #8.
```

**Key integration fact:** capabilities 3, 4, 5 all consume the weather snapshot (2) and the
knowledge base (7); 6 and 8 both render the provenance emitted by 2–5. This is why the build
is one integrated spine, not eight bolted-on features.

The diagram is the Tier-0 target. At the implemented checkpoint, live weather retrieval is
part of `/plan/preview` and emits a sanitized trace. Geospatial resolution, water balance,
financial projection, structured lookup and cited retrieval remain callable APIs.
`/plan/preview` composes reviewed location, season-filtered assessment, cited season
operations and opt-in financials, then persists a compact preview and traces every
computation it called. Non-paddy water scoring still fails closed when starting root-zone
depletion or irrigation scheduling is absent; paddy scoring additionally requires its
dedicated ponding/percolation inputs.

---

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Fastest path for agents + data |
| LLM | Any function-calling model (Claude / GPT-4-class) | Structured output + orchestration |
| Agent orchestration | Lightweight custom loop (or a minimal framework) | Full control of the tool-call → trace flow |
| Weather API | **Open-Meteo** (forecast + historical archive) | Forecast, ET₀ and a defined historical baseline |
| Vector store (current) | **Supabase pgvector** through a constrained RPC | Persistent filtered retrieval without a second database |
| Embeddings | Deterministic 192-d demo vectors now; tested multilingual model next | Replace vector generation only after Bengali/English evaluation; keep pgvector storage |
| Structured KB | **Supabase Postgres** tables, seeded from reviewed CSV/YAML | Exact relational joins plus managed persistence |
| Source registry | YAML + content hashes | Pins title/version/licence/access metadata before ingestion |
| Session/persistence DB | **Supabase Postgres** | Shared team environment, Auth/RLS path, managed backups |
| Units/money | `decimal.Decimal` plus explicit conversion constants | Prevent currency-rounding errors in the implemented slice |
| PDF/HTML extraction | `pdfplumber`, stdlib HTML cleaning, `pdftoppm`/Tesseract OCR fallback | Image-only and legacy-font sources fail closed pending review |
| Validation/testing | Pydantic + pytest + registry/manifest validators | Schema, hash, provenance, quarantine and formula quality gates |
| Backend API | FastAPI | Streams turns + serves trace to UI |
| Frontend | Any (React/plain) — keep it light | Chat + editable financial dashboard + trace panel. **Do not over-invest in UI** (judges say so). |

---

## 4. Shared Data Structures (the backbone)

### 4.1 Session State (source of truth, persisted to Supabase Postgres)

```json
{
  "session_id": "uuid",
  "farmer_id": "uuid",              // enables consented Tier-1 identity linkage
  "turn_count": 7,
  "profile": {
    "location_name": "Bogura",
    "coords": { "lat": 24.85, "lon": 89.37 },
    "admin": { "adm2_pcode": "BD5010", "adm3_pcode": "BD501020" },
    "farm_size": {
      "original": { "value": 2.0, "unit": "acre" },
      "canonical": { "value": 2.0, "unit": "acre" }
    },
    "soil": {
      "type": "clay loam",
      "evidence": "farmer_reported",
      "confidence": "medium"
    },
    "water": {
      "source": "surface water nearby",
      "reliability": "year-round",
      "irrigation_capacity_mm_per_week": 35,
      "capacity_evidence": "farmer_estimate",
      "security_label": "high"
    },
    "budget": { "value": 60000, "currency": "BDT", "basis": "total_season" },
    "season": "Kharif-2"            // enum, see 5.1
  },
  "weather_snapshot": {
    "source": "open-meteo",
    "fetched_at": "2026-07-24T10:30:00+06:00",
    "expires_at": "2026-07-24T16:30:00+06:00",
    "forecast_window": { "start": "2026-07-24", "end": "2026-08-08" },
    "daily": [
      {
        "date": "2026-07-24",
        "tmin_c": 26.1,
        "tmax_c": 32.4,
        "rain_mm": 12.0,
        "et0_mm": 3.7
      }
    ],
    "next_7d": { "rain_mm": 82, "effective_rain_mm": 61, "et0_mm": 29 },
    "historical_baseline": {
      "period": "1991-2020",
      "dataset": "ERA5-Land",
      "season_rain_mm": 1150
    },
    "degraded": false
  },
  "knowledge_version": "2026-07-24.1",
  "chosen_crop": "rice",
  "crop_ranking": [ /* CropScore[] from 5.3 */ ],
  "plan": { "calendar": [ /* CalendarEvent[] from 5.4 */ ] },
  "financials": { /* Financials from 5.5 */ },
  "provenance": [ /* ProvenanceRecord[] — collected across steps */ ]
}
```

**What is passed to the LLM each turn:** system prompt + this state (compact JSON) +
last N messages + freshly retrieved RAG for the current query. **Never** the raw API dumps,
the full RAG corpus, or the whole trace.

### 4.2 Provenance Record (powers BOTH #6 explanation and #8 trace)

Emitted by every decision-making step. One shape, two renderings.

```json
{
  "id": "prov-uuid",
  "output_path": "plan.calendar[2].action",
  "recommendation": "Apply 45 kg/acre urea by 2026-08-05",
  "inputs": [
    { "name": "soil_type", "value": "clay loam", "evidence": "farmer_reported" },
    { "name": "growth_stage", "value": "vegetative", "das": 18 },
    { "name": "forecast_rain_2026-08-05_to_2026-08-07", "value": 0, "unit": "mm",
      "trace_id": "trace-weather-uuid" }
  ],
  "sources": [
    { "source_id": "barc_frg_2024", "locator": "page/table to be curated" }
  ],
  "formula": { "id": "fertilizer_schedule", "version": "1.0.0" },
  "confidence": "high"
}
```

### 4.3 Trace Record (append-only log, rendered in the #8 panel)

Written by the tool-call wrapper for *every* external call, retrieval, and computation.

```json
{
  "id": "trace-weather-uuid",
  "parent_id": null,
  "step": 3,
  "tool": "open-meteo.forecast",
  "type": "external_api",          // external_api | rag_retrieval | computation
  "tool_version": "1.0.0",
  "status": "success",
  "params_in": { "lat": 24.85, "lon": 89.37, "days": 16, "timezone": "Asia/Dhaka" },
  "raw_output_ref": "trace-payloads/sha256.json",
  "raw_output_sha256": "sha256",
  "display_output": { "daily.precipitation_sum[12:15]": [0.0, 0.0, 0.0] },
  "timestamp": "2026-07-24T10:30:12+06:00",
  "duration_ms": 240,
  "redactions": []
}
```

---

## 5. Capability Specifications (the eight Tier-0 items)

### 5.1 — Conversational Intake

**Done when:** From a vague opening message, the agent collects at minimum **location, farm
size, soil type, water availability, budget, target season**, asking targeted follow-ups only
for fields still missing.

**Design:** No rigid form. Each turn, an LLM structured-output (function) call parses the
farmer's free text into the profile schema, fills known slots, and the controller asks only
for genuinely missing/ambiguous fields. Fuzzy fields use small controlled enums. Defaults
that can materially change crop choice, fertilizer, irrigation or money are never silently
invented; they remain flagged assumptions until the farmer confirms them.

**Field models:**

| Field | Type | Canonical values / rule | "Don't know" fallback |
|---|---|---|---|
| location | string → coords + P-code | geocode with `countryCode=BD`, show ambiguous matches, then spatially join to HDX COD | required; ask again |
| farm_size | number + original unit + canonical acres | value + {acre, bigha, hectare}; preserve the farmer's unit | required; ask again |
| soil_type | enum + evidence + confidence | `sandy`, `loamy`, `clay`, `sandy loam`, `clay loam`, `silt loam` | ask drainage question; map-derived values are low-confidence regional priors |
| water_source | enum | `rain-fed only`, `irrigation (tubewell/pump)`, `surface water nearby (river/canal/pond)` | required for water budgeting |
| water_reliability | enum | `year-round`, `seasonal`, `scarce` | ask one targeted follow-up |
| irrigation_capacity | number + unit | prefer `mm/week`; accept pump hours/discharge and convert | unknown is allowed but lowers confidence |
| budget | number + currency + basis | value, `BDT`, {total_season, per_acre} | ask once: total or per-acre |
| season | enum | `Rabi` (Nov–Mar), `Kharif-1` (Mar–Jun), `Kharif-2` (Jul–Oct) | **pre-fill from current date**, confirm |

**Area conversion:** never apply one universal `bigha → acre` conversion. Ask which local
definition the farmer uses, or show the assumed conversion for confirmation. Store both the
original quantity and canonical acres.

**Water model at intake:** keep source/reliability as descriptive fields, but capture or
derive a numeric irrigation capacity where possible. `high/medium/low` is a presentation
label calculated from the later water balance; it is not an input to agronomic formulas.

**Season pre-fill:** map current month → season enum and *confirm* rather than ask cold
(e.g. July → "Planning for the current Kharif-2 season, right?").

**Output:** a completed `profile` in session state. Every inferred field is flagged so the
trace/explanation notes it was inferred, not stated.

---

### 5.2 — Live Weather Grounding

**Done when:** The agent calls a real weather API using the farm's location and uses the
actual returned values (rainfall, temperature) in its recommendations. No invented forecasts.

**Pipeline:** `resolve location → fetch forecast + historical baseline → derive daily
features → cache evidence → cite downstream`.

1. **Resolve location:** call Open-Meteo geocoding with `countryCode=BD`, require the farmer
   to choose if multiple matches are plausible, then spatially join the coordinates to the
   versioned HDX Bangladesh COD boundaries. Store lat/lon plus ADM P-codes; do not join
   agronomic tables on free-text place names. HDX v03 supplies English administrative names
   only, so Bengali aliases live in a reviewed `admin_alias` table keyed by P-code.
   **HDX geometry does not resolve AEZ.** A farm coordinate may resolve to AEZ only through
   a licensed, versioned AEZ polygon layer. Until that layer is available, the demo can
   return reviewed ADM3-level AEZ *candidates* from `admin_aez_crosswalk`. The current
   Bogura Sadar fallback returns AEZ 3, 25 and 27 and explicitly sets
   `point_aez_resolved=false`; it must never select one candidate for the farm.
2. **Fetch two windows** (a 16-day forecast can't cover a 4-month crop):
   - **Short-term forecast** — imminent, task-level advice (e.g. "no rain in 3 days → apply urea"):
     ```
     https://api.open-meteo.com/v1/forecast
       ?latitude={lat}&longitude={lon}
       &daily=temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration
       &forecast_days=16&timezone=auto
     ```
   - **Historical baseline** — query the archive endpoint for a defined baseline such as
     1991–2020 ERA5-Land. Store the dataset, period, resolution and aggregation logic.
     Historical reanalysis is a seasonal prior, not a forecast or plot-level observation.
3. **Derive features:** before moving raw JSON out of session state, compute the daily series
   needed downstream: Tmin/Tmax, rain, ET₀, effective rainfall, heat units and threshold
   flags. A single `avg_temp_c` is insufficient for GDD or stage-level water calculations.
4. **Store evidence safely:** sanitized raw payload → trace payload store with hash; compact
   daily features and baseline → `weather_snapshot`. Store `fetched_at`, `expires_at`, model,
   timezone, units and requested window.
5. **Reliability:** use explicit timeouts, bounded exponential retries, response validation
   and a coordinate/time-window cache. If live forecast fails, mark near-term advice
   unavailable or stale; historical normals may support broad suitability but must not be
   presented as a live forecast.

**Consumers:** #3 (suitability), #4 (sowing date, GDD, task overlay), #6 (explanations).

---

### 5.3 — Crop Recommendation

**Done when:** The agent ranks **at least 3 candidate crops** for the profile, season, and
weather, each with **suitability, water need, risk level, and a rough profit estimate**.

**Brain = deterministic scoring over the knowledge base; LLM only explains.** Ranking must be
reproducible and traceable. Minimise free parameters (judges scrutinise weights).

**Method — three layers, almost no magic weights:**

1. **Viability checks (separate eligibility from ranking):** mark a crop ineligible where
   the selected target season, survivable temperature, or soil evidence makes it
   agronomically invalid. Do not silently discard records. Keep exclusions with their
   reasons, and validate at ingestion time that the curated catalog can produce at least
   three candidates for every supported season. If fewer than three eligible crops remain,
   show the best three assessed candidates but clearly label ineligible ones rather than
   fabricating suitability.

2. **FAO limiting-factor scoring (Liebig's Law of the Minimum — no weights):** For each
   surviving crop, compute per-factor suitability classes from **retrieved tables**, then take
   the **minimum** (a crop is only as good as its worst factor):
   ```
   suitability(crop) = min(soil_score, water_score, weather_score, season_score)
   ```
   Each sub-score maps to FAO classes **S1** (highly suitable) → **S2** (moderately) →
   **S3** (marginally) → **N** (not suitable). Sub-scores are **looked up**, not invented:
   - soil_score ← curated SRDI/BARI crop-vs-soil/AEZ evidence
   - water_score ← stage-level crop water deficit vs numeric irrigation capacity
   - weather_score ← crop temp/rainfall tolerance vs weather_snapshot
   - season_score ← crop calendar vs profile.season

   **Water calculation:** FAO-56 Rev.1 (2025) is the method authority. CROPWAT 8 crop
   files may seed Kc/stage values only and cannot override the revised method.
   ```
   ETc_stage = Kc_stage × ET0_stage
   TAW = 1000 × (theta_FC - theta_WP) × root_depth
   RAW = depletion_fraction × TAW
   Dr_i = Dr_(i-1) - (P - runoff) - net_irrigation - capillary_rise
          + ETc_actual + deep_percolation
   ```
   Effective rainfall is the rainfall retained in the daily root-zone balance after
   explicit runoff and deep percolation; a fixed percentage is forbidden. Irrigation inputs
   are net infiltrated millimetres by default. Gross irrigation requires an explicit
   efficiency, and there is no hidden default. Missing runoff may fall back to zero only
   with a `provisional_assumption` warning in provenance.

   The demo's water-class thresholds are a transparent project policy, not an FAO rule:
   stress-day fraction `≤0.05 → S1`, `≤0.15 → S2`, `≤0.30 → S3`, otherwise `N`. They remain
   provisional and uncalibrated for Bangladesh. The paddy CROPWAT file has a different
   structure; Boro rice water scoring fails closed until land-preparation water, ponding,
   percolation/seepage, field losses and local net irrigation are curated. Potential ETc may
   be shown separately but is not a suitability score.

3. **Soft tie-breaker (the ONLY place weights appear):** among already-suitable crops, rank by
   a small profit-vs-risk preference (2–3 weights), **exposed in the UI as sliders**, with a
   one-line sensitivity note. This reframes weights as a transparent user preference, not a
   hidden constant.

**Per-crop output contract (values below show missing-state behavior, not agronomic
defaults):**
```json
{
  "crop": "boro_rice",
  "suitability": "unassessed",
  "water_class": "unassessed_paddy_model",
  "rough_profit_estimate": null,
  "ranking_status": "not_ranked_until_all_limiting_factors_are_available",
  "missing": ["plot soil evidence", "paddy water inputs", "weather class"]
}
```

Rough profit uses a cited yield and dated price where available. The current editable
financial assumptions require `allow_assumptions=true` and are never represented as observed
market data.

---

### 5.4 — Season Plan

**Done when:** For the chosen crop, the agent produces a **dated calendar** from land
preparation to harvest (sowing window, fertilizer timing, irrigation, weed/pest checkpoints,
harvest).

**Not a raw RAG fetch.** RAG gives a generic, *relative* calendar; #4 needs a *dated,
farm-specific* one. Pipeline: **template → anchor → compute → overlay**.

1. **Load phenology template (structured Type-A tables):** growth stages, standard
   operations and relative timing in **days-after-sowing (DAS)**. Use RAG only for
   explanatory prose; dates and rates must come from validated rows. The template schema is
   `{crop_id, variety_id, stage_id, start_das, end_das, operation, source_id,
   source_locator}`. Do not seed stage numbers merely to make the calendar render.
2. **Anchor the sowing date:** if the sowing window overlaps the live forecast, choose a
   suitable date that avoids sourced weather thresholds. If it lies beyond the forecast
   horizon, use the local crop calendar plus historical baseline and mark the date
   `provisional`; do not claim that a future dry window was forecast.
3. **Compute absolute dates (date engine):**
   - **Baseline:** `event_date = sowing_date + DAS`.
   - **Observed GDD:** after sowing, update stage transitions from observed/reanalysis daily
     temperatures:
     `GDD = Σ max(0, (Tmax+Tmin)/2 − T_base)`. Beyond the live forecast, project stages using
     the historical baseline and mark them provisional. Never extrapolate a 16-day forecast
     across the whole season.
4. **Weather overlay (shift only forecast-grounded tasks):** apply the trigger ruleset
   using **live forecast values** vs **RAG/ruleset thresholds**:
   - don't schedule nitrogen right before heavy rain (runoff) → shift +N days;
   - add irrigation checkpoints during forecast dry spells;
   Re-evaluate an event when it enters the forecast horizon. This is also the seed of Tier-1
   proactive advice.

**Output — structured, cited calendar (each event carries its provenance):**
```json
[
 {"date":null,"stage":"sowing","action":"awaiting curated sowing anchor",
  "status":"blocked_missing_input","source_ids":[],"trace_ids":[]}
]
```

---

### 5.5 — Financial Projection

**Done when:** An itemized cost breakdown plus expected yield, revenue, net profit, ROI, and
break-even. The math is **inspectable and internally consistent** — change an input, outputs
change correctly.

**Note on market price:** live/real-time market price is **Tier 2**, intentionally out of
scope. Sale price and input costs are **seeded, editable assumptions**. This is fine — #5 only
requires correct, reactive math, not live prices. **README must label prices as
user-set/seeded assumptions, not live market data** (satisfies the real-vs-mock disclosure).

**Design — editable line-items + a pure recompute function:**

1. **Seed defaults from the KB, keep every field editable.** Retrieve typical per-unit costs
   (urea/DAP per kg, seed rate & price, labor, irrigation) and typical yield & farmgate price
   from Type-A tables; pre-fill; the farmer can override any value from the dashboard.
2. **Model rates and totals separately.** Each cost declares whether its quantity is
   `per_acre` or `total`; normalize once and then compute. Each line stores quantity, unit,
   price, subtotal, assumption flag and source locator; this document does not seed a price.
3. **Pure calculation engine** `financials(inputs) → outputs` uses `Decimal` for money and a
   tested conversion boundary for dimensional checks. The dashboard holds editable
   state and re-runs this function on every change (single source of truth). Same function
   powers Tier-1 scenario simulation later — for free.

**Derived metrics (all recompute live):**
```
area_acres                    = normalize(farm_size)
yield_kg_per_acre             = normalize(expected_yield)
total_yield_kg                = yield_kg_per_acre × area_acres
total_cost_bdt                = Σ line_item.subtotal_bdt
revenue_bdt                   = total_yield_kg × sale_price_bdt_per_kg
net_profit_bdt                = revenue_bdt − total_cost_bdt
roi_ratio                     = net_profit_bdt / total_cost_bdt
break_even_yield_kg_per_acre  = total_cost_bdt / (sale_price_bdt_per_kg × area_acres)
break_even_price_bdt_per_kg   = total_cost_bdt / total_yield_kg
```

**Optional integration touch:** if crop suitability (5.3) was marginal (S3), nudge the default
`expected_yield` toward the low end of the retrieved range — connects #5 back to #3.

**Output — `Financials` shape (nulls below mean the caller has not opted into assumptions):**
```json
{
  "currency": "BDT",
  "assumption_gate": "not_accepted",
  "line_items": [],
  "total_cost": null,
  "sale_price": null,
  "revenue": null,
  "net_profit": null,
  "roi_ratio": null,
  "break_even_yield": null,
  "break_even_price": null
}
```
After explicit opt-in or user edits, store full precision and round only for display.

---

### 5.6 — Explained Reasoning

**Done when:** Every recommendation states the specific farm inputs and retrieved data it
rests on.

**Explanation by construction, not generation.** The reasoning already exists as the
`provenance` records emitted by 5.2–5.5. The LLM's *only* job is to **verbalize a `based_on`
record** into fluent language — it must not add any reason not present in the record.

```
input  → { "recommendation": "Apply 45 kg/acre urea by Aug 5",
           "based_on": { soil, stage, weather, source } }
LLM out → "Apply 45 kg/acre urea by Aug 5, because your soil is clay loam, the rice is
           in vegetative stage, no rain is forecast this week, and the Fertilizer
           Recommendation Guide recommends top-dressing at 15–20 days after sowing."
```

**Guarantee:** because the LLM is constrained to the structured `based_on` fields, it cannot
drift. **A template renderer is a valid, fully-faithful fallback** if the LLM is slow or
unavailable — the LLM only buys fluency, not correctness. Explainability must **originate in
the data flow**, not the model.

---

### 5.7 — Knowledge Base with RAG

**Done when:** Relevant agronomic data is collected from publicly available sources and built
into a knowledge base; the agent retrieves from it, and crop/fertilizer/season advice is
grounded in what it retrieves — not model recall.

**Three ingestion layers → two query stores:**

1. **Raw:** immutable source snapshots named by `source_id`, version and SHA-256. Never
   silently replace a downloaded file.
2. **Normalized:** extracted rows/chunks with canonical units, bilingual labels, geographic
   keys and source locators.
3. **Curated:** records that pass schema checks and human spot-checks. Only curated data may
   drive recommendations.

The registry at `backend/kb/sources.yaml` is the allowlist. A source must have an exact URL, title,
publisher, version/date, access date, licence status, content hash when downloaded, language,
geographic scope and three independent states: `download_status`, `curation_status` and
`safety_status`. Generic organization homepages are discovery links, not ingestible assets.
`backend/kb/source_registry.schema.json`, `backend/kb/curation_manifest.yaml` and
`python -m kb.validate` enforces the registry shape, local hashes, curated schemas,
row counts, provenance, duplicate assets and quarantines.

**Source precedence (enforced policy):**

1. FAO-56 Rev.1 is the formula/method authority.
2. CROPWAT files are provisional parameter seeds only.
3. BARC FRG owns fertilizer rates and application timing.
4. BRRI owns rice-variety facts.
5. BARI owns detailed non-rice agronomy once its text is safely curated.
6. AIS owns the national calendar and concise extension guidance.
7. SRDI supplies soil/AEZ priors; HDX supplies administrative geometry/P-codes.
8. BBS owns area/production/yield statistics, not agronomy, prices or costs.
9. Project financial assumptions are last-resort editable demo inputs and require opt-in.

The machine-readable rule is `backend/kb/curated/source_precedence.yaml`. Similar facts are not
averaged or copied across tables; unresolved conflicts enter
`data_quality_quarantine.yaml`.

**Type A — structured numbers → Supabase Postgres lookup tables.** Consumed by scoring (5.3), date
(5.4) and cost (5.5). Every current row carries `source_id`, `source_locator`,
`curation_status` and its fact-specific dimensions; numeric rows also retain unit/basis,
geographic scope and confidence where applicable. The next schema version adds uniform
`valid_from`/`valid_to` and original/canonical value envelopes.

Implemented demo tables:

- `admin_alias` and `admin_aez_crosswalk`;
- `crop_variety`, `crop_soil_suitability`, `crop_water_stage`,
  `soil_water_profile` and `crop_calendar`;
- `fertilizer_recommendation`, `yield_baseline` and `cost_baseline`;
- `source`, `build_metadata`, `session`, `trace` and `rag_chunk`.

`soil_water_profile` contains the selected CROPWAT Light/Medium/Heavy soil seeds as
explicitly provisional, non-local rows. It never masquerades as a laboratory result or a
Bangladesh calibration.

Still required before the full Tier-0 contract: a licensed point-resolvable AEZ polygon
layer, `crop_temp_tolerance`, locally reviewed Kc/root-zone inputs and initial depletion, a complete season-plan
operation table and dated market/input-price observations. Pesticide data remains Tier 1
and blocked until the DAE cancellation/status overlay is applied.

Seeded prices remain editable assumptions unless a cited, dated price source is integrated.
Do not place price in the same record as agronomic yield.

**Type B — prose guidance → pgvector.** The implemented slice stores five reviewed,
bilingual/cited chunks and deterministic vectors in Supabase Postgres. This proves persistence,
metadata filtering and citation flow while explicitly setting
`semantic_model_claimed=false`; it is not represented as a production semantic embedding
model. A future multilingual embedding model changes vector generation, not the storage backend.

Ingestion pipeline:

1. **Collect sources** (publicly available, Bangladesh-relevant): DAE crop production guides,
   BARI/BRRI manuals, the **Fertilizer Recommendation Guide (FRG)**, FAO crop water/calendar
   docs, soil & yield references.
2. **Extract text:** `pdfplumber` for text/tables, a narrow HTML cleaner for AIS, and
   `pdftoppm` + Tesseract for image-only pages. Legacy/malformed Bengali detection sends the
   BARI handbook to OCR or a separately reviewed Bijoy/legacy-font converter; malformed
   glyphs never enter RAG.
3. **Chunk with metadata:** ~300–500 tokens per chunk, tagged
   `{crop, variety, topic, source_id, version, page, section, language, licence}`.
4. **Review before promotion:** table extracts and OCR records start as
   `needs_human_review`; only explicit human promotion can produce `human_reviewed`.
5. **Store:** text, metadata and vector live in Supabase `rag_chunk`; similarity search is
   exposed only through the bounded `match_rag_chunks` RPC.
6. **Retrieve → ground:** combine the current local vector/lexical score with crop/topic
   filters and return only cited chunks. If nothing relevant retrieves, say so; never fall
   back to model recall. Bengali and English citation tests are blocking.

**Two things that win the 12 points:** (a) **curated beats huge** — a small clean tagged
corpus retrieves better; (b) **make retrieval visible** — surface retrieved chunks + source in
the #8 trace so judges see the advice came from the FRG chunk, not the model.

---

### 5.8 — Visible Agent Trace

**Done when:** The interface exposes a trace of every tool call — parameters sent and raw
values returned — so a judge can confirm a number in the plan came from a real call, not the
model's imagination.

**The trace is a byproduct of instrumentation, not a feature built at the end.**

1. **Wrap every tool call in a tracer** (decorator). Applies to weather, geocoding, spatial
   joins, RAG retrieval, scoring, water balance, date engine and financial engine. Each
   appends a `TraceRecord` (see 4.3) with inputs, status, tool/formula version and output
   evidence.
2. **Log all three step types:** `external_api` (params + raw response), `rag_retrieval`
   (query + returned chunks + sources), `computation` (inputs + formula + result). Every number
   in the final plan must have a matching trace entry.
3. **Sanitize before persistence/display:** redact API credentials, tokens and farmer PII.
   Keep the agronomic values unchanged. Large raw responses live outside the main Postgres row
   and are referenced by immutable hash; apply retention and size limits.
4. **Render as an expandable side panel / log view:** collapsed by default, one row per step
   (`tool → params → evidence → source/formula version`), click to expand sanitized JSON.
   A live-updating log during the conversation is the most demo-friendly.
5. **Build for traceability:** the plan says "82 mm rain"; the trace shows the Open-Meteo call
   whose `precipitation_sum` values sum to 82. That one-to-one link between claim and raw value
   *is* the point of #8.

**Reuse:** the trace and the #6 provenance are the same data, two views (prose for farmer,
structured log for judge). Instrument once, render twice.

---

## 6. Persistence & Session Context

**Store the truth compactly; retrieve knowledge on demand.** Separate *what is stored* from
*what is passed to the LLM*.

- **What is passed to the LLM each turn:** system prompt + compact **session state** (4.1) +
  last N messages + freshly retrieved RAG for the current query. Nothing else.
- **What is NOT passed:** RAG chunks (retrieved fresh from the vector adapter; only source ids kept for
  trace), raw API/tool dumps (logged for #8, only summarized in state), old conversation turns
  (summarized into state).

**Storage split:**

| Data | Store | Notes |
|---|---|---|
| farmer, session, messages, plan, financial snapshots | **Supabase Postgres** | Auth-linked rows protected by RLS |
| vector corpus (Type B) | **Supabase pgvector `rag_chunk`** | retrieved through bounded RPC |
| structured curated tables (Type A) | **Supabase Postgres** | foreign keys to source/version and geographic keys |
| source registry | versioned YAML | allowlist, licence and ingestion status |
| raw/normalized source assets | content-addressed files | immutable build-time inputs; never fetched in a farmer turn |
| trace metadata | **Supabase Postgres** | sanitized values protected by user/session RLS |
| large trace payloads | Supabase Storage or content-addressed object storage (later) | bounded retention; no credentials or unnecessary PII |

**Supabase Postgres schema (minimum):**
```sql
agri_source(id, publisher, title, version, url, licence, accessed_at,
            download_status, curation_status, safety_status, sha256, metadata)
farmer_profile(id, user_id, profile_json, created_at, updated_at)
farmer_session(id, user_id, state_json, created_at, updated_at)
trace_record(id, session_id, user_id, step, tool, tool_version, trace_type,
             status, params_json, display_output_json, created_at)
rag_chunk(chunk_id, content, crop, topic, source_id, source_locator,
          metadata, embedding vector(192))
build_metadata(key, value, updated_at)
```

The migration also creates the nine curated lookup tables with source foreign keys,
uniqueness constraints, RLS/grants and the bounded `match_rag_chunks` function. Reference
tables are accessible only through server credentials. Farmer/session/trace rows have future
authenticated-owner policies. The secret or legacy service-role key never leaves the
FastAPI/seeding environment. The backend can use either the Supabase Data API with that key
or a direct TLS Postgres connection. The direct URL is also used by the checked-in migration
command and is never a frontend variable.

**Tier-0 vs Tier-1:** within-session memory only needs the session state. Cross-session
memory additionally requires a stable farmer identity, consent, data-retention behavior and
safe profile merging. Supabase enables shared persistence and Auth/RLS, but persistence alone
does not make Tier-1 memory
correct or private.

---

## 7. Implemented Module / File Layout

```
backend/
├── app.py                     # health, source, retrieval, geo, water, finance, weather APIs + /demo
├── config.py                  # paths + validated API/direct Supabase server settings
├── db.py                      # selects the configured backend transport
├── postgres.py                # narrow direct Postgres table/RPC adapter
├── agent/
│   ├── schemas.py             # deterministic plan-preview request/response contract
│   ├── controller.py          # location, assessment, season plan, finance + safe persistence
│   └── tracing.py             # compact, sanitized computation-trace summaries
├── intake/
│   └── parser.py              # explicit chat-field extraction; no fabricated facts
├── kb/
│   ├── registry.py            # YAML allowlist loader
│   ├── validate.py            # status/schema/hash/manifest/provenance/quarantine gates
│   ├── migrate.py             # hash-tracked direct Supabase migration
│   ├── build.py               # reviewed CSV/JSONL → validated Supabase upserts
│   ├── verify.py              # exact counts, metadata and cited vector smoke check
│   ├── vector_store.py        # Supabase pgvector/RPC adapter
│   └── ingest.py              # HTML/PDF/table/OCR extraction + human-review gate
├── state/
│   └── store.py               # sessions, consented farmer profiles and bounded traces
├── tools/
│   ├── weather.py             # live Open-Meteo forecast
│   ├── geo.py                 # coordinate → HDX ADM3 + aliases/AEZ candidates
│   ├── water_balance.py       # FAO-56 Rev.1 daily balance
│   ├── financials.py          # opt-in editable budget assumptions
│   ├── ranking.py             # same-season limiting-factor ranking
│   ├── season_plan.py         # dated land-preparation-to-harvest plan
│   └── advanced.py            # alerts, input schedule, pest risk and scenarios
├── agent/
│   └── advice.py              # deterministic based_on explanation renderer
├── kb/
│   ├── sources.yaml           # registry v2 with three independent statuses
│   ├── source_registry.schema.json
│   ├── curation_manifest.yaml
│   └── curated/               # reviewed tables, precedence, water policy, quarantine
├── tests/                      # API, data, geo, water, finance, ingestion, retrieval
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── supabase/migrations/        # Postgres schema, pgvector RPC, RLS and grants

dataset/                         # ignored downloaded source assets kept at repo root
frontend/                        # maintained Next.js judge UI; proxies server-side
docs/DEMO_RUNBOOK.md             # exact Bogura demo script and honest limitations
```

Conversational intake uses Gemini structured output to map natural farmer
phrases to canonical enums. Every accepted field requires an exact conversation
quote and adequate confidence; unsupported values are discarded and probed
rather than guessed. The deterministic narrative layer renders only
recommendations backed by structured inputs and crop-specific retrieved chunks.

---

## 8. Build Order (24-hour path)

Continue in dependency order:

1. **Delivered:** source registry v2, exact local hashes, schema/manifest validation,
   quarantine policy and the reviewed three-crop data slice.
2. **Delivered:** FastAPI/Supabase adapter, source/curated-table seed, session/trace tables,
   bilingual cited retrieval, Open-Meteo weather integrated into preview, HDX ADM3 join and
   Bogura alias/AEZ fallback.
3. **Delivered with explicit limits:** FAO-56 daily water balance, provisional non-rice
   CROPWAT seeds, paddy fail-closed behavior, opt-in editable financial assumptions and
   formula/API/data tests.
4. **Delivered:** deterministic `/plan/preview` composition of reviewed location, live
   weather, season-filtered assessments, cited season operations, missing/unassessed gates
   and opt-in financials. Drainage and laboratory soil fertility are never defaulted.
5. **Delivered with explicit limits:** generated/accepted opaque preview session IDs,
   compact reloadable derived state and sanitized traces for every computation the preview
   actually calls. A browser trace panel and authenticated ownership are still next.
6. **Next:** curate local crop-temperature and water parameters; add a licensed
   point-resolvable AEZ layer; calibrate or replace project water thresholds.
7. **Next:** complete limiting-factor ranking and support three genuinely assessable crops
   for the same declared season/window.
8. **Delivered with explicit limits:** cited crop-calendar/fertilizer helper; only maize
   numeric DAS ranges become dates, while all unsupported timing remains provisional.
9. **Next:** add broader sowing anchors, DAS/GDD engine and forecast overlay.
10. **Next:** integrate dated farmgate/input prices, narrative renderer and trace UI.
11. **Final gate:** run golden-farm end-to-end scenarios and label every value real, inferred,
   stale, provisional or assumed.

**Definition of done for Tier 0:** a single conversation takes a farmer from a vague opening
message to a grounded, explained, costed, dated season plan for one crop, with every number
traceable in the panel to a real tool call or an inspectable formula — and it runs cleanly in
the demo. The current checkpoint is runnable but has not yet met this full definition.

---

## 9. Data Quality and Acceptance Gates

The build fails closed if curated data does not satisfy these checks:

- registry v2 fields and the three status vocabularies are valid;
- all local source and curated-manifest hashes match;
- required curated columns, row counts, source IDs, locators and `human_reviewed` status pass;
- duplicate paths or byte-identical source assets fail the build;
- FRG path/page/hash, HDX 507 unique ADM3 P-codes/English metadata and BBS quarantine pass;
- fertilizer rates preserve soil-test/yield-target/nutrient/unit dimensions;
- financial formulas pass area-scaling, unit-conversion, break-even and zero-cost guards;
- RAG golden queries return a relevant cited chunk in both Bengali and English;
- gross irrigation without efficiency and paddy water scoring fail closed.

Before declaring full Tier 0, add blocking gates for weather dates/units/freshness, three
fully assessable same-window crop candidates, complete fertilizer geographic context,
season-plan operations and one-to-one provenance/trace coverage for every output number.

Every KB build writes a quality report and a version. The application loads only a build that
passed all blocking gates.

---

## 10. Licensing, Safety and Freshness

- Public access does not automatically grant redistribution rights. `backend/kb/sources.yaml`
  records licence status, and assets with unknown or restricted terms are not committed or
  re-published without permission.
- GADM is reference-only unless its non-commercial/redistribution restrictions fit the
  deployment; prefer the direct HDX Bangladesh COD dataset for P-codes and boundaries.
- Plantwise content has content-specific licences. Ingest only items whose licence permits
  the intended use, and retain attribution.
- Pesticide advice must be checked against a dated DAE registration/cancellation source.
  Prefer integrated pest management, show active ingredient and legal status, and never add
  a dosage, pre-harvest interval or safety claim absent from the cited source.
- BBS 2024 carrot Table 3.9.29 is quarantined because the expected 2023-24 heading and values
  repeat 2022-23. Exclude it until verified; never silently relabel or repair the values.
- The BBS registry notes that a 2025 edition is available, while the pinned local build still
  uses the reviewed 2024 asset.
- Scheduled source checks report broken links and newer editions. Updates create a new
  dataset version and require quality gates; they do not mutate a released KB in place.

---

## 11. What NOT to Do (from the brief)

- Do not build the full 14-feature marketplace/escrow vision. Core first, tiers only when the
  layer beneath works.
- Do not demo a flashy feature (e.g. payment gateway) while the crop recommendation ignores the
  weather it just fetched — judges will notice the disconnect.
- Do not over-invest in UI/UX (explicitly low-weight).
- Do not invent numbers. Every figure traces to a tool call or a formula.
