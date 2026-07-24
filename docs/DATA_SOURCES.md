# AgriSense AI Data Sources

This is the reviewed, human-readable source catalog for AgriSense AI. It corrects and
narrows the generic links in `external_dataset_link.pdf`. The PDF is preserved as received;
this file and `backend/kb/sources.yaml` are the maintained source of truth.

**Reviewed:** 2026-07-24

**Rule:** a public homepage is a discovery link, not an ingestible dataset. Downloaded
assets must be versioned, hashed, licensed for the intended use, and linked to individual
normalized rows or RAG chunks. Downloaded does not mean curated or safe: those states are
recorded separately in `backend/kb/sources.yaml`.

## Approved Core Sources

| ID | Source | Intended use | Ingestion decision |
|---|---|---|---|
| `barc_frg_2024` | [BARC Fertilizer Recommendation Guide 2024](https://apps.barc.gov.bd/fertilizer_recommendation/FRG%20English%2030.10.2024.pdf) | Fertilizer recommendations by crop and contextual dimensions | The exact local file `dataset/FRG English 30.10.2024.pdf` is registered as 260 pages with SHA-256 `fba07db…db927`. Medium-soil-test rows for BRRI dhan28/dhan29, maize and lentil are human-reviewed with PDF page locators. |
| `srdi_soil_maps` | [SRDI soil maps](https://srdi.gov.bd/pages/static-pages/6922dfb3933eb65569e23904) | AEZ and broad regional soil context | Four maps are pinned: AEZ (1995), General Soil (1997), Organic Matter (2020), and Soil Reaction (2020). Use only as regional priors; the first two assets are not 2010 maps. |
| `fao_cropwat` | [FAO CROPWAT](https://www.fao.org/land-water/databases-and-software/cropwat/en/) | Provisional Kc/stage/root-depth parameter seeds | Five crop and three soil files are pinned without the program/examples. They are starting values only. The Pulses file is a low-confidence lentil proxy, and the paddy Rice format is not approved for water suitability scoring. |
| `fao_56` | [FAO Irrigation and Drainage Paper 56 Rev.1](https://doi.org/10.4060/cd6621en) | ET₀, crop coefficients and crop evapotranspiration methodology | The 434-page second edition, revised 2025, is pinned under CC BY 4.0. Reference calculations by chapter/table locator; separately check third-party material and photographs. |
| `ais_crop_calendar` | [AIS Bangladesh crop calendar](https://ais.gov.bd/pages/static-pages/6922dbbd933eb65569e0c355) | Local sowing/harvest windows | The exact two-page Bengali calendar is pinned locally and is image-only. Demo rows are human visual transcriptions. Treat national month bands as priors, not location-specific dates. |
| `ais_crop_production` | [AIS crop production technologies](https://ais.gov.bd/site/page/2a525876-6ac6-45a4-b506-5b6363573c37/%5Bfront%5D) | Local extension guidance | Three live in-scope pages are pinned: Aus rice (2025), maize (2026), and lentil (2026). Wheat and potato URLs returned 404 and were not substituted because the pinned BARI handbook already covers those crops. |
| `hdx_cod_bgd` | [Bangladesh COD administrative boundaries](https://data.humdata.org/dataset/cod-ab-bgd) | ADM boundaries, gazetteer and stable P-codes | The v03 ADM3 GeoJSON is valid/current with 507 unique ADM3 P-codes. Its names are English only; Bengali aliases are curated separately. It supplies administrative geometry, not AEZ geometry. |
| `brri_released_varieties` | [BRRI released rice varieties](https://brri.gov.bd/pages/static-pages/6922dc75933eb65569e107be) | Rice varieties, season/ecosystem and stress tolerance | The three varieties named in the original demo brief—BRRI dhan28, dhan29 and salt-tolerant dhan97—are pinned. Other leaflets remain out of scope until explicitly supported. |
| `brri_rice_database` | [BRRI rice database index](https://brri.gov.bd/site/page/f6e878c8-ceac-402d-9bed-6fb29a787428/Rice-Database) | Location-specific rice variety guidance | Only the 19-page AEZ/district/land-type Aman variety guide is pinned. Duplicate statistics, calendar, irrigation, trade, fertilizer and dashboard assets are excluded. |
| `bari_agro_tech_handbook` | [BARI Agro-Technology Handbook](https://bari.gov.bd/site/page/841c811d-14ad-4796-97a4-41cd602d3cfa/Agro-Technology-Hand-Book) | Agronomy for non-rice crops | The 650-page 10th edition is pinned; editions 6–9 are excluded. Its extracted Bengali uses a legacy font and is not RAG-ready. Use OCR or a reviewed Bijoy/legacy conversion, then human-check before promotion. |
| `dae_registered_pesticides` | [DAE registered pesticide files](https://dae.gov.bd/site/files/4ea8e032-77df-4e6b-952b-5eab3004113c/-Registered-Pesticide) | Bangladesh registration status, crop/pest and dosage | The 189-page agricultural register approved through PTAC meeting 81 is pinned; public-health and separate bio-pesticide files are excluded. Do not recommend from this list until cancellation/status updates are cross-checked. |
| `bbs_agri_yearbook` | [BBS Agricultural Statistics Yearbooks](https://bbs.gov.bd/site/page/3e838eb6-30a2-4709-be85-40484b0c16c6/) | Area, production and yield statistics | The 696-page 2024 yearbook is pinned and national Boro/maize/lentil baselines are curated. A 2025 edition is now available but is not the local build asset. Carrot Table 3.9.29 is quarantined because the expected 2023-24 heading and values repeat 2022-23. |

## Local Dataset State

All broad assets planned for the current slice are present: FRG 2024, the four selected
SRDI maps, FAO-56 Rev.1, five CROPWAT crop files, three CROPWAT soil files, AIS calendar and
three crop pages, HDX ADM3, three BRRI variety leaflets, the selected BRRI rice-database
file, BARI 10th edition, DAE PTAC81 and BBS 2024. Open-Meteo is a live API, not a download;
GADM and Plantwise are reference-only and are intentionally not downloaded.

Presence is not readiness:

| Source | Download | Curation | Safety/use |
|---|---|---|---|
| FRG | complete | four demo groups, medium soil-test class | provisional licence; cited rows only |
| CROPWAT | chosen subset complete | maize + Pulses-proxy stages | provisional seeds; no paddy score |
| AIS calendar | complete | three visual rows | national prior |
| BARI | complete | requires OCR/conversion | excluded from RAG |
| HDX | complete | ADM3/P-codes + demo aliases | approved administrative geometry |
| DAE pesticide | complete | status overlay missing | blocked |
| BBS 2024 | complete | three yield baselines | approved with carrot-table quarantine |

## Source Precedence

Use FAO-56 Rev.1 for water formulas/methods; CROPWAT only for provisional parameter seeds;
BARC FRG for fertilizer rates/timing; BRRI for rice varieties; BARI for detailed non-rice
agronomy; AIS for calendar and concise extension guidance; SRDI for soil/AEZ priors; HDX for
administrative geometry; and BBS for area/production/yield statistics. Similar facts are not
blended. Conflicts are quarantined for human review. The enforceable form is
`backend/kb/curated/source_precedence.yaml`.

## Conditional or Reference-Only Sources

| ID | Source | Restriction or caution |
|---|---|---|
| `gadm_bgd_4_1` | [GADM 4.1 downloads](https://gadm.org/download_country.html) and [licence](https://gadm.org/license.html) | Academic/non-commercial use is allowed, but redistribution or commercial use requires permission. Prefer HDX COD for the product architecture. |
| `plantwise_kb` | [PlantwisePlus Knowledge Bank](https://plantwiseplusknowledgebank.org/) and [CABI terms](https://plantwiseplustoolkit.org/terms/) | Licences vary by content type. Technical factsheets and distribution downloads may be non-commercial; farmer factsheets/decision guides have different terms. Ingest only individually licensed content with attribution. |
| `hdx_bgd_group` | [HDX Bangladesh group](https://data.humdata.org/group/bgd) | Discovery page only. It does not itself establish that a crop-suitability dataset is authoritative or suitable for recommendation. |

## Live Operational Source

| ID | Source | Use |
|---|---|---|
| `open_meteo` | [Forecast API](https://open-meteo.com/en/docs) and [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) | Fetch the live 16-day forecast and ET₀ for near-term operations; use a declared historical baseline for seasonal priors. Store request window, timezone, units, model/dataset, timestamps and sanitized evidence. |

## Sources Still Needed

These gaps must stay visible instead of being filled with model recall:

- A dated, location-aware source for farmgate crop prices
- Dated input prices for seed, fertilizer, labor and irrigation
- Machine-readable plot- or region-level soil test data with a usable licence
- A licensed georeferenced AEZ polygon dataset for point lookup beyond the reviewed Bogura
  ADM3 candidate crosswalk
- Pesticide cancellation/status updates matched to the registered list
- Bangladesh-local Kc/root-zone/runoff/irrigation-efficiency calibration and reviewed paddy
  land-preparation, ponding, percolation and field-loss inputs

Until added, financial prices remain explicit editable assumptions, water-class thresholds
remain an uncalibrated project policy, and soil/map inferences carry an explicit confidence
label.
