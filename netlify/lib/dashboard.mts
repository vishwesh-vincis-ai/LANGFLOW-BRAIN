// Everything the console shows, from the brain's own tables. Port of brain/dashboard.py.
// Public viewers get masked phone numbers; the owner key unmasks them.
import { freeSlots } from "./booking.mts";
import { sql } from "./db.mts";
import { CHAT_MODEL, EMBED_MODEL, hasModel } from "./nvidia.mts";

const LATENCY_BUCKETS = [250, 500, 1000, 2000, 4000];
const mask = (p: string | null) => (p ? p.replace(/\d(?=(?:\D*\d){3})/g, "•") : p);

export const businesses = () =>
  sql`select id, name, settings->>'demo_of' as demo_of from businesses order by created_at, id`;

export async function snapshot(bid: string, owner: boolean, days = 7) {
  const [b] = await sql`select id, name, settings from businesses where id = ${bid}`;
  if (!b) return null;
  const [q] = await sql`select count(*)::int total, count(*) filter (where answered)::int answered,
      coalesce(percentile_cont(0.5) within group (order by latency_ms), 0)::int p50,
      coalesce(percentile_cont(0.95) within group (order by latency_ms), 0)::int p95
    from queries where business_id = ${bid}`;
  const lat = await sql`select latency_ms from queries where business_id = ${bid}`;
  const topics = await sql`select c.heading as section, d.title as doc, count(*)::int as count
    from queries q, unnest(q.cited_chunk_ids) cid join chunks c on c.id = cid join documents d on d.id = c.document_id
    where q.business_id = ${bid} group by 1, 2 order by 3 desc, 1 limit 8`;
  const gaps = await sql`select question, count(*)::int as count, max(created_at) as last from queries
    where business_id = ${bid} and not answered group by question order by 2 desc, 3 desc limit 8`;
  const recent = await sql`select q.question, q.answered, q.answer, q.latency_ms, q.channel, q.created_at,
      (select c.heading from chunks c where c.id = q.cited_chunk_ids[1]) as cited
    from queries q where q.business_id = ${bid} order by q.id desc limit 15`;
  const handoffs = await sql`select id::int, question, name, phone, status, session_id as channel, created_at from handoffs
    where business_id = ${bid} and status <> 'collecting' order by created_at desc limit 20`;
  const [{ collecting }] = await sql`select count(*)::int collecting from handoffs where business_id = ${bid} and status = 'collecting'`;
  const drafts = await sql`select id::int, to_address as to, subject, body, reason, status, created_at from email_drafts
    where business_id = ${bid} order by created_at desc limit 20`;
  const appts = await sql`select id::int, starts_at, ends_at, service, name, phone from appointments
    where business_id = ${bid} and status = 'booked' and starts_at >= date_trunc('day', now())
      and starts_at < date_trunc('day', now()) + make_interval(days => ${days}) order by starts_at`;
  const docs = await sql`select d.title, d.source_uri, d.synced_at, count(c.id)::int sections, count(c.embedding)::int embedded
    from documents d left join chunks c on c.document_id = d.id where d.business_id = ${bid} group by d.id order by d.title`;

  const tz = (b.settings?.timezone as string) || "Asia/Kolkata";
  const week = [];
  for (let i = 0; i < days; i++) {
    const day = new Date(Date.now() + i * 86400000).toLocaleDateString("en-CA", { timeZone: tz });
    week.push({ day, free_slots: (await freeSlots(bid, day)).length,
                booked: appts.filter((a) => new Date(a.starts_at).toLocaleDateString("en-CA", { timeZone: tz }) === day).length });
  }
  const counts = new Array(LATENCY_BUCKETS.length + 1).fill(0);
  for (const { latency_ms } of lat) {
    const i = LATENCY_BUCKETS.findIndex((x) => latency_ms <= x);
    counts[i === -1 ? LATENCY_BUCKETS.length : i]++;
  }

  return {
    generated_at: new Date().toISOString(),
    business: { id: b.id, name: b.name, timezone: tz, demo_of: b.settings?.demo_of ?? null },
    mode: { llm: hasModel() ? "nvidia" : "none", llm_model: hasModel() ? CHAT_MODEL : "none", embed_model: hasModel() ? EMBED_MODEL : "none" },
    owner,
    questions: { total: q.total, answered: q.answered, handed_off: q.total - q.answered, p50_ms: q.p50, p95_ms: q.p95,
                 latency_hist: { buckets: LATENCY_BUCKETS, counts } },
    topics, faq_gaps: gaps, recent, collecting,
    handoffs: handoffs.map((h) => ({ ...h, phone: owner ? h.phone : mask(h.phone) })),
    drafts: drafts.map((d) => ({ ...d, body: owner ? d.body : d.body.replace(/(Phone:\s+)(.+)/, (_m: string, a: string, p: string) => a + mask(p)) })),
    appointments: appts.map((a) => ({ ...a, phone: owner ? a.phone : mask(a.phone) })),
    week,
    documents: docs.map((d) => ({ title: d.title, source: String(d.source_uri).split("/").pop(), synced_at: d.synced_at,
                                  sections: d.sections, embedded: d.embedded })),
  };
}
