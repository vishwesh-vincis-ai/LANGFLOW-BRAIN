// Conversation layer: answer, or hand off to the team and collect name + phone. Port of brain/chat.py.
import { answer } from "./answer.mts";
import { sql } from "./db.mts";
import { draftHandoff } from "./drafts.mts";

const PHONE_IN = /(?:\+?91[\s-]?)?\b([6-9]\d{4})[\s-]?(\d{5})\b/;
const PHONE_US = /(?:\+?1[\s.-]?)?\(?\b([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})\b/;
const US_SHAPED = /\+1\b|\(\d{3}\)|\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b/;
const NAME = /\b(?:my name is|i am|i'm|this is|name[:\s]+)\s*([A-Za-z][A-Za-z .]{1,40})/i;
const WANTS_HUMAN = /\b(human|real person|staff|talk to|speak to|call me|call back|callback)\b/i;
const DECLINE = /^\s*(no|nope|cancel|stop|no thanks|not now|leave it)\b/i;

function phone(msg: string, country: string): [string | null, string] {
  const us = PHONE_US.exec(msg), ind = PHONE_IN.exec(msg);
  if (us && !msg.includes("+91") && (US_SHAPED.test(msg) || country === "US" || !ind)) {
    return [`+1 ${us[1]}-${us[2]}-${us[3]}`, msg.slice(0, us.index) + msg.slice(us.index + us[0].length)];
  }
  if (ind) return [`+91 ${ind[1]}${ind[2]}`, msg.slice(0, ind.index) + msg.slice(ind.index + ind[0].length)];
  return [null, msg];
}

export function extract(msg: string, country = "IN"): [string | null, string | null] {
  const [ph, restRaw] = phone(msg, country);
  let name: string | null = null;
  const m = NAME.exec(msg);
  if (m) name = m[1];
  else {
    const rest = restRaw.replace(/^[\s,.-]+|[\s,.-]+$/g, "");
    if (/^[A-Za-z][A-Za-z .]{1,40}$/.test(rest) && rest.split(/\s+/).length <= 3) name = rest;
  }
  if (name) {
    name = name.split(/\s+(?:and|my|phone|number|mobile)\b/i)[0].replace(/^[\s.]+|[\s.]+$/g, "")
      .toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return [name, ph];
}

const askFor = (missing: string[]) =>
  missing.length === 2 ? "Could you share your name and phone number?" :
  missing[0] === "name" ? "May I have your name?" : "What's the best phone number to reach you on?";

async function business(id: string) {
  const [b] = await sql`select settings from businesses where id = ${id}`;
  const s = (b?.settings ?? {}) as Record<string, string>;
  const country = s.country || ((s.timezone || "").startsWith("America/") ? "US" : "IN");
  return { country, promise: s.callback_promise || "soon", demo: Boolean(s.demo_of) };
}

async function finish(bid: string, handoffId: number, name: string, ph: string, returning = false) {
  await sql`update handoffs set name = ${name}, phone = ${ph}, status = 'open' where id = ${handoffId}`;
  const draft = await draftHandoff(bid, handoffId);
  const { promise, demo } = await business(bid);
  if (demo) return {   // real business, unofficial demo: never promise a call that won't happen
    reply: `Thanks, ${name}. In the live version your question and number would go straight to the team. ` +
           `This is an unofficial demo, so nobody will call: please contact the business directly.`,
    state: "handoff_open", handoff_id: handoffId, draft_id: draft.id,
  };
  return {
    reply: returning
      ? `I don't have that information right now, so I've passed this question to our team too. They will call you on ${ph} ${promise}, ${name}.`
      : `Thank you, ${name}. I've passed this to our team and they will call you on ${ph} ${promise}.`,
    state: "handoff_open", handoff_id: handoffId, draft_id: draft.id,
  };
}

async function start(bid: string, session: string, question: string, prefix: string) {
  const [h] = await sql`insert into handoffs (business_id, session_id, question) values (${bid}, ${session}, ${question}) returning id::int`;
  const [known] = await sql`select name, phone from handoffs where business_id = ${bid} and session_id = ${session}
                            and name is not null and phone is not null order by id desc limit 1`;
  if (known) return finish(bid, h.id, known.name, known.phone, true);   // never ask twice
  return { reply: `${prefix} I'll connect you with our team. ${askFor(["name", "phone"])}`, state: "collecting_details", handoff_id: h.id };
}

export async function chat(bid: string, session: string, message: string, channel = "web") {
  const [pending] = await sql`select id::int, question, name, phone from handoffs
    where business_id = ${bid} and session_id = ${session} and status = 'collecting' order by id desc limit 1`;
  if (pending) {
    if (DECLINE.test(message)) {
      await sql`update handoffs set status = 'closed' where id = ${pending.id}`;
      return { reply: "No problem. Is there anything else I can help you with?", state: "idle" };
    }
    const { country } = await business(bid);
    const [newName, newPhone] = extract(message, country);
    const name = pending.name || newName, ph = pending.phone || newPhone;
    await sql`update handoffs set name = ${name}, phone = ${ph} where id = ${pending.id}`;
    if (name && ph) return finish(bid, pending.id, name, ph);
    const missing = [["name", name], ["phone", ph]].filter(([, v]) => !v).map(([k]) => k as string);
    if (!newName && !newPhone) {
      const r = await answer(bid, message, channel);   // they asked something else instead: answer, then ask again
      if (r.answered) return { reply: `${r.answer}\n\nFor your earlier question: ${askFor(missing)}`, state: "collecting_details", handoff_id: pending.id, citations: r.citations };
    }
    return { reply: askFor(missing), state: "collecting_details", handoff_id: pending.id };
  }
  if (WANTS_HUMAN.test(message)) return start(bid, session, message, "Sure.");

  const r = await answer(bid, message, channel);
  if (r.answered) return { reply: r.answer, state: "idle", citations: r.citations, latency_ms: r.latency_ms, mode: r.mode };
  return start(bid, session, message, "I don't have that information right now, so");
}
