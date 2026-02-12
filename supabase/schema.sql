-- ============================================================
-- Acceler CRM Schema
-- Run this in the Supabase SQL Editor to set up all tables.
-- ============================================================

-- Enum for person status flow
CREATE TYPE person_status AS ENUM (
  'discovered',
  'enriched',
  'outreach_drafted',
  'contacted',
  'replied',
  'meeting'
);

-- ============================================================
-- updated_at trigger function
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- sources: curated URLs to monitor
-- ============================================================
CREATE TABLE sources (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  url         TEXT NOT NULL,
  title       TEXT,
  for_tag     TEXT NOT NULL DEFAULT 'other',
  check_frequency_hours INTEGER NOT NULL DEFAULT 168,
  is_active   BOOLEAN NOT NULL DEFAULT true,
  last_checked_at TIMESTAMPTZ,
  last_people_count INTEGER,
  notes       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER sources_updated_at
  BEFORE UPDATE ON sources
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- people: extracted contacts
-- ============================================================
CREATE TABLE people (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name             TEXT NOT NULL,
  title            TEXT DEFAULT '',
  organization     TEXT DEFAULT '',
  email            TEXT DEFAULT '',
  linkedin         TEXT DEFAULT '',
  context          TEXT DEFAULT '',
  source_url       TEXT,
  for_tag          TEXT NOT NULL DEFAULT 'other',
  status           person_status NOT NULL DEFAULT 'discovered',

  -- Generated columns for dedup (works with PostgREST + supabase-py)
  name_normalized  TEXT GENERATED ALWAYS AS (lower(trim(name))) STORED,
  org_normalized   TEXT GENERATED ALWAYS AS (lower(trim(organization))) STORED,

  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (name_normalized, org_normalized)
);

CREATE TRIGGER people_updated_at
  BEFORE UPDATE ON people
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- enrichment_log: tracks enrichment attempts per person
-- ============================================================
CREATE TABLE enrichment_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_id   UUID NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  source      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending',
  result      JSONB,
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER enrichment_log_updated_at
  BEFORE UPDATE ON enrichment_log
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- outreach: drafted emails / linkedin messages
-- ============================================================
CREATE TABLE outreach (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_id   UUID NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  channel     TEXT NOT NULL,
  subject     TEXT,
  body        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'drafted',
  sent_at     TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER outreach_updated_at
  BEFORE UPDATE ON outreach
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Row-Level Security
-- ============================================================
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE people ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrichment_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach ENABLE ROW LEVEL SECURITY;

-- Permissive policies for anon and service_role
CREATE POLICY "Allow all for anon" ON sources FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for service_role" ON sources FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow all for anon" ON people FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for service_role" ON people FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow all for anon" ON enrichment_log FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for service_role" ON enrichment_log FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow all for anon" ON outreach FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for service_role" ON outreach FOR ALL TO service_role USING (true) WITH CHECK (true);
