# Business Brain (Project 4, Layer 1)

The shared intelligence that the voice agent, WhatsApp agent and lead engine all call.

## What Layer 1 does
- **Ingest** markdown, text, PDF files and URLs → chunks → Postgres (+ pgvector embeddings when a Gemini key is set).
- **Re-sync**: re-running ingest skips unchanged sources (content hash) and rebuilds changed ones.
- **Hybrid retrieval**: full-text search + vector search, fused with reciprocal rank fusion.
- **Grounded answers**: every sentence is cited; an answer with no valid citation is rejected; otherwise "I don't know".
- **Tenant isolation**: every row and every query is scoped by `business_id`. The eval set checks for leaks.
- **Query log**: every question, answer, citations and latency go to `queries` (the source for the weekly report).

## Run
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost/brain
export GEMINI_API_KEY=...          # optional: enables embeddings + LLM answers
.venv/bin/python -m evals.run       # ingests sample data, prints pass rate
.venv/bin/uvicorn brain.api:app --port 8000
```

```bash
curl -s localhost:8000/ask -H 'content-type: application/json' \
  -d '{"business_id":"smile-point","question":"How much is a root canal for a molar?"}'
```

## Modes
| Keys set | Retrieval | Answering |
|---|---|---|
| none | keyword only | extractive (returns the best chunk, abstains on low coverage) |
| `GEMINI_API_KEY` | keyword + vector | Gemini, cited, abstains with NOT_FOUND |
| `ANTHROPIC_API_KEY` + `LLM_PROVIDER=claude` | keyword only (unless Gemini key also set) | Claude, cited |

## Layers still to build
1. ~~Ingest → retrieve → cite → abstain → API → evals~~ (this)
2. Real LLM + vector run; tune `MIN_VECTOR_SIM` against evals; Langfuse tracing
3. Tools: calendar availability, Google Sheets, email drafts (MCP)
4. Weekly report from `queries` (top questions, unanswered = missed opportunities)
5. Langflow flow wrapping this API so the owner edits it visually
6. Move DB to Supabase; Drive/website re-sync on a schedule
