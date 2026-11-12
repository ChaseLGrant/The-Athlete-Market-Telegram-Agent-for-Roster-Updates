-- Guardrail self-test against the live schema. Everything runs inside one transaction that is ROLLED BACK.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = fulfillment;
SET CONSTRAINTS ALL IMMEDIATE;
CREATE TEMP TABLE gt (name TEXT, ok BOOLEAN) ON COMMIT DROP;
DO $$
DECLARE pid BIGINT; cid BIGINT; aid BIGINT; sid BIGINT; oid_ BIGINT; mid BIGINT;
BEGIN
  INSERT INTO programs (school, school_slug, sport, sport_variant, gender, division, source, source_url)
    VALUES ('GT School','gt-school-selftest','baseball','baseball','M','NCAA D2','selftest','https://example.test/r') RETURNING id INTO pid;
  INSERT INTO coaches (program_id, name, email, source_url) VALUES (pid,'GT Coach','gt.coach@example.test','https://example.test/c') RETURNING id INTO cid;
  INSERT INTO athletes (first_name,last_name,sport,gender,service_tier,onboarded_at,updated_at,is_synthetic)
    VALUES ('GT','Selftest','baseball','M','premium_placement',now(),now(),TRUE) RETURNING id INTO aid;
  SELECT id INTO sid FROM staff WHERE email='chase@theathletemarket.com';

  -- T1 roster turnover can never be Verified Open Need (CHECK)
  BEGIN
    INSERT INTO opportunities (program_id,position_group,status,basis,source_url,verified_at,verified_by,created_at)
      VALUES (pid,'RHP','Verified Open Need','roster_turnover','https://example.test/r',now(),'selftest',now());
    INSERT INTO gt VALUES ('T1 turnover never Verified', FALSE);
  EXCEPTION WHEN check_violation THEN INSERT INTO gt VALUES ('T1 turnover never Verified', TRUE); END;

  -- T2 Verified Open Need without a staff verification record (trigger)
  BEGIN
    INSERT INTO opportunities (program_id,position_group,status,basis,announcement_url,source_url,verified_at,verified_by,created_at)
      VALUES (pid,'C','Verified Open Need','official_announcement','https://example.test/a','https://example.test/a',now(),'selftest',now());
    INSERT INTO gt VALUES ('T2 Verified needs staff verification', FALSE);
  EXCEPTION WHEN raise_exception THEN INSERT INTO gt VALUES ('T2 Verified needs staff verification', TRUE); END;

  -- T2b with a staff verification record it is accepted
  BEGIN
    INSERT INTO opportunities (program_id,position_group,status,basis,source_url,verified_at,verified_by,created_at)
      VALUES (pid,'OF','Likely Future Need','official_announcement','https://example.test/a',now(),'selftest',now()) RETURNING id INTO oid_;
    INSERT INTO opportunity_verifications (opportunity_id, decision, decided_by, evidence_url) VALUES (oid_,'verified',sid,'https://example.test/a');
    UPDATE opportunities SET status='Verified Open Need', announcement_url='https://example.test/a' WHERE id=oid_;
    INSERT INTO gt VALUES ('T2b Verified accepted with staff record', TRUE);
  EXCEPTION WHEN OTHERS THEN INSERT INTO gt VALUES ('T2b Verified accepted with staff record', FALSE); END;

  -- T3 approval without guardian consent is blocked
  BEGIN
    INSERT INTO outreach_messages (athlete_id,coach_id,subject,body,status,approved_by,approved_at,created_at)
      VALUES (aid,cid,'s','b','approved',sid,now(),now());
    INSERT INTO gt VALUES ('T3 no consent no approval', FALSE);
  EXCEPTION WHEN raise_exception THEN INSERT INTO gt VALUES ('T3 no consent no approval', TRUE); END;

  INSERT INTO guardians_consent (athlete_id,guardian_name,scope,granted,method,granted_at) VALUES (aid,'GT Parent','coach_contact',TRUE,'e_signature',now());

  -- T4 with consent: approval OK, but send is blocked while transport is OFF
  BEGIN
    INSERT INTO outreach_messages (athlete_id,coach_id,subject,body,status,approved_by,approved_at,created_at)
      VALUES (aid,cid,'s','b','approved',sid,now(),now()) RETURNING id INTO mid;
    INSERT INTO gt VALUES ('T4a consented approval allowed', TRUE);
  EXCEPTION WHEN OTHERS THEN INSERT INTO gt VALUES ('T4a consented approval allowed', FALSE); END;
  BEGIN
    UPDATE outreach_messages SET status='sent', sent_at=now() WHERE id=mid;
    INSERT INTO gt VALUES ('T4b transport OFF blocks send', FALSE);
  EXCEPTION WHEN raise_exception THEN INSERT INTO gt VALUES ('T4b transport OFF blocks send', TRUE); END;

  -- T5 suppression cancels pending messages and blocks new approvals
  INSERT INTO suppression_list (email, reason, source) VALUES ('gt.coach@example.test','opt_out','selftest');
  INSERT INTO gt SELECT 'T5a suppression cancels pending', (SELECT status FROM outreach_messages WHERE id=mid) = 'opted_out';
  BEGIN
    INSERT INTO athletes (first_name,last_name,sport,gender,service_tier,onboarded_at,updated_at,is_synthetic)
      VALUES ('GT2','Selftest','baseball','M','premium_placement',now(),now(),TRUE) RETURNING id INTO aid;
    INSERT INTO guardians_consent (athlete_id,guardian_name,scope,granted,method,granted_at) VALUES (aid,'GT Parent','coach_contact',TRUE,'e_signature',now());
    INSERT INTO outreach_messages (athlete_id,coach_id,subject,body,status,approved_by,approved_at,created_at)
      VALUES (aid,cid,'s','b','approved',sid,now(),now());
    INSERT INTO gt VALUES ('T5b suppressed coach blocked', FALSE);
  EXCEPTION WHEN raise_exception THEN INSERT INTO gt VALUES ('T5b suppressed coach blocked', TRUE); END;

  -- T6 placement stage needs evidence + staff actor
  BEGIN
    INSERT INTO athlete_stage_events (athlete_id,stage_code,entered_at,actor) VALUES (aid,'commitment',now(),'job:auto');
    INSERT INTO gt VALUES ('T6 placement needs evidence', FALSE);
  EXCEPTION WHEN raise_exception THEN INSERT INTO gt VALUES ('T6 placement needs evidence', TRUE); END;
END $$;
SELECT name, CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END AS result FROM gt ORDER BY name;
SELECT CASE WHEN bool_and(ok) THEN 'ALL GUARDRAIL TESTS PASSED' ELSE 'GUARDRAIL TEST FAILURE' END AS summary FROM gt;
ROLLBACK;
