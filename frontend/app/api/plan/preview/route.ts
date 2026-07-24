import { NextRequest, NextResponse } from "next/server";

const backendBaseUrl = () =>
  (process.env.AGRISENSE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function POST(request: NextRequest) {
  try {
    const upstream = await fetch(`${backendBaseUrl()}/plan/preview`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(await request.json()),
      cache: "no-store",
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "AgriSense backend is unavailable. Start FastAPI and check AGRISENSE_API_BASE_URL." },
      { status: 502 },
    );
  }
}
