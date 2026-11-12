-- Load public program/coach/roster-signal data into schema `fulfillment` (run from the CSV directory, one transaction).
SET search_path = fulfillment;
CREATE TEMP TABLE s_prog (school TEXT, school_slug TEXT, sport TEXT, sport_variant TEXT, gender TEXT, division TEXT,
  conference TEXT, state TEXT, roster_url TEXT, stats_url TEXT, source TEXT, source_url TEXT, last_verified_at TEXT);
CREATE TEMP TABLE s_coach (school_slug TEXT, sport_variant TEXT, name TEXT, title TEXT, email TEXT, source_url TEXT);
CREATE TEMP TABLE s_opp (school_slug TEXT, sport_variant TEXT, position_group TEXT, position_label TEXT, target_season TEXT,
  status TEXT, signal TEXT, confidence TEXT, reason TEXT, source_url TEXT, evidence_urls TEXT, verified_at TEXT,
  verified_by TEXT, expires_at TEXT, external_id TEXT, needs_review TEXT);
\copy s_prog FROM 'programs.csv' CSV
\copy s_coach FROM 'coaches.csv' CSV
\copy s_opp FROM 'opportunities.csv' CSV

INSERT INTO programs (school, school_slug, sport, sport_variant, gender, division, conference, state, roster_url, stats_url,
                      source, source_url, last_verified_at)
SELECT school, school_slug, sport, sport_variant, gender, division, nullif(conference,''), nullif(state,''),
       nullif(roster_url,''), nullif(stats_url,''), source, source_url, nullif(last_verified_at,'')::timestamptz
FROM s_prog
ON CONFLICT (school_slug, sport_variant) DO UPDATE SET
  school = EXCLUDED.school, division = EXCLUDED.division, conference = EXCLUDED.conference, state = EXCLUDED.state,
  roster_url = EXCLUDED.roster_url, stats_url = EXCLUDED.stats_url, source = EXCLUDED.source,
  source_url = EXCLUDED.source_url, last_verified_at = EXCLUDED.last_verified_at;

-- opted_out is never reset by a reload
INSERT INTO coaches (program_id, name, title, email, source_url)
SELECT p.id, c.name, nullif(c.title,''), c.email, c.source_url
FROM s_coach c JOIN programs p ON p.school_slug = c.school_slug AND p.sport_variant = c.sport_variant
ON CONFLICT (program_id, name) DO UPDATE SET title = EXCLUDED.title, email = EXCLUDED.email, source_url = EXCLUDED.source_url;

-- roster turnover only; the CHECKs refuse 'Verified Open Need' for this basis
INSERT INTO opportunities (program_id, position_group, position_label, target_season, status, basis, signal, confidence,
  reason, source_url, evidence_urls, verified_at, verified_by, expires_at, external_id, needs_staff_review, created_at)
SELECT p.id, o.position_group, nullif(o.position_label,''), nullif(o.target_season,''), o.status, 'roster_turnover',
       nullif(o.signal,'')::real, nullif(o.confidence,''), nullif(o.reason,''), o.source_url, o.evidence_urls::jsonb,
       o.verified_at::timestamptz, o.verified_by, nullif(o.expires_at,'')::timestamptz, 'engine:' || o.external_id,
       o.needs_review = 't', now()
FROM s_opp o JOIN programs p ON p.school_slug = o.school_slug AND p.sport_variant = o.sport_variant
ON CONFLICT (program_id, position_group, basis, target_season) DO UPDATE SET
  position_label = EXCLUDED.position_label, status = EXCLUDED.status, signal = EXCLUDED.signal,
  confidence = EXCLUDED.confidence, reason = EXCLUDED.reason, source_url = EXCLUDED.source_url,
  evidence_urls = EXCLUDED.evidence_urls, verified_at = EXCLUDED.verified_at, verified_by = EXCLUDED.verified_by,
  expires_at = EXCLUDED.expires_at, external_id = EXCLUDED.external_id, needs_staff_review = EXCLUDED.needs_staff_review;

-- roster signals that dropped out of the current export: Unknown + staff review (never deleted, never shown)
UPDATE opportunities o SET status = 'Unknown', needs_staff_review = TRUE
FROM programs p
WHERE p.id = o.program_id AND o.basis = 'roster_turnover' AND o.status <> 'Unknown'
  AND NOT EXISTS (SELECT 1 FROM s_opp s WHERE s.school_slug = p.school_slug AND s.sport_variant = p.sport_variant
                  AND s.position_group = o.position_group AND coalesce(nullif(s.target_season,''),'~') = coalesce(o.target_season,'~'));

INSERT INTO audit_log (at, actor, action, entity, detail)
SELECT now(), 'job:fulfillment-db', 'load_public', 'opportunities',
       jsonb_build_object('programs', (SELECT count(*) FROM s_prog), 'coaches', (SELECT count(*) FROM s_coach),
                          'opportunities', (SELECT count(*) FROM s_opp));
