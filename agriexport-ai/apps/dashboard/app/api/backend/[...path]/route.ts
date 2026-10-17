import { NextRequest, NextResponse } from "next/server";

// Fixed upstream and explicit route allowlist: request input never controls an origin.
const allowed = /^(health|products|countries|trade|opportunities(?:\/[a-zA-Z0-9_-]+)?|forecasts(?:\/[a-zA-Z0-9_-]+)?|markets\/[0-9]{3}|commodities\/[a-z_]+|feedback|alerts|alert-subscriptions|pipeline-runs|commercial\/(quotes(?:\/[a-zA-Z0-9_-]+)?|decisions(?:\/[a-zA-Z0-9_-]+)?|events|policies|risks|documents\/[a-zA-Z0-9_-]+))$/;
export const dynamic = "force-dynamic";
async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const endpoint = path.join("/");
  if (!allowed.test(endpoint) || (request.method === "POST" && !["feedback", "alert-subscriptions"].includes(endpoint))) return NextResponse.json({ detail: "Route not supported" }, { status: 404 });
  // Next may canonicalize nextUrl.hostname to localhost even when the browser
  // connects to 127.0.0.1. Compare with the actual Host, or an explicit public origin.
  const expectedOrigin = process.env.AGRI_DASHBOARD_ORIGIN || `${request.nextUrl.protocol}//${request.headers.get("host")}`;
  if (request.method === "POST" && request.headers.get("origin") !== expectedOrigin) return NextResponse.json({ detail: "Same-origin write required" }, { status: 403 });
  const body = request.method === "POST" ? await request.text() : undefined;
  if (body && Buffer.byteLength(body) > 16384) return NextResponse.json({ detail: "Request too large" }, { status: 413 });
  try {
    const origin = new URL(process.env.AGRI_API_ORIGIN || "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password || origin.search || origin.hash || origin.pathname !== "/") throw new Error("Invalid upstream configuration");
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    // No shared server token: each user's Bearer token is checked by FastAPI.
    const bearer = request.headers.get("authorization");
    if (bearer) headers.Authorization = bearer;
    const response = await fetch(new URL(`/api/v1/${endpoint}${request.nextUrl.search}`, origin), { method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20000) });
    return new NextResponse(await response.text(), { status: response.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "Backend unavailable. Start the API and verify AGRI_API_ORIGIN." }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
export const GET = handle;
export const POST = handle;
