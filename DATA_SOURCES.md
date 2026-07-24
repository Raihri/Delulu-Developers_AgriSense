# AgriSense AI Data Sources

This is the reviewed, human-readable source catalog for AgriSense AI. It corrects and
narrows the generic links in `external_dataset_link.pdf`. The PDF is preserved as received;
this file and `kb/sources.yaml` are the maintained source of truth.

**Reviewed:** 2026-07-24

**Rule:** a public homepage is a discovery link, not an ingestible dataset. Downloaded
assets must be versioned, hashed, licensed for the intended use, and linked to individual
normalized rows or RAG chunks.

## Approved Core Sources

| ID | Source | Intended use | Ingestion decision |
|---|---|---|---|
| `barc_frg_2024` | [BARC Fertilizer Recommendation Guide 2024](https://apps.barc.gov.bd/fertilizer_recommendation/FRG%20English%2030.10.2024.pdf) | Fertilizer recommendations by crop and contextual dimensions | Use the exact 2024 document. Extract crop, AEZ/land type, soil-test/yield-target, nutrient, rate, timing, unit and page/table locator. Human-check every demo crop. |
| `srdi_soil_maps` | [SRDI soil maps](https://srdi.gov.bd/pages/static-pages/6922dfb3933eb65569e23904) | AEZ and broad regional soil context | Use only as a regional prior. Record map year and scale. Do not present a map-derived class as a plot-level soil test. |
| `fao_cropwat` | [FAO CROPWAT](https://www.fao.org/land-water/resources/tools/software/cropwat/en) | Crop-water methodology and irrigation scheduling | Correct replacement for the PDF's indirect Google/obsolete URL. Use with local crop/soil data and Open-Meteo ET₀; do not copy an unexplained static seasonal water number. |
| `fao_56` | [FAO Irrigation and Drainage Paper 56](https://www.fao.org/4/X0490E/X0490E00.htm) | ET₀, crop coefficients and crop evapotranspiration methodology | Reference calculations by chapter/table locator. Treat publication copyright separately from public web access. |
| `ais_crop_calendar` | [AIS Bangladesh crop calendar](https://ais.gov.bd/pages/static-pages/6922dbbd933eb65569e0c355) | Local sowing/harvest windows | Use the exact calendar asset rather than the AIS homepage. Preserve Bengali names and calendar conventions. |
| `ais_crop_production` | [AIS crop production technologies](https://ais.gov.bd/site/page/2a525876-6ac6-45a4-b506-5b6363573c37/%5Bfront%5D) | Local extension guidance | Curate crop-specific pages. Store page title, update date, language and section locator. |
| `hdx_cod_bgd` | [Bangladesh COD administrative boundaries](https://data.humdata.org/dataset/cod-ab-bgd) | ADM boundaries, gazetteer and stable P-codes | Preferred boundary source. Pin a resource/version and its own licence; spatially join coordinates instead of matching free-text place names. |
| `brri_released_varieties` | [BRRI released rice varieties](https://brri.gov.bd/site/page/6952c1d9-af2c-404c-a2e7-f7eb5c1cae92/-/released-rice-variety-of-brri) | Rice varieties, season/ecosystem and stress tolerance | Curate exact released-variety assets and publication/update dates. Do not ingest test-looking dynamic rows without validation. |
| `brri_rice_database` | [BRRI rice database index](https://brri.gov.bd/site/page/f6e878c8-ceac-402d-9bed-6fb29a787428/Rice-Database) | Rice calendars, yield and district/season references | Discovery index only until each linked dataset is pinned and validated. |
| `bari_agro_tech_handbook` | [BARI Agro-Technology Handbook](https://bari.gov.bd/site/page/841c811d-14ad-4796-97a4-41cd602d3cfa/Agro-Technology-Hand-Book) | Agronomy for non-rice crops | Pin one handbook edition and exact asset before ingestion. Store crop, variety, operation, timing, region and locator. |
| `dae_registered_pesticides` | [DAE registered pesticide list](https://dae.gov.bd/sites/default/files/files/dae.portal.gov.bd/page/8a812db0_3544_4105_b066_df78074d3efb/Registered%20Agricultural%20PesticidesList%20%286%29.pdf) | Bangladesh registration status, crop/pest and dosage | Tier 1 safety source. Pair with DAE cancellation/status updates and record the source date. Never recommend an unregistered product. |
| `bbs_agri_yearbook` | [BBS Agricultural Statistics Yearbooks](https://bbs.gov.bd/site/page/3e838eb6-30a2-4709-be85-40484b0c16c6/) | Area, production, yield and selected labor/statistical baselines | Pin the 2024 yearbook asset. Keep geography, season, year, statistic and unit. Do not assume it contains every input-cost line item. |

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
- Pesticide cancellation/status updates matched to the registered list
- Reviewed effective-rainfall and irrigation-efficiency assumptions for Bangladesh

Until added, financial prices remain editable assumptions and soil/map inferences carry an
explicit confidence label.
