"""PHASE 2 -- run Batfish over all 50 candidates and keep everything it says.

    python pipeline\\run_phase2.py                 # full run
    python pipeline\\run_phase2.py --limit 3       # smoke test first
    python pipeline\\run_phase2.py --resume        # continue after a crash

GATE: refuses to start unless data/pilot-v1/phase2/spike_result.json exists and
says GO. Run pipeline/spike_frr_batfish.py first. If the spike says STOP, this
stops too -- it will not silently switch vendors or translate configurations.

NOTHING here computes a label, a risk score, or a research target. It records
what Batfish said. Phase 4 decides what any of it means.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl.batching import (append_ledger, ledger_integrity,      # noqa: E402
                          now as bnow, plan_batch, print_batch_summary)
from nrl import GENERATOR_VERSION                                  # noqa: E402
from nrl.bf_eval import (RAW_QUESTIONS, differential_reachability,  # noqa: E402
                         evaluate_all, run_raw_questions)
from nrl.properties import PROPERTIES, SUITE_VERSION               # noqa: E402
from nrl.topologies import resolve as resolve_topology             # noqa: E402

NETWORK = None  # set per-pilot in main(); a shared constant made two
                # different pilots share one Batfish network, so a stale
                # snapshot from the other pilot could answer a question.
PIDS = [p["pid"] for p in PROPERTIES]
SPEC_PIDS = [p["pid"] for p in PROPERTIES if p["in_spec"]]
ORACLE_PIDS = [p["pid"] for p in PROPERTIES if not p["in_spec"]]

DIFF_SRC, DIFF_DST = "10.10.0.10", "10.20.0.0/23"




def resolve_pilot(raw: str) -> Path:
    """Resolve --pilot and REFUSE a directory that is not a pilot.

    A mistyped path (`data\\pilot-v` for `data\\pilot-v2` -- a shell wrapping
    the last character) used to get several steps in: the header printed
    "pilot.lock.json: UNREADABLE", a Batfish network `nrl-spike-pilot-v` was
    created, and only then did it die on a missing manifest. Half-executing
    against a target that does not exist is the wrong-target failure this
    project has already been bitten by; the run must stop at the first step.
    """
    p = Path(raw)
    if not p.is_absolute():
        p = (REPO / p).resolve()
    if not p.is_dir():
        raise SystemExit(f"BLOCKED: no such pilot directory: {p}\n"
                         f"         (check for a truncated or wrapped path)")
    missing = [f for f in ("manifest.json", "pilot.lock.json")
               if not (p / f).exists()]
    if missing:
        raise SystemExit(f"BLOCKED: {p} is not a pilot directory -- missing "
                         f"{', '.join(missing)}.\n"
                         f"         Run build_pilot_v2.py first.")
    return p

def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wj(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n",
                    newline="\n", encoding="utf-8")


def summarise_questions(q: dict) -> dict:
    """Scalar rollups for the human-readable CSV. The full records stay on disk
    untouched -- this only makes the CSV browsable."""
    def rows(name):
        return q.get(name, {}).get("row_count")

    fps = q.get("fileParseStatus", {}).get("records", [])
    passed = sum(1 for r in fps if str(r.get("Status")) == "PASSED")
    ifs = q.get("interfaceProperties", {}).get("records", [])
    active = sum(1 for r in ifs if r.get("Active") in (True, "True"))
    osp = q.get("ospfSessionCompatibility", {}).get("records", [])
    est = sum(1 for r in osp if str(r.get("Session_Status")) == "ESTABLISHED")
    return {
        "parse_files_total": len(fps),
        "parse_files_passed": passed,
        "parse_ok": bool(fps) and passed == len(fps),
        "parse_warning_rows": rows("parseWarning"),
        "init_issue_rows": rows("initIssues"),
        "undefined_reference_rows": rows("undefinedReferences"),
        "unused_structure_rows": rows("unusedStructures"),
        "defined_structure_rows": rows("definedStructures"),
        "nodes_parsed": rows("nodeProperties"),
        "interfaces_total": len(ifs),
        "interfaces_active": active,
        "ip_owner_rows": rows("ipOwners"),
        "layer3_edge_rows": rows("layer3Edges"),
        "route_rows": rows("routes"),
        "ospf_session_rows": len(osp),
        "ospf_sessions_established": est,
        "loop_rows": rows("detectLoops"),
        "multipath_inconsistency_rows": rows("multipathConsistency"),
        "subnet_multipath_inconsistency_rows":
            rows("subnetMultipathConsistency"),
        "questions_errored": sorted(k for k, v in q.items()
                                    if v.get("status") == "ERROR"),
    }


def normalise_questions(questions: dict, run_error) -> dict:
    """Guarantee one entry per question, always.

    A candidate whose snapshot failed to initialise collects nothing. Left as
    an empty dict it would produce zero rows in the questions CSV and simply
    vanish from any per-candidate count -- a missing candidate that looks like
    no candidate at all. Placeholders make the failure visible instead.
    """
    out = {}
    for name, _ in RAW_QUESTIONS:
        out[name] = questions.get(name) or {
            "status": "ERROR",
            "error": run_error or "question not run (candidate aborted)",
            "row_count": None, "columns": [], "records": [], "seconds": 0.0}
    return out


def normalise_props(props: list, run_error) -> list:
    """Same guarantee for the twelve properties."""
    if props:
        return props
    return [{"property_id": p["pid"], "kind": p["kind"],
             "in_spec": p["in_spec"], "text": p["text"],
             "status": "ERROR", "verdict": None,
             "error": run_error or "not evaluated (candidate aborted)",
             "counterexample_count": 0, "evidence": {}, "extra": {},
             "seconds": 0.0}
            for p in PROPERTIES]


def build_records(cid, iid, manifest_entry, questions, props,
                  diff_inc, diff_gold, run_status, run_error, seconds):
    """Assemble the three flat records for one candidate.

    Extracted from the run loop so the CSV schema can be exercised without
    Batfish -- tested by the same code that produces it, rather than by a
    duplicate that can drift.
    """
    qs = summarise_questions(questions)
    by_pid = {p["property_id"]: p for p in props}

    def tally(pids):
        return (sum(1 for p in pids if by_pid.get(p, {}).get("verdict") == "PASS"),
                sum(1 for p in pids if by_pid.get(p, {}).get("verdict") == "FAIL"),
                sum(1 for p in pids if by_pid.get(p, {}).get("status") == "ERROR"))

    s_pass, s_fail, s_err = tally(SPEC_PIDS)
    o_pass, o_fail, o_err = tally(ORACLE_PIDS)

    if run_status == "ERROR" or not props:
        spec_verdict = "ERROR"
    elif not qs["parse_ok"]:
        spec_verdict = "INVALID"     # parsed badly -> the verdict is meaningless
    elif s_err:
        spec_verdict = "ERROR"
    else:
        spec_verdict = "PASS" if s_fail == 0 else "FAIL"

    oracle_verdict = ("ERROR" if (o_err or run_status == "ERROR")
                      else ("PASS" if o_fail == 0 else "FAIL"))

    row = {
        "candidate_id": cid,
        "incident_id": iid,
        "prov_fault_family_BANNED": manifest_entry["fault_family"],
        "prov_repair_id_BANNED": manifest_entry["repair_id"],
        "batfish_snapshot_name": cid,
        "reference_snapshot_name": iid,
        "run_status": run_status,
        "run_error": run_error,
        "run_seconds": round(seconds, 2),
        **qs,
        "spec_n": len(SPEC_PIDS), "spec_pass": s_pass,
        "spec_fail": s_fail, "spec_error": s_err,
        "batfish_spec_verdict": spec_verdict,
        "oracle_only_n": len(ORACLE_PIDS), "oracle_only_pass": o_pass,
        "oracle_only_fail": o_fail, "oracle_only_error": o_err,
        "batfish_oracle_only_verdict": oracle_verdict,
        "diff_vs_incident_rows": diff_inc.get("row_count"),
        "diff_vs_incident_status": diff_inc.get("status"),
        "diff_vs_golden_rows_BANNED": diff_gold.get("row_count"),
        "diff_vs_golden_status": diff_gold.get("status"),
        **{f"verdict_{p}": by_pid.get(p, {}).get("verdict") for p in PIDS},
        **{f"status_{p}": by_pid.get(p, {}).get("status") for p in PIDS},
    }
    row["questions_errored"] = ";".join(qs["questions_errored"])

    prow = [{"candidate_id": cid, "incident_id": iid,
             "property_id": p["property_id"], "kind": p["kind"],
             "in_spec": p["in_spec"], "text": p["text"],
             "status": p["status"], "verdict": p["verdict"],
             "error": p["error"],
             "counterexample_count": p["counterexample_count"],
             "seconds": p["seconds"],
             "extra_json": json.dumps(p["extra"], default=str)}
            for p in props]
    qrow = [{"candidate_id": cid, "question": k, "status": v["status"],
             "row_count": v["row_count"], "seconds": v["seconds"],
             "error": v["error"], "columns": ";".join(v["columns"])}
            for k, v in questions.items()]
    return row, prow, qrow


def write_csv(path: Path, records):
    if not records:
        return 0, 0
    cols = list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in records:
            w.writerow(r)
    return len(records), len(cols)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. There is deliberately "
                         "NO default: a default silently pointed every run at the old "
                         "pilot, whose ledger was already complete, so the run executed "
                         "nothing and reported ALL ITEMS COMPLETE.")
    ap.add_argument("--only", default="",
                    help="comma-separated candidate ids. --limit takes the FIRST n, "
                         "which on a topology-ordered manifest means one topology "
                         "and one repair class -- a smoke test that exercises very "
                         "little. Use --only for a stratified sample.")
    ap.add_argument("--limit", type=int, default=0,
                    help="process only the first N candidates (smoke test)")
    ap.add_argument("--batch-size", type=int, default=0,
                    help="process only the next N pending candidates, then "
                         "stop cleanly. 0 = all remaining.")
    ap.add_argument("--resume", action="store_true",
                    help="skip candidates that already have a record.json")
    args = ap.parse_args()

    root = resolve_pilot(args.pilot)
    out = root / "phase2"
    raw = out / "raw"
    out.mkdir(parents=True, exist_ok=True)

    spike_p = out / "spike_result.json"
    if not spike_p.exists():
        print("BLOCKED: no spike result.")
        print(f"  Run this first:  python pipeline\\spike_frr_batfish.py "
              f"--pilot {args.pilot}")
        print("  Phase 2 must not run against an artifact Batfish cannot read.")
        return 2
    spike = json.loads(spike_p.read_text())
    if spike.get("verdict") != "GO":
        print(f"BLOCKED: spike verdict is {spike.get('verdict')}.")
        print(f"  failing checks: "
              f"{[k for k, v in spike.get('checks', {}).items() if not v]}")
        print("  Fix the artifact or switch vendor deliberately -- do NOT")
        print("  translate configs to make this pass. See docs/ARCHITECTURE.md.")
        return 2

    # A GO verdict is about ONE artifact. If the pilot has been rebuilt since,
    # the verdict is stale and says nothing about what is on disk now.
    lock = json.loads((root / "pilot.lock.json").read_text())
    # Gate on the SNAPSHOT digest: Phase 2 reads batfish-snapshot/ and nothing
    # else, so a change to the clab topology or a container image must not
    # invalidate a valid Batfish dataset.
    cur = lock.get("snapshot_digest") or lock.get("artifact_digest")
    was = spike.get("snapshot_digest") or spike.get("artifact_digest")
    if cur and was and cur != was:
        print("BLOCKED: the spike verdict is for a different snapshot.")
        print(f"  spike ran against : {was[:16]}...")
        print(f"  pilot on disk is  : {cur[:16]}...")
        print("  The pilot was rebuilt after the spike. Re-run:")
        print(f"     python pipeline\\spike_frr_batfish.py --pilot {args.pilot}")
        return 2
    if cur and not was:
        print("WARNING: this spike result predates artifact-digest stamping.")
        print("  Re-run the spike to remove the ambiguity.")

    manifest = json.loads((root / "manifest.json").read_text())
    cands = manifest["candidates"]
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        cands = [c for c in cands if c["candidate_id"] in want]
        missing = want - {c["candidate_id"] for c in cands}
        if missing:
            print(f"BLOCKED: not in manifest: {sorted(missing)}")
            return 2
    if args.limit:
        cands = cands[:args.limit]

    # An item is DONE iff its record exists. Disk is the state; nothing else.
    all_ids = [c["candidate_id"] for c in cands]
    def _done(cid): return (raw / cid / "record.json").exists()
    plan = plan_batch(all_ids, _done, args.batch_size)
    todo = set(plan["this_batch"])
    print(f"batch plan: {plan['already_done']} done, {plan['pending']} pending, "
          f"{len(todo)} this batch, {plan['remaining_after']} after")

    import logging
    import pybatfish
    from pybatfish.client.session import Session
    logging.getLogger("pybatfish").setLevel(logging.ERROR)

    global NETWORK
    NETWORK = f"nrl-{root.name}"
    bf = Session(host="localhost")
    bf.set_network(NETWORK)

    t_start = time.time()
    print(f"Phase 2 -- {len(cands)} candidates, network '{NETWORK}'")
    print(f"  pilot           : {root.resolve()}")
    print(f"  artifact digest : {lock.get('artifact_digest','?')[:16]}")
    print(f"  manifest        : {len(manifest.get('candidates', []))} candidates total")
    print(f"spike verdict: {spike.get('verdict')}"
          f"{'  (OVERRIDDEN)' if False else ''}\n")

    print("loading reference + incident snapshots for the differential questions")
    topos = sorted({c.get("topology") for c in cands if c.get("topology")})
    if topos:
        for tn in topos:
            bf.init_snapshot(str(root / "reference" / f"golden-{tn}"
                                 / "batfish-snapshot"),
                             name=f"golden-{tn}", overwrite=True)
            print(f"  golden-{tn}")
    else:
        bf.init_snapshot(str(root / "reference" / "golden" / "batfish-snapshot"),
                         name="golden", overwrite=True)
    for iid in sorted({c["incident_id"] for c in cands
                       if c["candidate_id"] in todo}):
        bf.init_snapshot(str(root / "incidents" / iid / "batfish-snapshot"),
                         name=iid, overwrite=True)
        print(f"  {iid}")

    rows, prop_rows, q_rows, errors = [], [], [], []
    for n, c in enumerate(cands, start=1):
        cid, iid = c["candidate_id"], c["incident_id"]
        cdir = raw / cid
        if _done(cid):
            rec = json.loads((cdir / "record.json").read_text())
            rows.append(rec["summary_row"])
            prop_rows.extend(rec["property_rows"])
            q_rows.extend(rec["question_rows"])
            print(f"[{n:3d}/{len(cands)}] {cid}  (already done)")
            continue
        if cid not in todo:
            continue                       # deferred to a later batch

        t0 = time.time()
        eta = ""
        if n > 1:
            per = (time.time() - t_start) / (n - 1)
            eta = f"  eta {int(per * (len(cands) - n + 1))}s"
        print(f"[{n:3d}/{len(cands)}] {cid}  ({iid}){eta}", flush=True)

        run_status, run_error = "OK", None
        questions, props = {}, []
        diff_inc = diff_gold = {"status": "NOT_RUN", "row_count": None}
        try:
            bf.init_snapshot(str(root / "candidates" / cid / "batfish-snapshot"),
                             name=cid, overwrite=True)
            bf.set_snapshot(cid)
            spec = resolve_topology(c.get("topology"))
            questions = run_raw_questions(bf)
            try:
                bf.generate_dataplane()
            except Exception as exc:                              # noqa: BLE001
                run_status = "DATAPLANE_ERROR"
                run_error = f"{type(exc).__name__}: {exc}"
            props = evaluate_all(bf, spec)
            diff_inc = differential_reachability(bf, cid, iid,
                                                 DIFF_SRC, DIFF_DST, spec)
            gref = (f"golden-{c['topology']}" if c.get("topology")
                    else "golden")
            diff_gold = differential_reachability(bf, cid, gref,
                                                  DIFF_SRC, DIFF_DST, spec)
        except Exception as exc:                                  # noqa: BLE001
            run_status, run_error = "ERROR", f"{type(exc).__name__}: {exc}"
            errors.append((cid, run_error))
            print(f"        ERROR: {run_error}")

        questions = normalise_questions(questions, run_error)
        props = normalise_props(props, run_error)
        row, prow, qrow = build_records(
            cid, iid, c, questions, props, diff_inc, diff_gold,
            run_status, run_error, time.time() - t0)

        for qname, qval in questions.items():
            wj(cdir / "questions" / f"{qname}.json", qval)
        wj(cdir / "properties.json", props)
        wj(cdir / "differential.json",
           {"vs_incident": diff_inc, "vs_golden_BANNED": diff_gold,
            "flow": {"src": DIFF_SRC, "dst": DIFF_DST}})
        wj(cdir / "record.json", {
            "candidate_id": cid, "incident_id": iid,
            "collected_utc": now(), "run_status": run_status,
            "run_error": run_error,
            "summary_row": row, "property_rows": prow, "question_rows": qrow,
        })

        rows.append(row)
        prop_rows.extend(prow)
        q_rows.extend(qrow)

    nr, nc = write_csv(out / "batfish_summary.csv", rows)
    pr, pc = write_csv(out / "batfish_properties.csv", prop_rows)
    qr, qc = write_csv(out / "batfish_questions_index.csv", q_rows)

    src_dd = REPO / "docs" / "PHASE2-DATA-DICTIONARY.md"
    if src_dd.exists():
        shutil.copyfile(src_dd, out / "DATA-DICTIONARY.md")

    wj(out / "run_metadata.json", {
        "phase": 2, "run_utc": now(),
        "generator_version": GENERATOR_VERSION,
        "suite_version": SUITE_VERSION,
        "network": NETWORK,
        "pybatfish_version": getattr(pybatfish, "__version__", "unknown"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "spike_verdict": spike.get("verdict"),
        "snapshot_digest": cur,
        "artifact_digest": lock.get("artifact_digest"),
        "spike_overridden": bool(False),
        "candidates_requested": len(cands),
        "candidates_processed": len(rows),
        # verify_phase2 recomputes the expected set from these plus the
        # manifest, rather than assuming every manifest candidate should be
        # present. Without them a batched or --only run looks like a dataset
        # with 1433 candidates missing.
        "candidate_filter": sorted(x.strip() for x in args.only.split(",")
                                   if x.strip()) or None,
        "limit": args.limit or None,
        "batch_size": args.batch_size or None,
        "candidates_errored": [c for c, _ in errors],
        "differential_flow": {"src": DIFF_SRC, "dst": DIFF_DST},
        "spec_property_ids": SPEC_PIDS,
        "oracle_only_property_ids": ORACLE_PIDS,
        "raw_questions": [n for n, _ in
                          __import__("nrl.bf_eval", fromlist=["RAW_QUESTIONS"])
                          .RAW_QUESTIONS],
        "wall_seconds": round(time.time() - t_start, 1),
        "note": "No label, risk score or research target is computed in "
                "Phase 2. See docs/HARM-DEFINITION.md.",
    })

    v = [r["batfish_spec_verdict"] for r in rows]
    batch_rows = [r for r in rows if r["candidate_id"] in todo]
    bv = [r["batfish_spec_verdict"] for r in batch_rows]
    ledger = out / "batch_log.jsonl"
    append_ledger(ledger, {
        "batch": len(ledger_integrity(ledger).get("duplicates", [])) * 0
                 + ledger_integrity(ledger)["batches"] + 1,
        "utc": bnow(), "phase": 2, "ids": sorted(todo),
        "n": len(todo), "seconds": round(time.time() - t_start, 1),
        "pass": bv.count("PASS"), "fail": bv.count("FAIL"),
        "error": bv.count("ERROR"), "invalid": bv.count("INVALID")})
    print_batch_summary(
        "PHASE 2 BATCH COMPLETE", plan,
        {"generated (in manifest)": plan["total"],
         "batfish PASS": bv.count("PASS"), "batfish FAIL": bv.count("FAIL"),
         "ERROR": bv.count("ERROR"), "INVALID": bv.count("INVALID"),
         "errors (harness)": len(errors)},
        {"candidates processed": len(rows),
         "cumulative PASS": v.count("PASS"), "cumulative FAIL": v.count("FAIL"),
         "cumulative ERROR": v.count("ERROR"),
         "ledger duplicates (must be 0)":
             len(ledger_integrity(ledger)["duplicates"])},
        time.time() - t_start)
    print(f"  batfish_summary.csv         {nr} rows x {nc} cols")
    print(f"  batfish_properties.csv      {pr} rows x {pc} cols")
    print(f"  batfish_questions_index.csv {qr} rows x {qc} cols")
    print(f"  raw evidence -> {raw}")
    if errors:
        print(f"\n  {len(errors)} candidate(s) errored:")
        for cid, e in errors:
            print(f"    {cid}: {e}")
    print(f"{'=' * 70}")
    print("next:  python pipeline\\verify_phase2.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
