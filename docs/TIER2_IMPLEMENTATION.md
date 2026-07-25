# Tier-2 plant-health image module

AgriSense exposes plant-health screening as a separate `/plant-health` page so
the existing Tier-0/Tier-1 farm-planning workflow remains isolated.

## Request path

1. The browser accepts one JPEG, PNG or WebP image, previews it locally and
   sends it only after the farmer presses **Check plant health**.
2. The Next.js route validates the file and forwards Base64 data to FastAPI.
3. FastAPI validates the declared MIME type against the binary signature and
   caps the decoded image at 8 MB.
4. FastAPI sends the image inline to Gemini `generateContent`, using structured
   JSON output, the selected English/Bangla response language and the
   backend-only Gemini API key.
5. AgriSense normalizes the visual screening to at most three possible causes.
   The browser receives no API key or unbounded raw model response.

## Bengali and voice access

- The `/plant-health` page has an **English / বাংলা** switch. Selecting Bangla
  localizes the complete interface and asks Gemini to write every farmer-facing
  diagnosis field in Bangla while keeping scientific names in Latin form.
- Farmers may type optional symptom notes or dictate them through the browser's
  speech-recognition feature (`bn-BD` or `en-US`). AgriSense sends only the
  resulting text with the scan; it does not upload microphone audio.
- Instruction and result buttons use browser speech synthesis to read the
  guidance aloud in the selected language.
- Voice controls disable cleanly when the browser lacks the relevant Web Speech
  capability, while photo upload and typed notes continue to work.

## Configuration

```dotenv
GEMINI_API_KEY=replace-with-your-google-ai-studio-key
GEMINI_MODEL=gemini-3.1-flash-lite
```

The same server-only Gemini configuration supports intake extraction, project
scenario chat and Tier-2 image screening. The key belongs only in
`backend/.env`; do not create a `NEXT_PUBLIC_*` copy.

The provider endpoint is fixed to Google's
`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
API and authenticates using the `x-goog-api-key` header. Images remain below
Gemini's 20 MB total inline-request limit because AgriSense enforces an 8 MB
decoded-image limit.

## Safety boundary

- Results are visual screening, not laboratory confirmation.
- Percentages are explicitly labelled rough Gemini estimates, not calibrated
  diagnostic probabilities.
- The UI shows multiple possible causes instead of presenting the first result
  as a confirmed diagnosis.
- The system prompt treats image text as untrusted and forbids pesticide names,
  active ingredients, dosage, mixing and chemical-treatment instructions.
- The public response includes visible evidence, low-risk prevention and a
  field sign to check next, followed by a DAE confirmation warning.
- Optional dictated or typed notes are capped at 1,000 characters and treated
  as unverified farmer context, never as instructions to the model.
- Gemini is not asked for citations or source links, so fabricated references
  are not rendered.
- Invalid formats, disguised files, oversized images, missing credentials,
  quota exhaustion, unavailable models and provider outages fail explicitly.

## Main code locations

- `frontend/app/plant-health/page.tsx`: upload/camera and result interface.
- `frontend/app/api/plant-health/diagnose/route.ts`: frontend server proxy.
- `backend/app.py`: validation and public AgriSense endpoint.
- `backend/tools/plant_health.py`: Gemini multimodal adapter and normalization.
- `backend/tests/test_plant_health.py`: security and response-contract tests.
