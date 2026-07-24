# AgriSense AI — Tier 0 Architecture

> **Scope of this document:** Tier 0 (Core, required) only. Every one of the eight
> Tier-0 capabilities from the problem statement is specified here in enough detail
> that an AI coding agent (or a developer) can implement the system end to end without
> further design decisions. Tier 1 / Tier 2 are out of scope, but hooks are noted where
> a Tier-0 choice cheaply unlocks a later tier.

**Team:** Delulu Developers · **Project:** AgriSense AI
**Goal of Tier 0:** From a short conversation, produce a *grounded, explained, costed
season plan* for one farm, with a visible agent trace. A single path that runs end to end.

---

## 1. Guiding Principles (read first — they explain every later decision)

These five principles are non-negotiable and shape every module:

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
 │ 2. WEATHER        │  geocode → forecast + climate (Open-Meteo) → store raw + summary
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 3. CROP REC       │  hard filters → FAO limiting-factor score over retrieved tables
 │                   │  → rank ≥3 crops (suitability, water need, risk, rough profit)
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 4. SEASON PLAN    │  RAG phenology template → anchor sowing date → DAS/GDD date engine
 │                   │  → weather overlay shifts tasks → dated calendar
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 5. FINANCIALS     │  editable line-items (qty×unit×area) → cost, yield, revenue,
 │  (pure function)  │  net profit, ROI, break-even (yield & price)
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ 6. REASONING      │  narrate the provenance records collected by 2–5
 └─────────┬─────────┘
           ▼
        Response  ──────────►  UI renders plan + #8 TRACE panel (all tool calls, raw values)

  Cross-cutting:  #7 KNOWLEDGE BASE (tables + vector RAG) feeds 3/4/5.
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
| Weather API | **Open-Meteo** (forecast + archive) | Free, no API key, no signup |
| Vector store (RAG) | **Chroma** (persistent, in-process) | Zero-config, single-file persistence |
| Embeddings | `text-embedding-3-small` (hosted) or `bge-small` (local) | Cheap, good enough |
| Structured KB | CSV/JSON loaded into memory + queried | Exact lookups, inspectable |
| Session/persistence DB | **SQLite** | Zero-config, single file, keyed by farmer_id |
| PDF/HTML extraction | `pdfplumber`, `BeautifulSoup` | KB ingestion |
| Backend API | FastAPI | Streams turns + serves trace to UI |
| Frontend | Any (React/plain) — keep it light | Chat + editable financial dashboard + trace panel. **Do not over-invest in UI** (judges say so). |

---

## 4. Shared Data Structures (the backbone)

### 4.1 Session State (source of truth, persisted to SQLite)

```json
{
  "session_id": "uuid",
  "farmer_id": "uuid",              // enables Tier-1 cross-session memory for free
  "turn_count": 7,
  "profile": {
    "location_name": "Bogura",
    "coords": { "lat": 24.85, "lon": 89.37 },
    "farm_size": { "value": 2.0, "unit": "acre" },
    "soil_type": "clay loam",       // enum, see 5.1
    "water_security": "high",       // derived score, see 5.1
    "water_source": "surface water nearby",
    "water_reliability": "year-round",
    "budget": { "value": 60000, "currency": "BDT", "basis": "total_season" },
    "season": "Kharif-2"            // enum, see 5.1
  },
  "weather_snapshot": {             // SUMMARY only — raw payload goes to trace, not here
    "source": "open-meteo",
    "fetched_at": "2026-07-24T10:30:00",
    "next_7d_rain_mm": 82,
    "avg_temp_c": 31,
    "rain_days_next7": 5,
    "season_climate_rain_mm": 1150
  },
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
  "recommendation": "Apply 45 kg/acre urea by 2026-08-14",
  "based_on": {
    "soil": "clay loam",
    "stage": "vegetative (18 DAS)",
    "weather": "no rain forecast Aug 14–17 (Open-Meteo)",
    "source": "Fertilizer Recommendation Guide, top-dressing 15–20 DAS"
  }
}
```

### 4.3 Trace Record (append-only log, rendered in the #8 panel)

Written by the tool-call wrapper for *every* external call, retrieval, and computation.

```json
{
  "step": 3,
  "tool": "open-meteo.forecast",
  "type": "external_api",          // external_api | rag_retrieval | computation
  "params_in": { "lat": 24.85, "lon": 89.37, "days": 16 },
  "raw_output": { "...": "full unmodified payload" },
  "timestamp": "2026-07-24T10:30:12",
  "duration_ms": 240
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
for genuinely missing/ambiguous fields. Fuzzy fields are modeled as **small controlled
enums**; the LLM maps free speech → enum; a **"don't know" branch infers a default** so
nothing blocks the flow.

**Field models:**

| Field | Type | Canonical values / rule | "Don't know" fallback |
|---|---|---|---|
| location | string → coords | place name → geocode to lat/lon | required; ask again |
| farm_size | number + unit | value + {acre, bigha, hectare} | required; ask again |
| soil_type | enum | `sandy`, `loamy`, `clay`, `sandy loam`, `clay loam`, `silt loam` | infer from coords (SoilGrids) or ask "does water drain fast or pool?" |
| water_source | enum | `rain-fed only`, `irrigation (tubewell/pump)`, `surface water nearby (river/canal/pond)` | assume `rain-fed only` (conservative) |
| water_reliability | enum | `year-round`, `seasonal`, `scarce` | assume `seasonal` |
| **water_security** | derived enum | `high` / `medium` / `low` — collapse source+reliability | — |
| budget | number + currency + basis | value, `BDT`, {total_season, per_acre} | ask once: total or per-acre |
| season | enum | `Rabi` (Nov–Mar), `Kharif-1` (Mar–Jun), `Kharif-2` (Jul–Oct) | **pre-fill from current date**, confirm |

**water_security derivation (example rule):**
`surface water nearby` OR `irrigation` + `year-round` → `high`;
`irrigation`+`seasonal` or `surface`+`seasonal` → `medium`;
`rain-fed only` or any + `scarce` → `low`.

**Season pre-fill:** map current month → season enum and *confirm* rather than ask cold
(e.g. July → "Planning for the current Kharif-2 season, right?").

**Output:** a completed `profile` in session state. Every inferred field is flagged so the
trace/explanation notes it was inferred, not stated.

---

### 5.2 — Live Weather Grounding

**Done when:** The agent calls a real weather API using the farm's location and uses the
actual returned values (rainfall, temperature) in its recommendations. No invented forecasts.

**Pipeline:** `geocode → fetch (forecast + climate) → store raw + summary → cite downstream`.

1. **Geocode** (if only a place name): Open-Meteo geocoding endpoint → lat/lon. Skip if
   coords already collected.
2. **Fetch two windows** (a 16-day forecast can't cover a 4-month crop):
   - **Short-term forecast** — imminent, task-level advice (e.g. "no rain in 3 days → apply urea"):
     ```
     https://api.open-meteo.com/v1/forecast
       ?latitude={lat}&longitude={lon}
       &daily=temperature_2m_max,temperature_2m_min,precipitation_sum
       &forecast_days=16&timezone=auto
     ```
   - **Historical/climate normals** — season-long suitability (archive endpoint
     `archive-api.open-meteo.com`) for typical seasonal rainfall/temperature.
3. **Store raw + summary:** full payload → **trace log** (`raw_output`). Compact summary
   (`next_7d_rain_mm`, `avg_temp_c`, `rain_days_next7`, `season_climate_rain_mm`) →
   `weather_snapshot` in session state.
4. **Failure handling:** if the API fails, fall back to historical normals and mark the
   snapshot `degraded: true`. Never fabricate.

**Consumers:** #3 (suitability), #4 (sowing date, GDD, task overlay), #6 (explanations).

---

### 5.3 — Crop Recommendation

**Done when:** The agent ranks **at least 3 candidate crops** for the profile, season, and
weather, each with **suitability, water need, risk level, and a rough profit estimate**.

**Brain = deterministic scoring over the knowledge base; LLM only explains.** Ranking must be
reproducible and traceable. Minimise free parameters (judges scrutinise weights).

**Method — three layers, almost no magic weights:**

1. **Hard filters (eliminate, no weights):** drop any crop where
   - season ≠ profile.season, OR
   - crop water requirement > water_security capacity, OR
   - forecast/climate temperature outside the crop's survivable range, OR
   - soil fundamentally unsuitable.
   Eliminated crops are recorded with the reason (feeds explanation: "maize not
   recommended — it is a Rabi crop, current season is Kharif-2").

2. **FAO limiting-factor scoring (Liebig's Law of the Minimum — no weights):** For each
   surviving crop, compute per-factor suitability classes from **retrieved tables**, then take
   the **minimum** (a crop is only as good as its worst factor):
   ```
   suitability(crop) = min(soil_score, water_score, weather_score, season_score)
   ```
   Each sub-score maps to FAO classes **S1** (highly suitable) → **S2** (moderately) →
   **S3** (marginally) → **N** (not suitable). Sub-scores are **looked up**, not invented:
   - soil_score ← DAE/BARI crop-vs-soil suitability table
   - water_score ← FAO crop water requirement vs water_security
   - weather_score ← crop temp/rainfall tolerance vs weather_snapshot
   - season_score ← crop calendar vs profile.season

3. **Soft tie-breaker (the ONLY place weights appear):** among already-suitable crops, rank by
   a small profit-vs-risk preference (2–3 weights), **exposed in the UI as sliders**, with a
   one-line sensitivity note. This reframes weights as a transparent user preference, not a
   hidden constant.

**Per-crop output:**
```json
{
  "crop": "rice",
  "suitability": "S1",
  "water_need": "high (1200 mm/season, FAO)",
  "risk_level": "medium",
  "rough_profit_estimate": { "value": 18000, "currency": "BDT", "basis": "per acre" },
  "based_on": { "soil": "clay loam→S1", "water": "high security→S1",
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

1. **Retrieve phenology template (RAG, Type A tables):** growth stages, standard operations,
   and *relative* timing in **days-after-sowing (DAS)** for the chosen crop. Example (rice):
   ```
   stages: sowing(0), vegetative(0–40), tillering(20–40), panicle(40–65),
           flowering(65–90), maturity(90–120)
   ops:    basal fertilizer @0, 1st top-dress @15–20 DAS, 2nd @40–45 DAS,
           irrigation checkpoints, pest scouting windows, harvest @110–120
   ```
2. **Anchor the sowing date:** compute from `season` window + `weather_snapshot` — pick the
   first suitable date within the season's sowing window that avoids a forecast heavy-rain
   spell. This becomes day 0.
3. **Compute absolute dates (date engine):**
   - **Baseline:** `event_date = sowing_date + DAS`.
   - **Upgrade — Growing Degree Days (GDD):** drive stage transitions by accumulated heat
     instead of fixed days: `GDD = Σ max(0, (Tmax+Tmin)/2 − T_base)`, using temperatures from
     `weather_snapshot`. Each crop has a known GDD target per stage. A hot spell advances the
     calendar; a cool one delays it. **Reuses weather data already fetched → cheap
     differentiator.** Fall back to DAS if short on time.
4. **Weather overlay (shift individual tasks):** apply the trigger ruleset (see 5.7 ruleset)
   using **live forecast values** vs **RAG/ruleset thresholds**:
   - don't schedule nitrogen right before heavy rain (runoff) → shift +N days;
   - add irrigation checkpoints during forecast dry spells;
   This is also the seed of Tier-1 proactive advice.

**Output — structured, cited calendar (each event carries its provenance):**
```json
[
 {"date":"2026-07-28","stage":"sowing","action":"Sow rice",
  "source":"BRRI Kharif-2 window + forecast (no rain 28–31 Jul)"},
 {"date":"2026-08-14","stage":"vegetative","action":"1st urea top-dress 25 kg",
  "source":"FRG 15–20 DAS; dry window confirmed"}
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
2. **Model each cost as `quantity × unit_cost`, scaled by farm size** (never lump sums), so
   edits propagate and the math stays inspectable:
   ```json
   { "name": "Urea", "quantity": 90, "unit": "kg", "unit_cost": 27,
     "subtotal": 2430 }   // e.g. 45 kg/acre × 2 acre × 27 BDT
   ```
3. **Pure calculation engine** `financials(inputs) → outputs`. The dashboard holds editable
   state and re-runs this function on every change (single source of truth). Same function
   powers Tier-1 scenario simulation later — for free.

**Derived metrics (all recompute live):**
```
total_cost        = Σ line_item.subtotal
revenue           = expected_yield × sale_price
net_profit        = revenue − total_cost
ROI               = net_profit / total_cost
break_even_yield  = total_cost / sale_price       // yield needed to not lose money
break_even_price  = total_cost / expected_yield   // price needed to not lose money
```

**Optional integration touch:** if crop suitability (5.3) was marginal (S3), nudge the default
`expected_yield` toward the low end of the retrieved range — connects #5 back to #3.

**Output — `Financials`:**
```json
{
  "currency": "BDT",
  "line_items": [ /* ... */ ],
  "total_cost": 41200,
  "expected_yield": { "value": 2.4, "unit": "t/acre" },
  "sale_price": { "value": 26, "unit": "BDT/kg", "assumption": true },
  "revenue": 62400, "net_profit": 21200, "roi": 0.51,
  "break_even_yield": 1.58, "break_even_price": 17.2
}
```

---

### 5.6 — Explained Reasoning

**Done when:** Every recommendation states the specific farm inputs and retrieved data it
rests on.

**Explanation by construction, not generation.** The reasoning already exists as the
`provenance` records emitted by 5.2–5.5. The LLM's *only* job is to **verbalize a `based_on`
record** into fluent language — it must not add any reason not present in the record.

```
input  → { "recommendation": "Apply 45 kg/acre urea by Aug 14",
           "based_on": { soil, stage, weather, source } }
LLM out → "Apply 45 kg/acre urea by Aug 14, because your soil is clay loam, the rice is
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

**Two knowledge types → two stores (the design most teams get wrong):**

**Type A — structured numbers → lookup tables (CSV/JSON/SQLite).** Consumed by the scoring
(5.3), date (5.4) and cost (5.5) engines. Queried exactly, not semantically.
Tables to build (per crop, ~10–15 crops for the region, e.g. rice, wheat, maize, jute, potato,
lentil, mustard, onion, chili, sugarcane):
- `crop_soil_suitability` (crop × soil → S1/S2/S3/N)
- `crop_water_requirement` (crop → mm/season, FAO)
- `crop_temp_tolerance` (crop → min/opt/max °C)
- `crop_calendar` (crop × season → sowing window, stage DAS/GDD, operations)
- `fertilizer_rates` (crop × stage → nutrient kg/acre, FRG)
- `crop_yield_price` (crop → typical yield range, seeded farmgate price)

**Type B — prose guidance → vector store (Chroma).** Pest/disease management text, agronomic
best-practice paragraphs. Earns the "RAG on top" points. Pipeline:

1. **Collect sources** (publicly available, Bangladesh-relevant): DAE crop production guides,
   BARI/BRRI manuals, the **Fertilizer Recommendation Guide (FRG)**, FAO crop water/calendar
   docs, soil & yield references.
2. **Extract text:** `pdfplumber` (PDF), `BeautifulSoup` (HTML); strip headers/footers/page
   numbers.
3. **Chunk with metadata:** ~300–500 tokens per chunk, tagged `{crop, topic, source, section}`.
4. **Embed:** `text-embedding-3-small` (hosted) or `bge-small` (local).
5. **Store in Chroma:** vector + text + metadata, persisted to disk.
6. **Retrieve → ground:** embed query → top-k **filtered by metadata** (e.g. `crop=rice`) →
   pass chunks to the LLM as context → answer *from* them. If nothing relevant retrieves,
   say so; never fall back to model recall.

**Two things that win the 12 points:** (a) **curated beats huge** — a small clean tagged
corpus retrieves better; (b) **make retrieval visible** — surface retrieved chunks + source in
the #8 trace so judges see the advice came from the FRG chunk, not the model.

---

### 5.8 — Visible Agent Trace

**Done when:** The interface exposes a trace of every tool call — parameters sent and raw
values returned — so a judge can confirm a number in the plan came from a real call, not the
model's imagination.

**The trace is a byproduct of instrumentation, not a feature built at the end.**

1. **Wrap every tool call in a tracer** (decorator). Applies to: weather API, geocoding, RAG
   retrieval, the scoring engine, the date engine, the cost engine. Each appends a
   `TraceRecord` (see 4.3) with `params_in` and the **unmodified `raw_output`**.
2. **Log all three step types:** `external_api` (params + raw response), `rag_retrieval`
   (query + returned chunks + sources), `computation` (inputs + formula + result). Every number
   in the final plan must have a matching trace entry.
3. **Render as an expandable side panel / log view:** collapsed by default, one row per step
   (`tool → params → raw values`), click to expand raw JSON. A live-updating log during the
   conversation is the most demo-friendly.
4. **Build for traceability:** the plan says "82 mm rain"; the trace shows the Open-Meteo call
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
| farmer, session, messages, plan, financials snapshots | **SQLite** | zero-config, single file |
| vector corpus (Type B) | **Chroma** | retrieved on demand |
| trace / raw tool logs | JSON column or file per session | large, write-heavy, read only by UI |
| structured tables (Type A) | CSV/JSON loaded in memory | exact lookups |

**SQLite schema (minimum):**
```sql
farmer(id, name, created_at)
session(id, farmer_id, season, created_at, state_json)      -- state_json = compact state
message(id, session_id, role, content, turn, ts)
trace(id, session_id, step, tool, type, params_json, raw_json, ts, duration_ms)
```

**Tier-0 vs Tier-1:** within-session memory only needs the in-memory state object, but
persisting it to SQLite keyed by `farmer_id` is ~10 lines and **unlocks Tier-1 cross-session
memory for free** (next session: load the farmer's last state → agent already knows the farm).

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
│   ├── weather.py             # 5.2 geocode + forecast + climate (Open-Meteo)
│   ├── crop_reco.py           # 5.3 filters + FAO limiting-factor scoring
│   ├── season_plan.py         # 5.4 template → anchor → DAS/GDD engine → weather overlay
│   ├── financials.py          # 5.5 pure financials(inputs) → outputs
│   └── rules.py               # 5.4/5.7 weather/water trigger thresholds + sources
├── kb/
│   ├── ingest.py              # 5.7 extract → chunk → embed → Chroma
│   ├── retrieve.py            # 5.7 metadata-filtered top-k retrieval
│   ├── tables/                # Type A: crop_soil_suitability.csv, crop_water_requirement.csv, ...
│   └── chroma/                # Type B: persisted vector store
├── state/
│   ├── schema.py              # session state, provenance, trace dataclasses (section 4)
│   └── store.py               # SQLite load/save keyed by farmer_id
├── explain/
│   └── narrator.py            # 5.6 provenance → prose (LLM) with template fallback
├── ui/                        # chat + editable financial dashboard + trace panel (keep light)
└── README.md                  # setup, APIs, per-feature tier, real vs mock disclosure
```

---

## 8. Build Order (24-hour path)

Ship one complete feature before adding the next; a core that runs end to end beats ten
half-built features.

1. **Skeleton + state + tracer** — session state (4.1), SQLite store, tool-call tracer (5.8).
   Everything else writes into these.
2. **Intake (5.1)** — enums, inference, follow-up loop. Gets a complete profile.
3. **Weather (5.2)** — Open-Meteo forecast + climate; store raw→trace, summary→state.
4. **Knowledge base (5.7)** — build Type-A tables first (needed by 3/4/5), then the Chroma
   Type-B pipeline.
5. **Crop rec (5.3)** — filters + FAO limiting-factor over the tables.
6. **Season plan (5.4)** — template → anchor → DAS (GDD if time) → weather overlay.
7. **Financials (5.5)** — editable line-items + pure function + dashboard wiring.
8. **Reasoning (5.6)** — narrate provenance (template first, LLM polish).
9. **Trace panel (5.8 UI)** — render the trace log; verify every plan number links to a call.
10. **End-to-end pass + README** — one farm from empty field to costed plan; label real vs mock.

**Definition of done for Tier 0:** a single conversation takes a farmer from a vague opening
message to a grounded, explained, costed, dated season plan for one crop, with every number
traceable in the panel to a real tool call or an inspectable formula — and it runs cleanly in
the demo.

---

## 9. What NOT to Do (from the brief)

- Do not build the full 14-feature marketplace/escrow vision. Core first, tiers only when the
  layer beneath works.
- Do not demo a flashy feature (e.g. payment gateway) while the crop recommendation ignores the
  weather it just fetched — judges will notice the disconnect.
- Do not over-invest in UI/UX (explicitly low-weight).
- Do not invent numbers. Every figure traces to a tool call or a formula.
```
