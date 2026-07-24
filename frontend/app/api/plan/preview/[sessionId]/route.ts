import { NextRequest, NextResponse } from "next/server";

const backendBaseUrl = () =>
  (process.env.AGRISENSE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  try {
    const upstream = await fetch(
      `${backendBaseUrl()}/plan/preview/${encodeURIComponent(sessionId)}`,
      { cache: "no-store" },
    );
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "Saved plan could not be loaded because the backend is unavailable." },
      { status: 502 },
    );
  }
}
