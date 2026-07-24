# AgriSense 3.5-Hour Sequential Sprint

**Team:** Raima and Ahan  
**Total time:** 3 hours 30 minutes  
**Working rule:** exactly one person codes at a time. Seven 30-minute rounds,
alternating Raima → Ahan → Raima → Ahan → Raima → Ahan → Raima.

Write the actual start time here before beginning: `________ Asia/Dhaka`.

**Layout note:** all executable backend files now live in `backend/`. Run Python,
pytest, migration and Supabase commands from that folder. The ignored root `dataset/`
directory remains outside it because it contains downloaded source assets.

## Sprint rules

- Each round is 25 minutes of work and 5 minutes for verification plus handoff.
- The inactive person may read the latest handoff, but must not edit files.
- At minute 25, stop adding features. Run the round's acceptance check and
  record what passed, failed and changed.
- Commit or checkpoint after every round. The next owner starts only after the
  previous owner says `HANDOFF READY`.
- An unfinished task is handed over honestly; it does not consume the next
  person's time invisibly.
- Do not collect new datasets during this sprint.
- Do not add pesticide advice, paddy-water scoring, full authentication,
  production embeddings or a second database.
- Never commit `.env`, Supabase secret/service-role keys or farmer PII.

## Round schedule

| Round | Time | Owner | Single objective | Must finish with |
|---|---:|---|---|---|
| 1 | T+00–T+30 | Raima | Bring up and seed Supabase | Migrated project, successful seed, healthy backend |
| 2 | T+30–T+60 | Ahan | Verify the Supabase API contract | Tested endpoints and a short defect list/fixes |
| 3 | T+60–T+90 | Raima | Build the minimal plan orchestrator | One `/plan/preview` request composes existing tools |
| 4 | T+90–T+120 | Ahan | Build the provisional season-plan engine | Cited calendar/fertilizer events with tests |
| 5 | T+120–T+150 | Raima | Integrate season plan, session and traces | Plan persisted; each tool step creates a trace |
| 6 | T+150–T+180 | Ahan | Prepare the judge-facing demo surface | One clear flow showing plan, warnings and sources |
| 7 | T+180–T+210 | Raima | Integrate, deploy and freeze | Green checks, deployed demo and rehearsed script |

---

## Round 1 — Raima — Supabase bring-up

**Goal:** convert the checked-in Supabase contract into a working shared backend.

Work only on:

- Supabase dashboard/CLI or the checked-in direct migration command
- `.env` locally
- `backend/supabase/migrations/` only if the migration fails
- database adapter/build only if a real Supabase incompatibility is found

Steps:

1. Create/select the Supabase project.
2. Set backend-only `SUPABASE_DB_URL` locally; never paste it into frontend code.
3. Apply `backend/supabase/migrations/202607240001_agrisense.sql` with the checked-in
   migration command.
4. Run:

   ```bash
   python -m kb.validate
   python -m kb.migrate
   python -m kb.build
   python -m kb.verify
   uvicorn app:app --reload
   ```

5. Check `GET /health` and one `GET /kb/search` request.

Acceptance:

- Migration completes.
- Seed output says `quality_status: passed`.
- `/health` reports `supabase_postgres_pgvector`.
- No secret appears in terminal screenshots, Git diff or browser code.

Handoff to Ahan:

- Project/migration status
- Backend base URL
- Seed counts
- Exact failed command/error, if any
- `HANDOFF READY`

### Round 1 execution record — 2026-07-24

**Status:** `HANDOFF READY`

- Implemented backend-only direct Postgres configuration, a narrow table/RPC
  adapter, hash-tracked migration command and exact seed/vector verification.
- Applied migration `202607240001_agrisense` to the shared Supabase project.
- Seed result: 18 source records; 6 admin aliases; 3 ADM3–AEZ crosswalks; 3
  varieties; 7 soil-suitability rows; 8 water-stage rows; 3 calendars; 28
  fertilizer rows; 3 yield rows; 18 editable cost rows; 5 RAG chunks; and 6
  build-metadata records.
- Remote verification passed with no count mismatches, `quality_status: passed`,
  `storage_backend: supabase_postgres_pgvector`, and a cited pgvector result.
- Real API smoke checks passed: `GET /health` returned 200/`ok`; `GET /kb/search`
  returned the maize FRG chunk with `source_id: barc_frg_2024` and `PDF page 91`.
- Local gate: dataset validation has zero errors/warnings; 24 tests pass.
- Credential safety gate: the real connection URL/password remains only in the
  ignored local `.env`, never in tracked files or Git diff.
- The configured Session pooler supports this IPv4-only runner. Direct database
  URLs remain suitable on an IPv6-capable deployment.

Handoff to Ahan: use the shared Supabase backend as configured in ignored `.env`.
Start `uvicorn app:app --reload` for live local API calls; the Round 2
contract cases may now run against real data.

---

## Round 2 — Ahan — API contract verification

**Goal:** prove that the migrated storage works through FastAPI, then fix only
contract-breaking defects.

Work only on:

- `backend/app.py`
- `backend/kb/vector_store.py`
- `backend/tests/test_api.py`
- `backend/tests/test_retrieval.py`
- API collection/run notes

Test these cases:

1. `/health` returns seeded Supabase metadata.
2. `/kb/search` returns a chunk with `source_id` and `source_locator`.
3. `/geo/resolve` returns Bogura Sadar plus AEZ candidates without claiming a
   point-level AEZ.
4. `/water/balance` rejects Boro paddy scoring.
5. `/financials` rejects assumptions when false and succeeds when explicitly
   true.
6. `/recommendations` returns three transparent assessments without inventing
   a ranking.

Acceptance:

- Targeted API tests pass.
- Response shapes are written in the handoff.
- No schema redesign and no new feature.

Handoff to Raima:

- Working request/response examples
- Any remaining 4xx/5xx issue
- Stable fields the controller may consume
- `HANDOFF READY`

### Round 2 execution record — 2026-07-24

**Status:** `HANDOFF READY`

- Ran all six contract cases against the live migrated/seeded Supabase backend.
  `/health`, `/kb/search`, `/geo/resolve`, accepted `/financials` and
  `/recommendations` returned `200`.
- Expected gates behaved correctly: Boro `/water/balance` returned `422`; the
  financial endpoint returned `422` until `allow_assumptions:true` was sent.
- Search returned the cited FRG maize chunk; Bogura Sadar returned ADM3 P-code
  `BD50100020` and AEZ candidates 3, 25 and 27 with no point-AEZ claim.
- Recommendation output contained Boro rice, maize and lentil with no fabricated
  ranking; Boro retained `unassessed` soil/water constraints.
- Added API regression coverage for the geo and transparent-recommendation
  contract. No API or retrieval defect required a behavioral code change.
- Full response shapes, working requests and Round-3-safe fields are in
  [`docs/round2_api_contract.md`](docs/round2_api_contract.md).
- Remaining issue: none for this Round 2 contract. The deterministic hashed
  vectors remain intentionally labelled non-semantic; replacing them is outside
  this round's scope.

Handoff to Raima: compose `/plan/preview` only from the stable fields in the run
note. Preserve `unassessed`, the ADM3-level AEZ warning and the financial
assumption gate. `HANDOFF READY`

---

## Round 3 — Raima — Minimal plan orchestrator

**Goal:** add one endpoint that composes the existing deterministic tools.

Own these files:

- `backend/agent/controller.py`
- `backend/agent/schemas.py`
- the `/plan/preview` route in `backend/app.py`
- `backend/tests/test_plan_preview.py`

Required input:

- coordinates
- soil class and drainage
- area
- optional `allow_assumptions`

Required output:

- resolved administrative location and AEZ candidate warning
- three crop assessments
- financial result only after assumption opt-in
- explicit `missing`/`unassessed` fields
- source IDs/locators already returned by tools

Do not add an LLM in this round. The controller is deterministic orchestration.

Acceptance:

- One request reaches `/plan/preview` and returns a structured partial plan.
- It never changes `unassessed` into a suitability class.
- Test covers both assumption-gate states.

Handoff to Ahan:

- Exact controller input/output schema
- Where season events must be inserted
- Test command and result
- `HANDOFF READY`

### Round 3 execution record — 2026-07-24

**Status:** `HANDOFF READY`

- Added deterministic `POST /plan/preview`; it composes HDX/AEZ location,
  three transparent crop assessments, missing-input declarations and optional
  provisional budgets from the existing reviewed Supabase tables.
- Input schema: coordinates, `soil_class`, optional drainage, `area_acres` and
  `allow_assumptions`. Output schema is documented in
  [`docs/round3_plan_preview_contract.md`](docs/round3_plan_preview_contract.md).
- With no opt-in, `financials.status` is `blocked_until_assumption_opt_in` and
  no financial values are returned. With opt-in, `financials.by_crop` contains
  provisional budgets for Boro rice, maize and lentil.
- Bogura Sadar preview returned ADM3 P-code `BD50100020`, AEZ candidates but no
  point-AEZ claim. Boro stayed `unassessed` for soil suitability and
  `unassessed_paddy_model` for water; no crop ranking was introduced.
- `season_events` is the reserved Round-4 insertion point. It currently returns
  an empty `not_available_until_round_4` placeholder and must be replaced only
  by cited provisional/dated events.
- Tests: `pytest tests/test_plan_preview.py` plus the full suite pass. No schema
  migration or LLM was added.

Handoff to Ahan: implement cited calendar/fertilizer events only inside
`season_events`, preserve the partial-plan fields exactly, and never invent a
date when the sowing date or curated timing is absent. `HANDOFF READY`

---

## Round 4 — Ahan — Provisional season-plan engine

**Goal:** turn curated crop-calendar and fertilizer rows into a small cited
event list without fabricating dates.

Own these files:

- `backend/tools/season_plan.py`
- `backend/tests/test_season_plan.py`
- only the documented season-plan response schema if needed

Rules:

- Use Supabase `crop_calendar` and `fertilizer_recommendation`.
- If no sowing date is supplied, return month windows and
  `status=provisional`; do not invent a calendar date.
- If a sowing date is supplied, calculate only events whose timing is explicitly
  present in curated text/fields.
- Every event must retain `source_id` and `source_locator`.
- Do not parse new PDFs in this round.

Acceptance:

- Boro, maize and lentil each return a cited sow/harvest window.
- Fertilizer timing is attached only where supported.
- Missing timing remains missing.
- Unit tests pass.

Handoff to Raima:

- Function signature
- Event response example
- Unsupported cases
- `HANDOFF READY`

### Round 4 execution record — 2026-07-24

**Status:** `HANDOFF READY`

- Added `build_season_plan(client, crop_id, *, sowing_date=None,
  variety_id=None, soil_test_class="medium")` in
  `backend/tools/season_plan.py`.
- It reads only shared Supabase `crop_calendar` and
  `fertilizer_recommendation` records. Boro rice, maize and lentil all return
  cited sow/transplant and harvest windows; each event retains `source_id` and
  `source_locator`.
- With no sowing date, all events are `provisional`. With a 2026-10-01 maize
  sowing date, the explicitly curated N ranges became 2026-11-20–25 and
  2026-12-20–25, both cited to BARC FRG 2024 PDF page 91.
- Boro without a variety returns calendar windows only and asks for
  `variety_id`; variety-specific fertilizer rates are never blended. Basal,
  Boro stage-based and lentil inoculation timing remain cited but undated.
- Function signature, response example and unsupported cases are in
  [`docs/round4_season_plan_contract.md`](docs/round4_season_plan_contract.md).
- Tests: `pytest tests/test_season_plan.py` passes, including all three crops,
  explicit maize DAS dates and the Boro variety gate. No endpoint or schema was
  changed in this round.

Handoff to Raima: replace only `/plan/preview.season_events` with this function
in Round 5. Keep the existing partial-plan fields, provenance and safety gates.
`HANDOFF READY`

---

## Round 5 — Raima — Integration, session and trace

**Goal:** integrate Ahan's season-plan function and make the plan inspectable.

Own these files:

- `backend/agent/controller.py`
- `backend/state/store.py`
- tracing helper under `backend/agent/`
- `/plan/preview` route and integration tests

Required behavior:

- Generate or accept a `session_id`.
- Save compact plan state to `farmer_session`.
- Append one `trace_record` for each geo, retrieval, water, financial and
  season-plan computation actually called.
- Store sanitized inputs and outputs only.
- Return trace IDs with the preview.

Acceptance:

- A preview can be reloaded from Supabase.
- Trace count matches the tools called.
- No secret, full raw source document or unnecessary farmer PII is stored.

Handoff to Ahan:

- Final `/plan/preview` response
- UI fields to display
- Known blockers that must be shown as warnings
- `HANDOFF READY`

### Round 5 execution record — 2026-07-24

**Status:** `HANDOFF READY`

- Integrated the cited Round-4 season-plan engine into `POST /plan/preview` for
  Boro rice, maize and lentil. Every event preserves its source ID and locator;
  only the reviewed maize DAS rule becomes dated when a sowing date is supplied.
- The endpoint accepts an opaque `session_id` or generates one, returns it with
  `trace_ids`, saves only the compact derived plan to `farmer_session`, and can
  reload it through `GET /plan/preview/{session_id}`.
- Added a safe trace recorder. It writes exactly one trace for location resolution,
  structured retrieval, crop assessment and each called crop season plan; it adds a
  financial trace only after explicit assumption opt-in. No water trace is written because this
  preview does not call the water model without the required daily inputs.
- Stored trace summaries exclude raw coordinates, credentials, raw source documents
  and unnecessary farmer PII. The full state is equally compact and derived.
- Tests: `pytest tests/test_plan_preview.py tests/test_season_plan.py
  tests/test_supabase_state.py` passes (9 tests). Contract detail is in
  [`docs/round5_session_trace_contract.md`](docs/round5_session_trace_contract.md).

Handoff to Ahan: display `session_id`, cited `season_events`, `financials`,
`missing`/`unassessed`, warnings and a trace-count/evidence link from `trace_ids`.
Keep the ADM3-only AEZ and water-model limitations visible. `HANDOFF READY`

---

## Round 6 — Ahan — Judge-facing demo

**Goal:** make one coherent flow demonstrable without changing backend logic.

Primary option:

- Connect the existing frontend to `/plan/preview`.

Fallback if no frontend is ready:

- Create a minimal page under `backend/demo/` or use `/docs` plus a saved request.
- Create/update `DEMO_RUNBOOK.md`.

The demo must show:

- location and P-code
- AEZ candidate warning
- three crop assessments
- source citations
- financial assumption toggle
- plan events
- trace records or trace IDs

Do not display the Supabase secret key or call Supabase directly from the
browser with it.

Acceptance:

- A fresh browser can complete one Bogura demo flow.
- Bengali text renders correctly.
- Loading/error/unassessed states are visible.
- The runbook fits on one page.

Handoff to Raima:

- Demo URL or exact local command
- Demo input
- Expected visible outputs
- Any last blocking defect
- `HANDOFF READY`

### Round 6 execution record — 2026-07-24

**Status:** `HANDOFF READY`

- Added a self-contained responsive judge page at `GET /demo` in
  [`backend/demo/index.html`](backend/demo/index.html). It calls only same-origin FastAPI
  `/plan/preview` endpoints; browser code contains no Supabase URL or key.
- The prefilled Bangla/English Bogura scenario visibly shows ADM3 P-code,
  explicit AEZ-candidate limitation, three transparent crop assessments,
  source IDs/locators, cited plan events, missing/unassessed states, warnings,
  finance opt-in and safe trace IDs.
- Loading, API-error and deliberately unassessed states are rendered instead of
  silently hidden. The page can reload the saved compact plan using its session
  ID.
- Browser QA passed with Bengali text, no-finance and finance-opt-in paths, plus
  saved-plan reload. The finance path showed seven traces; the no-finance path
  showed six.
- One-page presenter instructions are in [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).

Handoff to Raima: run `uvicorn app:app --reload`, open `/demo`, and
use the prefilled Bogura values. No blocking defect remains. Keep the displayed
AEZ, water, finance and ranking limitations in the final pitch. `HANDOFF READY`

---

## Round 7 — Raima — Final integration and freeze

**Goal:** ship the most reliable end-to-end slice; no feature expansion.

First 15 minutes:

1. Fix only blockers from Round 6.
2. Run:

   ```bash
   python -m kb.validate
   pytest
   ```

3. Verify `/health`, `/plan/preview`, `/kb/search` and the demo surface against
   the deployed environment.

Next 10 minutes:

- Deploy/redeploy.
- Confirm environment variables are set server-side.
- Confirm `.env` and keys are absent from Git.
- Capture the final demo request and expected response.

Final 5 minutes:

- Freeze code.
- Rehearse the demo once.
- State the limitations honestly: admin-level AEZ fallback, provisional
  financial values, no paddy water score and no calibrated final ranking.

Acceptance:

- Validation and tests pass.
- Deployed health check passes.
- One complete demo flow succeeds.
- No P0 defect remains.

---

## Handoff template

Copy this at minute 25 of every round:

```text
ROUND:
OWNER:
COMPLETED:
FILES CHANGED:
COMMANDS/TESTS RUN:
RESULT:
KNOWN ISSUE:
NEXT PERSON'S FIRST ACTION:
COMMIT/CHECKPOINT:
HANDOFF READY
```

## Cut line if time slips

Protect these in order:

1. Supabase migration/seed and health
2. One deterministic `/plan/preview` flow
3. Provenance and assumption warnings
4. Tests and demo runbook
5. Session/trace persistence
6. Visual polish

If behind, cut visual polish first. Never cut source provenance, safety
warnings, the assumption gate or the paddy fail-closed behavior.

### Round 7 execution record — 2026-07-24

**Status:** `HANDOFF READY / FROZEN`

- No new product feature was added. The only Phase-6 presentation defect found
  during browser QA (a missing Boro soil citation) was fixed so an unassessed
  crop renders safely.
- Final checks passed: `python -m kb.validate` reported no errors or
  warnings, `pytest` reported 34 passing tests, and `git diff --check` passed.
- Final live local rehearsal against the configured Supabase project passed:
  `/health` was `ok`; `/kb/search` returned cited `barc_frg_2024` maize content;
  `/plan/preview` returned a partial plan with seven finance-enabled safe traces;
  saved state reloaded; and `/demo` rendered the full Bogura flow with P-code
  `BD50100020` and 13 cited events.
- `.env` is Git-ignored. A repository scan found only deliberately redacted
  examples and test fixtures, never a live credential.
- Deployment caveat: no hosting target or deployment configuration is present
  in this repository, so no external deployment was created. The exact local
  command, request and expected output are frozen in
  [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).

Final limitations to say aloud: AEZ is an ADM3 candidate rather than a
point-in-polygon result; financial amounts are provisional assumptions; paddy
water scoring fails closed; and crop assessment is explicitly not a calibrated
final ranking. `HANDOFF READY`
