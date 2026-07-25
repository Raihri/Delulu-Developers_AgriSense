# Tier-1 implementation map

The authoritative list is page 4 of
`docs/Agentic_AI_Hackathon_Final_Question.pdf`. Tier 1 has five capabilities.
“Farmer profile” and “farm project” are not extra rubric points; they are the
persistence structure that makes the five capabilities coherent across
sessions.

## Data lifecycle

1. The first page requires the farmer to create or log into a named farm using
   its opaque **Farm Access ID**, or explicitly continue as a guest. Logout
   clears named-farm access from that browser and never deletes the saved farm.
2. `farmer_profile.profile_json` follows
   `backend/state/farmer_memory.schema.json` (`farmer_memory_v3`) and stores a
   bounded profile, a location rounded to
   six decimals, up to eight recent conversation entries, and an index of at
   most ten confirmed projects.
3. A saved profile is never silently applied by a location click. The farmer
   selects **Use saved profile**, which sends the auditable
   `profile_restore` intake event.
4. Before the advisor opens, the farmer must create or open a canonical
   `farm_project` row. Draft intake, the ranked plan, farmer crop selection,
   trace sessions and scenario sessions remain attached to that same project.
5. The active project refreshes when the app opens and every 15 minutes while
   the app remains open. **Open + refresh** is also available. This is not a
   server-side push notification service; no monitoring occurs while every
   client is offline.

## Five capabilities

| PDF requirement | Implementation | Visible proof | Boundary |
|---|---|---|---|
| Persistent memory | `POST /farmer/profile/session`; `POST /farmer/profile/{farmer_id}/projects`; canonical `farm_project` rows; project-linked intake/plan/scenario sessions; bounded `farmer_memory_v3` profile index | First-screen farm/guest entry, mandatory project hub, **Use saved profile**, project cards | The Farm Access ID is opaque demo access, not password-grade authentication; guest rows persist but have no resumable key; logout is non-destructive |
| Proactive weather-triggered advice | `POST /farmer/profile/{farmer_id}/projects/{project_id}/refresh` fetches Open-Meteo again, recomputes alerts, and creates adjusted operation dates | Project alert count, adjusted-operation text, `advanced.refresh_saved_project` trace | App-open/15-minute monitoring, not an offline push daemon; trigger thresholds are disclosed project policy |
| Fertilizer and irrigation scheduler | `build_input_scheduler` derives farm totals, stage/date, allocated costs, and organic options from the farmer-selected crop plan and laboratory soil-test class | Scheduler header names crop and soil-test class; expanded cited quantities | Irrigation entries are checkpoints using the farmer-declared net depth, not an invented prescription |
| Pest and disease risk | `build_pest_disease_risk` combines crop, derived current growth stage, and live forecast with conservative rules | Each risk shows growth stage, weather trigger, prevention, treatment, scouting cost, and DAE warning | Screening only; no pesticide product or dosage |
| Scenario simulation | `POST /plan/scenario` reuses the base project’s saved weather snapshot, applies rainfall and/or budget changes, reruns the deterministic planner and saves a new plan session | Plain-language “what could happen” cards for ranking, water, budget and rough profit; raw deltas stay technical | Holding the base snapshot constant isolates the farmer’s hypothetical change; the same disclosed provisional finance and water policies still apply |

## Main code locations

- `backend/app.py`: profile restore, project creation, project refresh and
  scenario endpoints.
- `backend/state/store.py`: bounded Supabase profile/project/session/trace persistence.
- `backend/supabase/migrations/202607250003_farm_project.sql`: canonical
  project ownership and lifecycle schema.
- `backend/tools/advanced.py`: weather adjustments, input scheduler,
  growth-stage pest screening and scenario deltas.
- `frontend/app/page.tsx`: first-screen login/guest gate, mandatory project hub,
  explicit memory restore, active-project refresh and all five evidence panels.
- `backend/tests/test_intake_api.py`,
  `backend/tests/test_plan_from_conversation.py`, and
  `backend/tests/test_advanced.py`: cross-session, project refresh and
  growth-stage regression coverage.
