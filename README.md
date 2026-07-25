# AgriSense AI

AgriSense AI is a source-grounded Bangladesh farm-planning prototype for the
IUT Agentic AI Hackathon. Its judge-ready path covers the Rabi season in Bogura
with three comparable crops: maize, lentil and wheat.

## Capability status

The maintained flow is:

`POST /intake/chat` → `POST /plan/from-conversation` → the Next.js result view.

It fails closed until the conversation has collected the farm profile, a manual
sowing date, lab soil-test class, water-balance inputs and explicit permission
to use editable demo financial assumptions. The agent then ranks three crops
and labels its recommendation; the farmer must explicitly select one of those
ranked crops before the dated season plan is built.

| # | Tier 0 capability | Status | Evidence in the result |
|---|---|---|---|
| 1 | Short conversational intake | **Pass** | Evidence-checked structured extraction and targeted follow-ups |
| 2 | Live weather used by the recommendation | **Pass** | Open-Meteo rain, temperature and ET0 drive FAO-56 water balance and risks |
| 3 | Rank at least three same-season crops | **Pass (Rabi)** | Maize, lentil and wheat, with soil/water/risk/profit evidence |
| 4 | Dated farmer-chosen crop season plan | **Pass** | The farmer selects one ranked crop; its plan runs from land preparation through harvest |
| 5 | Itemized financial projection | **Pass with consent** | Cost, yield, revenue, profit, ROI, break-even and budget fit; editable inputs |
| 6 | Explain every recommendation | **Pass** | Each rendered recommendation has a `based_on` object and trace link |
| 7 | Public agronomic KB and RAG | **Pass for demo slice** | Structured Supabase records plus crop-specific retrieved chunks used before advice rendering |
| 8 | Visible agent trace | **Pass** | Parameters and bounded full outputs for retrievals, weather, calculations, ranking, RAG and advice |

| Tier 1 capability | Status | Behaviour |
|---|---|---|
| Persistent farmer memory | **Pass with consent** | Explicitly restores a bounded profile and lists farmer-confirmed crop projects across sessions |
| Proactive weather advice | **Pass while app is active** | Refreshes the active project on open/every 15 minutes, raises heavy-rain/heat alerts and adjusts eligible near-term tasks |
| Input scheduler | **Pass** | Converts cited rates to farm totals and exposes crop, soil-test class, stage, timing, cost and organic alternatives |
| Pest and disease risk | **Pass (screening only)** | Combines crop, derived growth stage and weather with prevention, treatment, DAE warning and scouting cost |
| What-if simulation | **Pass** | Re-runs the plan for rainfall and budget changes and reports changed numeric deltas |

These claims are intentionally narrow: Rabi is the only season with three
reviewed candidates. AEZ resolution is administrative, financial values are
editable demo assumptions, the water thresholds are a disclosed project policy,
and pest output is conservative screening—not a pesticide prescription.

## Data basis

| Layer | Basis | Example |
|---|---|---|
| Live API | Open-Meteo forecast | rain, temperature and ET0 used in water balance |
| Reviewed local | BBS 2024, FRG 2024, AIS calendar, HDX ADM3 | yield, fertilizer range, crop dates and location |
| Provisional parameter seed | CROPWAT 8 `.CRO`/`.SOI` | Kc, root depth and critical depletion |
| Editable assumption | `project_demo_assumptions` | costs and farmgate prices, used only after consent |

Paddy water scoring remains unassessed until ponding, percolation and field-loss
inputs are curated. Any crop missing a limiting factor is excluded with a
machine-readable reason. Advice is withheld when crop-specific retrieval does
not clear the disclosed relevance threshold.

## Run with Docker

```bash
cp backend/.env.example backend/.env
# Add server-only Supabase credentials and optional Gemini credentials.

docker compose run --rm -w /app/backend app python -m kb.migrate
docker compose run --rm -w /app/backend app python -m kb.build
docker compose up --build
```

Open <http://localhost:3000>. `GET /demo` on port 8000 redirects to this
maintained frontend.

The root Docker context excludes `.env` files, Git metadata, caches and local
dependencies. Never place a Supabase credential in `frontend/.env.local` or a
`NEXT_PUBLIC_*` variable.

## Run locally

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

python -m kb.validate
python -m kb.migrate
python -m kb.build
python -m kb.verify
pytest
uvicorn app:app --reload
```

Frontend:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Set server-only `AGRISENSE_API_BASE_URL` in `frontend/.env.local` if FastAPI is
not at `http://127.0.0.1:8000`. A Google Maps pin is optional and requires only a
browser-origin-restricted `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`; browser geolocation
or a place name also works.

## Important endpoints

- `POST /intake/chat` — conversational profile collection and consented memory
- `POST /farmer/profile/session` — named-farm create/login or database-backed guest entry
- `GET /farmer/profile/{farmer_id}` — restore a consented bounded profile
- `POST /farmer/profile/{farmer_id}/projects` — create the mandatory draft project
- `GET /farmer/profile/{farmer_id}/projects` — list canonical projects for one farm
- `POST /farmer/profile/{farmer_id}/projects/{project_id}/refresh` — refresh a saved project with live weather
- `POST /plan/from-conversation` — complete Tier-0 path
- `POST /plan/rank` — deterministic planning core
- `POST /plan/scenario` — budget/rainfall what-if comparison
- `GET /plan/preview/{session_id}` — restore a saved plan
- `GET /plan/preview/{session_id}/traces` — inspect the agent trace
- `GET /kb/search` — cited knowledge retrieval
- `GET /weather/forecast` — live forecast adapter
- `GET /docs` — interactive FastAPI documentation

## Verification and security

The checked-in test suite is offline and uses fake adapters. Live verification
requires the server-only Supabase configuration:

```bash
cd backend
python -m kb.validate
python -m kb.verify
pytest

cd ../frontend
npm run lint
npm run build
```

Local `.env` files are ignored and excluded from Docker. If a credential was
ever committed, removing the file from the latest tree is not sufficient:
rotate the credential in its provider and purge the affected Git history before
publishing. See [`SECURITY.md`](SECURITY.md).

## Documentation

- [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) — exact judge flow
- [`docs/TIER0_GAP_ANALYSIS.md`](docs/TIER0_GAP_ANALYSIS.md) — resolved acceptance audit
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design
- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) — source and curation audit
- [`backend/kb/curated/`](backend/kb/curated/) — reviewed tables and policies
- [`backend/supabase/`](backend/supabase/) — Postgres/pgvector schema
- [`backend/tests/`](backend/tests/) — behavioural and safety tests

The original problem statement and source-list PDFs remain unchanged for
auditability.
