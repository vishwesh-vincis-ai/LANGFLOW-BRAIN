// Add or re-sync documents, and fill in missing embeddings. Port of brain/ingest.py (same chunker).
import { createHash } from "node:crypto";
import { sql } from "./db.mts";
import { embed, hasModel } from "./nvidia.mts";

const MAX_CHARS = 900, OVERLAP = 150;

export function chunk(text: string): [string, string][] {
  const sections: [string, string][] = [];
  let heading = "", buf: string[] = [];
  const flush = () => { const b = buf.join("\n").trim(); if (b) sections.push([heading, b]); };
  for (const line of text.split("\n")) {
    const m = /^#{1,6}\s+(.*)/.exec(line);
    if (m) { flush(); heading = m[1].trim(); buf = []; } else buf.push(line);
  }
  flush();
  const out: [string, string][] = [];
  for (const [h, body] of sections) {
    for (let start = 0; start < body.length; start += MAX_CHARS - OVERLAP) {
      out.push([h, body.slice(start, start + MAX_CHARS)]);
      if (start + MAX_CHARS >= body.length) break;
    }
  }
  return out;
}

export type Doc = { uri: string; title?: string; text: string };

export async function ingest(bid: string, name: string, docs: Doc[], settings?: Record<string, unknown>) {
  const stats = { added: 0, updated: 0, unchanged: 0, chunks: 0 };
  await sql`insert into businesses (id, name, settings) values (${bid}, ${name}, ${sql.json((settings ?? {}) as any)})
            on conflict (id) do update set name = excluded.name,
              settings = case when ${settings ? true : false} then excluded.settings else businesses.settings end`;
  for (const d of docs) {
    const hash = createHash("sha256").update(d.text).digest("hex");
    const [row] = await sql`select id::int, content_hash from documents where business_id = ${bid} and source_uri = ${d.uri}`;
    if (row?.content_hash === hash) { stats.unchanged++; continue; }
    const pieces = chunk(d.text);
    const vecs = (await embed(pieces.map(([h, b]) => `${h}\n${b}`), "passage")) ?? pieces.map(() => null);
    await sql.begin(async (tx) => {
      let docId: number;
      if (row) {
        docId = row.id;
        await tx`delete from chunks where document_id = ${docId}`;
        await tx`update documents set content_hash = ${hash}, title = ${d.title ?? d.uri}, synced_at = now() where id = ${docId}`;
        stats.updated++;
      } else {
        [{ id: docId }] = await tx`insert into documents (business_id, source_uri, title, content_hash)
          values (${bid}, ${d.uri}, ${d.title ?? d.uri}, ${hash}) returning id::int`;
        stats.added++;
      }
      for (let i = 0; i < pieces.length; i++) {
        const v = vecs[i] ? `[${vecs[i]!.join(",")}]` : null;
        await tx`insert into chunks (document_id, business_id, ord, heading, body, embedding)
          values (${docId}, ${bid}, ${i}, ${pieces[i][0]}, ${pieces[i][1]}, ${v}::extensions.vector)`;
      }
    });
    stats.chunks += pieces.length;
  }
  return stats;
}

// Chunks stored before a key was configured have no embedding; vector search silently skips them. Fix that.
export async function backfillEmbeddings(limit = 200) {
  if (!hasModel()) return { embedded: 0, reason: "NVIDIA_API_KEY not set" };
  const rows = await sql`select id::int, heading, body from chunks where embedding is null order by id limit ${limit}`;
  if (!rows.length) return { embedded: 0, remaining: 0 };
  const vecs = (await embed(rows.map((r) => `${r.heading}\n${r.body}`), "passage"))!;
  for (let i = 0; i < rows.length; i++) {
    await sql`update chunks set embedding = ${`[${vecs[i].join(",")}]`}::extensions.vector where id = ${rows[i].id}`;
  }
  const [{ n }] = await sql`select count(*)::int n from chunks where embedding is null`;
  return { embedded: rows.length, remaining: n };
}
