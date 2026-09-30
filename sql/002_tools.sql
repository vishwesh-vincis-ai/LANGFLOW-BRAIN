-- Layer 2: human handoff, calendar, email drafts.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- When the brain can't answer, it hands off to the team and collects contact details first.
CREATE TABLE IF NOT EXISTS handoffs (
  id           bigserial PRIMARY KEY,
  business_id  text NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  session_id   text NOT NULL,                  -- conversation the customer is in (WhatsApp number, call id, ...)
  question     text NOT NULL,                  -- what the brain could not answer
  name         text,
  phone        text,
  status       text NOT NULL DEFAULT 'collecting' CHECK (status IN ('collecting', 'open', 'closed')),
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS handoffs_session_idx ON handoffs (business_id, session_id, status);

-- Weekly opening hours. One row per open block (a clinic with a lunch break has two per day).
CREATE TABLE IF NOT EXISTS opening_hours (
  business_id  text NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  weekday      int  NOT NULL CHECK (weekday BETWEEN 0 AND 6),   -- 0 = Monday
  opens        time NOT NULL,
  closes       time NOT NULL,
  PRIMARY KEY (business_id, weekday, opens)
);

CREATE TABLE IF NOT EXISTS appointments (
  id           bigserial PRIMARY KEY,
  business_id  text NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  starts_at    timestamptz NOT NULL,
  ends_at      timestamptz NOT NULL,
  service      text NOT NULL,
  name         text NOT NULL,
  phone        text NOT NULL,
  status       text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled', 'completed', 'no_show')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at > starts_at),
  -- The database itself refuses a double booking, even if two agents race for the same slot.
  EXCLUDE USING gist (business_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status = 'booked')
);

-- Drafts only. Nothing is sent without a human approving it.
CREATE TABLE IF NOT EXISTS email_drafts (
  id           bigserial PRIMARY KEY,
  business_id  text NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  to_address   text NOT NULL,
  subject      text NOT NULL,
  body         text NOT NULL,
  reason       text NOT NULL,                  -- handoff, booking_confirmation, ...
  status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'sent', 'discarded')),
  created_at   timestamptz NOT NULL DEFAULT now()
);
