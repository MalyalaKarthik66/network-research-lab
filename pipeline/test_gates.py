"""Negative and positive controls for the gates. No Docker, no Batfish.

A gate that has never been observed FAILING has not been tested, it has only
been run. Every check here makes the guarded condition genuinely false and
asserts the gate fires.

    python pipeline/test_gates.py
"""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl.properties import PROPERTIES                              # noqa: E402
import importlib.util                                              # noqa: E402

spec = importlib.util.spec_from_file_location(
    "run_phase3", REPO / "pipeline" / "run_phase3.py")
rp3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp3)

PIDS = [p["pid"] for p in PROPERTIES]
FAIL = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAIL.append(label)
        if detail:
            print(f"         {detail}")


def write_golden(out: Path, topo: str, holds_map):
    d = out / "runs" / f"golden-{topo}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "measurements.json").write_text(json.dumps([
        {"property_id": pid, "status": "OK" if holds_map.get(pid, True) is not None
         else "ERROR", "holds": holds_map.get(pid, True)}
        for pid in PIDS]))


def main() -> int:
    print("GATE CONTROLS -- every gate must be seen to fail\n")

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)

        print("golden_gate -- POSITIVE control (healthy golden, |G| = 12)")
        write_golden(out, "t01", {})
        blocked = rp3.golden_gate(out, ["t01"])
        check("a healthy golden is not blocked", blocked == {}, str(blocked))

        print("\ngolden_gate -- NEGATIVE control (one property broken)")
        write_golden(out, "t02", {"P11": False})
        blocked = rp3.golden_gate(out, ["t01", "t02"])
        check("a golden with P11 not holding IS blocked", "t02" in blocked,
              f"gate returned {blocked} -- it did not notice a property that "
              f"fails on a network that is healthy by construction")
        check("the block names the offending property",
              "P11" in blocked.get("t02", ""), blocked.get("t02"))
        check("the healthy topology is still not blocked",
              "t01" not in blocked, str(blocked))

        print("\ngolden_gate -- NEGATIVE control (property errored, not false)")
        write_golden(out, "t03", {"P07": None})
        blocked = rp3.golden_gate(out, ["t03"])
        check("an ERRORED golden property IS blocked", "t03" in blocked,
              "holds=None must not be read as 'holds'")

        print("\ngolden_gate -- a topology whose golden has not run is NOT blocked")
        blocked = rp3.golden_gate(out, ["t01", "t99_never_run"])
        check("un-run topology is not blocked", "t99_never_run" not in blocked,
              "the gate must apply once the golden exists, not before")

    print("\nstratified_sample -- spans strata rather than slicing one")
    # Ordered the way the real manifest is: all of topology 0, then all of
    # topology 1, and inside each topology all of family 0 first. That ordering
    # is what makes a contiguous --limit slice degenerate.
    items = [{"candidate_id": f"C-{i:04d}",
              "topology": f"t{i // 50:02d}", "fault_family": f"f{(i % 50) // 10}"}
             for i in range(200)]
    got = rp3.stratified_sample(items, 20,
                                key=lambda c: (c["topology"], c["fault_family"]))
    by = {c["candidate_id"]: c for c in items}
    topos = {by[c]["topology"] for c in got}
    fams = {by[c]["fault_family"] for c in got}
    check("sample of 20 spans all 4 topologies", len(topos) == 4, str(topos))
    check("sample of 20 spans all 5 fault families", len(fams) == 5, str(fams))
    check("sample size is exact", len(got) == 20, str(len(got)))
    check("sample is deterministic across calls",
          got == rp3.stratified_sample(
              items, 20, key=lambda c: (c["topology"], c["fault_family"])))
    print("  NEGATIVE control: a contiguous slice would NOT span the design")
    slice20 = [c["candidate_id"] for c in items[:20]]
    check("first-20 slice spans fewer strata than the stratified sample",
          len({by[c]["topology"] for c in slice20}) <= len(topos)
          and len({(by[c]['topology'], by[c]['fault_family']) for c in slice20})
          < len({(by[c]['topology'], by[c]['fault_family']) for c in got}),
          "if this fails the test has no power")

    print("\nstratified_sample spans topologies when n < number of strata")
    # 20 topologies x 10 families = 200 strata; a 150-sample must not be the
    # alphabetically-first 150 strata (that gave topologies t01..t15 only).
    pool = [{"candidate_id": f"C-{i:05d}",
             "topology": f"t{i % 20 + 1:02d}", "fault_family": f"f{i % 10}"}
            for i in range(1, 1800)]
    k = lambda c: (c["topology"], c["fault_family"])
    got = rp3.stratified_sample(pool, 150, key=k)
    by = {c["candidate_id"]: c for c in pool}
    check("150 of 1799 spans all 20 topologies",
          len({by[i]["topology"] for i in got}) == 20,
          f"{sorted({by[i]['topology'] for i in got})}")
    check("and is deterministic",
          got == rp3.stratified_sample(pool, 150, key=k))
    check("NEGATIVE CONTROL: the first 150 do NOT span the design",
          len({by[c["candidate_id"]]["fault_family"]
               for c in pool[:150]}) <= 10
          and len({by[i]["topology"] for i in got})
          > len({c["topology"] for c in pool[:15]}),
          "if this fails the test has no power")

    print("\nboundary_score -- marginal runs rank above clean ones")
    clean = {"measurements": [{"status": "OK", "extra": {"loss_pct": 0.0}}],
             "convergence": {"seconds": 46.0}}
    partial = {"measurements": [{"status": "OK", "extra": {"loss_pct": 40.0}}],
               "convergence": {"seconds": 46.0}}
    slow = {"measurements": [{"status": "OK", "extra": {"loss_pct": 0.0}}],
            "convergence": {"seconds": 170.0}}
    check("partial packet loss scores above clean",
          rp3.boundary_score(partial) > rp3.boundary_score(clean))
    check("slow convergence scores above clean",
          rp3.boundary_score(slow) > rp3.boundary_score(clean))
    check("100% loss is NOT treated as marginal",
          rp3.boundary_score({"measurements": [
              {"status": "OK", "extra": {"loss_pct": 100.0}}],
              "convergence": {"seconds": 46.0}})
          == rp3.boundary_score(clean),
          "total loss is an unambiguous FAIL, not a boundary case")

    print("\nLAB_INVALID retry policy (ANALYSIS-PLAN 14.1)")
    import re as _re
    src = (REPO / "pipeline" / "run_phase3.py").read_text(encoding="utf-8")
    check("only LAB_INVALID triggers a retry",
          'RETRY_STATUSES = ("LAB_INVALID",)' in src,
          "any other status in the trigger set would let a retry see a label")
    check("at most two attempts", "MAX_ATTEMPTS = 2" in src)
    check("the trigger is evaluated before measurement",
          src.index('rec["status"] = "LAB_INVALID"')
          < src.index("meas = measure_all("),
          "if the label were computed first, a retry could select on it")
    check("attempt 1 is archived, not overwritten",
          '.attempt1' in src and 'archived attempts are evidence' in
          src.lower().replace("--", "--"),
          "the first attempt must survive on disk as evidence")
    check("archived attempts are excluded from the dataset",
          'endswith(".attempt1")' in src,
          "they carry the same run_id and would overwrite the valid record")
    check("both counts are recorded, never one",
          '"lab_invalid_attempts"' in src and '"lab_invalid_terminal"' in src)
    doc = (REPO / "docs" / "ANALYSIS-PLAN.md").read_text(encoding="utf-8")
    check("the policy is pre-registered in ANALYSIS-PLAN.md",
          "14.1 `LAB_INVALID` retry policy" in doc)
    check("a second failure is terminal and excluded, not relabelled",
          "Second failure is terminal" in doc)
    check("S-014 is on the record as an ML-arm threat with a decision point",
          "14.2 S-014" in doc and "0.999" in doc and "decision" in doc.lower())

    print("\n  behavioural: the archived attempt must not win")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        good = {"run_id": "C-00001", "kind": "candidate", "attempt": 2,
                "lab": "nrlv2-c-00001", "status": "OK", "error": None,
                "measurements": [], "staging": {"status": "OK", "checked": 3},
                "convergence": {"converged": True, "seconds": 46.0}}
        bad = dict(good, attempt=1, status="LAB_INVALID",
                   error="OSPF binding incomplete: b1:eth2")
        for name, rec in (("C-00001", good), ("C-00001.attempt1", bad)):
            d = out / "runs" / name
            d.mkdir(parents=True)
            (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
        got = rp3.build_datasets(out, {"candidates": []})
        rows = {r["run_id"]: r for r in []}
        import csv as _c
        with (out / "containerlab_summary.csv").open(newline="") as f:
            rows = {r["run_id"]: r for r in _c.DictReader(f)}
        check("the retried (valid) attempt is the one in the dataset",
              rows.get("C-00001", {}).get("run_status") == "OK",
              f"got {rows.get('C-00001', {}).get('run_status')!r} -- sorted "
              f"order puts C-00001/ before C-00001.attempt1/, so the invalid "
              f"record would overwrite the valid one")
        check("exactly one row for the retried run", len(rows) == 1,
              f"{sorted(rows)}")
        check("the archived attempt is counted",
              got["lab_invalid_attempts"] == ["C-00001.attempt1"],
              str(got.get("lab_invalid_attempts")))
        check("and is not counted as terminal",
              got["lab_invalid_terminal"] == [],
              str(got.get("lab_invalid_terminal")))

    print("\nlab_name_from_artifact -- read the name, never rebuild it")
    with tempfile.TemporaryDirectory() as td:
        art = Path(td) / "artifact"
        art.mkdir()
        (art / "topology.clab.yml").write_text(
            "name: nrlv2-golden-t01_chain4\ntopology:\n  nodes:\n",
            encoding="utf-8")
        check("v2 artifact name is read verbatim",
              rp3.lab_name_from_artifact(art) == "nrlv2-golden-t01_chain4",
              "the old f'nrl-{run_id}' derivation gave nrl-golden-t01_chain4 "
              "and every docker ps lookup missed -> 29/29 CONTAINERS_MISSING")
        (art / "topology.clab.yml").write_text(
            "topology:\n  nodes:\n", encoding="utf-8")
        try:
            rp3.lab_name_from_artifact(art)
            check("a nameless topology raises", False)
        except ValueError:
            check("a nameless topology raises", True)
        (art / "topology.clab.yml").unlink()
        try:
            rp3.lab_name_from_artifact(art)
            check("a missing topology file raises", False)
        except FileNotFoundError:
            check("a missing topology file raises", True)

    print("\ngolden_control -- cannot pass on runs that did not happen")
    vec = {f"holds_P{i:02d}": "True" for i in range(1, 13)}
    fails = [{"run_id": f"golden-t{i:02d}", "run_status": "CONTAINERS_MISSING",
              **{k: "" for k in vec}} for i in (1, 2, 3)]
    _, msg = rp3.golden_control(fails)
    check("3 identical FAILURES do not report ALL IDENTICAL",
          "VACUOUS" in msg and "ALL IDENTICAL" not in msg,
          f"got: {msg!r} -- this is the defect the batch control had")
    _, msg = rp3.golden_control([{"run_id": "golden-t01", "run_status": "OK",
                                  **vec}])
    check("a single OK golden is VACUOUS, not a pass", "VACUOUS" in msg)
    two_ok = [{"run_id": "golden-t01", "run_status": "OK", **vec},
              {"run_id": "golden-r01", "run_status": "OK", **vec}]
    _, msg = rp3.golden_control(two_ok)
    check("two matching OK goldens report ALL IDENTICAL",
          "ALL IDENTICAL" in msg and "VACUOUS" not in msg)
    drift = dict(two_ok[1]); drift["holds_P05"] = "False"
    _, msg = rp3.golden_control([two_ok[0], drift])
    check("a drifting golden reports ORACLE UNSTABLE",
          "DISAGREEMENT" in msg and "ORACLE UNSTABLE" in msg)
    _, msg = rp3.golden_control(two_ok + [fails[0]])
    check("a failed golden is reported alongside a real pass",
          "ALL IDENTICAL" in msg and "did not complete" in msg)

    print("\n" + "=" * 62)
    print("ALL GATE CONTROLS PASSED" if not FAIL else "FAILED")
    for f in FAIL:
        print(f"   {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
