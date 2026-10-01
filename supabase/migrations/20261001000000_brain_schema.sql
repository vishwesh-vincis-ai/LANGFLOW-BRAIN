-- Business brain on Supabase (applied to project business-brain). Same tables as sql/001 + 002,
-- extensions in the extensions schema, RLS on with no policies (only the server role reads data),
-- and hybrid retrieval as one SQL function.
create extension if not exists vector with schema extensions;
create extension if not exists btree_gist with schema extensions;

create table if not exists businesses (
  id text primary key, name text not null, settings jsonb not null default '{}', created_at timestamptz not null default now());

create table if not exists documents (
  id bigserial primary key, business_id text not null references businesses(id) on delete cascade,
  source_uri text not null, title text not null, content_hash text not null, synced_at timestamptz not null default now(),
  unique (business_id, source_uri));

create table if not exists chunks (
  id bigserial primary key, document_id bigint not null references documents(id) on delete cascade,
  business_id text not null, ord int not null, heading text not null default '', body text not null,
  tsv tsvector generated always as (to_tsvector('english', heading || ' ' || body)) stored,
  embedding extensions.vector(1024));
create index if not exists chunks_business_idx on chunks (business_id);
create index if not exists chunks_tsv_idx on chunks using gin (tsv);
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding extensions.vector_cosine_ops);

create table if not exists queries (
  id bigserial primary key, business_id text not null, question text not null, answered boolean not null, answer text,
  cited_chunk_ids bigint[] not null default '{}', latency_ms int not null, channel text not null default 'web',
  created_at timestamptz not null default now());
create index if not exists queries_business_time_idx on queries (business_id, created_at);

create table if not exists handoffs (
  id bigserial primary key, business_id text not null references businesses(id) on delete cascade,
  session_id text not null, question text not null, name text, phone text,
  status text not null default 'collecting' check (status in ('collecting', 'open', 'closed')),
  created_at timestamptz not null default now());
create index if not exists handoffs_session_idx on handoffs (business_id, session_id, status);

create table if not exists opening_hours (
  business_id text not null references businesses(id) on delete cascade, weekday int not null check (weekday between 0 and 6),
  opens time not null, closes time not null, primary key (business_id, weekday, opens));

create table if not exists appointments (
  id bigserial primary key, business_id text not null references businesses(id) on delete cascade,
  starts_at timestamptz not null, ends_at timestamptz not null, service text not null, name text not null, phone text not null,
  status text not null default 'booked' check (status in ('booked', 'cancelled', 'completed', 'no_show')),
  created_at timestamptz not null default now(), check (ends_at > starts_at),
  exclude using gist (business_id with =, tstzrange(starts_at, ends_at) with &&) where (status = 'booked'));

create table if not exists email_drafts (
  id bigserial primary key, business_id text not null references businesses(id) on delete cascade,
  to_address text not null, subject text not null, body text not null, reason text not null,
  status text not null default 'draft' check (status in ('draft', 'approved', 'sent', 'discarded')),
  created_at timestamptz not null default now());

alter table businesses enable row level security;
alter table documents enable row level security;
alter table chunks enable row level security;
alter table queries enable row level security;
alter table handoffs enable row level security;
alter table opening_hours enable row level security;
alter table appointments enable row level security;
alter table email_drafts enable row level security;

create or replace function hybrid_search(p_business text, p_words text[], p_embedding extensions.vector,
                                         p_k int default 5, p_min_sim float default 0.30)
returns table (chunk_id bigint, source_uri text, title text, heading text, body text,
               score float, keyword_rank float, vector_sim float)
language sql stable set search_path = public, extensions as $$
  with q as (
    select case when coalesce(array_length(p_words, 1), 0) = 0 then null
                else to_tsquery('english', array_to_string(p_words, ' | ')) end as tsq
  ),
  kw as (
    select c.id, ts_rank_cd(c.tsv, q.tsq) as kr, row_number() over (order by ts_rank_cd(c.tsv, q.tsq) desc) - 1 as rnk
    from chunks c, q
    where q.tsq is not null and c.business_id = p_business and c.tsv @@ q.tsq
    order by kr desc limit 20
  ),
  vec as (
    select id, sim, row_number() over (order by sim desc) - 1 as rnk from (
      select c.id, 1 - (c.embedding <=> p_embedding) as sim
      from chunks c
      where p_embedding is not null and c.business_id = p_business and c.embedding is not null
      order by c.embedding <=> p_embedding limit 20
    ) v where sim >= p_min_sim
  ),
  fused as (
    select coalesce(kw.id, vec.id) as id,
           coalesce(1.0 / (60 + kw.rnk), 0) + coalesce(1.0 / (60 + vec.rnk), 0) as score,
           kw.kr, vec.sim
    from kw full outer join vec on kw.id = vec.id
  )
  select c.id, d.source_uri, d.title, c.heading, c.body, f.score, f.kr, f.sim
  from fused f join chunks c on c.id = f.id join documents d on d.id = c.document_id
  order by f.score desc limit p_k
$$;
revoke all on function hybrid_search from anon, authenticated;
