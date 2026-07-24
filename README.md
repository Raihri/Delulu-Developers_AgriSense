# AgriSense AI

AgriSense AI is the Delulu Developers entry for the IUT Agentic AI Hackathon. The product
goal is to take a Bangladesh smallholder farmer from a vague request to a grounded,
weather-aware, costed season plan and keep every recommendation inspectable.

## Repository Status

The repository is currently in the **architecture and data-source curation phase**. It does
not yet contain a runnable prototype. This is intentional disclosure, not a setup omission.

Current artifacts:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — corrected Tier 0 implementation contract
- [`DATA_SOURCES.md`](DATA_SOURCES.md) — corrected and reviewed source catalog
- [`kb/sources.yaml`](kb/sources.yaml) — machine-readable source/licence allowlist
- `Agentic_AI_Hackathon_Final_Question.pdf` — official problem statement
- `external_dataset_link.pdf` — original source-list PDF, preserved as received

## Tier 0 Scope

The planned end-to-end path covers all eight required capabilities:

1. Conversational intake for location, farm size, soil, water, budget and target season
2. Live weather grounding using Open-Meteo
3. At least three crop candidates with suitability, water deficit, risk and rough profit
4. A dated season calendar with confirmed near-term and provisional long-term events
5. Unit-aware itemized costs, revenue, profit, ROI and break-even
6. Structured, source-backed explanations
7. A curated structured knowledge base plus bilingual RAG
8. A visible, sanitized trace of APIs, retrievals and deterministic calculations

Tier 1 pesticide, proactive alert and persistent-memory hooks are designed but should not be
built until the Tier 0 path is stable.

## Architecture Summary

```text
Farmer conversation
  → validated farm profile + coordinates/P-code
  → live forecast + historical weather baseline
  → deterministic water balance and crop suitability
  → structured phenology/fertilizer calendar
  → unit-aware financial engine
  → provenance-backed explanation + judge-visible trace
```

The LLM extracts intent, chooses tools and verbalizes existing evidence. It does not create
agronomic numbers. Structured facts live in validated SQLite tables; prose guidance uses
metadata-filtered lexical/vector retrieval.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for schemas, formulas, failure behavior, module
layout, build order and acceptance gates.

## Data Policy

Public access is not treated as permission to redistribute. Every source must have:

- an exact asset or API URL rather than an organization homepage;
- publisher, title, version/date, access date and update policy;
- licence/redistribution status;
- a SHA-256 hash for downloaded assets;
- page/table/section or API-field locators;
- canonical units, geographic/temporal scope and confidence.

Only data that passes raw → normalized → curated quality gates may drive a recommendation.
See [`DATA_SOURCES.md`](DATA_SOURCES.md) and [`kb/sources.yaml`](kb/sources.yaml).

## Real, Inferred and Assumed Data

| Category | Planned treatment |
|---|---|
| Weather forecast | Real Open-Meteo API response; cached with request time, model/window, units and trace evidence |
| Historical climate | Open-Meteo reanalysis for a declared baseline such as 1991–2020; labelled as a regional seasonal prior |
| Fertilizer guidance | Curated from the exact BARC FRG-2024 asset with contextual dimensions and page/table locators |
| Crop/variety/calendar guidance | Curated from pinned BRRI, BARI and AIS assets |
| Administrative geography | Versioned HDX Bangladesh COD resource with P-codes |
| Soil | Farmer-reported where possible; map/model inference is labelled low-confidence and is not a soil test |
| Yield baseline | Cited BBS/BRRI/BARI value with crop, geography, season, year and statistic |
| Market/input prices | Seeded editable assumptions until a dated source is integrated |
| Financial outputs | Deterministic calculations from area, yield, price and itemized quantities; never LLM-generated |

## Planned Local Development

These commands describe the intended implementation contract; they will become executable
when the application scaffold is added:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn agrisense.app:app --reload
```

Do not claim the prototype is runnable until `requirements.txt`, the `agrisense/` package,
curated demo data and tests exist.

## Required Quality Gates

Before a demo build can be marked complete:

- financial area scaling, unit conversion, break-even and zero guards pass;
- weather payload dates/units/freshness validate;
- supported seasons each return at least three assessed crops;
- fertilizer records retain AEZ/soil-test/yield-target context;
- Bengali and English retrieval tests return relevant cited material;
- every final number has a provenance and trace/formula reference;
- no trace displays secrets or unnecessary farmer PII;
- source and licence checks pass for every bundled asset.

## Source Documents

The official requirements are in `Agentic_AI_Hackathon_Final_Question.pdf`. The original
`external_dataset_link.pdf` contains useful organizations but several generic, indirect or
licence-sensitive links. It remains unchanged for auditability; the maintained corrections
are in [`DATA_SOURCES.md`](DATA_SOURCES.md).
