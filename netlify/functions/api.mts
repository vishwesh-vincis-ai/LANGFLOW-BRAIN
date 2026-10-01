// The brain's HTTP API on Netlify. Same contract as brain/api.py, under /api.
// Public: ask, chat, slots, dashboard reads (phones masked). Key required: anything that changes data.
import type { Config, Context } from "@netlify/functions";
import { answer } from "../lib/answer.mts";
import * as booking from "../lib/booking.mts";
import { chat } from "../lib/chat.mts";
import { businesses, snapshot } from "../lib/dashboard.mts";
import { sql } from "../lib/db.mts";
import { closeHandoff, setDraftStatus } from "../lib/drafts.mts";
import { backfillEmbeddings, ingest } from "../lib/ingest.mts";
import { handleMcp } from "../lib/mcp.mts";
import { hasModel } from "../lib/nvidia.mts";

const API_KEY = process.env.BRAIN_API_KEY || "";
const DAILY_LIMIT = Number(process.env.DAILY_QUESTION_LIMIT || "300");   // per business; protects model credits on a public demo
const MAX_MESSAGE = 500;

class HttpError extends Error { constructor(public status: number, message: string) { super(message); } }

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", "access-control-allow-origin": "*" } });

function authed(req: Request) {
  const h = req.headers.get("authorization")?.replace(/^Bearer\s+/i, "") || req.headers.get("x-api-key") || "";
  return API_KEY.length > 0 && h === API_KEY;
}
const requireKey = (req: Request) => { if (!authed(req)) throw new HttpError(401, "This action changes data. Send the brain API key as 'Authorization: Bearer <key>'."); };

async function guard(bid: string) {
  if (!bid) throw new HttpError(400, "business_id is required");
  const [b] = await sql`select 1 from businesses where id = ${bid}`;
  if (!b) throw new HttpError(404, `unknown business ${bid}`);
  const [{ n }] = await sql`select count(*)::int n from queries where business_id = ${bid} and created_at > now() - interval '1 day'`;
  if (n >= DAILY_LIMIT) throw new HttpError(429, `Daily demo limit of ${DAILY_LIMIT} questions reached for ${bid}. Try again tomorrow.`);
}
const message = (s: unknown) => {
  const m = String(s ?? "").trim();
  if (!m) throw new HttpError(400, "message is empty");
  if (m.length > MAX_MESSAGE) throw new HttpError(413, `message is longer than ${MAX_MESSAGE} characters`);
  return m;
};

export default async (req: Request, _ctx: Context) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: {
    "access-control-allow-origin": "*", "access-control-allow-headers": "content-type, authorization, x-api-key, mcp-protocol-version, mcp-session-id",
    "access-control-allow-methods": "GET, POST, OPTIONS" } });
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/api/, "").replace(/\/$/, "") || "/";
  const body = req.method === "POST" ? await req.json().catch(() => ({})) : {};
  const q = (k: string) => url.searchParams.get(k) ?? "";
  try {
    const R = `${req.method} ${path}`;
    if (R === "GET /health") return json({ ok: true, model: hasModel() ? "nvidia" : "offline" });
    if (R === "GET /businesses") return json(await businesses());
    if (R === "POST /ask") { await guard(body.business_id); return json(await answer(body.business_id, message(body.question), body.channel || "web")); }
    if (R === "POST /chat") {
      await guard(body.business_id);
      if (!body.session_id) throw new HttpError(400, "session_id is required");
      return json(await chat(body.business_id, String(body.session_id).slice(0, 120), message(body.message), body.channel || "web"));
    }
    if (R === "GET /calendar/slots") return json({ slots: await booking.freeSlots(q("business_id"), q("day"), Number(q("duration_min") || 30)) });
    if (R === "POST /calendar/book") {
      requireKey(req);
      try { return json(await booking.book(body.business_id, body.starts_at, body.service, body.name, body.phone, body.duration_min ?? 30)); }
      catch (e) { if (e instanceof booking.SlotUnavailable) throw new HttpError(409, e.message); throw e; }
    }
    if (R === "POST /calendar/reschedule") {
      requireKey(req);
      try { return json(await booking.reschedule(body.business_id, body.appointment_id, body.new_start)); }
      catch (e) { if (e instanceof booking.SlotUnavailable) throw new HttpError(409, e.message); throw e; }
    }
    if (R === "POST /calendar/cancel") {
      requireKey(req);
      if (!(await booking.cancel(body.business_id, body.appointment_id))) throw new HttpError(404, "no booked appointment with that id");
      return json({ cancelled: body.appointment_id });
    }
    if (R === "GET /dashboard/data") {
      const s = await snapshot(q("business_id"), authed(req));
      if (!s) throw new HttpError(404, "unknown business");
      return json(s);
    }
    let m = /^POST \/drafts\/(\d+)\/status$/.exec(R);
    if (m) {
      requireKey(req);
      if (!["approved", "discarded"].includes(body.status)) throw new HttpError(400, "status must be approved or discarded");
      if (!(await setDraftStatus(body.business_id, Number(m[1]), body.status))) throw new HttpError(404, "no pending draft with that id");
      return json({ id: Number(m[1]), status: body.status });
    }
    m = /^POST \/handoffs\/(\d+)\/close$/.exec(R);
    if (m) {
      requireKey(req);
      if (!(await closeHandoff(body.business_id, Number(m[1])))) throw new HttpError(404, "no open handoff with that id");
      return json({ id: Number(m[1]), status: "closed" });
    }
    if (R === "POST /ingest") { requireKey(req); return json(await ingest(body.business_id, body.business_name, body.documents ?? [], body.settings)); }
    if (R === "POST /admin/embed") { requireKey(req); return json(await backfillEmbeddings(Number(body.limit ?? 200))); }
    if (R === "POST /mcp") {
      const out = await handleMcp(body, authed(req), guard);
      return out === null ? new Response(null, { status: 202 }) : json(out);
    }
    if (R === "GET /mcp") return json({ error: "This MCP server is stateless: POST JSON-RPC to this URL." }, 405);
    throw new HttpError(404, `no route ${R}`);
  } catch (e: any) {
    if (e instanceof HttpError) return json({ detail: e.message }, e.status);
    console.error(e);
    return json({ detail: "Something went wrong on the server. The error is in the function log." }, 500);
  }
};

export const config: Config = { path: "/api/*" };
