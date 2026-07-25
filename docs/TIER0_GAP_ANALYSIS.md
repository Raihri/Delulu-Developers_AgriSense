# Tier-0 and Tier-1 acceptance audit

Audit date: 2026-07-25
Scope: the maintained Rabi judge flow in the current repository.

## Verdict

The previously identified implementation gaps are resolved for the declared
Rabi demo slice. The single supported end-to-end path starts with a short
conversation and returns a grounded, explained, costed season plan with visible
traces. Tier-1 features are attached to that same saved plan.

This is not a claim of national or all-season coverage. Rabi is the only season
with three reviewed comparable crops, and the limitations listed below remain
visible to the farmer.

## Tier-0 acceptance

| # | Acceptance condition | Result | Verification surface |
|---|---|---|---|
| 1 | Collect location, size, soil, water, budget and season conversationally; ask only for missing values | **Pass** | `/intake/chat`, evidence-checked Gemini schema, targeted prompts |
| 2 | Use real weather values in recommendations | **Pass** | Open-Meteo daily rain/temp/ET0 enter the FAO-56 balance and risk flags |
| 3 | Rank at least three profile/season/weather candidates with suitability, water, risk and rough profit | **Pass (Rabi)** | Maize, lentil and wheat from `/plan/rank` |
| 4 | Give the chosen crop a dated land-preparation-to-harvest plan | **Pass** | The agent ranks and recommends; the farmer explicitly selects a ranked crop before `chosen_plan.events` is built |
| 5 | Produce itemized cost, yield, revenue, profit, ROI and break-even and react to changed inputs | **Pass with consent** | Editable overrides and recalculation in the financial panel |
| 6 | State the farm inputs and retrieved data behind every recommendation | **Pass** | Deterministic `explanations[].based_on`; weak retrieval suppresses advice |
| 7 | Store public agronomy in a KB and use RAG in advice | **Pass for slice** | Structured tables plus per-crop vector retrieval before rendering |
| 8 | Show every tool call, parameters and raw returned values needed to check numbers | **Pass** | Linked session traces with full bounded outputs |

## Tier-1 acceptance

| Capability | Result | Safety boundary |
|---|---|---|
| Persistent farmer memory | **Pass with explicit opt-in** | Explicit profile restore plus farmer-confirmed project index keyed by opaque farmer ID |
| Proactive weather alerts | **Pass while app is active** | Active projects refresh on open/every 15 minutes; eligible near-term events receive revised dates |
| Fertilizer and irrigation scheduler | **Pass** | Crop/soil-specific farm totals, stage, timing and allocated costs are derived from the cited plan |
| Pest and disease risk | **Pass as conservative screening** | Crop + derived growth stage + weather; no pesticide prescription; DAE confirmation required |
| What-if scenarios | **Pass** | Budget and rainfall changes re-run the deterministic planner and expose deltas |

## Closed findings

- Added wheat across calendar, soil, water-stage, fertilizer, yield, cost and
  RAG data so Rabi has three comparable crops.
- Made live weather values enter the crop water balance, risk flags and
  weather-triggered advice.
- Connected conversational intake directly to the complete ranking path and
  forwarded the farmer's sowing date.
- Gated finance behind explicit consent and made overrides affect recalculation.
- Retrieved crop-specific RAG evidence before rendering any recommendation.
- Added per-recommendation `based_on` records and links to explanation traces.
- Expanded trace output to include the bounded structured rows and raw weather
  series needed to reproduce results.
- Replaced the stale standalone demo with a redirect to the maintained frontend.
- Added consented memory, weather watch, input scheduling, pest screening and
  scenario comparison.
- Made memory restoration explicit, organized selected plans as farmer projects,
  and added live project refresh plus growth-stage-aware pest screening.
- Removed the local environment file from Git tracking and excluded secrets from
  Git and Docker contexts.

## Deliberate limitations

- Non-Rabi seasons fail closed if three complete candidates are unavailable.
- AEZ is an ADM3-level candidate set, not a farm-point soil classification.
- CROPWAT parameters and water-class thresholds remain labelled provisional
  seeds/project policy.
- Financial values are editable assumptions, not live market prices.
- Deterministic demo vectors are not presented as a production semantic model.
- Pest output cannot choose a chemical product or assert current registration.
- Project monitoring runs while the app is active; there is no offline push
  notification daemon.
- Provider credential rotation and published-history cleanup require repository
  owner action; see `SECURITY.md`.

## Reproduction

```bash
cd backend
python -m kb.validate
python -m kb.verify
pytest

cd ../frontend
npm run lint
npm run build
```

The exact human demo is in `docs/DEMO_RUNBOOK.md`.
