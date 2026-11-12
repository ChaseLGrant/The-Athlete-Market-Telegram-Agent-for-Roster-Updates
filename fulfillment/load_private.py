"""Fulfillment Engine Phase 0: Insider Plus family payload -> CSVs for load_private.sql.
The payload is built in the private workspace (fulfillment-engine/live/build_payload.py) and reaches this job only as an
encrypted Actions secret. It is pseudonymous (signup id + sport/position/class/levels/regions, plus school slugs) and is
never printed or committed. Output CSVs live in the runner's temp dir and are deleted with it."""
import csv, json, sys

def main(payload_path, outdir):
    p = json.load(open(payload_path))
    fams, dels, mts = [], [], []
    for f in p["families"]:
        r = f["signup_ref"]
        fams.append([r, f["sport"], f["gender"], f.get("position") or "", f.get("match_class") or "", f.get("level") or "hs",
                     f.get("juco_year") or "", ",".join(f.get("levels") or []), ",".join(f.get("regions") or []),
                     f.get("plan") or "", f.get("sub_status") or "", f["sport_variant"], p.get("export_generated_at") or ""])
        for d in f.get("deliveries") or []:
            dels.append([r, d["school_slug"], d.get("school") or "", d.get("sent_at") or "", d.get("kind") or ""])
        for m in f.get("matches") or []:
            mts.append([r, m["school_slug"], m["sport_variant"], m["position_group"], m.get("target_season") or "",
                        m.get("export_opp_id") or "", m["rank"], m.get("timing") or "", "t" if m.get("early") else "f",
                        m.get("score") if m.get("score") is not None else ""])
    for name, rows in (("families", fams), ("deliveries", dels), ("fmatches", mts)):
        with open(f"{outdir}/{name}.csv", "w", newline="") as fh:
            csv.writer(fh).writerows(rows)
    print(json.dumps({"families": len(fams), "deliveries": len(dels), "matches": len(mts)}))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
