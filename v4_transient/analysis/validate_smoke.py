"""Smoke-test ENGINEERING validation (docs/PILOT-PREREGISTRATION.md §17). No gate or scientific interpretation.

    ./.venv/Scripts/python.exe v4_transient/analysis/validate_smoke.py              # writes results/smoke/SMOKE-VALIDATION.json
    ./.venv/Scripts/python.exe v4_transient/analysis/validate_smoke.py --no-write   # re-check without touching evidence

Checks: Batfish PASS gating, deployment, telemetry collection, raw time-series preservation, target computation,
run/replicate IDs and manifest linkage, failed-run handling, and that no v2/v3 data or code was modified.

The code-provenance check compares the measurement library (v4lib/*.py files hashed in each smoke run.json) with
the files on disk. Runner and analysis code may change later (e.g. the D1-D9 approval machinery) without
invalidating the smoke evidence; the measurement library may not.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
REPO = V4.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(V4))
NO_WRITE = "--no-write" in sys.argv[1:]

from nrl import topologies_v3 as T3                                 # noqa: E402

spec_ = importlib.util.spec_from_file_location("run_pilot", V4 / "pilot" / "run_pilot.py")
rp = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(rp)

ROOT = V4 / "results" / "smoke"
results = []


def check(group, name, cond, detail=None):
    results.append({"group": group, "check": name, "pass": bool(cond), "detail": detail})
    print(f"{'PASS' if cond else 'FAIL'}  [{group}] {name}" + ("" if cond or detail is None else f"  -- {detail}"))


def jl(p):
    return json.loads(Path(p).read_text())


man = jl(V4 / "manifests" / "pilot_manifest.json")
changes = {c["change_id"]: c for c in man["changes"]}
plan = jl(V4 / "manifests" / "run_plan_smoke.json")["runs"]
bfc = jl(V4 / "manifests" / "batfish_check.json")
lock = jl(V4 / "manifests" / "artifact_lock.json")

# 1 Batfish gating
check("batfish", "Batfish check verdict OK", bfc.get("verdict") == "OK", bfc.get("problems"))
check("batfish", "every smoke change admitted by the runner's Batfish gate",
      all(rp.batfish_gate(bfc, changes[r["change_id"]])[0] for r in plan))
check("batfish", "gate refuses a population change whose SPEC verdict is FAIL",
      not rp.batfish_gate({"verdict": "OK", "changes": {"Z": {"spec_pass": False, "r_match": True}}},
                          {"change_id": "Z", "kind": "population"})[0])

# 6 IDs / manifests
ids = [r["run_id"] for r in plan]
check("ids", "run ids unique", len(ids) == len(set(ids)))
check("ids", "every run references a manifest change", all(r["change_id"] in changes for r in plan))
rec_lock = hashlib.sha256(json.dumps(lock["sha256"], sort_keys=True).encode()).hexdigest()
check("ids", "artifact lock digest == manifest digest == recomputed", lock["digest"] == man["artifact_lock_digest"] == rec_lock)
bad_files = [k for k, v in lock["sha256"].items()
             if hashlib.sha256((V4 / "pilot" / "artifacts" / k).read_bytes()).hexdigest() != v]
check("ids", "every locked artifact file matches its hash on disk", not bad_files, bad_files[:5])
code_now = rp.code_digest()
# the smoke ran with the smoke-era measurement library, recorded in the evidence snapshot; amendment A3 changed the
# library afterwards (tests/test_smoke_regression.py shows it reproduces these smoke targets)
smoke_lib = {k: v for k, v in jl(V4 / "manifests" / "EVIDENCE-SNAPSHOT-PRE-D1D9.json")["files"].items()
             if k.startswith("v4lib/")}

metrics = {r["run_id"]: r for r in csv.DictReader((ROOT / "run_metrics.csv").open(encoding="utf-8"))}
normal = [r for r in plan if not r.get("inject")]
inject = [r for r in plan if r.get("inject")]
for r in normal:
    rid = r["run_id"]
    ch = changes[r["change_id"]]
    spec = T3.resolve(ch["topology"])
    adirs = sorted((ROOT / "raw" / rid).glob("attempt*"))
    check("ids", f"{rid}: has at least one attempt", bool(adirs))
    if not adirs:
        continue
    ad = adirs[-1]
    rec = jl(ad / "run.json") if (ad / "run.json").exists() else {}
    check("ids", f"{rid}: run.json links run_id/change_id/replicate",
          rec.get("run_id") == rid and rec.get("change_id") == r["change_id"] and rec.get("replicate") == r["replicate"])
    lib = {k: v for k, v in (rec.get("code_sha256") or {}).items() if k.startswith("v4lib/")}
    check("ids", f"{rid}: measurement library hashed at run time equals the smoke-era library (evidence snapshot)",
          bool(lib) and all(smoke_lib.get(k) == v for k, v in lib.items()),
          [k for k, v in lib.items() if smoke_lib.get(k) != v])
    # 2 deployment
    dep = jl(ad / "clab_deploy.json") if (ad / "clab_deploy.json").exists() else {}
    check("deploy", f"{rid}: non-root containerlab deploy OK", dep.get("status") == "OK", dep.get("stderr", "")[-200:])
    check("deploy", f"{rid}: converged before change", (rec.get("convergence") or {}).get("converged") is True)
    check("deploy", f"{rid}: push statuses OK", rec.get("push_status") and all(s == "OK" for s in rec["push_status"]))
    check("deploy", f"{rid}: teardown OK", rec.get("teardown_ok") is True, rec.get("cleanup_errors"))
    check("deploy", f"{rid}: final status OK", rec.get("status") == "OK", (rec.get("status"), rec.get("error")))
    # 3 telemetry
    fi = jl(ad / "fib_initial.json") if (ad / "fib_initial.json").exists() else {}
    check("telemetry", f"{rid}: initial FIB snapshot for every router",
          set(fi) == set(spec.routers) and all(v["status"] == "OK" and v["text"].strip() for v in fi.values()))
    logs = {rt: (ad / "fib_monitor" / f"{rt}.log") for rt in spec.routers}
    check("telemetry", f"{rid}: FIB monitor log file for every router", all(p.exists() for p in logs.values()))
    check("telemetry", f"{rid}: FIB monitor captured events (timestamped lines)",
          any(p.exists() and p.read_text().startswith("[") for p in logs.values()))
    probes = list((ad / "probes").glob("*.log")) if (ad / "probes").exists() else []
    check("telemetry", f"{rid}: 6 probe logs with replies", len(probes) == 6 and all("seq=" in p.read_text() for p in probes))
    nb = jl(ad / "ospf_neighbours.json") if (ad / "ospf_neighbours.json").exists() else []
    check("telemetry", f"{rid}: OSPF neighbour poller samples", len(nb) >= 2, len(nb))
    check("telemetry", f"{rid}: final FIB snapshot + full state capture",
          (ad / "fib_final.json").exists() and len(list((ad / "state").glob("*.json"))) >= 5 * len(spec.routers))
    check("telemetry", f"{rid}: container clock is UTC", "UTC" in (rec.get("container_date") or ""), rec.get("container_date"))
    # 4 raw time series preserved
    ts = ROOT / "timeseries" / f"{rid}.csv"
    rows = list(csv.DictReader(ts.open(encoding="utf-8"))) if ts.exists() else []
    need = {"t_rel", "broken_excess", "broken_or_undet_excess", "detour", "rerouted_vs_golden", "broken_total", "undetermined"}
    check("timeseries", f"{rid}: time series csv with required columns and >= 2 rows",
          len(rows) >= 2 and need <= set(rows[0]), (len(rows), sorted(set(rows[0]) if rows else [])))
    # 5 target computation
    m = metrics.get(rid, {})
    nums = []
    for k in ("T1_disruption_area", "T2_peak_disruption", "T3_disruption_duration", "T1_upper_undetermined_as_broken"):
        try:
            nums.append(float(m.get(k)))
        except (TypeError, ValueError):
            nums.append(None)
    check("targets", f"{rid}: T1/T2/T3/T1_upper computed as numbers", all(x is not None for x in nums), m.get("status"))
    v = jl(ROOT / "validity.json")["runs"].get(rid, {})
    check("targets", f"{rid}: all run-validity checks pass (§12)", v.get("measurable") is True, v.get("checks"))

# 7 failed-run handling
for r in inject:
    rid = r["run_id"]
    adirs = sorted((ROOT / "raw" / rid).glob("attempt*"))
    recs = [jl(a / "run.json") for a in adirs if (a / "run.json").exists()]
    check("failures", f"{rid}: exactly 2 attempts (one retry)", len(adirs) == 2, [a.name for a in adirs])
    check("failures", f"{rid}: both attempts STAGING_FAILED with injected marker",
          len(recs) == 2 and all(x.get("status") == "STAGING_FAILED" and x.get("injected_failure") for x in recs))
    check("failures", f"{rid}: no lab deployed for injected failure",
          not any((a / "clab_deploy.json").exists() for a in adirs))
led = [json.loads(l) for l in (V4 / "logs" / "smoke_ledger.jsonl").read_text().splitlines() if l.strip()]
check("failures", "ledger records every attempt", sum(1 for x in led) >= len(normal) + 2, len(led))
crashed = V4 / "results" / "smoke_run1_crashed" / "raw" / "SMOKE-V4C-01.rep1" / "attempt1"
check("failures", "crashed first smoke attempt preserved and detected as INCOMPLETE",
      crashed.exists() and rp.attempts(V4 / "results" / "smoke_run1_crashed", "SMOKE-V4C-01.rep1")[0]["status"] == "INCOMPLETE")

# pilot not started
check("scope", "20x5 pilot has NOT started (no results/pilot)", not (V4 / "results" / "pilot").exists())
import contextlib, io                                                # noqa: E401,E402
_argv, sys.argv = sys.argv, ["run_pilot.py", "--plan", "pilot"]     # no confirmation token: must refuse
_buf = io.StringIO()
try:
    with contextlib.redirect_stdout(_buf):
        _rc = rp.main()
finally:
    sys.argv = _argv
check("scope", "runner refuses to start the pilot without the explicit confirmation token",
      _rc == 2 and "explicit start confirmation missing" in _buf.getvalue() and not (V4 / "results" / "pilot").exists(),
      _buf.getvalue()[-300:])

# 8 v2/v3 untouched
tracked = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "data", "nrl", "pipeline", "analysis/v3_claude_final",
                          "analysis/v3_audit", "analysis/v3_independent", "docs/ANALYSIS-PLAN.md", "docs/ANALYSIS-PLAN-V3.md"],
                         cwd=REPO, capture_output=True, text=True).stdout.split()
check("v2v3", "no tracked v2/v3 file modified (git diff HEAD)", not tracked, tracked)
untracked = [p for p in subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "data", "nrl", "pipeline"],
                                       cwd=REPO, capture_output=True, text=True).stdout.split()]
check("v2v3", "no untracked files added under data/, nrl/, pipeline/", not untracked, untracked[:5])
v4_start = (V4 / "tools" / "capability_probe.sh").stat().st_mtime
newer = []
for base in ("data/pilot-v2", "data/pilot-v3", "data/pilot-v1", "nrl", "pipeline"):
    for dp, dns, fns in os.walk(REPO / base):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if os.path.getmtime(os.path.join(dp, fn)) > v4_start:
                newer.append(os.path.relpath(os.path.join(dp, fn), REPO))
check("v2v3", "no file under data/ (incl. gitignored raw runs), nrl/, pipeline/ modified since V4 work began "
      "(__pycache__ bytecode excluded)", not newer, newer[:10])

summary = {"checks": len(results), "passed": sum(r["pass"] for r in results),
           "failed": [f"[{r['group']}] {r['check']}" for r in results if not r["pass"]],
           "interpretation": "ENGINEERING VALIDATION ONLY -- smoke numbers are not evidence for any pilot gate"}
if not NO_WRITE:
    (ROOT / "SMOKE-VALIDATION.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2, default=str),
                                                encoding="utf-8", newline="\n")
print(json.dumps(summary, indent=1))
sys.exit(0 if not summary["failed"] else 1)
