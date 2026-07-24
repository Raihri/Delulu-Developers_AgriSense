# AgriSense AI

AgriSense AI is a source-grounded Bangladesh farm-planning prototype for the IUT
Agentic AI Hackathon. The repository contains a runnable foundation and one
reviewed winter/dry-season (Rabi) data slice for maize, lentil and wheat, plus
Boro rice.

## Tier-0 capability status

The `POST /plan/rank` endpoint delivers the Tier-0 analytical path for the Rabi
demo season: from a farm profile it ranks three comparable crops using real
weather and the FAO-56 water balance, picks a chosen crop, builds a dated
land-preparation-to-harvest plan for it, costs it, and grounds the advice in
retrieved agronomic chunks. Every ranked number carries reproducible evidence.

| # | Tier-0 capability | Status | Where |
|---|---|---|---|
| 1 | Conversational intake → plan as one path | Pass | `POST /intake/chat` → `POST /plan/from-conversation` |
| 2 | Real weather API values used in recommendations | Pass | `tools/agro_score.py` → `/plan/rank` (ETc = Kc × ET0) |
| 3 | Rank ≥3 crops with suitability, water, risk, rough profit | Pass (Rabi) | `tools/ranking.py` → `/plan/rank` |
| 4 | Chosen crop gets a dated land-prep→harvest plan | Pass | `tools/season_plan.py` → `/plan/rank` `chosen_plan` |
| 5 | Itemized cost, yield, revenue, profit, ROI, break-even | Pass | `tools/financials.py`; budget fit in `/plan/rank` |
| 6 | Every recommendation states its inputs and retrieved data | Partial | `/plan/rank` `evidence` per crop; provenance renderer pending |
| 7 | Public agronomic data in a KB with RAG feeding advice | Pass (demo embeddings) | `/plan/rank` `chosen_plan.grounding`; deterministic vectors, not a semantic model |
| 8 | UI shows every tool call, params and raw returned values | Partial | `/plan/preview` traces now carry raw weather values + distinct trace types |

Fail-closed behaviour is preserved throughout: paddy rice water scoring stays
unassessed, a crop missing any limiting factor is excluded from the ranking with
a machine-readable reason, and prose advice is withheld below the RAG relevance
threshold.

## Real vs. reviewed vs. assumed data

| Layer | Basis | Example |
|---|---|---|
| Real API | Live Open-Meteo forecast (temp, rain, ET0) | weather window driving the water balance |
| Reviewed local | BBS 2024, FRG 2024, AIS calendar, HDX ADM3 | wheat yield 3.763 t/ha; wheat N 41–80 kg/ha (FRG p.75) |
| Provisional seed | CROPWAT 8 `.CRO`/`.SOI` | crop Kc/root-depth and critical depletion `p` |
| Mock assumption | `project_demo_assumptions` (editable) | input costs and farmgate prices (gated by `allow_assumptions`) |

No selected season outside Rabi yet has three curated candidates; Rabi is the
judge-ready scenario.

## What runs now

- FastAPI endpoints for source precedence, cited knowledge retrieval, HDX
  coordinate-to-ADM3 resolution, FAO-56 daily water balance, editable financial
  projections, three crop assessments, a deterministic partial-plan preview and
  live Open-Meteo forecasts.
- A Supabase Postgres migration and seed pipeline for the source registry, nine
  structured lookup tables, five cited pgvector chunks, session state and trace
  storage.
- A registry v2 with separate `download_status`, `curation_status` and
  `safety_status`.
- Automated source/curated hashes, schemas, row counts, provenance, duplicate
  detection and quarantine checks.
- HTML/PDF/table extraction, image OCR hooks, legacy-Bengali detection and an
  explicit human-review promotion gate.

This is a runnable foundation, not a finished Tier-0 product. It includes a
chat-led Gemini intake controller that extracts explicit farmer facts through
structured output, normalizes them to canonical enums, validates exact evidence
quotes and returns cited retrieval context. Ambiguous or unsupported values fail
closed and trigger a targeted follow-up. A dated season-plan engine and a
deterministic same-season crop ranking are now implemented for the Rabi slice
(`/plan/rank`); a production semantic embedding model, locally calibrated water
thresholds and folding the ranking into the conversational preview path remain
out of scope.

## Run with Docker (no local Python/Node needed)

If you don't have Python 3.11+ or Node installed, use the bundled Docker setup.
The root `Dockerfile` is an **all-in-one image** that runs both the FastAPI
backend and the Next.js frontend in one container (Python pinned to 3.12,
Node 20 installed).

```bash
cp backend/.env.example backend/.env   # fill Supabase (+ optional Gemini) values
docker compose up --build
```

Then open http://localhost:3000 (frontend); it proxies to the backend on
http://localhost:8000. Or without Compose:

```bash
docker build -t agrisense .
docker run --rm -p 3000:3000 -p 8000:8000 --env-file backend/.env agrisense
```

First-time database seeding reads the local `dataset/` folder (mounted
read-only by Compose) and is a one-off:

```bash
docker compose run --rm -w /app/backend app python -m kb.migrate
docker compose run --rm -w /app/backend app python -m kb.build
```

The app runtime does not need `dataset/`; only migration/seed/validation do.
Separate `backend/Dockerfile` and `frontend/Dockerfile` are also provided if you
prefer to run the two services in their own containers.

## Supabase setup and run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# Fill backend-only SUPABASE_DB_URL, then:

python -m kb.validate
python -m kb.migrate
python -m kb.build
python -m kb.verify
pytest
uvicorn app:app --reload
```

The build command validates and upserts the reviewed source/curated slice into
Supabase. It does not create a local database. The direct database URL is
server-only and is sufficient for migration, seed and FastAPI. `SUPABASE_URL`
plus `SUPABASE_SECRET_KEY` remains a supported alternative for seed and FastAPI,
but migrations still require the direct URL or the Supabase SQL editor/CLI.
No database URL, password or secret key may be exposed in browser code. Locally
downloaded source assets remain ignored by Git because several assets do not
grant redistribution rights.

No Supabase credentials are committed. Until a project is migrated and one
server connection method is configured, database-backed endpoints return a
configuration error; offline validation and tests still use a fake client.
Supabase direct database hosts are IPv6 by default. On an IPv4-only machine,
copy the project-specific **Session pooler** URL from Dashboard → Connect into
`SUPABASE_DB_URL`; do not guess the pooler region or hostname.
If you must retain a direct URL locally, set the non-secret
`SUPABASE_DB_POOLER_HOST` to that exact Session pooler hostname; the backend
rewrites the host and pooled username only in memory.

Useful endpoints:

- `GET /health`
- `GET /sources/precedence`
- `GET /kb/search?q=maize+nitrogen&crop=maize`
- `POST /geo/resolve`
- `POST /water/balance`
- `POST /financials`
- `POST /recommendations`
- `POST /intake/chat` (chat input → explicit filters + cited RAG context)
- `POST /plan/from-conversation` (single path: reads the intake session profile → ranked, costed, dated, traced plan)
- `POST /plan/rank` (costed, weather-grounded Rabi ranking + chosen-crop dated plan + RAG grounding)
- `POST /plan/preview` (creates or updates a compact, traced session preview)
- `GET /plan/preview/{session_id}` (reloads that compact derived preview)
- `GET /plan/preview/{session_id}/traces` (sanitized tool parameters and outputs)
- `GET /demo` (judge-facing local demo page; calls FastAPI only)
- `GET /weather/forecast`

Interactive API documentation is available at `/docs` while the server runs.
For the judge flow, open `/demo`; the exact Bogura scenario and expected safety
messages are in [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md).

## Next.js frontend

The browser frontend is in `frontend/` and proxies requests to FastAPI server-side;
it never uses or exposes Supabase credentials.

```bash
# terminal 1
cd backend
uvicorn app:app --reload

# terminal 2
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. Set server-only `AGRISENSE_API_BASE_URL` in
`frontend/.env.local` when the backend is not on `http://127.0.0.1:8000`.
The farm context step accepts a natural-language message, not manually entered
coordinates. It supports browser live location and an optional Google Maps pin.
The interface is organized around the eight judge-facing capabilities:
conversational intake, live weather, crop assessment, season plan, financial
projection, explained reasoning, cited RAG and a visible tool trace.
To enable the pin picker, set `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` to a
browser-origin-restricted key with the Maps JavaScript API enabled. Never place a
Supabase or backend secret in this frontend environment file.

## Data boundaries

- FAO-56 Rev.1 (2025) is the formula/method authority. CROPWAT 8 files
  are provisional parameter seeds, not Bangladesh measurements.
- BRRI owns rice-variety facts; BARI owns detailed non-rice agronomy;
  AIS owns the national crop calendar and concise extension guidance.
- SRDI maps are regional soil/AEZ priors. JPEG/PDF maps cannot resolve a
  coordinate to an AEZ.
- HDX v03 resolves coordinates to English ADM3/P-codes. The current reviewed
  Bogura Sadar crosswalk returns AEZ candidates 3, 25 and 27 at administrative
  resolution and never chooses one for a farm point.
- BARI's 10th-edition handbook is present but its extracted Bengali uses a
  legacy font. It remains outside RAG until OCR or a reviewed conversion passes
  human checks.
- AIS/BRRI image-only records in the demo slice are explicitly marked as human
  visual transcriptions.
- DAE pesticide data is blocked until current cancellation/registration notices
  are applied.
- BBS 2024 carrot Table 3.9.29 is quarantined because the expected 2023-24
  column repeats the 2022-23 heading and values. It is excluded, not corrected.

## Water and financial safety

Effective rainfall is computed through the FAO-56 root-zone balance, not as a
fixed percentage. Irrigation values are net infiltrated millimetres by default;
gross values require an explicit efficiency. The current water-class thresholds
are labelled as an uncalibrated project policy. Paddy water scoring fails closed
until land preparation, ponding, percolation and field-loss inputs are curated.

Input prices, labor, irrigation costs and farmgate prices are editable demo
assumptions, not observed market data. The financial endpoint refuses to use
them unless `allow_assumptions=true`.

## Key files

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — implemented checkpoint and remaining
  Tier-0 contract
- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) — human-readable source audit
- [`backend/kb/sources.yaml`](backend/kb/sources.yaml) — registry v2
- [`backend/kb/curation_manifest.yaml`](backend/kb/curation_manifest.yaml) — curated hashes,
  schemas and row counts
- [`backend/kb/curated/`](backend/kb/curated/) — reviewed demo tables and policies
- [`backend/`](backend/) — API, build, validation, ingestion and tools
- [`backend/supabase/`](backend/supabase/) — Postgres/pgvector schema, RLS and setup instructions
- [`docs/distribution.md`](docs/distribution.md) — seven alternating 30-minute rounds for
  Raima and Ahan
- [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) — one-page judge demo script
- [`backend/tests/`](backend/tests/) — offline quality and behavior tests
- [`frontend/`](frontend/) — Next.js browser client and FastAPI proxy routes

The original problem statement and source-list PDFs remain unchanged for
auditability.
