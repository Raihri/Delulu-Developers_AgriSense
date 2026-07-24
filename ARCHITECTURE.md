# AgriSense AI — Tier 0 Architecture

> **Scope of this document:** Tier 0 (Core, required) only. Every one of the eight
> Tier-0 capabilities from the problem statement is specified as an implementation
> contract. Agronomic constants and source assets still require the curation and acceptance
> gates defined below. Tier 1 / Tier 2 are out of scope, but hooks are noted where a Tier-0
> choice cheaply unlocks a later tier.

**Team:** Delulu Developers · **Project:** AgriSense AI
**Goal of Tier 0:** From a short conversation, produce a *grounded, explained, costed
season plan* for one farm, with a visible agent trace. A single path that runs end to end.

---

## 1. Guiding Principles (read first — they explain every later decision)

These seven principles are non-negotiable and shape every module:

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
   retrieved fresh per query. Raw API/tool dumps are logged for the trace but not fed back
   into the prompt.

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

---

## 2. System Overview & Data Flow

A single farmer request flows through a chain of dependent steps. Each step reads/writes
the shared **session state** and appends to the **trace log**.

```
  Farmer message
        │
        ▼
 ┌───────────────────┐
 │ 1. INTAKE         │  LLM structured-output → fill 6 slots (enums + inference)
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
                  SESSION STATE (SQLite) persists everything, keyed by farmer_id.
                  TRACE LOG records every tool call for #8.
```

**Key integration fact:** capabilities 3, 4, 5 all consume the weather snapshot (2) and the
knowledge base (7); 6 and 8 both render the provenance emitted by 2–5. This is why the build
is one integrated spine, not eight bolted-on features.

---

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Fastest path for agents + data |
| LLM | Any function-calling model (Claude / GPT-4-class) | Structured output + orchestration |
| Agent orchestration | Lightweight custom loop (or a minimal framework) | Full control of the tool-call → trace flow |
| Weather API | **Open-Meteo** (forecast + historical archive) | Forecast, ET₀ and a defined historical baseline |
| Vector store (RAG) | **Chroma** (persistent, in-process) | Zero-config local persistence for the demo |
| Embeddings | `text-embedding-3-small` (hosted) or `multilingual-e5-small`/`bge-m3` (local) | Supports Bengali/English retrieval |
| Structured KB | **SQLite** tables, optionally exported as CSV | Exact relational joins across crop, variety, AEZ, season and source |
| Source registry | YAML + content hashes | Pins title/version/licence/access metadata before ingestion |
| Session/persistence DB | **SQLite** | Zero-config, single file, keyed by farmer_id |
| Units/money | `pint` + `decimal.Decimal` | Prevent dimensional and currency-rounding errors |
| PDF/HTML extraction | `pdfplumber`, `BeautifulSoup`, OCR fallback | English/Bengali KB ingestion |
| Validation/testing | Pydantic/Pandera + pytest/Hypothesis | Schema, range, unit and formula quality gates |
| Backend API | FastAPI | Streams turns + serves trace to UI |
| Frontend | Any (React/plain) — keep it light | Chat + editable financial dashboard + trace panel. **Do not over-invest in UI** (judges say so). |

---

## 4. Shared Data Structures (the backbone)

### 4.1 Session State (source of truth, persisted to SQLite)

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
   agronomic tables on free-text place names.
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

   **Water calculation:**
   ```
   ETc_stage = Kc_stage × ET0_stage
   water_deficit_stage = max(0, ETc_stage - effective_rainfall_stage
                                - available_irrigation_stage)
   ```
   Store the assumptions used for effective rainfall and irrigation efficiency. Never
   compare millimetres directly with a `high/medium/low` label.

3. **Soft tie-breaker (the ONLY place weights appear):** among already-suitable crops, rank by
   a small profit-vs-risk preference (2–3 weights), **exposed in the UI as sliders**, with a
   one-line sensitivity note. This reframes weights as a transparent user preference, not a
   hidden constant.

**Per-crop output:**
```json
{
  "crop": "rice",
  "suitability": "S1",
  "water_need": {
    "etc_mm_season": 1200,
    "effective_rain_mm": 860,
    "estimated_irrigation_deficit_mm": 340
  },
  "risk_level": "medium",
  "rough_profit_estimate": { "value": 18000, "currency": "BDT", "basis": "per acre" },
  "based_on": { "soil": "clay loam→S1", "water": "340 mm deficit→S2",
                "weather": "Kharif-2 rain suits high need", "season": "Kharif-2→S1" }
}
```

Rough profit uses seeded yield × seeded price from the tables (refined in #5).

---

### 5.4 — Season Plan

**Done when:** For the chosen crop, the agent produces a **dated calendar** from land
preparation to harvest (sowing window, fertilizer timing, irrigation, weed/pest checkpoints,
harvest).

**Not a raw RAG fetch.** RAG gives a generic, *relative* calendar; #4 needs a *dated,
farm-specific* one. Pipeline: **template → anchor → compute → overlay**.

1. **Load phenology template (structured Type-A tables):** growth stages, standard
   operations and relative timing in **days-after-sowing (DAS)**. Use RAG only for
   explanatory prose; dates and rates must come from validated rows. Example (rice):
   ```
   stages: sowing(0), vegetative(0–40), tillering(20–40), panicle(40–65),
           flowering(65–90), maturity(90–120)
   ops:    basal fertilizer @0, 1st top-dress @15–20 DAS, 2nd @40–45 DAS,
           irrigation checkpoints, pest scouting windows, harvest @110–120
   ```
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
 {"date":"2026-07-28","stage":"sowing","action":"Sow rice","status":"confirmed",
  "source_ids":["brri_released_varieties"],"trace_ids":["trace-weather-uuid"]},
 {"date":"2026-08-14","stage":"vegetative","action":"1st urea top-dress 25 kg",
  "status":"provisional","source_ids":["barc_frg_2024"],
  "recheck_on":"2026-08-08"}
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
   `per_acre` or `total`; normalize once and then compute:
   ```json
   { "name": "Urea", "rate": 45, "rate_unit": "kg/acre",
     "farm_area": 2, "farm_area_unit": "acre",
     "quantity_total": 90, "quantity_unit": "kg",
     "unit_cost": 27, "unit_cost_unit": "BDT/kg", "subtotal_bdt": 2430 }
   ```
3. **Pure calculation engine** `financials(inputs) → outputs` uses `Decimal` for money and a
   unit library for dimensional checks. The dashboard holds editable
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

**Output — `Financials`:**
```json
{
  "currency": "BDT",
  "farm_area": { "value": 2.0, "unit": "acre" },
  "line_items": [ /* ... */ ],
  "total_cost": 41200,
  "expected_yield": { "value": 2.4, "unit": "t/acre" },
  "total_yield": { "value": 4.8, "unit": "t" },
  "sale_price": { "value": 26, "unit": "BDT/kg", "assumption": true },
  "revenue": 124800, "net_profit": 83600, "roi_ratio": 2.029,
  "break_even_yield": { "value": 0.7923, "unit": "t/acre" },
  "break_even_price": { "value": 8.5833, "unit": "BDT/kg" }
}
```

The example is dimensionally consistent:
`2 acre × 2.4 t/acre × 1000 kg/t × 26 BDT/kg = 124,800 BDT`. Store full precision;
round only for display.

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

The registry at `kb/sources.yaml` is the allowlist. A source must have an exact URL, title,
publisher, version/date, access date, licence status, content hash when downloaded, language,
geographic scope and ingestion status. Generic organization homepages are discovery links,
not ingestible assets.

**Type A — structured numbers → SQLite lookup tables.** Consumed by scoring (5.3), date
(5.4) and cost (5.5). Every row includes `source_id`, `source_locator`, `valid_from`,
`valid_to`, `geographic_scope`, `original_value`, `original_unit`, `canonical_value`,
`canonical_unit`, `curation_status` and `confidence`.

Minimum tables:

- `admin_area` (ADM level, P-code, multilingual names, geometry version)
- `agro_ecological_zone` and `admin_aez_crosswalk`
- `crop_variety` (crop × variety × season/ecosystem → duration, tolerances, yield range)
- `crop_soil_suitability` (crop/variety × soil/AEZ → S1/S2/S3/N)
- `crop_water_stage` (crop × stage → Kc, duration, root depth, depletion fraction)
- `crop_temp_tolerance` (crop/stage → min/opt/max °C)
- `crop_calendar` (crop/variety × season/region → sowing window, DAS/GDD, operations)
- `fertilizer_recommendation` (crop × AEZ/land type/soil-test class/yield target × nutrient
  × stage → rate)
- `yield_baseline` (crop/variety × district × season × year → min/base/max yield)
- `cost_baseline` (item × district × season × year → quantity/price basis)
- `pesticide_registration` (active ingredient/trade name × crop/pest → dose, registration
  status and source date; Tier 1)

Seeded prices remain editable assumptions unless a cited, dated price source is integrated.
Do not place price in the same record as agronomic yield.

**Type B — prose guidance → vector store (Chroma).** Pest/disease management text, agronomic
best-practice paragraphs. Earns the "RAG on top" points. Pipeline:

1. **Collect sources** (publicly available, Bangladesh-relevant): DAE crop production guides,
   BARI/BRRI manuals, the **Fertilizer Recommendation Guide (FRG)**, FAO crop water/calendar
   docs, soil & yield references.
2. **Extract text:** `pdfplumber` (PDF), `BeautifulSoup` (HTML), table extraction where
   appropriate, and Bengali OCR only when the text layer is missing. Store extraction
   warnings; do not silently accept malformed glyphs or merged columns.
3. **Chunk with metadata:** ~300–500 tokens per chunk, tagged
   `{crop, variety, topic, source_id, version, page, section, language, licence}`.
4. **Embed:** `text-embedding-3-small` (hosted) or a tested multilingual local model such
   as `multilingual-e5-small` or `bge-m3`.
5. **Store in Chroma:** vector + text + metadata, persisted to disk.
6. **Retrieve → ground:** combine lexical and vector retrieval, filter by crop/variety/topic
   and supported geography, optionally rerank, then pass only cited chunks to the LLM. If
   nothing relevant retrieves, say so; never fall back to model recall. Bengali and English
   queries must be included in the retrieval evaluation set.

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
   Keep the agronomic values unchanged. Large raw responses live outside the main SQLite row
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
- **What is NOT passed:** RAG chunks (retrieved fresh from Chroma; only source ids kept for
  trace), raw API/tool dumps (logged for #8, only summarized in state), old conversation turns
  (summarized into state).

**Storage split:**

| Data | Store | Notes |
|---|---|---|
| farmer, session, messages, plan, financial snapshots | **SQLite** | encrypt/restrict access where practical |
| vector corpus (Type B) | **Chroma** | retrieved on demand |
| structured curated tables (Type A) | **SQLite** | foreign keys to source/version and geographic keys |
| source registry | versioned YAML | allowlist, licence and ingestion status |
| raw/normalized source assets | content-addressed files | immutable build-time inputs; never fetched in a farmer turn |
| trace metadata | **SQLite** | sanitized display values, status, timings and payload hashes |
| large trace payloads | content-addressed JSON files | bounded retention; no credentials or unnecessary PII |

**SQLite schema (minimum):**
```sql
farmer(id, name, created_at)
session(id, farmer_id, season, created_at, state_json)      -- state_json = compact state
message(id, session_id, role, content, turn, ts)
source(id, publisher, title, version, url, licence, accessed_at, sha256, status)
dataset_version(id, source_id, schema_version, built_at, quality_report_json)
trace(id, session_id, parent_id, step, tool, tool_version, type, status,
      params_json, display_output_json, raw_ref, raw_sha256, ts, duration_ms)
```

**Tier-0 vs Tier-1:** within-session memory only needs the session state. Cross-session
memory additionally requires a stable farmer identity, consent, data-retention behavior and
safe profile merging. SQLite enables it, but persistence alone does not make Tier-1 memory
correct or private.

---

## 7. Module / File Layout

```
agrisense/
├── app.py                     # FastAPI entry: chat endpoint, trace endpoint, dashboard API
├── agent/
│   ├── controller.py          # turn loop: parse → decide tools → call → update state
│   ├── intake.py              # 5.1 structured-output slot filling + enum mapping + inference
│   ├── prompts.py             # system prompt, structured-output schemas
│   └── tracer.py              # 5.8 tool-call decorator → TraceRecord
├── tools/
│   ├── weather.py             # 5.2 geocode + forecast + historical baseline
│   ├── geo.py                 # coordinate → versioned P-code/AEZ joins
│   ├── water_balance.py       # ETc/effective rain/irrigation deficit
│   ├── crop_reco.py           # 5.3 filters + FAO limiting-factor scoring
│   ├── season_plan.py         # 5.4 template → anchor → DAS/GDD engine → weather overlay
│   ├── financials.py          # 5.5 pure financials(inputs) → outputs
│   └── rules.py               # 5.4/5.7 weather/water trigger thresholds + sources
├── kb/
│   ├── sources.yaml           # exact source/version/licence allowlist
│   ├── ingest.py              # raw → normalized → validated/curated
│   ├── schema.py              # normalized row schemas and quality constraints
│   ├── retrieve.py            # hybrid, metadata-filtered retrieval
│   ├── agrisense.db           # curated Type-A tables
│   └── chroma/                # Type B: persisted vector store
├── data/
│   ├── raw/                   # immutable, content-hashed source snapshots
│   ├── normalized/            # extracted canonical records
│   └── curated/               # only reviewed inputs to KB build
├── state/
│   ├── schema.py              # session state, provenance, trace dataclasses (section 4)
│   └── store.py               # SQLite load/save keyed by farmer_id
├── explain/
│   └── narrator.py            # 5.6 provenance → prose (LLM) with template fallback
├── ui/                        # chat + editable financial dashboard + trace panel (keep light)
├── tests/
│   ├── test_financials.py     # dimensions, area scaling, break-even, zero guards
│   ├── test_water_balance.py  # ETc/effective rain/irrigation math
│   ├── test_data_quality.py   # schema, ranges, duplicates, source locators
│   ├── test_retrieval.py      # Bengali/English golden queries and citation checks
│   └── test_golden_farms.py   # end-to-end scenarios across regions/seasons
├── DATA_SOURCES.md            # reviewed human-readable catalog
└── README.md                  # setup, APIs, per-feature tier, real vs mock disclosure
```

---

## 8. Build Order (24-hour path)

Ship one complete feature before adding the next; a core that runs end to end beats ten
half-built features.

1. **Source registry + quality gate** — pin exact sources and licences; define schemas,
   canonical units and a tiny curated dataset for the demo crops.
2. **Skeleton + state + tracer** — session state (4.1), SQLite store, tool-call tracer (5.8).
   Everything else writes into these.
3. **Intake (5.1)** — enums, evidence/confidence and targeted follow-ups.
4. **Weather + geospatial identity (5.2)** — forecast/baseline, P-code join, derived daily
   features and sanitized evidence.
5. **Knowledge base (5.7)** — build Type-A tables first (needed by 3/4/5), then the Chroma
   Type-B pipeline.
6. **Crop rec (5.3)** — numeric water balance + limiting-factor score over curated tables.
7. **Season plan (5.4)** — structured template → anchor → DAS/observed GDD → horizon-aware
   weather overlay.
8. **Financials (5.5)** — unit-aware pure function, editable assumptions and formula tests.
9. **Reasoning (5.6)** — render structured provenance (template first, LLM polish).
10. **Trace panel (5.8 UI)** — verify every plan number links to sanitized evidence.
11. **End-to-end tests + README** — run golden farms; label real, inferred, stale and assumed.

**Definition of done for Tier 0:** a single conversation takes a farmer from a vague opening
message to a grounded, explained, costed, dated season plan for one crop, with every number
traceable in the panel to a real tool call or an inspectable formula — and it runs cleanly in
the demo.

---

## 9. Data Quality and Acceptance Gates

The build fails closed if curated data does not satisfy these checks:

- required fields and source locators are present;
- canonical units are dimensionally compatible and values remain within reviewed ranges;
- crop/variety/admin identifiers resolve through foreign keys;
- duplicate and conflicting rows are reported, never silently overwritten;
- supported seasons each have at least three assessable crop candidates;
- fertilizer rates preserve AEZ/land type/soil-test/yield-target dimensions;
- financial formulas pass area-scaling, unit-conversion, break-even and zero-cost guards;
- weather responses have expected dates/units and are not stale;
- RAG golden queries return a relevant cited chunk in both Bengali and English;
- each final numeric output has a provenance record and trace/formula reference.

Every KB build writes a quality report and a version. The application loads only a build that
passed all blocking gates.

---

## 10. Licensing, Safety and Freshness

- Public access does not automatically grant redistribution rights. `kb/sources.yaml`
  records licence status, and assets with unknown or restricted terms are not committed or
  re-published without permission.
- GADM is reference-only unless its non-commercial/redistribution restrictions fit the
  deployment; prefer the direct HDX Bangladesh COD dataset for P-codes and boundaries.
- Plantwise content has content-specific licences. Ingest only items whose licence permits
  the intended use, and retain attribution.
- Pesticide advice must be checked against a dated DAE registration/cancellation source.
  Prefer integrated pest management, show active ingredient and legal status, and never add
  a dosage, pre-harvest interval or safety claim absent from the cited source.
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
