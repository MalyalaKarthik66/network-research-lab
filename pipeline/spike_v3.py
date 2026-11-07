"""The v3 Batfish gate: the real spike, plus a documented substitution.

    ./.venv-wsl/bin/python pipeline/spike_v3.py --pilot data/pilot-v3

WHY THIS EXISTS

spike_frr_batfish.py is the gate run_phase2.py obeys, and two of its checks are
written against fault snapshots:

    CHECK 5  is the static_route_loop fault family observable to Batfish
    CHECK 6  do static routes reach the RIB, read off a static_blackhole fault

v3 has no faults. Every candidate is golden plus one intervention, so no
incident snapshot carries either construct and both checks skip. A skipped
check is recorded FAILED by the spike, correctly -- a check that did not run
has not passed -- so the verdict is STOP and Phase 2 is blocked.

WHAT THIS DOES, AND WHAT IT REFUSES TO DO

It does NOT reimplement checks 1-4. It invokes the real spike as a subprocess
and reads its verdict file, so parse status, init issues, construct coverage and
OSPF adjacency verification are the frozen logic, byte for byte. A gate that
reimplements the thing it verifies is a gate that can lie, and this whole arm
already has one instance of exactly that: a consistency check that rebuilt the
build-scope filter instead of importing it and reported a file-count mismatch
that did not exist.

It then substitutes ONE check and declares ONE not applicable:

    CHECK 6 statics          SUBSTITUTED. The check asks whether Batfish
                             installs a static route into the RIB. v3 does
                             contain statics -- 72 of 151 candidates are
                             blackholes -- they are simply in candidate
                             snapshots rather than fault snapshots. Verified
                             directly on candidates by
                             analysis/v3_batfish_precheck.py: the route is
                             present, its next hop is `discard`, and `static`
                             is the only protocol listed for the prefix, so it
                             beat OSPF on administrative distance and is
                             installed. Same question, better evidence: read
                             off the snapshots the corpus will actually use.

    CHECK 5 f10_observable   NOT APPLICABLE. It asks whether Batfish can see a
                             fault family. v3 has no fault families. There is
                             no substitute evidence because there is nothing to
                             substitute for, and marking an inapplicable check
                             as passed would be as wrong as marking it failed.
                             It is recorded N/A with this reasoning and excluded
                             from the verdict.

Everything else must pass unchanged. If any check other than those two fails,
the verdict is STOP.

Pre-registered in docs/ANALYSIS-PLAN-V3.md 12.2.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: excluded from the verdict, each with a stated reason. Nothing else may be.
NOT_APPLICABLE = {
    "f10_observable":
        "v3 has no fault families, so there is no fault for Batfish to observe. "
        "No substitute evidence exists because there is nothing to substitute "
        "for. Excluded from the verdict rather than scored either way.",
}
SUBSTITUTED = {
    "statics":
        "v3 statics live in candidate snapshots, not fault snapshots. Verified "
        "directly on candidates by analysis/v3_batfish_precheck.py: route "
        "present, next hop `discard`, and `static` the only protocol for the "
        "prefix, so it beat OSPF on administrative distance and is installed.",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", default="data/pilot-v3")
    ap.add_argument("--per-topology", type=int, default=3)
    ap.add_argument("--precheck-n", type=int, default=8)
    a = ap.parse_args()
    root = (REPO / a.pilot).resolve()
    out = root / "phase2"
    out.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    print("=" * 74)
    print("STEP 1 -- the real spike, unmodified")
    print("=" * 74)
    r = subprocess.run([py, str(REPO / "pipeline" / "spike_frr_batfish.py"),
                        "--pilot", a.pilot,
                        "--per-topology", str(a.per_topology)],
                       cwd=str(REPO), capture_output=True, text=True)
    tail = (r.stdout or "").rstrip().split("\n")[-22:]
    print("\n".join(tail))
    # The spike exits non-zero on a STOP verdict, and STOP is the EXPECTED
    # outcome here: two fault-dependent checks cannot pass on a corpus with no
    # faults. Completion is therefore judged by whether it produced a verdict
    # with checks in it, not by the exit code. A genuine early failure --
    # preflight, no Batfish reachable -- writes no verdict file and is still
    # blocked below.
    sp = out / "spike_result.json"
    if not sp.exists():
        print(f"\nBLOCKED: the spike wrote no verdict file (exit {r.returncode}).")
        print((r.stderr or "")[-1500:])
        return 2
    spike = json.loads(sp.read_text())
    checks = dict(spike.get("checks", {}))
    if not checks:
        print(f"\nBLOCKED: the spike recorded no checks (exit {r.returncode}).")
        return 2
    print(f"\n  spike exit {r.returncode}, verdict {spike.get('verdict')}, "
          f"{len(checks)} checks recorded")

    print("\n" + "=" * 74)
    print("STEP 2 -- substitute evidence for the fault-dependent checks")
    print("=" * 74)
    pre = subprocess.run([py, str(REPO / "analysis" / "v3_batfish_precheck.py"),
                          "--pilot", a.pilot, "--n", str(a.precheck_n)],
                         cwd=str(REPO), capture_output=True, text=True)
    print((pre.stdout or "").rstrip().split("\n")[-6:][0] if pre.stdout else "")
    pj = REPO / "analysis" / "v3_batfish_precheck.json"
    precheck = json.loads(pj.read_text()) if pj.exists() else {}
    sub_ok = precheck.get("verdict") == "MODELLED"
    print(f"  blackhole construct: {precheck.get('n_ok')}/"
          f"{precheck.get('n_checked')} -> {precheck.get('verdict')}")

    print("\n" + "=" * 74)
    print("STEP 3 -- v3 verdict")
    print("=" * 74)
    decided, excluded = {}, {}
    for k, v in checks.items():
        if k in NOT_APPLICABLE:
            excluded[k] = {"status": "N/A", "reason": NOT_APPLICABLE[k]}
        elif k in SUBSTITUTED:
            decided[k] = bool(sub_ok)
            excluded[k] = {"status": "SUBSTITUTED", "passed": bool(sub_ok),
                           "reason": SUBSTITUTED[k],
                           "evidence": "analysis/v3_batfish_precheck.json"}
        else:
            decided[k] = bool(v)
    for k, v in sorted(decided.items()):
        note = "  (substituted)" if k in SUBSTITUTED else ""
        print(f"  {'PASS' if v else 'FAIL'}  {k}{note}")
    for k, v in sorted(excluded.items()):
        if v["status"] == "N/A":
            print(f"  N/A   {k}")
    go = bool(decided) and all(decided.values())

    lock = json.loads((root / "pilot.lock.json").read_text())
    payload = {
        "verdict": "GO" if go else "STOP",
        "gate": "spike_v3.py",
        "analysis_plan": "docs/ANALYSIS-PLAN-V3.md 12.2",
        "artifact_digest": lock.get("artifact_digest"),
        "snapshot_digest": lock.get("snapshot_digest"),
        "checks": decided,
        "checks_excluded_or_substituted": excluded,
        "underlying_spike": {
            "checks": checks, "notes": spike.get("notes", []),
            "coverage": spike.get("coverage", {}),
            "snapshots_checked": spike.get("snapshots_checked", []),
            "total_parse_warnings": spike.get("total_parse_warnings"),
            "pybatfish_version": spike.get("pybatfish_version"),
            "verdict_as_written": spike.get("verdict")},
        "substitute_evidence": precheck,
        "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "run_phase2.py reads this and refuses unless verdict == GO. "
                "The underlying spike's own verdict is preserved above; it is "
                "STOP whenever a fault-dependent check skipped, which is "
                "correct for that gate and is why this one exists.",
    }
    sp.write_text(json.dumps(payload, indent=2, default=str) + "\n",
                  newline="\n", encoding="utf-8")
    print(f"\n  underlying spike verdict : {spike.get('verdict')}")
    print(f"  v3 verdict               : {payload['verdict']}")
    print(f"  artifact digest          : {(lock.get('artifact_digest') or '')[:16]}")
    print(f"\nwritten to {sp}")
    return 0 if go else 1


if __name__ == "__main__":
    sys.exit(main())
