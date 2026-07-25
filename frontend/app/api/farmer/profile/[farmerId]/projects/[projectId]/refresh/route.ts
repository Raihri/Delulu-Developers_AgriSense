import { NextRequest, NextResponse } from "next/server";

const backendBaseUrl = () =>
  (process.env.AGRISENSE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function POST(
  _request: NextRequest,
  context: {
    params: Promise<{ farmerId: string; projectId: string }>;
  },
) {
  const { farmerId, projectId } = await context.params;
  try {
    const upstream = await fetch(
      `${backendBaseUrl()}/farmer/profile/${encodeURIComponent(farmerId)}/projects/${encodeURIComponent(projectId)}/refresh`,
      {
        method: "POST",
        cache: "no-store",
      },
    );
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "The saved project could not refresh because AgriSense is unavailable." },
      { status: 502 },
    );
  }
}
