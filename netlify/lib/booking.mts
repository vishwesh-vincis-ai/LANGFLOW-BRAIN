// Calendar: slots, book, reschedule, cancel. Time zones are Postgres's job, so slots are computed in SQL.
import type { TransactionSql } from "postgres";
import { sql } from "./db.mts";

type Q = typeof sql | TransactionSql;

export class SlotUnavailable extends Error {}

const tzOf = async (bid: string) =>
  ((await sql`select coalesce(settings->>'timezone', 'Asia/Kolkata') as tz from businesses where id = ${bid}`)[0]?.tz as string) || "Asia/Kolkata";

// day: YYYY-MM-DD in the business's local time. Returns ISO instants of open 30-min-step starts.
export async function freeSlots(bid: string, day: string, durationMin = 30): Promise<string[]> {
  const tz = await tzOf(bid);
  const rows = await sql`
    select s as start from opening_hours oh,
      generate_series((${day}::date + oh.opens) at time zone ${tz},
                      (${day}::date + oh.closes) at time zone ${tz} - make_interval(mins => ${durationMin}),
                      interval '30 minutes') s
    where oh.business_id = ${bid} and oh.weekday = (extract(isodow from ${day}::date)::int - 1)
      and s > now()
      and not exists (select 1 from appointments a where a.business_id = ${bid} and a.status = 'booked'
                      and tstzrange(a.starts_at, a.ends_at) && tstzrange(s, s + make_interval(mins => ${durationMin})))
    order by s`;
  return rows.map((r) => new Date(r.start).toISOString());
}

async function withinHours(tx: Q, bid: string, start: string, end: string) {
  const tz = await tzOf(bid);
  const [r] = await tx`select exists (select 1 from opening_hours where business_id = ${bid}
      and weekday = extract(isodow from (${start}::timestamptz at time zone ${tz}))::int - 1
      and opens <= (${start}::timestamptz at time zone ${tz})::time
      and closes >= (${end}::timestamptz at time zone ${tz})::time
      and (${start}::timestamptz at time zone ${tz})::date = (${end}::timestamptz at time zone ${tz})::date) as ok`;
  return r.ok as boolean;
}

const isExclusion = (e: any) => e?.code === "23P01";

export async function book(bid: string, startsAt: string, service: string, name: string, phone: string, durationMin = 30) {
  const start = new Date(startsAt), end = new Date(start.getTime() + durationMin * 60000);
  if (isNaN(start.getTime())) throw new SlotUnavailable("starts_at is not a valid timestamp");
  if (start <= new Date()) throw new SlotUnavailable("in the past");
  if (!(await withinHours(sql, bid, start.toISOString(), end.toISOString()))) throw new SlotUnavailable("outside opening hours");
  try {
    const [a] = await sql`insert into appointments (business_id, starts_at, ends_at, service, name, phone)
      values (${bid}, ${start.toISOString()}, ${end.toISOString()}, ${service}, ${name}, ${phone}) returning id::int`;
    return { id: a.id, starts_at: start.toISOString(), ends_at: end.toISOString(), service, name, phone };
  } catch (e) {
    if (isExclusion(e)) throw new SlotUnavailable("slot already booked");   // the database refuses double bookings
    throw e;
  }
}

export async function cancel(bid: string, id: number) {
  const r = await sql`update appointments set status = 'cancelled' where id = ${id} and business_id = ${bid} and status = 'booked'`;
  return r.count === 1;
}

// Atomic: the old slot is released only if the new one is taken.
export async function reschedule(bid: string, id: number, newStart: string) {
  return sql.begin(async (tx) => {
    const [old] = await tx`select service, name, phone, extract(epoch from ends_at - starts_at)::int / 60 as minutes
      from appointments where id = ${id} and business_id = ${bid} and status = 'booked' for update`;
    if (!old) throw new SlotUnavailable("appointment not found");
    const start = new Date(newStart), end = new Date(start.getTime() + old.minutes * 60000);
    if (!(await withinHours(tx, bid, start.toISOString(), end.toISOString()))) throw new SlotUnavailable("outside opening hours");
    await tx`update appointments set status = 'cancelled' where id = ${id}`;
    try {
      const [a] = await tx.savepoint((sp) => sp`insert into appointments (business_id, starts_at, ends_at, service, name, phone)
        values (${bid}, ${start.toISOString()}, ${end.toISOString()}, ${old.service}, ${old.name}, ${old.phone}) returning id::int`);
      return { id: a.id, replaces: id, starts_at: start.toISOString(), service: old.service };
    } catch (e) {
      if (isExclusion(e)) throw new SlotUnavailable("slot already booked");
      throw e;
    }
  });
}
