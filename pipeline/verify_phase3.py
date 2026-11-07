"""Quality checks on the Phase 3 dataset. Run straight after run_phase3.py.

    python pipeline/verify_phase3.py --pilot data/pilot-v2

Checks the DATASET, not the network: completeness, same-artifact usage,
reproducibility metadata, and whether execution failures are distinguishable
from genuine property violations.

DERIVATION OF THE EXPECTED RUN SET  (defect B1)
-----------------------------------------------
Every completeness check here used to be hardcoded to pilot-v1: `golden` plus
`I-01..I-10` plus exactly 50 candidates, and `len(manifest.candidates) * 12`
delta rows. Under pilot-v2 -- ten-plus topologies, per-topology goldens, and
`--only-passing` running a subset -- every one of those checks fails, and it
fails AFTER the 24 hours of Containerlab time it was supposed to protect.

The expected set is now recomputed independently, from
    the lock          -> one golden per topology
    the manifest      -> incidents and candidates
    run_metadata.json -> the run's own declared eligibility filter
    phase2 summary    -> which candidates passed the SPEC gate
It is NOT derived from what actually ran. Deriving the expectation from the
result is the "success measured by the thing being tested" pattern that this
project's defect log is made of: a run that executed nothing would define its
own expectation as nothing and report complete.

Batching is handled explicitly. Runs that exist must be complete and expected;
runs that have not happened yet are reported as REMAINING, not as failures.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl.properties import PROPERTIES                              # noqa: E402

PIDS = {p["pid"] for p in PROPERTIES}
ALLOWED_OUTCOMES = {"SAFE", "HARMFUL", "NO_CONVERGENCE", "UNDETERMINED",
                    "EXECUTION_FAILED"}
# Outcomes that are NOT a label. See docs/HARM-DEFINITION.md and nrl/phase4.py:
# they are excluded from y, never mapped to SAFE.
NON_LABEL_OUTCOMES = {"UNDETERMINED", "EXECUTION_FAILED"}
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


def tri(v):
    """CSV round-trips Python None as '' and booleans as 'True'/'False'."""
    return {"True": True, "False": False, "": None}.get(v, v)


def expected_run_set(root: Path, manifest: dict, lock: dict, meta: dict):
    """What this run SHOULD contain, recomputed from independent sources.

    Returns (goldens, incidents, candidates, replicates) as sorted lists.
    """
    topos = sorted(lock.get("topologies") or [])
    goldens = [f"golden-{t}" for t in topos] if topos else ["golden"]

    cands = [c["candidate_id"] for c in manifest["candidates"]]

    # the run's own declared filters, recomputed rather than trusted
    if meta.get("only_passing"):
        p2 = root / "phase2" / "batfish_summary.csv"
        if not p2.exists():
            raise SystemExit("BLOCKED: run_metadata says only_passing but "
                             "phase2/batfish_summary.csv is missing, so the "
                             "expected set cannot be recomputed.")
        keep = {r["candidate_id"] for r in load_csv(p2)
                if r["batfish_spec_verdict"] == "PASS"}
        cands = [c for c in cands if c in keep]
    if meta.get("fail_control_ids"):
        cands = sorted(set(cands) | set(meta["fail_control_ids"]))
    if meta.get("candidate_filter"):
        sel = set(meta["candidate_filter"])
        cands = [c for c in cands if c in sel]

    inc_of = {c["candidate_id"]: c["incident_id"] for c in manifest["candidates"]}
    incidents = sorted({inc_of[c] for c in cands if c in inc_of})

    replicates = sorted(meta.get("replicate_ids") or [])
    return sorted(goldens), incidents, sorted(cands), replicates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. There is deliberately "
                         "NO default: a default silently pointed every run at the old "
                         "pilot, whose ledger was already complete, so the run executed "
                         "nothing and reported ALL ITEMS COMPLETE.")
    args = ap.parse_args()
    root = resolve_pilot(args.pilot)
    p3 = root / "phase3"
    print(f"verifying {p3}\n")
    if not p3.exists():
        print("no phase3 directory -- run pipeline/run_phase3.py first")
        return 2

    print("CHECK 1 -- dataset files exist and load")
    need = ["containerlab_summary.csv", "containerlab_measurements.csv",
            "containerlab_deltas.csv", "containerlab_outcomes.csv",
            "run_metadata.json"]
    ok = True
    for n in need:
        ok &= check(f"{n} present", (p3 / n).exists())
    if not ok:
        print("\nmissing files -- stopping")
        return 1
    summary = load_csv(p3 / "containerlab_summary.csv")
    meas = load_csv(p3 / "containerlab_measurements.csv")
    deltas = load_csv(p3 / "containerlab_deltas.csv")
    outcomes = load_csv(p3 / "containerlab_outcomes.csv")
    meta = json.loads((p3 / "run_metadata.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    lock = json.loads((root / "pilot.lock.json").read_text())
    check("DATA-DICTIONARY.md present", (p3 / "DATA-DICTIONARY.md").exists())

    goldens, incidents, cands, replicates = expected_run_set(
        root, manifest, lock, meta)
    expected = goldens + incidents + cands + replicates
    ids = [r["run_id"] for r in summary]
    ran = set(ids)

    print("\nCHECK 2 -- completeness against the recomputed expected set")
    print(f"         expected: {len(goldens)} golden, {len(incidents)} incident, "
          f"{len(cands)} candidate, {len(replicates)} replicate "
          f"= {len(expected)}")
    print(f"         present : {len(ids)}")
    extra = sorted(ran - set(expected) - {i for i in ran
                                          if i.startswith("golden-r")})
    check("no run outside the expected set", not extra,
          f"unexpected run_ids: {extra[:6]} -- these were executed but the "
          f"manifest/lock/filter does not account for them")
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    check("no duplicate run_id", not dupes, str(dupes))
    remaining = sorted(set(expected) - ran)
    if remaining:
        print(f"         REMAINING: {len(remaining)} expected runs not yet "
              f"executed (batched run in progress) e.g. {remaining[:4]}")
    else:
        print("         all expected runs present")
    # Every golden must be present before any candidate of that topology
    # counts. Scoped to the topologies whose candidates actually ran: a
    # topology no candidate has reached yet has nothing to judge, and demanding
    # its golden made every partial/filtered collection FAIL by construction
    # -- the same defect as B1, an expectation that ignores the run's own
    # filter. The gate keeps its full force at final collection, where every
    # topology has candidates.
    topo_by_cand = {c["candidate_id"]: c.get("topology")
                    for c in manifest["candidates"]}
    live_topos = sorted({topo_by_cand.get(r["run_id"])
                         for r in summary if r["kind"] == "candidate"
                         and topo_by_cand.get(r["run_id"])})
    need = [f"golden-{t}" for t in live_topos]
    missing_goldens = [g for g in need if g not in ran]
    check("every topology with an executed candidate has its golden",
          not missing_goldens,
          f"{missing_goldens} -- harm is defined against the golden, so a "
          f"candidate without its golden has no definition to be judged by")
    not_yet = [g for g in goldens if g not in ran and g not in need]
    if not_yet:
        print(f"         {len(not_yet)} topologies have no executed candidate "
              f"yet, so their goldens are not required in THIS batch: "
              f"{not_yet[:4]}")

    print("\nCHECK 2b -- kind classification")
    kinds = Counter(r["kind"] for r in summary)
    print(f"         {dict(kinds)}")
    check("no run classified 'candidate' that is actually a golden",
          not [r for r in summary
               if r["run_id"].startswith("golden") and r["kind"] == "candidate"],
          "golden runs are being counted as candidates -- see the kind= "
          "assignment in run_phase3.run_one()")

    print("\nCHECK 3 -- every property measured for every run that happened")
    per = Counter(r["run_id"] for r in meas)
    bad = {i: per.get(i, 0) for i in ran if per.get(i, 0) != len(PIDS)}
    check(f"all {len(PIDS)} property rows for every executed run", not bad,
          f"wrong counts: {dict(list(bad.items())[:6])}")
    check("no unknown property_id",
          not {r["property_id"] for r in meas} - PIDS)
    check("measurement rows exist at all", len(meas) > 0,
          "zero measurement rows is not a clean run, it is an empty one")

    print("\nCHECK 4 -- execution failures are distinguishable from violations")
    inconsistent = [r for r in meas
                    if (r["status"] == "ERROR") != (tri(r["holds"]) is None)]
    check("holds is empty if and only if status == ERROR", not inconsistent,
          f"{len(inconsistent)} bad: "
          f"{[(r['run_id'], r['property_id'], r['status'], r['holds']) for r in inconsistent[:4]]}")
    silent = [r for r in meas if r["status"] == "ERROR" and not r["error"]]
    check("every ERROR measurement carries a message", not silent,
          f"{len(silent)} silent")
    statuses = Counter(r["run_status"] for r in summary)
    print(f"         run_status distribution: {dict(statuses)}")
    bad_out = [o for o in outcomes if o["outcome_harm_v1"] not in ALLOWED_OUTCOMES]
    check("every outcome is from the frozen vocabulary", not bad_out,
          f"unexpected: {[o['outcome_harm_v1'] for o in bad_out][:4]}")
    mis = [o for o in outcomes
           if o["run_status"] == "NO_CONVERGENCE"
           and o["outcome_harm_v1"] != "NO_CONVERGENCE"]
    check("NO_CONVERGENCE runs are not silently recorded as SAFE/HARMFUL",
          not mis, f"{[o['candidate_id'] for o in mis][:5]}")

    print("\nCHECK 4b -- the harm definition was not silently narrowed (B2)")
    # |G| must be the full oracle on every topology. If a property fails on a
    # healthy golden it drops out of G for every candidate of that topology,
    # no error is raised, and the false-pass rate falls.
    gsizes = {o["candidate_id"]: int(o["golden_properties_in_G"] or 0)
              for o in outcomes if o.get("golden_properties_in_G") not in (None, "")}
    narrowed = {c: n for c, n in gsizes.items() if n != len(PIDS)}
    check(f"|G| == {len(PIDS)} for every candidate", not narrowed,
          f"{len(narrowed)} candidates judged against a NARROWED harm "
          f"definition, e.g. {dict(list(narrowed.items())[:4])}. "
          f"docs/HARM-DEFINITION.md: 'expected to be all 12; if it is not, "
          f"the pilot is broken'.")

    print("\nCHECK 5 -- SAME-ARTIFACT usage at runtime")
    stage_bad = [r["run_id"] for r in summary if r["staging_status"] != "OK"]
    check("every run staged its artifact with verified hashes", not stage_bad,
          f"{stage_bad[:6]}")
    zero = [r["run_id"] for r in summary
            if not r["staging_files_verified"]
            or int(r["staging_files_verified"] or 0) == 0]
    check("every run verified a non-zero number of files", not zero,
          f"{zero[:6]}")
    cfg_bad = [r["run_id"] for r in summary
               if r["runtime_config_match"] not in ("OK", "")]
    check("the running FRR config matches the artifact for every run",
          not cfg_bad,
          f"{cfg_bad[:6]} -- the emulator ran something Batfish did not analyse")
    addr_bad = [r["run_id"] for r in summary
                if r["runtime_address_match"] not in ("OK", "")]
    check("container interface addresses match the artifact", not addr_bad,
          f"{addr_bad[:6]}")
    # S-020: config and addresses can both be correct on a lab where ospfd
    # never bound to an interface, and that lab produced a flipped label.
    have_binding = [r for r in summary if r.get("runtime_ospf_binding")]
    if not have_binding:
        print("  [NOT MEASURED] OSPF binding check -- this dataset was "
              "collected before S-020; the column does not exist, so the "
              "gate below would pass vacuously")
    ospf_bad = [r["run_id"] for r in summary
                if r.get("runtime_ospf_binding") not in ("OK", "", None)]
    labelled_bad = [r for r in ospf_bad
                    if r in {o["candidate_id"] for o in outcomes
                             if o["outcome_harm_v1"] in ("SAFE", "HARMFUL")}]
    check("no run was LABELLED on a lab with incomplete OSPF binding",
          not labelled_bad,
          f"{labelled_bad[:6]} -- the config and addresses are correct but "
          f"ospfd is not on some interface, so an adjacency that should exist "
          f"cannot form; such a lab has not been measured")
    if ospf_bad:
        print(f"         {len(ospf_bad)} run(s) invalidated by the binding "
              f"check (excluded from y, not labelled): {ospf_bad[:6]}")

    print("\nCHECK 6 -- convergence recorded, never assumed")
    noconv = [r["run_id"] for r in summary if tri(r["converged"]) is False]
    check("converged recorded for every run",
          all(r["converged"] not in (None, "") for r in summary))
    check("convergence_seconds recorded for every run",
          all(r["convergence_seconds"] not in (None, "") for r in summary))
    if noconv:
        rate = 100.0 * len(noconv) / max(1, len(summary))
        print(f"         NOTE: {len(noconv)} run(s) ({rate:.1f}%) did not "
              f"converge within the timeout: {noconv[:6]}")
        print("         Recorded as NO_CONVERGENCE. Per the frozen definition "
              "that is HARMFUL in the primary analysis, excluded in the "
              "sensitivity analysis.")
        check("NO_CONVERGENCE rate below the 5% stage gate", rate < 5.0,
              f"{rate:.1f}% -- see the stop rules in docs/FINAL-PLAN.md")

    print("\nCHECK 7 -- raw evidence preserved")
    missing = []
    for i in sorted(ran):
        d = p3 / "runs" / i
        for f in ("run.json", "measurements.json", "convergence.json",
                  "clab_deploy.json", "artifact_runtime_check.json"):
            if not (d / f).exists():
                missing.append(f"{i}/{f}")
        if not (d / "state").is_dir() or not list((d / "state").glob("*.json")):
            missing.append(f"{i}/state/")
    check("every executed run has run + measurements + convergence + deploy "
          "log + state", not missing, f"{len(missing)} missing: {missing[:5]}")
    probes = 0
    for i in sorted(ran)[:3]:
        mj = p3 / "runs" / i / "measurements.json"
        if mj.exists():
            for m in json.loads(mj.read_text()):
                ev = m.get("evidence", {})
                probes += sum(1 for k in ("ping", "tcp", "traceroute")
                              if k in ev)
    check("raw probe output preserved in the evidence (sampled)", probes > 0)

    print("\nCHECK 8 -- deltas and outcomes")
    cand_ran = sorted(c for c in cands if c in ran)
    check(f"{len(cand_ran) * len(PIDS)} delta rows for the "
          f"{len(cand_ran)} candidates that ran",
          len(deltas) == len(cand_ran) * len(PIDS),
          f"got {len(deltas)}, expected {len(cand_ran) * len(PIDS)}")
    check("one outcome row per executed candidate",
          len(outcomes) == len(cand_ran),
          f"got {len(outcomes)}, expected {len(cand_ran)}")
    ocount = Counter(o["outcome_harm_v1"] for o in outcomes)
    print(f"         outcome_harm_v1: {dict(ocount)}")
    nonlabel = sum(ocount.get(k, 0) for k in NON_LABEL_OUTCOMES)
    if outcomes:
        nl_rate = 100.0 * nonlabel / len(outcomes)
        print(f"         non-label outcomes (excluded from y): "
              f"{nonlabel} ({nl_rate:.1f}%)")
        check("non-label outcome rate below the 5% stage gate", nl_rate < 5.0,
              f"{nl_rate:.1f}% -- UNDETERMINED/EXECUTION_FAILED are excluded "
              f"from the dataset, so a high rate shrinks the usable sample "
              f"and widens the Manski bounds")
    bad_join = [d["candidate_id"] for d in deltas
                if d["candidate_id"] not in {c["candidate_id"]
                                             for c in manifest["candidates"]}]
    check("every delta row joins to a manifest candidate", not bad_join)

    print("\nCHECK 8b -- the replicate arm produced its measurement")
    ran_reps = sorted(r["run_id"] for r in summary
                      if r["kind"] == "candidate_replicate")
    rep_path = root / "phase3" / "containerlab_replicates.csv"
    if not ran_reps:
        print("         no replicate labs in this collection -- SKIP")
    else:
        rep_rows = load_csv(rep_path) if rep_path.exists() else []
        # The replicate labs used to run and produce nothing: both dataset
        # loops iterate the manifest, which has no `<base>~r1` entry. Emulator
        # time was spent, the batch reported COMPLETE, and the label-noise
        # floor was never computed.
        check("containerlab_replicates.csv exists", rep_path.exists(),
              f"{len(ran_reps)} replicate labs ran and produced no rows")
        check("one replicate row per executed replicate lab",
              len(rep_rows) == len(ran_reps),
              f"{len(rep_rows)} rows for {len(ran_reps)} labs")
        if rep_rows:
            ag = [r for r in rep_rows if tri(r["outcome_agrees"]) is True]
            flips = [r for r in rep_rows if tri(r["outcome_agrees"]) is not True]
            rate = len(flips) / len(rep_rows)
            print(f"         outcome agreement: {len(ag)}/{len(rep_rows)} "
                  f"({rate:.0%} flipped)")
            for r in flips:
                print(f"         FLIP {r['candidate_id']}: "
                      f"{r['base_outcome']} -> {r['replicate_outcome']} on "
                      f"{r['differing_properties']} "
                      f"(adj {r['base_adjacency_pairs']} -> "
                      f"{r['replicate_adjacency_pairs']})")
            # Not a gate: the flip rate is a RESULT, and a floor on any
            # model's achievable accuracy. It is reported, not enforced.
            if rate > 0:
                print(f"         NOTE: label noise is {rate:.0%} on "
                      f"{len(rep_rows)} replicates -- no model can beat this "
                      f"floor, and Phase 4 must report it alongside its AUC")

    print("\nCHECK 9 -- no Phase 4 creep")
    labelled = [o["candidate_id"] for o in outcomes if o["label"] not in ("", None)]
    check("no final label assigned in Phase 3", not labelled,
          f"{labelled[:5]}")
    banned = {"risk_score", "prediction", "y_pred", "feature"}
    cols = {c.lower() for c in (summary[0].keys() if summary else [])}
    check("no model or risk column in the dataset", not (banned & cols))

    print("\nCHECK 10 -- reproducibility metadata")
    check("dataset was collected from the artifact currently on disk",
          meta.get("artifact_digest") == lock.get("artifact_digest"),
          f"phase3={str(meta.get('artifact_digest'))[:16]} "
          f"disk={str(lock.get('artifact_digest'))[:16]}")
    for k in ("harm_definition_version", "suite_version",
              "convergence_timeout_s", "ping_count", "platform"):
        check(f"run_metadata.{k} present", meta.get(k) not in (None, ""))

    print("\nCHECK 11 -- no leaked labs left running")
    if shutil.which("docker"):
        try:
            p = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=60)
            # "clab-nrl-" missed every v2 lab: those are clab-nrlv2-*.
            leaked = [n for n in p.stdout.split() if n.startswith("clab-nrl")]
            check("no clab-nrl* containers still running", not leaked,
                  f"{leaked[:6]} -- run: containerlab destroy --all --cleanup")
        except Exception as exc:                                   # noqa: BLE001
            print(f"  [SKIP] docker unreachable ({exc})")
    else:
        print("  [SKIP] docker not on PATH (verifying off-box)")

    print(f"\n{'=' * 70}")
    print(f"{PASSED} passed, {len(FAIL)} failed")
    for l, d in FAIL:
        print(f"  FAILED: {l}\n          {d}")
    if remaining:
        print(f"  {len(remaining)} expected runs still pending "
              f"(batched collection in progress)")
    print(f"{'=' * 70}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
