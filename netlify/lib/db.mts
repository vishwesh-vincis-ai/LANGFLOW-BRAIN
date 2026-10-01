// One pooled connection per function instance. Supabase's transaction pooler (port 6543) needs prepare:false.
import postgres from "postgres";

const url = process.env.DATABASE_URL;
if (!url) throw new Error("DATABASE_URL is not set");

export const sql = postgres(url, {
  prepare: false,
  max: 1,
  idle_timeout: 20,
  ssl: url.includes("localhost") || url.includes("127.0.0.1") ? false : "require",
});
// int8 columns arrive as strings; queries cast ids with ::int (every id here fits comfortably).
