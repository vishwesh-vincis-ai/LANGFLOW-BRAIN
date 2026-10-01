// Email drafts. Written here, approved and sent by a person. Nothing is sent from the brain.
import { sql } from "./db.mts";

export async function draftHandoff(bid: string, handoffId: number) {
  const [b] = await sql`select name, settings from businesses where id = ${bid}`;
  const [h] = await sql`select question, name, phone, session_id from handoffs where id = ${handoffId} and business_id = ${bid}`;
  const s = (b.settings ?? {}) as Record<string, string>;
  const body =
    `A customer asked something the assistant could not answer from ${b.name}'s documents.\n\n` +
    `Name:     ${h.name}\nPhone:    ${h.phone}\nChannel:  ${h.session_id}\nQuestion: ${h.question}\n\n` +
    `Promised to the customer: ${s.callback_promise || "a call back soon"}.\n` +
    `If this question comes up often, add the answer to your FAQ and the assistant will handle it next time.`;
  const [d] = await sql`insert into email_drafts (business_id, to_address, subject, body, reason)
    values (${bid}, ${s.owner_email || ""}, ${`Call back ${h.name}: ${String(h.question).slice(0, 60)}`}, ${body}, 'handoff')
    returning id::int`;
  return d;
}

export async function setDraftStatus(bid: string, id: number, status: "approved" | "discarded") {
  const r = await sql`update email_drafts set status = ${status} where id = ${id} and business_id = ${bid} and status = 'draft'`;
  return r.count === 1;
}

export async function closeHandoff(bid: string, id: number) {
  const r = await sql`update handoffs set status = 'closed' where id = ${id} and business_id = ${bid} and status = 'open'`;
  return r.count === 1;
}
