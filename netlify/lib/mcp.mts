// MCP server over streamable HTTP (stateless, JSON responses). Lets other agents use the brain as tools:
// Claude, Langflow's MCP client, the voice agent, the WhatsApp agent.
import { answer } from "./answer.mts";
import * as booking from "./booking.mts";
import { chat } from "./chat.mts";
import { businesses } from "./dashboard.mts";

const PROTOCOL = "2025-06-18";
const bizArg = { business_id: { type: "string", description: "Tenant id, e.g. smile-point. See list_businesses." } };

export const TOOLS = [
  { name: "list_businesses", description: "Businesses this brain answers for.", inputSchema: { type: "object", properties: {} }, write: false },
  { name: "ask", description: "One-off question. Returns a cited answer from the business's own documents, or answered=false.",
    inputSchema: { type: "object", properties: { ...bizArg, question: { type: "string" } }, required: ["business_id", "question"] }, write: false },
  { name: "chat", description: "Conversation turn for one customer thread. Answers with citations, or hands off to the team and collects name and phone. Reuse session_id for the same customer.",
    inputSchema: { type: "object", properties: { ...bizArg, session_id: { type: "string" }, message: { type: "string" } }, required: ["business_id", "session_id", "message"] }, write: false },
  { name: "free_slots", description: "Open appointment start times (ISO 8601, UTC) for a local date.",
    inputSchema: { type: "object", properties: { ...bizArg, day: { type: "string", description: "YYYY-MM-DD" }, duration_min: { type: "integer", default: 30 } }, required: ["business_id", "day"] }, write: false },
  { name: "book_appointment", description: "Book a slot. Fails with a reason if the slot is taken or outside opening hours. Requires the brain API key.",
    inputSchema: { type: "object", properties: { ...bizArg, starts_at: { type: "string" }, service: { type: "string" }, name: { type: "string" }, phone: { type: "string" }, duration_min: { type: "integer", default: 30 } }, required: ["business_id", "starts_at", "service", "name", "phone"] }, write: true },
  { name: "cancel_appointment", description: "Cancel a booked appointment. Requires the brain API key.",
    inputSchema: { type: "object", properties: { ...bizArg, appointment_id: { type: "integer" } }, required: ["business_id", "appointment_id"] }, write: true },
];

const ok = (id: unknown, result: unknown) => ({ jsonrpc: "2.0", id, result });
const err = (id: unknown, code: number, message: string) => ({ jsonrpc: "2.0", id, error: { code, message } });
const text = (v: unknown, isError = false) => ({ content: [{ type: "text", text: typeof v === "string" ? v : JSON.stringify(v, null, 2) }], isError });

async function callTool(name: string, a: any, authed: boolean, guard: (bid: string) => Promise<void>) {
  const tool = TOOLS.find((t) => t.name === name);
  if (!tool) throw new Error(`unknown tool ${name}`);
  if (tool.write && !authed) return text("This tool changes data. Send the brain API key as 'Authorization: Bearer <key>'.", true);
  switch (name) {
    case "list_businesses": return text(await businesses());
    case "ask": await guard(a.business_id); return text(await answer(a.business_id, a.question, "mcp"));
    case "chat": await guard(a.business_id); return text(await chat(a.business_id, a.session_id, a.message, "mcp"));
    case "free_slots": return text(await booking.freeSlots(a.business_id, a.day, a.duration_min ?? 30));
    case "book_appointment":
      try { return text(await booking.book(a.business_id, a.starts_at, a.service, a.name, a.phone, a.duration_min ?? 30)); }
      catch (e) { if (e instanceof booking.SlotUnavailable) return text(`Not booked: ${e.message}`, true); throw e; }
    case "cancel_appointment": return text({ cancelled: await booking.cancel(a.business_id, a.appointment_id) });
  }
}

export async function handleMcp(body: any, authed: boolean, guard: (bid: string) => Promise<void>) {
  const msgs = Array.isArray(body) ? body : [body];
  const out = [];
  for (const m of msgs) {
    if (m.id === undefined) continue;   // notifications (e.g. notifications/initialized) get no response
    try {
      if (m.method === "initialize") out.push(ok(m.id, { protocolVersion: PROTOCOL, capabilities: { tools: {} },
        serverInfo: { name: "business-brain", version: "1.0.0" },
        instructions: "Answers come only from each business's own documents, with citations. When the brain can't answer, chat hands off to a human and collects contact details." }));
      else if (m.method === "ping") out.push(ok(m.id, {}));
      else if (m.method === "tools/list") out.push(ok(m.id, { tools: TOOLS.map(({ write, ...t }) => t) }));
      else if (m.method === "tools/call") out.push(ok(m.id, await callTool(m.params?.name, m.params?.arguments ?? {}, authed, guard)));
      else out.push(err(m.id, -32601, `method not found: ${m.method}`));
    } catch (e: any) {
      out.push(ok(m.id, text(e?.message ?? String(e), true)));
    }
  }
  return Array.isArray(body) ? out : out[0] ?? null;
}
