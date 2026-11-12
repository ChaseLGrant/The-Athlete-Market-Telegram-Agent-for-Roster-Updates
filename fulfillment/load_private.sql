-- Load Insider Plus families (pseudonymous), their delivered schools and their ranked matches. One transaction.
SET search_path = fulfillment;
CREATE TEMP TABLE s_fam (signup_ref TEXT, sport TEXT, gender TEXT, position TEXT, match_class TEXT, level TEXT, juco_year TEXT,
  levels TEXT, regions TEXT, plan TEXT, sub_status TEXT, sport_variant TEXT, export_generated_at TEXT);
CREATE TEMP TABLE s_del (signup_ref TEXT, school_slug TEXT, school TEXT, sent_at TEXT, kind TEXT);
CREATE TEMP TABLE s_fm (signup_ref TEXT, school_slug TEXT, sport_variant TEXT, position_group TEXT, target_season TEXT,
  export_opp_id TEXT, rank INTEGER, timing TEXT, early TEXT, score TEXT);
\copy s_fam FROM 'families.csv' CSV
\copy s_del FROM 'deliveries.csv' CSV
\copy s_fm FROM 'fmatches.csv' CSV

-- athletes: no names, emails or DOB here (they stay in the Insider sender's own store)
INSERT INTO athletes (external_ref, first_name, last_name, sport, gender, primary_position, grad_year, level,
                      division_preferences, service_tier, current_stage, onboarded_at, updated_at)
SELECT 'ip:' || signup_ref, 'Insider', left(signup_ref, 8), sport, gender, nullif(position,''), nullif(match_class,'')::int,
       CASE WHEN level = 'juco' THEN 'juco' ELSE 'hs' END,
       (SELECT string_agg('NCAA ' || x, ',') FROM unnest(string_to_array(levels, ',')) x),
       'insider_plus', 'onboarded', now(), now()
FROM s_fam
ON CONFLICT (external_ref) DO UPDATE SET sport = EXCLUDED.sport, gender = EXCLUDED.gender,
  primary_position = EXCLUDED.primary_position, grad_year = EXCLUDED.grad_year, level = EXCLUDED.level,
  division_preferences = EXCLUDED.division_preferences, updated_at = now();

INSERT INTO insider_profiles (athlete_id, signup_ref, sport_variant, position, match_class, level, juco_year, levels, regions,
                              plan, sub_status, export_generated_at, synced_at)
SELECT a.id, f.signup_ref, f.sport_variant, nullif(f.position,''), nullif(f.match_class,'')::int, f.level, nullif(f.juco_year,''),
       f.levels, f.regions, f.plan, f.sub_status, f.export_generated_at, now()
FROM s_fam f JOIN athletes a ON a.external_ref = 'ip:' || f.signup_ref
ON CONFLICT (signup_ref) DO UPDATE SET sport_variant = EXCLUDED.sport_variant, position = EXCLUDED.position,
  match_class = EXCLUDED.match_class, level = EXCLUDED.level, juco_year = EXCLUDED.juco_year, levels = EXCLUDED.levels,
  regions = EXCLUDED.regions, plan = EXCLUDED.plan, sub_status = EXCLUDED.sub_status,
  export_generated_at = EXCLUDED.export_generated_at, synced_at = now();
-- families no longer active/trialing stay on file but get no picks
UPDATE insider_profiles SET sub_status = 'inactive', synced_at = now()
WHERE signup_ref NOT IN (SELECT signup_ref FROM s_fam) AND sub_status <> 'inactive';

INSERT INTO insider_deliveries (signup_ref, school_slug, school, sent_at, kind)
SELECT signup_ref, school_slug, nullif(school,''), nullif(sent_at,'')::timestamptz, nullif(kind,'') FROM s_del
ON CONFLICT (signup_ref, school_slug) DO NOTHING;

-- matches from the sender's own ranking, tied to the engine opportunity row by program + position + season
CREATE TEMP TABLE s_fm2 AS
SELECT a.id AS athlete_id, p.id AS program_id, o.id AS opportunity_id, fm.*
FROM s_fm fm
JOIN athletes a ON a.external_ref = 'ip:' || fm.signup_ref
JOIN programs p ON p.school_slug = fm.school_slug AND p.sport_variant = fm.sport_variant
JOIN opportunities o ON o.program_id = p.id AND o.position_group = fm.position_group AND o.basis = 'roster_turnover'
                    AND coalesce(o.target_season,'~') = coalesce(nullif(fm.target_season,''),'~');

DELETE FROM matches m USING athletes a
WHERE a.id = m.athlete_id AND a.service_tier = 'insider_plus' AND a.external_ref LIKE 'ip:%' AND NOT m.human_reviewed
  AND NOT EXISTS (SELECT 1 FROM outreach_messages om WHERE om.match_id = m.id)
  AND NOT EXISTS (SELECT 1 FROM s_fm2 s WHERE s.athlete_id = m.athlete_id AND s.program_id = m.program_id);

INSERT INTO matches (athlete_id, program_id, opportunity_id, score, tier, components, explanation, evidence_urls,
                     evidence_backed, created_at, insider_rank, insider_timing, insider_early, export_opp_id, synced_at)
SELECT DISTINCT ON (s.athlete_id, s.program_id)
       s.athlete_id, s.program_id, s.opportunity_id, coalesce(nullif(s.score,'')::real, 0) / 100.0, 'competitive',
       jsonb_build_object('source', 'insider_plus.school_rank', 'insider_score', nullif(s.score,''),
                          'tier_note', 'tier not assessed: no athlete metrics on Insider Plus profiles'),
       coalesce(nullif(s.timing,''), 'roster turnover at the athlete''s position') , o.evidence_urls, TRUE, now(),
       s.rank, nullif(s.timing,''), s.early = 't', nullif(s.export_opp_id,''), now()
FROM s_fm2 s JOIN opportunities o ON o.id = s.opportunity_id
ORDER BY s.athlete_id, s.program_id, s.rank
ON CONFLICT (athlete_id, program_id) DO UPDATE SET opportunity_id = EXCLUDED.opportunity_id, score = EXCLUDED.score,
  components = EXCLUDED.components, explanation = EXCLUDED.explanation, evidence_urls = EXCLUDED.evidence_urls,
  insider_rank = EXCLUDED.insider_rank, insider_timing = EXCLUDED.insider_timing, insider_early = EXCLUDED.insider_early,
  export_opp_id = EXCLUDED.export_opp_id, synced_at = now();

UPDATE athletes a SET current_stage = 'matches_identified', updated_at = now()
WHERE a.service_tier = 'insider_plus' AND a.current_stage = 'onboarded'
  AND EXISTS (SELECT 1 FROM matches m WHERE m.athlete_id = a.id);

INSERT INTO audit_log (at, actor, action, entity, detail)
SELECT now(), 'job:fulfillment-db', 'load_insider_families', 'matches',
       jsonb_build_object('families', (SELECT count(*) FROM s_fam), 'deliveries', (SELECT count(*) FROM s_del),
                          'matches_in', (SELECT count(*) FROM s_fm), 'matches_mapped', (SELECT count(*) FROM s_fm2));
