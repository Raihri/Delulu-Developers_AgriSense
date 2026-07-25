import { NextRequest, NextResponse } from "next/server";

const backendBaseUrl = () =>
  (process.env.AGRISENSE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function POST(request: NextRequest) {
  try {
    const upstream = await fetch(`${backendBaseUrl()}/plan/from-conversation`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(await request.json()),
      cache: "no-store",
    });
    const rawBody = await upstream.text();
    try {
      return NextResponse.json(JSON.parse(rawBody), { status: upstream.status });
    } catch {
      return NextResponse.json(
        {
          detail: upstream.ok
            ? "AgriSense returned an unreadable planning response."
            : `AgriSense planning failed with HTTP ${upstream.status}. ${rawBody.slice(0, 180)}`,
        },
        { status: upstream.ok ? 502 : upstream.status },
      );
    }
  } catch (error) {
    console.error("AgriSense planning proxy could not reach FastAPI:", error);
    return NextResponse.json(
      { detail: "AgriSense backend is unavailable. Start FastAPI and check AGRISENSE_API_BASE_URL." },
      { status: 502 },
    );
  }
}
