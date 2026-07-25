# AgriSense judge demo

## Start

Configure the server-only `backend/.env`, migrate and seed once, then run:

```bash
# terminal 1
cd backend
uvicorn app:app --reload

# terminal 2
cd frontend
npm run dev
```

Open <http://127.0.0.1:3000>. Opening
<http://127.0.0.1:8000/demo> redirects to the same maintained interface.
The browser never receives a Supabase credential.

## One complete Tier-0 path

1. The first screen is **Farm login**. Create a named farm, log in with an
   existing Farm Access ID, or choose **Continue as guest**.
2. On **Projects**, create a project such as `Bogura Rabi 2026`, or open an
   existing project. The advisor is not available outside a project.
3. In **Conversational intake**, use live location or choose Bogura Sadar on the
   map. A reproducible coordinate is `24.89539917, 89.35605547`.
4. Send: “I have 1 acre of well-drained loam land in Bogura Sadar for the Rabi
   season. Irrigation is available and my budget is BDT 80,000.”
5. Answer only the targeted follow-ups, if any.
6. Choose sowing date `2026-10-01`, laboratory soil-test class **Medium**, net
   planned irrigation `0 mm/day`, and starting moisture deficit `40 mm`.
7. Enable **Include editable finance assumptions**. The app deliberately cannot
   produce the required costed ranking without this consent.
8. Select **Rank 3 candidate crops**.
9. Compare maize, lentil and wheat. The top row is labelled **Agent
   recommended**, but nothing is preselected.
10. Select any ranked crop and confirm **Build plan for …**. Use a non-top crop
   once to demonstrate that the farmer—not the agent—makes the final choice.

Named farms can copy their opaque Farm Access ID from the project hub. Guest
projects are stored in Supabase during that guest session but cannot be resumed
after logout.

Show the result panels in order:

- Live Weather: exact returned rain, temperature and ET0.
- Crop Assessment: maize, lentil and wheat ranked with soil, water, risk, rough
  profit and budget fit.
- Season Plan: dated land preparation through harvest.
- Financial Projection: editable assumptions, itemized costs, yield, revenue,
  profit, ROI and break-even. Change one input and recalculate.
- Explained Reasoning: a four-step, plain-language decision trail from farmer
  inputs through farmer crop confirmation.
- Cited Knowledge: deduplicated crop-specific guidance without internal
  similarity scores or chunk IDs.
- Agent Trace: readable activities such as checking location, calling
  Open-Meteo, retrieving guidance and calculating water stress. Expand
  **Technical call details** only when a judge asks for payload-level evidence.

## Tier-1 proof

Open **Advanced advisor**:

- show the consented-memory status;
- select **Use saved profile** to prove restoration is explicit rather than a side effect of location;
- open a saved crop project with **Open + refresh**;
- show forecast-triggered alerts and any adjusted near-term tasks;
- inspect fertilizer totals, application dates, irrigation checks and organic
  alternatives;
- show conservative pest/disease screening, non-chemical options, DAE warning
  and estimated scouting cost;
- leave rainfall at `-30%`, budget at `-40%`, select **Simulate revised plan**,
  and inspect the farmer-facing **What could happen** cards for rank, water,
  budget fit and rough profit.

Use **Saved plan reload** to prove persisted results and trace retrieval.

## Expected safety messages

- Bogura Sadar resolves to ADM3 P-code `BD50100020`; AEZ values are
  administrative candidates, not a farm-point classification.
- Finance is explicitly labelled as editable project-demo assumptions.
- Water thresholds are an uncalibrated project policy.
- Paddy water scoring fails closed.
- Pest advice is screening and prevention only; registered product choice and
  current status must be confirmed with DAE.
- Advice is omitted if crop-specific RAG retrieval is below threshold.

If planning fails, run `python -m kb.verify` from `backend/`, confirm the
server-only environment, and confirm Open-Meteo is reachable.
