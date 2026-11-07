"""Quality checks on the Phase 2 dataset. Run immediately after run_phase2.py.

    python pipeline\\verify_phase2.py

Checks nothing about whether the network is correct -- only whether the DATASET
is complete, consistent, loadable, and honest about its own failures.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl.bf_eval import RAW_QUESTIONS                              # noqa: E402
from nrl.properties import PROPERTIES                              # noqa: E402

PIDS = {p["pid"] for p in PROPERTIES}
QNAMES = {n for n, _ in RAW_QUESTIONS}
FAIL, PASSED = [], 0




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

def check(label, ok, detail=""):
    global PASSED
    if ok:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAIL.append((label, detail))
        print(f"  [FAIL] {label}")
        if detail:
            print(f"         {detail}")
    return ok


def load_csv(p: Path):
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. There is deliberately "
                         "NO default: a default silently pointed every run at the old "
                         "pilot, whose ledger was already complete, so the run executed "
                         "nothing and reported ALL ITEMS COMPLETE.")
    args = ap.parse_args()
    root = resolve_pilot(args.pilot)
    p2 = root / "phase2"
    print(f"verifying {p2}\n")

    if not p2.exists():
        print("no phase2 directory -- run pipeline/run_phase2.py first")
        return 2

    print("CHECK 1 -- dataset files exist and load")
    ok = True
    for name in ("batfish_summary.csv", "batfish_properties.csv",
                 "batfish_questions_index.csv"):
        ok &= check(f"{name} loads", (p2 / name).exists())
    for name in ("run_metadata.json", "spike_result.json"):
        ok &= check(f"{name} loads", (p2 / name).exists())
    if not ok:
        print("\nmissing files -- stopping")
        return 1
    summary = load_csv(p2 / "batfish_summary.csv")
    props = load_csv(p2 / "batfish_properties.csv")
    qidx = load_csv(p2 / "batfish_questions_index.csv")
    meta = json.loads((p2 / "run_metadata.json").read_text())
    spike = json.loads((p2 / "spike_result.json").read_text())
    check("DATA-DICTIONARY.md present", (p2 / "DATA-DICTIONARY.md").exists())

    print("\nCHECK 2 -- completeness against the recomputed expected set")
    # DEFECT B1, second instance. This expected EVERY manifest candidate, so a
    # deliberately restricted run (--only for a stratified validation batch, or
    # --batch-size for a staged collection) reported 1,433 candidates "missing"
    # from a dataset that was exactly right. Same shape as the version fixed in
    # verify_phase3.py: the expectation must be recomputed from the manifest AND
    # the run's own declared eligibility filter -- never from what happened to
    # run, and never from the whole manifest regardless of what was asked for.
    manifest = json.loads((root / "manifest.json").read_text())
    all_ids = [c["candidate_id"] for c in manifest["candidates"]]
    expected = list(all_ids)
    if meta.get("candidate_filter"):
        sel = set(meta["candidate_filter"])
        unknown = sorted(sel - set(all_ids))
        check("every id in the run's --only filter is in the manifest",
              not unknown, f"not in manifest: {unknown[:5]}")
        expected = [c for c in all_ids if c in sel]
    if meta.get("limit"):
        expected = expected[:int(meta["limit"])]
    got = [r["candidate_id"] for r in summary]

    print(f"         manifest {len(all_ids)} | eligible this run "
          f"{len(expected)} | present {len(got)}")
    check("no candidate outside the expected set",
          not (set(got) - set(expected)),
          f"unexpected: {sorted(set(got) - set(expected))[:5]} -- these were "
          f"processed but the manifest and filter do not account for them")
    remaining = sorted(set(expected) - set(got))
    if remaining:
        if meta.get("batch_size"):
            print(f"         REMAINING: {len(remaining)} eligible candidates "
                  f"not yet processed (batched run in progress) e.g. "
                  f"{remaining[:4]}")
        else:
            check("every eligible candidate was processed", not remaining,
                  f"{len(remaining)} missing and the run was NOT batched: "
                  f"{remaining[:5]}")
    else:
        print("         all eligible candidates present")
    dupes = [c for c, n in Counter(got).items() if n > 1]
    check("no duplicate candidate_id", not dupes, f"dupes: {dupes}")
    check("incident_id matches the manifest for every candidate",
          all(r["incident_id"] == next(c["incident_id"]
                                       for c in manifest["candidates"]
                                       if c["candidate_id"] == r["candidate_id"])
              for r in summary))

    # from here on, "expected" means the candidates that actually ran
    expected = [c for c in expected if c in set(got)]

    print("\nCHECK 3 -- every property and every question recorded")
    # Count over EXPECTED candidates. Counting only the ids present in the CSV
    # makes a candidate with zero rows invisible -- it drops out of the Counter
    # entirely instead of showing up as a count of 0.
    per_cand_props = Counter(r["candidate_id"] for r in props)
    bad = {c: per_cand_props.get(c, 0) for c in expected
           if per_cand_props.get(c, 0) != len(PIDS)}
    check(f"all {len(PIDS)} property rows present for every expected "
          f"candidate ({len(PIDS) * len(expected)} total)", not bad,
          f"wrong counts: {dict(list(bad.items())[:5])}")
    missing_pid = {r["candidate_id"] for r in props if r["property_id"] not in PIDS}
    check("no unknown property_id", not missing_pid, str(sorted(missing_pid)[:5]))
    per_cand_q = Counter(r["candidate_id"] for r in qidx)
    badq = {c: per_cand_q.get(c, 0) for c in expected
            if per_cand_q.get(c, 0) != len(QNAMES)}
    check(f"all {len(QNAMES)} question rows present for every expected "
          f"candidate ({len(QNAMES) * len(expected)} total)", not badq,
          f"wrong counts: {dict(list(badq.items())[:5])}")

    print("\nCHECK 4 -- parse status recorded for every candidate")
    check("parse_ok present and non-empty for all",
          all(r.get("parse_ok") not in (None, "") for r in summary))
    check("parse_files_total recorded for all",
          all(r.get("parse_files_total") not in (None, "") for r in summary))
    parse_bad = [r["candidate_id"] for r in summary
                 if str(r.get("parse_ok")).lower() != "true"]
    if parse_bad:
        print(f"         NOTE: {len(parse_bad)} candidate(s) did not parse "
              f"cleanly: {parse_bad[:6]}")
        print("         Their verdicts are recorded as INVALID, not FAIL.")

    print("\nCHECK 5 -- harness errors are distinguishable from genuine FAILs")
    inconsistent = [r for r in props
                    if (r["status"] == "ERROR") != (r["verdict"] in ("", "None"))]
    check("verdict is empty if and only if status == ERROR", not inconsistent,
          f"{len(inconsistent)} inconsistent row(s): "
          f"{[(r['candidate_id'], r['property_id'], r['status'], r['verdict']) for r in inconsistent[:4]]}")
    err_no_msg = [r for r in props if r["status"] == "ERROR" and not r["error"]]
    check("every ERROR row carries an error message", not err_no_msg,
          f"{len(err_no_msg)} silent error(s)")
    bad_gate = [r for r in summary
                if r["run_status"] == "ERROR"
                and r["batfish_spec_verdict"] != "ERROR"]
    check("run_status ERROR implies batfish_spec_verdict ERROR", not bad_gate,
          f"{[r['candidate_id'] for r in bad_gate][:5]}")
    verdicts = Counter(r["batfish_spec_verdict"] for r in summary)
    print(f"         batfish_spec_verdict distribution: {dict(verdicts)}")

    print("\nCHECK 6 -- gate arithmetic is self-consistent")
    bad_math = []
    for r in summary:
        if r["batfish_spec_verdict"] == "PASS" and int(r["spec_fail"] or 0) != 0:
            bad_math.append(r["candidate_id"])
        if r["batfish_spec_verdict"] == "FAIL" and int(r["spec_fail"] or 0) == 0:
            bad_math.append(r["candidate_id"])
    check("spec_verdict PASS iff spec_fail == 0", not bad_math,
          f"{bad_math[:5]}")

    print("\nCHECK 7 -- raw evidence preserved on disk")
    missing_raw = []
    for cid in got:
        d = p2 / "raw" / cid
        for f in ("record.json", "properties.json", "differential.json"):
            if not (d / f).exists():
                missing_raw.append(f"{cid}/{f}")
        n_q = len(list((d / "questions").glob("*.json"))) \
            if (d / "questions").is_dir() else 0
        if n_q != len(QNAMES):
            missing_raw.append(f"{cid}/questions ({n_q}/{len(QNAMES)})")
    check("every candidate has record + properties + differential + all "
          "question dumps", not missing_raw,
          f"{len(missing_raw)} missing: {missing_raw[:5]}")

    traced = 0
    for cid in got[:5]:
        pj = json.loads((p2 / "raw" / cid / "properties.json").read_text())
        traced += sum(len(p.get("evidence", {}).get("traces", [])) for p in pj)
    check("hop-by-hop traces are present in the evidence (sampled)",
          traced > 0, "no traces found in the first 5 candidates")

    print("\nCHECK 8 -- no Phase 4 creep")
    banned_cols = {"label", "target", "y", "harm", "risk_score", "is_harmful"}
    leaked = banned_cols & {c.lower() for c in (summary[0].keys() if summary else [])}
    check("no label / target / risk column in the Phase 2 dataset", not leaked,
          f"found: {leaked}")

    print("\nCHECK 9 -- provenance columns are marked, not hidden")
    prov = [c for c in (summary[0].keys() if summary else []) if "prov_" in c]
    check("provenance columns carry the _BANNED suffix",
          all(c.endswith("_BANNED") for c in prov), f"unmarked: {prov}")
    print(f"         banned-from-X columns: "
          f"{[c for c in (summary[0].keys() if summary else []) if c.endswith('_BANNED')]}")

    print("\nCHECK 10 -- run metadata is complete")
    for k in ("pybatfish_version", "spike_verdict", "candidates_processed",
              "spec_property_ids", "run_utc"):
        check(f"run_metadata.{k} present", meta.get(k) not in (None, ""))
    lockp = root / "pilot.lock.json"
    if lockp.exists():
        _lk = json.loads(lockp.read_text())
        cur = _lk.get("snapshot_digest") or _lk.get("artifact_digest")
        check("dataset was collected from the snapshots currently on disk",
              (not cur) or (meta.get("snapshot_digest")
                            or meta.get("artifact_digest")) == cur,
              f"dataset={str(meta.get('snapshot_digest'))[:16]} "
              f"disk={str(cur)[:16]} -- rebuild happened after collection")
    check("spike verdict recorded as GO (or override is recorded)",
          spike.get("verdict") == "GO" or meta.get("spike_overridden") is True,
          f"spike={spike.get('verdict')} override={meta.get('spike_overridden')}")

    print(f"\n{'=' * 70}")
    print(f"{PASSED} passed, {len(FAIL)} failed")
    for l, d in FAIL:
        print(f"  FAILED: {l}\n          {d}")
    print(f"{'=' * 70}")
    if not FAIL:
        n_pass = verdicts.get("PASS", 0)
        print(f"""
Phase 2 dataset is complete and consistent.

  candidates passing the SPEC gate in Batfish: {n_pass} of {len(summary)}

That number is the DENOMINATOR for the false-pass rate. Phase 3 measures how
many of those {n_pass} are actually harmful. If it is very small the pilot
cannot estimate anything and the spec or the fault set needs widening BEFORE
scaling up -- that judgement belongs at the end of Phase 3, not here.
""")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
