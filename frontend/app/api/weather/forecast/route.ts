import { NextRequest, NextResponse } from "next/server";

const backendBaseUrl = () =>
  (process.env.AGRISENSE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function GET(request: NextRequest) {
  const lat = request.nextUrl.searchParams.get("lat");
  const lon = request.nextUrl.searchParams.get("lon");
  const days = request.nextUrl.searchParams.get("days") ?? "7";
  if (!lat || !lon) {
    return NextResponse.json({ detail: "lat and lon are required" }, { status: 400 });
  }
  try {
    const upstream = await fetch(
      `${backendBaseUrl()}/weather/forecast?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&days=${encodeURIComponent(days)}`,
      { cache: "no-store" },
    );
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "Live weather is unavailable." },
      { status: 502 },
    );
  }
}
