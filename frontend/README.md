# AgriSense Next.js frontend

This frontend uses same-origin Next.js proxy routes for the FastAPI plan API. It never
receives a Supabase credential and does not call Supabase directly.

The first screen is chat-led: the farmer describes the farm in Bangla or English,
then FastAPI extracts only explicit fields and retrieves cited knowledge before a
plan can be created. Gemini structured extraction
(`gemini_structured_intake_v1`) maps farmer phrases such as “pond nearby” to
canonical internal enums without requiring enum-shaped input. Every accepted
field must retain an exact supporting quote; ambiguous or unsupported output is
discarded and triggers one targeted follow-up.

Farm coordinates are never typed manually. The user can grant browser live-location
permission or select a pin through Google Maps. Live location needs no key. For the
Google Maps picker, add a browser-restricted Maps JavaScript API key to `.env.local`:

```env
NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=your_browser_restricted_key
```

Enable the Google Maps JavaScript API for that key and restrict it to the frontend
origin (for example `http://localhost:3000/*`). This public browser key is distinct
from—and must never be replaced with—any Supabase or backend secret.

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

In another terminal, start the backend:

```bash
cd backend
uvicorn app:app --reload
```

Open [http://localhost:3000](http://localhost:3000). Set the server-only
`AGRISENSE_API_BASE_URL` in `frontend/.env.local` if FastAPI runs elsewhere.
