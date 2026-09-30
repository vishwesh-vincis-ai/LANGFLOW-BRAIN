-- Business brain: multi-tenant document store with hybrid (keyword + vector) search.
-- Every row carries business_id. Every query filters by it. No exceptions.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS businesses (
  id          text PRIMARY KEY,
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  id           bigserial PRIMARY KEY,
  business_id  text NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  source_uri   text NOT NULL,          -- file path or URL; the citation target
  title        text NOT NULL,
  content_hash text NOT NULL,          -- re-sync skips unchanged sources
  synced_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, source_uri)
);

CREATE TABLE IF NOT EXISTS chunks (
  id           bigserial PRIMARY KEY,
  document_id  bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  business_id  text NOT NULL,
  ord          int NOT NULL,
  heading      text NOT NULL DEFAULT '',
  body         text NOT NULL,
  tsv          tsvector GENERATED ALWAYS AS
                 (to_tsvector('english', heading || ' ' || body)) STORED,
  embedding    vector(768)              -- NULL when no embedding provider is configured
);

CREATE INDEX IF NOT EXISTS chunks_business_idx ON chunks (business_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

-- Every question asked, and what the brain did with it. Feeds the weekly report and evals.
CREATE TABLE IF NOT EXISTS queries (
  id           bigserial PRIMARY KEY,
  business_id  text NOT NULL,
  question     text NOT NULL,
  answered     boolean NOT NULL,
  answer       text,
  cited_chunk_ids bigint[] NOT NULL DEFAULT '{}',
  latency_ms   int NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
