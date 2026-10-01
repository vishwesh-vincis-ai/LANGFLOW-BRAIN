// Contract tests for the hosted brain. Run against local or the live site:
//   BRAIN_URL=http://localhost:8888 BRAIN_API_KEY=... node web/test-api.mjs
//   BRAIN_URL=https://<your-site>.netlify.app BRAIN_API_KEY=... node web/test-api.mjs
const BASE = (process.env.BRAIN_URL || "http://localhost:8888").replace(/\/$/, "") + "/api";
const KEY = process.env.BRAIN_API_KEY || "";
let passed = 0, failed = 0;
const sid = () => "test-" + Math.random().toString(36).slice(2, 10);

async function call(method, path, body, key) {
  const headers = { "content-type": "application/json" };
  if (key) headers.authorization = "Bearer " + key;
  const r = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  return { status: r.status, body: text ? JSON.parse(text) : null };
}
async function check(name, fn) {
  try { await fn(); passed++; console.log("  ok  " + name); }
  catch (e) { failed++; console.log("FAIL  " + name + "\n      " + e.message); }
}
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };

function nextDay(weekday) {   // next date (YYYY-MM-DD) that falls on weekday (0 = Monday) in Asia/Kolkata
  for (let i = 1; i < 9; i++) {
    const d = new Date(Date.now() + i * 86400000);
    const wd = (new Date(d.toLocaleString("en-US", { timeZone: "Asia/Kolkata" })).getDay() + 6) % 7;
    if (wd === weekday) return d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  }
}

await check("health", async () => { const r = await call("GET", "/health"); assert(r.status === 200 && r.body.ok, JSON.stringify(r.body)); });

await check("answer cites the clinic's own price list", async () => {
  const r = await call("POST", "/chat", { business_id: "smile-point", session_id: sid(), message: "How much is a zirconia crown?" });
  assert(r.body.reply.includes("14,000"), r.body.reply);
  assert(r.body.citations?.[0]?.source.endsWith("prices.md"), JSON.stringify(r.body.citations));
});

await check("no data leaks between businesses", async () => {
  const r = await call("POST", "/ask", { business_id: "smile-point", question: "How much is a men's haircut?" });
  assert(r.body.answered === false && !r.body.answer.includes("400"), JSON.stringify(r.body));
});

await check("handoff collects name and Indian number, drafts owner email", async () => {
  const s = sid();
  const a = await call("POST", "/chat", { business_id: "smile-point", session_id: s, message: "Do you offer home visits?" });
  assert(a.body.state === "collecting_details", a.body.reply);
  const b = await call("POST", "/chat", { business_id: "smile-point", session_id: s, message: "Meena, 98400 55555" });
  assert(b.body.state === "handoff_open" && b.body.reply.includes("+91 9840055555") && b.body.draft_id, b.body.reply);
});

await check("demo of a real business never promises a call back; US number parsed", async () => {
  const s = sid();
  await call("POST", "/chat", { business_id: "mclanefamilydental", session_id: s, message: "How much is a cleaning without insurance?" });
  const r = await call("POST", "/chat", { business_id: "mclanefamilydental", session_id: s, message: "Maria Lopez, 512 555 0142" });
  assert(r.body.state === "handoff_open" && r.body.reply.includes("nobody will call"), r.body.reply);
});

await check("free slots respect the lunch break", async () => {
  const day = nextDay(0);
  const r = await call("GET", `/calendar/slots?business_id=smile-point&day=${day}`);
  const local = r.body.slots.map((t) => new Date(t).toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" }));
  assert(local.includes("09:30") && local.includes("16:30") && !local.includes("14:00"), local.join(" "));
});

let apptId;
await check("booking needs the key", async () => {
  const day = nextDay(1);
  const r = await call("POST", "/calendar/book", { business_id: "smile-point", starts_at: `${day}T11:00:00+05:30`, service: "Cleaning", name: "T", phone: "+91 9840000001" });
  assert(r.status === 401, `status ${r.status}`);
});

await check("book, then the same slot is refused (409)", async () => {
  assert(KEY, "set BRAIN_API_KEY to run write tests");
  const day = nextDay(1);
  const body = { business_id: "smile-point", starts_at: `${day}T11:00:00+05:30`, service: "Cleaning", name: "Test", phone: "+91 9840000001" };
  const a = await call("POST", "/calendar/book", body, KEY);
  assert(a.status === 200, JSON.stringify(a.body)); apptId = a.body.id;
  const b = await call("POST", "/calendar/book", { ...body, starts_at: `${day}T11:15:00+05:30` }, KEY);
  assert(b.status === 409 && b.body.detail.includes("already booked"), JSON.stringify(b.body));
});

await check("booking at lunch is refused", async () => {
  const r = await call("POST", "/calendar/book", { business_id: "smile-point", starts_at: `${nextDay(2)}T14:00:00+05:30`, service: "Cleaning", name: "T", phone: "+91 9840000002" }, KEY);
  assert(r.status === 409 && r.body.detail.includes("opening hours"), JSON.stringify(r.body));
});

await check("cancel frees the slot", async () => {
  const r = await call("POST", "/calendar/cancel", { business_id: "smile-point", appointment_id: apptId }, KEY);
  assert(r.status === 200, JSON.stringify(r.body));
});

await check("public dashboard masks phone numbers; owner key unmasks", async () => {
  const pub = await call("GET", "/dashboard/data?business_id=smile-point");
  const own = await call("GET", "/dashboard/data?business_id=smile-point", null, KEY);
  const p = pub.body.handoffs.find((h) => h.phone)?.phone, o = own.body.handoffs.find((h) => h.phone)?.phone;
  assert(p && p.includes("•") && !pub.body.owner, p);
  assert(o && !o.includes("•") && own.body.owner, o);
});

await check("draft approval needs the key", async () => {
  const d = (await call("GET", "/dashboard/data?business_id=smile-point")).body.drafts.find((x) => x.status === "draft");
  const no = await call("POST", `/drafts/${d.id}/status`, { business_id: "smile-point", status: "approved" });
  assert(no.status === 401, `status ${no.status}`);
  const other = await call("POST", `/drafts/${d.id}/status`, { business_id: "glow-studio", status: "approved" }, KEY);
  assert(other.status === 404, "another tenant changed this draft");
  const yes = await call("POST", `/drafts/${d.id}/status`, { business_id: "smile-point", status: "approved" }, KEY);
  assert(yes.status === 200, JSON.stringify(yes.body));
});

await check("MCP: initialize, list tools, call ask", async () => {
  const init = await call("POST", "/mcp", { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "0" } } });
  assert(init.body.result.serverInfo.name === "business-brain", JSON.stringify(init.body));
  const note = await call("POST", "/mcp", { jsonrpc: "2.0", method: "notifications/initialized" });
  assert(note.status === 202, `notification status ${note.status}`);
  const list = await call("POST", "/mcp", { jsonrpc: "2.0", id: 2, method: "tools/list" });
  const names = list.body.result.tools.map((t) => t.name);
  assert(["ask", "chat", "free_slots", "book_appointment"].every((n) => names.includes(n)), names.join(","));
  const ask = await call("POST", "/mcp", { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "ask", arguments: { business_id: "smile-point", question: "Root canal price for a molar?" } } });
  assert(ask.body.result.content[0].text.includes("8,000"), ask.body.result.content[0].text);
});

await check("MCP write tools refuse without the key", async () => {
  const r = await call("POST", "/mcp", { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "book_appointment", arguments: { business_id: "smile-point", starts_at: "2030-01-01T10:00:00+05:30", service: "x", name: "x", phone: "x" } } });
  assert(r.body.result.isError && r.body.result.content[0].text.includes("API key"), JSON.stringify(r.body));
});

await check("input limits: empty, too long, unknown business", async () => {
  assert((await call("POST", "/chat", { business_id: "smile-point", session_id: sid(), message: "" })).status === 400, "empty");
  assert((await call("POST", "/chat", { business_id: "smile-point", session_id: sid(), message: "x".repeat(600) })).status === 413, "long");
  assert((await call("POST", "/chat", { business_id: "nope", session_id: sid(), message: "hi" })).status === 404, "unknown");
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
