# AgriSense judge demo

Run the API with its server-only Supabase database variable configured:

```bash
cd backend
uvicorn app:app --reload
```

Open [http://127.0.0.1:8000/demo](http://127.0.0.1:8000/demo). The page talks only to
the local FastAPI API; it never receives a Supabase key or connects to Supabase directly.

Use the prefilled Bogura Sadar scenario:

- Latitude `24.89539917`, longitude `89.35605547`
- loam, well drained, 1 acre
- sowing date `2026-10-01`
- first leave **Include provisional financial assumptions** off; then turn it on and run again

The final API payload behind the finance-enabled demonstration is:

```json
{
  "lat": 24.89539917,
  "lon": 89.35605547,
  "soil_class": "loam",
  "drainage_condition": "well_drained",
  "area_acres": 1,
  "sowing_date": "2026-10-01",
  "soil_test_class": "medium",
  "allow_assumptions": true
}
```

Expected visible proof:

1. Bogura Sadar ADM3 P-code `BD50100020` and the explicit ADM3-level AEZ-candidate warning.
2. Boro rice, maize and lentil assessments with their source IDs/locators; no fabricated ranking.
3. Cited seasonal operations. Maize shows reviewed dated N windows after the supplied sowing date.
4. Finance is blocked until the checkbox is explicitly enabled; after opt-in it is labelled provisional.
5. Missing weather/irrigation inputs, unassessed paddy constraints and warnings remain visible.
6. Session ID and safe trace IDs are visible; click **Saved plan reload করুন** to demonstrate persistence. Expect six traces without finance and seven with finance enabled.

Honest limitations: AEZ is an administrative candidate, not point-resolved; financial values
are demo assumptions; paddy water scoring fails closed; the crop list is not a calibrated final
ranking. If the page shows an error, confirm the migration/build has run and the server-only
Supabase URL is available in `.env`.
