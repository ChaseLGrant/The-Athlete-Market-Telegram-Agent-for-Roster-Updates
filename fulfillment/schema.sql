-- The Athlete Market: Fulfillment Engine, Phase 0 (schema `fulfillment`).
-- Core tables = fulfillment-engine/mvp/schema.sql (ported by port_pg.py), UNCHANGED. Additions below are strictly additive
-- (ARCHITECTURE.md 2.1). Lives beside the roster engine's `public` tables and never touches them.
-- Idempotent: safe to re-run.
CREATE SCHEMA IF NOT EXISTS fulfillment;
SET search_path = fulfillment;
-- The Athlete Market — Recruiting Fulfillment Engine (pilot MVP)
-- Written to run on SQLite 3.35+ AND port to Supabase/Postgres.
-- Portability rules used throughout:
--   * ids are "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY" -> port_pg.py rewrites to "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
--   * timestamps are TEXT ISO-8601 UTC ("2026-11-12T14:52:00Z") -> port_pg.py rewrites the *_at TEXT columns to TIMESTAMPTZ
--   * booleans are BOOLEAN with TRUE/FALSE literals (SQLite stores 0/1)
--   * business invariants are CHECK constraints so they hold in both engines, not just in app code
--   * no SQLite-only functions in DDL

CREATE TABLE IF NOT EXISTS staff (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('admin','case_manager','recruiting_coordinator','analyst')),
  can_approve_outreach BOOLEAN NOT NULL DEFAULT FALSE,
  can_verify_opportunities BOOLEAN NOT NULL DEFAULT FALSE,
  max_caseload INTEGER NOT NULL DEFAULT 60,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_stages (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  stage_order INTEGER NOT NULL UNIQUE,
  manual_only BOOLEAN NOT NULL DEFAULT FALSE,     -- offer/commitment/placement need staff + evidence
  requires_evidence BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS athletes (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  external_ref TEXT UNIQUE,                       -- Stripe customer / Typeform response id in production
  is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  email TEXT,
  date_of_birth TEXT,
  sport TEXT NOT NULL CHECK (sport IN ('baseball','softball','football','basketball','soccer','volleyball')),
  gender TEXT CHECK (gender IN ('M','F')),
  primary_position TEXT,
  secondary_position TEXT,
  grad_year INTEGER,
  level TEXT NOT NULL DEFAULT 'hs' CHECK (level IN ('hs','juco','transfer')),
  height_in REAL,
  weight_lb REAL,
  gpa REAL CHECK (gpa IS NULL OR (gpa >= 0 AND gpa <= 5)),
  test_score TEXT,
  intended_major TEXT,
  video_url TEXT,
  home_state TEXT,
  preferred_states TEXT,                          -- comma list; '' = anywhere
  division_preferences TEXT,                      -- comma list of NCAA D1,NCAA D2,NCAA D3,NAIA,NJCAA
  needs_athletic_aid BOOLEAN,
  cost_preference TEXT CHECK (cost_preference IS NULL OR cost_preference IN ('aid_required','aid_preferred','cost_not_a_factor')),
  recruiting_history TEXT,
  service_tier TEXT NOT NULL CHECK (service_tier IN ('insider_plus','mentorship','premium_placement')),
  case_owner_id BIGINT REFERENCES staff(id),
  current_stage TEXT NOT NULL DEFAULT 'onboarded' REFERENCES pipeline_stages(code),
  readiness_score REAL,
  readiness_components JSONB,                      -- JSON, transparent breakdown
  missing_info JSONB,                              -- JSON list
  onboarded_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS guardians_consent (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  athlete_id BIGINT NOT NULL REFERENCES athletes(id),
  guardian_name TEXT NOT NULL,
  guardian_email TEXT,
  relationship TEXT,
  scope TEXT NOT NULL CHECK (scope IN ('profile_sharing','coach_contact','data_processing')),
  granted BOOLEAN NOT NULL,
  method TEXT NOT NULL CHECK (method IN ('e_signature','typeform_checkbox','paper','verbal_logged')),
  granted_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  UNIQUE (athlete_id, scope, granted_at)
);

CREATE TABLE IF NOT EXISTS athlete_metrics (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  athlete_id BIGINT NOT NULL REFERENCES athletes(id),
  metric TEXT NOT NULL,                           -- e.g. fb_velo_mph, sixty_yd_s, approach_jump_in
  value REAL NOT NULL,
  unit TEXT,
  source TEXT NOT NULL,                           -- 'self_reported', 'Perfect Game event 2026-07', 'coach verified', ...
  source_url TEXT,
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  verified_by BIGINT REFERENCES staff(id),
  verified_at TIMESTAMPTZ,
  recorded_at TIMESTAMPTZ NOT NULL,
  CHECK (verified = FALSE OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS programs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  school TEXT NOT NULL,
  school_slug TEXT NOT NULL,
  sport TEXT NOT NULL,                            -- normalized pilot sport
  sport_variant TEXT NOT NULL,                    -- source sport key, e.g. womens_volleyball
  gender TEXT CHECK (gender IN ('M','F')),
  division TEXT NOT NULL,
  conference TEXT,
  state TEXT,
  roster_url TEXT,
  stats_url TEXT,
  source TEXT NOT NULL,                           -- which local export it came from
  source_url TEXT NOT NULL,                       -- official athletics page
  academic_profile TEXT,                          -- NULL until a verified academic source is loaded
  last_verified_at TIMESTAMPTZ,
  UNIQUE (school_slug, sport_variant)
);

CREATE TABLE IF NOT EXISTS coaches (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  program_id BIGINT NOT NULL REFERENCES programs(id),
  name TEXT NOT NULL,
  title TEXT,
  email TEXT,
  source_url TEXT NOT NULL,                       -- public staff-directory page; no scraped private data
  opted_out BOOLEAN NOT NULL DEFAULT FALSE,
  preferred_contact TEXT,
  UNIQUE (program_id, name)
);

CREATE TABLE IF NOT EXISTS coach_submissions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  coach_id BIGINT NOT NULL REFERENCES coaches(id),
  program_id BIGINT NOT NULL REFERENCES programs(id),
  position_group TEXT NOT NULL,
  grad_years TEXT NOT NULL,                       -- comma list
  min_gpa REAL,
  benchmarks JSONB,                                -- JSON
  notes TEXT,
  channel TEXT NOT NULL CHECK (channel IN ('coach_portal','email_reply','phone_logged','official_announcement')),
  is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
  submitted_at TIMESTAMPTZ NOT NULL,
  verified_by BIGINT REFERENCES staff(id),
  verified_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS opportunities (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  program_id BIGINT NOT NULL REFERENCES programs(id),
  position_group TEXT NOT NULL,
  position_label TEXT,
  target_season TEXT,
  status TEXT NOT NULL CHECK (status IN ('Verified Open Need','Likely Future Need','Possible Fit','Unknown')),
  basis TEXT NOT NULL CHECK (basis IN ('roster_turnover','coach_submission','official_announcement','staff_research')),
  coach_submission_id BIGINT REFERENCES coach_submissions(id),
  announcement_url TEXT,
  signal REAL,
  confidence TEXT,
  reason TEXT,
  source_url TEXT NOT NULL,
  evidence_urls JSONB,                             -- JSON list of every source URL
  verified_at TIMESTAMPTZ NOT NULL,
  verified_by TEXT NOT NULL,                      -- staff email or 'roster-pipeline:<export>'
  expires_at TIMESTAMPTZ,
  external_id TEXT,
  needs_staff_review BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL,
  -- Rule 1: roster turnover can never be a confirmed vacancy.
  CHECK (basis <> 'roster_turnover' OR status IN ('Likely Future Need','Possible Fit','Unknown')),
  -- Rule 2: Verified Open Need only from a coach submission or an official announcement record.
  CHECK (status <> 'Verified Open Need' OR (
          (basis = 'coach_submission' AND coach_submission_id IS NOT NULL)
       OR (basis = 'official_announcement' AND announcement_url IS NOT NULL))),
  UNIQUE (program_id, position_group, basis, target_season)
);

CREATE TABLE IF NOT EXISTS matches (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  athlete_id BIGINT NOT NULL REFERENCES athletes(id),
  program_id BIGINT NOT NULL REFERENCES programs(id),
  opportunity_id BIGINT REFERENCES opportunities(id),
  score REAL NOT NULL,
  tier TEXT NOT NULL CHECK (tier IN ('strong','competitive','reach')),
  components JSONB NOT NULL,                       -- JSON breakdown
  explanation TEXT NOT NULL,
  evidence_urls JSONB NOT NULL,                    -- JSON list
  evidence_backed BOOLEAN NOT NULL,
  human_reviewed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (athlete_id, program_id)
);

CREATE TABLE IF NOT EXISTS outreach_messages (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  athlete_id BIGINT NOT NULL REFERENCES athletes(id),
  coach_id BIGINT NOT NULL REFERENCES coaches(id),
  match_id BIGINT REFERENCES matches(id),
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','sent','bounced','opted_out')),
  approved_by BIGINT REFERENCES staff(id),
  approved_at TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  is_simulated BOOLEAN NOT NULL DEFAULT FALSE,    -- TRUE only in the pilot simulation DB
  follow_up_due_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL,
  -- Nothing leaves draft without an explicit staff approval record.
  CHECK (status IN ('draft','opted_out') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
  CHECK (status NOT IN ('sent','bounced') OR sent_at IS NOT NULL),
  UNIQUE (athlete_id, coach_id)
);

CREATE TABLE IF NOT EXISTS coach_responses (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  outreach_message_id BIGINT REFERENCES outreach_messages(id),
  athlete_id BIGINT REFERENCES athletes(id),
  program_id BIGINT REFERENCES programs(id),
  received_at TIMESTAMPTZ NOT NULL,
  body TEXT NOT NULL,
  classification TEXT NOT NULL CHECK (classification IN ('interested','info_requested','visit_or_call_requested','not_recruiting','not_interested','no_response','human_review')),
  confidence REAL NOT NULL,
  classifier TEXT NOT NULL,                       -- 'rules-v1' or 'llm:<model>'
  matched_rules JSONB,                             -- JSON
  suggested_next_step TEXT,
  needs_review BOOLEAN NOT NULL,
  reviewed_by BIGINT REFERENCES staff(id),
  reviewed_at TIMESTAMPTZ,
  is_simulated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS athlete_stage_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  athlete_id BIGINT NOT NULL REFERENCES athletes(id),
  stage_code TEXT NOT NULL REFERENCES pipeline_stages(code),
  entered_at TIMESTAMPTZ NOT NULL,
  actor TEXT NOT NULL,
  evidence_url TEXT,
  note TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at TIMESTAMPTZ NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  detail JSONB
);

CREATE INDEX IF NOT EXISTS idx_opp_program ON opportunities(program_id);
CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_prog_sport ON programs(sport, gender, division);
CREATE INDEX IF NOT EXISTS idx_match_athlete ON matches(athlete_id);
CREATE INDEX IF NOT EXISTS idx_out_status ON outreach_messages(status);
CREATE INDEX IF NOT EXISTS idx_resp_review ON coach_responses(needs_review);

INSERT INTO pipeline_stages (code,label,stage_order,manual_only,requires_evidence) VALUES
 ('onboarded','Onboarded',1,FALSE,FALSE),
 ('profile_ready','Profile Ready',2,FALSE,FALSE),
 ('matches_identified','Matches Identified',3,FALSE,FALSE),
 ('outreach_approved','Outreach Approved',4,FALSE,FALSE),
 ('coaches_contacted','Coaches Contacted',5,FALSE,FALSE),
 ('coach_engaged','Coach Engaged',6,FALSE,FALSE),
 ('serious_interest','Serious Recruiting Interest',7,FALSE,FALSE),
 ('offer_or_roster_opportunity','Offer/Roster Opportunity',8,TRUE,TRUE),
 ('commitment','Commitment',9,TRUE,TRUE),
 ('verified_placement','Verified Placement',10,TRUE,TRUE)
ON CONFLICT (code) DO NOTHING;

-- ===================================================================== Phase 0 additions (additive only)
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  note TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Coach outreach transport is OFF until Chase confirms the sending domain + transactional provider (Postmark).
INSERT INTO settings (key, value, note) VALUES
 ('coach_outreach_transport', 'off', 'No coach email leaves the engine until Chase confirms domain + provider')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS suppression_list (
  email TEXT PRIMARY KEY,                -- lower-case address
  reason TEXT NOT NULL,                  -- opt_out | hard_bounce | complaint | manual | college_policy
  source TEXT,
  added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opportunity_verifications (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  opportunity_id BIGINT NOT NULL REFERENCES opportunities(id),
  decision TEXT NOT NULL CHECK (decision IN ('verified','rejected','expired')),
  decided_by BIGINT NOT NULL REFERENCES staff(id),
  evidence_url TEXT NOT NULL,
  note TEXT,
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Insider Plus families (pseudonymous: signup id only; names/emails stay in the sender's own store)
CREATE TABLE IF NOT EXISTS insider_profiles (
  athlete_id BIGINT PRIMARY KEY REFERENCES athletes(id),
  signup_ref TEXT NOT NULL UNIQUE,
  sport_variant TEXT NOT NULL,
  position TEXT,
  match_class INTEGER,
  level TEXT,
  juco_year TEXT,
  levels TEXT,                           -- comma list D1,D2,D3
  regions TEXT,                          -- comma list
  plan TEXT,
  sub_status TEXT,
  export_generated_at TEXT,
  synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS insider_deliveries (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  signup_ref TEXT NOT NULL,
  school_slug TEXT NOT NULL,
  school TEXT,
  sent_at TIMESTAMPTZ,
  kind TEXT,
  UNIQUE (signup_ref, school_slug)
);

-- Insider candidate rank from the sender's own ranking (insider_plus.school_rank) for each family
ALTER TABLE matches ADD COLUMN IF NOT EXISTS insider_rank INTEGER;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS insider_timing TEXT;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS insider_early BOOLEAN;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS export_opp_id TEXT;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_opp_external ON opportunities(external_id);
CREATE INDEX IF NOT EXISTS idx_opp_status_exp ON opportunities(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_match_tier ON matches(athlete_id, tier);
CREATE INDEX IF NOT EXISTS idx_out_coach_sent ON outreach_messages(coach_id, sent_at);

-- --------------------------------------------------------------------- guardrail triggers
-- G1: a Verified Open Need needs a staff verification record (staff with can_verify_opportunities), checked at commit.
CREATE OR REPLACE FUNCTION fn_opp_verified_requires_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'Verified Open Need' AND NOT EXISTS (
       SELECT 1 FROM opportunity_verifications v JOIN staff s ON s.id = v.decided_by
        WHERE v.opportunity_id = NEW.id AND v.decision = 'verified'
          AND s.can_verify_opportunities AND s.active) THEN
    RAISE EXCEPTION 'GUARDRAIL: opportunity % cannot be Verified Open Need without a staff verification record', NEW.id;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_opp_verified_requires_record ON opportunities;
CREATE CONSTRAINT TRIGGER trg_opp_verified_requires_record AFTER INSERT OR UPDATE OF status ON opportunities
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_opp_verified_requires_record();

-- G2/G3/G4: approval or send needs consent, an unsuppressed coach, and (for send) the transport switched on.
CREATE OR REPLACE FUNCTION fn_outreach_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c_email TEXT; c_opt BOOLEAN; transport TEXT;
BEGIN
  IF NEW.status NOT IN ('approved','sent') THEN RETURN NEW; END IF;
  SELECT lower(email), opted_out INTO c_email, c_opt FROM coaches WHERE id = NEW.coach_id;
  IF c_opt OR (c_email IS NOT NULL AND EXISTS (SELECT 1 FROM suppression_list WHERE email = c_email)) THEN
    RAISE EXCEPTION 'GUARDRAIL: coach % is suppressed/opted out; outreach % blocked', NEW.coach_id, NEW.id;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM guardians_consent g WHERE g.athlete_id = NEW.athlete_id AND g.granted
                   AND g.revoked_at IS NULL AND g.scope IN ('coach_contact','profile_sharing')) THEN
    RAISE EXCEPTION 'GUARDRAIL: athlete % has no active guardian consent (coach_contact/profile_sharing); outreach % blocked',
      NEW.athlete_id, NEW.id;
  END IF;
  IF NEW.status = 'sent' THEN
    SELECT value INTO transport FROM settings WHERE key = 'coach_outreach_transport';
    IF coalesce(transport,'off') <> 'on' THEN
      RAISE EXCEPTION 'GUARDRAIL: coach outreach transport is OFF; message % cannot be marked sent', NEW.id;
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_outreach_guard ON outreach_messages;
CREATE TRIGGER trg_outreach_guard BEFORE INSERT OR UPDATE OF status ON outreach_messages
  FOR EACH ROW EXECUTE FUNCTION fn_outreach_guard();

-- G5: an opt-out/suppression cancels pending drafts and approvals to that coach.
CREATE OR REPLACE FUNCTION fn_suppression_cascade() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE coaches SET opted_out = TRUE WHERE lower(email) = NEW.email AND NOT opted_out;
  UPDATE outreach_messages m SET status = 'opted_out'
    FROM coaches c WHERE c.id = m.coach_id AND lower(c.email) = NEW.email AND m.status IN ('draft','approved');
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_suppression_cascade ON suppression_list;
CREATE TRIGGER trg_suppression_cascade AFTER INSERT ON suppression_list
  FOR EACH ROW EXECUTE FUNCTION fn_suppression_cascade();

-- G6: offer/commitment/placement stages need evidence and a non-automated actor.
CREATE OR REPLACE FUNCTION fn_stage_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM pipeline_stages WHERE code = NEW.stage_code AND requires_evidence) AND
     (NEW.evidence_url IS NULL OR NEW.actor LIKE 'job:%' OR NEW.actor LIKE 'system:%') THEN
    RAISE EXCEPTION 'GUARDRAIL: stage % needs evidence_url and a staff actor', NEW.stage_code;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_stage_evidence ON athlete_stage_events;
CREATE TRIGGER trg_stage_evidence BEFORE INSERT ON athlete_stage_events
  FOR EACH ROW EXECUTE FUNCTION fn_stage_evidence();

-- --------------------------------------------------------------------- Insider Plus picks (workstream D reads this)
-- Order: Verified Open Need first; then on-time before early-look; then Likely Future Need (observed departures) before
-- Possible Fit (class-year projection); then the sender's own rank.
-- Never: Unknown/expired signals, schools already delivered to that family, suppressed programs.
CREATE OR REPLACE VIEW v_insider_picks AS
SELECT ip.signup_ref, ip.sport_variant, ip.position, ip.match_class,
       p.school, p.school_slug, p.division, p.state, p.conference,
       o.id AS opportunity_id, o.status, o.basis, o.position_group, o.position_label, o.target_season,
       o.source_url, o.evidence_urls, o.verified_at, o.expires_at,
       m.id AS match_id, m.export_opp_id, m.insider_rank, m.insider_timing, m.insider_early, m.score, m.tier,
       row_number() OVER (PARTITION BY ip.signup_ref ORDER BY
         (o.status <> 'Verified Open Need'), coalesce(m.insider_early, FALSE),
         CASE o.status WHEN 'Likely Future Need' THEN 0 ELSE 1 END,
         m.insider_rank NULLS LAST, m.score DESC) AS pick_order
FROM insider_profiles ip
JOIN matches m ON m.athlete_id = ip.athlete_id
JOIN opportunities o ON o.id = m.opportunity_id
JOIN programs p ON p.id = m.program_id
WHERE o.status IN ('Verified Open Need','Likely Future Need','Possible Fit')
  AND (o.expires_at IS NULL OR o.expires_at > now())
  AND NOT EXISTS (SELECT 1 FROM insider_deliveries d WHERE d.signup_ref = ip.signup_ref AND d.school_slug = p.school_slug);

-- Verified needs that fit an Insider family but are not in its match list yet (staff notification queue)
CREATE OR REPLACE VIEW v_verified_need_alerts AS
SELECT o.id AS opportunity_id, p.school, p.school_slug, p.sport_variant, o.position_group, o.target_season,
       ip.signup_ref
FROM opportunities o JOIN programs p ON p.id = o.program_id
JOIN insider_profiles ip ON ip.sport_variant = p.sport_variant
WHERE o.status = 'Verified Open Need' AND (o.expires_at IS NULL OR o.expires_at > now())
  AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.athlete_id = ip.athlete_id AND m.program_id = p.id)
  AND NOT EXISTS (SELECT 1 FROM insider_deliveries d WHERE d.signup_ref = ip.signup_ref AND d.school_slug = p.school_slug);

-- --------------------------------------------------------------------- lock down: no PostgREST access
DO $$ DECLARE t RECORD; BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'fulfillment' LOOP
    EXECUTE format('ALTER TABLE fulfillment.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    EXECUTE 'REVOKE ALL ON SCHEMA fulfillment FROM anon, authenticated';
    EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA fulfillment FROM anon, authenticated';
  END IF;
END $$;
ALTER VIEW v_insider_picks SET (security_invoker = true);
ALTER VIEW v_verified_need_alerts SET (security_invoker = true);

-- staff seed (Chase = admin, the only approver/verifier until §17.1 #4 is decided)
INSERT INTO staff (name, email, role, can_approve_outreach, can_verify_opportunities, created_at)
VALUES ('Chase Grant', 'chase@theathletemarket.com', 'admin', TRUE, TRUE, now())
ON CONFLICT (email) DO NOTHING;
