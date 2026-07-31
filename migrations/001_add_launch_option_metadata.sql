-- Adds risk/category/engine metadata to launch_options so the website can
-- render risk badges and category tags (per the 2026-07 site audit).
--
-- Safe to run on production: all columns are nullable/defaulted, so existing
-- rows and the running application are unaffected until the scraper starts
-- populating them and the one-time backfill script runs.
--
-- Run this manually in the Supabase SQL editor.

ALTER TABLE launch_options
  ADD COLUMN IF NOT EXISTS risk_level TEXT NOT NULL DEFAULT 'experimental'
    CHECK (risk_level IN ('safe', 'caution', 'experimental')),
  ADD COLUMN IF NOT EXISTS categories TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS engine_compatibility TEXT[] NOT NULL DEFAULT '{}';

-- Speeds up "show me all Performance options" / "show me all Proton-Deck
-- options" style filtering queries the website will want for category badges.
CREATE INDEX IF NOT EXISTS idx_launch_options_categories
  ON launch_options USING GIN (categories);

CREATE INDEX IF NOT EXISTS idx_launch_options_risk_level
  ON launch_options (risk_level);

COMMENT ON COLUMN launch_options.risk_level IS
  'safe = known-good, no side effects. caution = can affect anti-cheat, saves, cloud-sync, or security. experimental = unverified/unrecognized, default for anything not explicitly vetted.';
COMMENT ON COLUMN launch_options.categories IS
  'Functional tags for UI badges, e.g. {Performance,Skip-Intro,Display,Proton-Deck,Audio,Network,Debug-Dev,Experimental}. An option can have multiple.';
COMMENT ON COLUMN launch_options.engine_compatibility IS
  'Game engines this option is known to apply to, e.g. {Source Engine,Unreal Engine} or {Universal}. Empty means unclassified.';
