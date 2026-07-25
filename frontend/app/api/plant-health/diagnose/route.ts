import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const backendBaseUrl = () =>
  (process.env.AGRISENSE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxImageBytes = 8 * 1024 * 1024;

export async function POST(request: NextRequest) {
  try {
    const form = await request.formData();
    const image = form.get("image");
    if (!(image instanceof File)) {
      return NextResponse.json({ detail: "Choose a plant image first." }, { status: 400 });
    }
    if (!allowedTypes.has(image.type)) {
      return NextResponse.json(
        { detail: "Upload a JPEG, PNG or WebP image." },
        { status: 415 },
      );
    }
    if (image.size > maxImageBytes) {
      return NextResponse.json(
        { detail: "The image is larger than the 8 MB limit." },
        { status: 413 },
      );
    }
    const language = form.get("language") === "bn" ? "bn" : "en";
    const rawNotes = form.get("symptom_notes");
    const symptomNotes = typeof rawNotes === "string" ? rawNotes.trim().slice(0, 1000) : "";
    const imageBase64 = Buffer.from(await image.arrayBuffer()).toString("base64");
    const upstream = await fetch(`${backendBaseUrl()}/plant-health/diagnose`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        image_base64: imageBase64,
        mime_type: image.type,
        filename: image.name,
        language,
        symptom_notes: symptomNotes || null,
      }),
      cache: "no-store",
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      {
        detail:
          "Plant Health is unavailable. Start FastAPI and check AGRISENSE_API_BASE_URL.",
      },
      { status: 502 },
    );
  }
}
