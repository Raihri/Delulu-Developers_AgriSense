# AgriSense AI

**Team Delulu Developers · repository `Delulu-Developers_AgriSense`**
Submission for the IUT 12th ICT Fest — Bdapps Agentic AI Hackathon (Final Round).

AgriSense AI is a source-grounded Bangladesh farm-planning agent. From a short
conversation it produces a grounded, explained, costed season plan for one farm,
then keeps advising through harvest. The judge-ready path covers the Rabi season
in Bogura with three comparable crops: maize, lentil and wheat.

The maintained core flow is:

`POST /intake/chat` → `POST /plan/from-conversation` → the Next.js result view.

It fails closed until the conversation has collected the farm profile, a manual
sowing date, a lab soil-test class, water-balance inputs and explicit permission
to use editable demo financial assumptions. The agent ranks three crops and
labels its recommendation; the farmer must explicitly select one ranked crop
before the dated season plan is built.

---


## Tools and APIs

| Layer | Technology | Role | Real / key needed |
|---|---|---|---|
| Weather API | **Open-Meteo Forecast API** | Live rainfall, temperature and ET0 for the farm location | Real, no key |
| LLM | **Google Gemini** (`generativelanguage` API) | Conversational intake parsing, scenario chat, Tier-2 image screening | Real, server-only `GEMINI_API_KEY` (optional; core degrades gracefully) |
| Database + vector store | **Supabase** (Postgres + `pgvector`) | Knowledge-base storage and RAG retrieval | Real, server-only credentials |
| Backend | **FastAPI** + Uvicorn (Python) | Agent controller, tools, tracing, REST API | — |
| Frontend | **Next.js 15 / React 19** (TypeScript) | Chat intake, result view, agent-trace panel, plant-health module | — |
| Map pin (optional) | **Google Maps JS** | Optional location pin during intake | Optional browser-restricted `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` |
| Agronomic method | **FAO-56 / CROPWAT 8** parameters | Water-balance and crop-stage arithmetic | Local, reviewed |

External services the agent actually calls at runtime: **Open-Meteo** (weather),
**Google Gemini** (language), and **Supabase** (KB/RAG). Weather values returned
by Open-Meteo flow directly into the FAO-56 water balance, crop ranking and risk
screening — nothing is invented.

---

## Feature coverage by tier

### Tier 0 — Core (required): all pass

| # | Tier 0 capability | Status | Evidence in the result |
|---|---|---|---|
| 1 | Short conversational intake | **Pass** | Evidence-checked structured extraction; targeted follow-ups only for missing fields (location, farm size, soil, water, budget, season) |
| 2 | Live weather used by the recommendation | **Pass** | Open-Meteo rain, temperature and ET0 drive the FAO-56 water balance and risks |
| 3 | Rank at least three same-season crops | **Pass (Rabi)** | Maize, lentil and wheat, each with soil/water/risk/profit evidence |
| 4 | Dated farmer-chosen crop season plan | **Pass** | Farmer selects one ranked crop; its plan runs from land preparation through harvest |
| 5 | Itemized financial projection | **Pass (with consent)** | Cost, yield, revenue, profit, ROI, break-even and budget fit; inputs editable and internally consistent |
| 6 | Explain every recommendation | **Pass** | Each rendered recommendation carries a `based_on` object and trace link |
| 7 | Public agronomic KB with RAG | **Pass (demo slice)** | Structured Supabase records plus crop-specific retrieved chunks used before advice is rendered |
| 8 | Visible agent trace | **Pass** | Parameters and bounded raw outputs for retrievals, weather, calculations, ranking, RAG and advice |

### Tier 1 — Advanced: implemented

| Tier 1 capability | Status | Behaviour |
|---|---|---|
| Persistent farmer memory | **Pass (with consent)** | Restores a bounded profile and lists farmer-confirmed crop projects across sessions |
| Proactive weather-triggered advice | **Pass (while app active)** | Refreshes the active project on open / every 15 min, raises heavy-rain and heat alerts, adjusts eligible near-term tasks |
| Fertilizer & irrigation scheduler | **Pass** | Converts cited rates to farm totals; exposes crop, soil-test class, stage, timing, cost and organic alternatives |
| Pest & disease risk | **Pass (screening only)** | Combines crop, derived growth stage and weather with prevention, treatment, DAE warning and scouting cost |
| Scenario simulation | **Pass** | Saved-project chat plus rainfall/budget what-ifs re-run deterministic calculations and report numeric deltas |

### Tier 2 — Ambitious (bonus)

| Tier 2 capability | Status | Behaviour |
|---|---|---|
| Plant disease detection from images | **Pass (when Gemini configured)** | Bilingual `/plant-health` module accepts a leaf photo plus typed/voice symptom notes, reads results aloud, returns a Gemini visual screening (top-three possible issues, estimated confidence, prevention, DAE safety boundary) |
| Bengali / voice accessibility | **Partial** | Bilingual UI and voice input/read-aloud in the plant-health module |
| Marketplace & supplier comparison | **Not built** | Deliberately out of scope for 24 h |
| Market price intelligence | **Not built** | Farmgate prices are static demo assumptions, not a live price board |
| bdapps CaaS payment gateway | **Not built** | No checkout / balance-deduction flow implemented |

These claims are intentionally narrow: Rabi is the only season with three
reviewed candidates, AEZ resolution is administrative, financial values are
editable demo assumptions, water thresholds are a disclosed project policy, and
pest output is conservative screening — not a pesticide prescription.

---

## Real vs mock data

The brief requires stating what is real versus mock.

| Layer | Basis | Real or mock | Example |
|---|---|---|---|
| Live weather | Open-Meteo forecast API | **Real (live)** | Rain, temperature and ET0 used in the water balance |
| Reviewed local reference | BBS 2024, FRG 2024, AIS crop calendar, HDX ADM3 | **Real (collected, curated offline)** | Yield ranges, fertilizer ranges, crop dates, location resolution |
| Crop-stage parameters | CROPWAT 8 `.CRO` / `.SOI` seeds | **Real but provisional** | Kc, root depth, critical depletion |
| Financial costs & farmgate prices | `project_demo_assumptions` | **Mock (editable demo)** | Input costs and sell prices, used only after farmer consent |
| Knowledge base / RAG corpus | Public extension manuals, fertilizer guides, crop calendars (Supabase + pgvector) | **Real (collected from public sources)** | Retrieved chunks grounding crop/fertilizer/season advice |
| Plant-health image screening | Google Gemini multimodal | **Real model output, advisory only** | Top-three possible issues with a DAE safety boundary |

Paddy water scoring remains unassessed until ponding, percolation and field-loss
inputs are curated. Any crop missing a limiting factor is excluded with a
machine-readable reason. Advice is withheld when crop-specific retrieval does not
clear the disclosed relevance threshold.

---

## Run with Docker

One all-in-one image runs **both** the FastAPI backend (`:8000`) and the Next.js
frontend (`:3000`) in a single container. Requires Docker Engine with the
Compose plugin (`docker compose`).

**1. Configure credentials** (server-only — never in the frontend):

```bash
cp backend/.env.example backend/.env
# Fill Supabase credentials (required) and Gemini credentials (optional).
```

**2. Seed the knowledge base** once. This mounts the local `dataset/`
read-only and builds the KB into Supabase:

```bash
docker compose run --rm -w /app/backend app python -m kb.migrate
docker compose run --rm -w /app/backend app python -m kb.build
```

**3. Build and start the app:**

```bash
docker compose up --build
```

Open <http://localhost:3000> for the frontend; the backend API is at
<http://localhost:8000> (`GET /demo` on port 8000 redirects to the frontend,
`GET /docs` serves interactive API docs). Stop with `Ctrl+C` or
`docker compose down`.

### Plain Docker (without Compose)

```bash
docker build -t agrisense .
docker run --rm -p 3000:3000 -p 8000:8000 --env-file backend/.env agrisense
```

The frontend proxies to the backend inside the same container via
`AGRISENSE_API_BASE_URL=http://127.0.0.1:8000` (set automatically in
`start.sh`). The root Docker context excludes `.env` files, Git metadata, caches
and local dependencies. Never place a Supabase credential in
`frontend/.env.local` or a `NEXT_PUBLIC_*` variable.

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
not at `http://127.0.0.1:8000`. A Google Maps pin is optional and needs only a
browser-origin-restricted `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`; browser geolocation
or a place name also works.

### Environment variables

| Variable | Where | Required | Purpose |
|---|---|---|---|
| `SUPABASE_DB_URL` / `SUPABASE_URL` + `SUPABASE_SECRET_KEY` | backend only | Yes | KB storage and RAG |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | backend only | Optional | Intake parsing, scenario chat, image screening |
| `AGRISENSE_API_BASE_URL` | frontend only | If backend not on `:8000` | Backend location |
| `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` | frontend | Optional | Map pin during intake |

Open-Meteo needs no key. Server-only secrets must never appear in
`frontend/.env.local` or any `NEXT_PUBLIC_*` variable.

## Important endpoints

- `POST /intake/chat` — conversational profile collection and consented memory
- `POST /farmer/profile/session` — named-farm create/login or database-backed guest entry
- `GET /farmer/profile/{farmer_id}` — restore a consented bounded profile
- `POST /farmer/profile/{farmer_id}/projects` — create the mandatory draft project
- `GET /farmer/profile/{farmer_id}/projects` — list canonical projects for one farm
- `POST /farmer/profile/{farmer_id}/projects/{project_id}/refresh` — refresh a saved project with live weather
- `POST /plan/from-conversation` — complete Tier-0 path
- `POST /plan/rank` — deterministic planning core
- `POST /plan/scenario` — saved-project chat plus audited budget/rainfall what-if comparison
- `POST /plant-health/diagnose` — server-only Gemini multimodal image proxy
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
ever committed, removing the file from the latest tree is not sufficient: rotate
the credential in its provider and purge the affected Git history before
publishing. See [`SECURITY.md`](SECURITY.md).

The Tier-2 image module reuses `GEMINI_API_KEY` and `GEMINI_MODEL` from
`backend/.env`. Never place the key in `frontend/.env.local` or a `NEXT_PUBLIC_*`
variable.

## Documentation

- [`docs/Agentic_AI_Hackathon_Final_Question.pdf`](docs/Agentic_AI_Hackathon_Final_Question.pdf) — original problem statement

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design
- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) — source and curation audit

