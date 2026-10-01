# Deploy the Business Brain to Netlify

The site is the owner console (`web/`) plus the brain API as one Netlify Function (`netlify/functions/api.mts`),
backed by Supabase Postgres + pgvector (project **business-brain**, `ussiblcvmrvvboeuoctp`, us-east-2, next to
Netlify's default function region). The schema and seed data are already applied
(`supabase/migrations/`, `supabase/seed.sql`).

## 1. Database connection string (Supabase)
1. Supabase dashboard → project **business-brain** → **Project Settings → Database → Reset database password**.
   (The project was created through the API, so no password was ever shown.) Save it somewhere safe.
2. Click **Connect** (top bar) → **Transaction pooler** → copy the URI. It looks like
   `postgresql://postgres.ussiblcvmrvvboeuoctp:<PASSWORD>@aws-0-us-east-2.pooler.supabase.com:6543/postgres`

## 2. Netlify site
1. Netlify → **Add new project → Import an existing project → GitHub** → `vishwesh-vincis-ai/LANGFLOW-BRAIN`.
2. Build settings come from `netlify.toml`; leave them as they are.
3. **Site configuration → Environment variables**, add:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Transaction pooler URI from step 1 |
   | `NVIDIA_API_KEY` | your NVIDIA key |
   | `BRAIN_API_KEY` | a long random string (e.g. `openssl rand -hex 24`). Agents and the owner send it to book, cancel, or act on the inbox |
   | `DAILY_QUESTION_LIMIT` | optional, default `300` questions per business per day (protects your model credits on a public link) |

4. **Deploys → Trigger deploy**.

## 3. After the first deploy
```bash
SITE=https://<your-site>.netlify.app
KEY=<BRAIN_API_KEY>

# Make every section searchable by meaning (seeded content has no embeddings yet). Repeat until remaining is 0.
curl -s -X POST $SITE/api/admin/embed -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{}'

# Contract tests against the live site (15 checks: citations, tenant isolation, handoff, booking, MCP, auth)
BRAIN_URL=$SITE BRAIN_API_KEY=$KEY node web/test-api.mjs
```

## 4. Publish the head-to-head
In a session with `NVIDIA_API_KEY` set:
```bash
.venv/bin/python -m benchmark.run      # brain vs paste-all-docs, 51 questions, writes benchmark/results.json
git add benchmark/results.json && git commit -m "Benchmark run" && git push
```
Netlify redeploys and the **Compare** tab fills in from that file.

## Connect agents
- MCP (Claude, Langflow MCP client, other agents): `https://<site>/api/mcp`, streamable HTTP. Booking tools need
  `Authorization: Bearer <BRAIN_API_KEY>`.
- REST: `https://<site>/api/chat`, `/api/ask`, `/api/calendar/*`, `/api/dashboard/data`.
- Langflow component: set **Brain API URL** to `https://<site>/api`.

## Run it locally
```bash
npm install
DATABASE_URL=postgresql://postgres:postgres@localhost/brain_web BRAIN_API_KEY=local-test-key node web/dev-server.mjs
# → http://localhost:8888 ; tests: BRAIN_URL=http://localhost:8888 BRAIN_API_KEY=local-test-key node web/test-api.mjs
```
