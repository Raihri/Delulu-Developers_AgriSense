import { NextRequest, NextResponse } from "next/server";

const backendBaseUrl = () =>
  (process.env.AGRISENSE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ farmerId: string }> },
) {
  const { farmerId } = await context.params;
  try {
    const upstream = await fetch(
      `${backendBaseUrl()}/farmer/profile/${encodeURIComponent(farmerId)}`,
      { cache: "no-store" },
    );
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "AgriSense backend is unavailable." },
      { status: 502 },
    );
  }
}

