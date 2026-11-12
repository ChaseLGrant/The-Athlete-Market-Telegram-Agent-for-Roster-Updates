-- Export the Insider Plus picks (top 20 per active family) + verified-need alerts + counts as one JSON document.
SET search_path = fulfillment;
SELECT json_build_object(
  'exported_at', now(),
  'counts', (SELECT json_build_object(
      'programs', (SELECT count(*) FROM programs), 'coaches', (SELECT count(*) FROM coaches),
      'opportunities', (SELECT json_object_agg(status, n) FROM (SELECT status, count(*) n FROM opportunities GROUP BY status) s),
      'insider_families_active', (SELECT count(*) FROM insider_profiles WHERE sub_status <> 'inactive'),
      'matches', (SELECT count(*) FROM matches), 'deliveries', (SELECT count(*) FROM insider_deliveries),
      'suppressed', (SELECT count(*) FROM suppression_list),
      'transport', (SELECT value FROM settings WHERE key = 'coach_outreach_transport'))),
  'picks', coalesce((SELECT json_agg(t ORDER BY t.signup_ref, t.pick_order) FROM (
      SELECT v.* FROM v_insider_picks v JOIN insider_profiles ip USING (signup_ref)
      WHERE ip.sub_status <> 'inactive' AND v.pick_order <= 20) t), '[]'::json),
  'verified_need_alerts', coalesce((SELECT json_agg(a) FROM v_verified_need_alerts a), '[]'::json)
);
