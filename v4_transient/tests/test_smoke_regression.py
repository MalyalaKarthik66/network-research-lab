"""Regression: the amended (A3) extraction reproduces the preserved smoke results in memory. Nothing is written.
The first smoke ran with the smoke-era instrument (route events only, no link data), so the amended code must give
exactly the same targets for those runs, and every amended validity check must hold on them.
    ./.venv/Scripts/python.exe v4_transient/tests/test_smoke_regression.py
"""
import csv
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

spec = importlib.util.spec_from_file_location("extract_runs", V4 / "analysis" / "extract_runs.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


ROOT = V4 / "results" / "smoke"
man = {c["change_id"]: c for c in json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())["changes"]}
recorded = {r["run_id"]: r for r in csv.DictReader((ROOT / "run_metrics.csv").open(encoding="utf-8"))}
before = {p: p.stat().st_mtime for p in ROOT.rglob("*") if p.is_file()}
n = 0
for rid, row in sorted(recorded.items()):
    if row.get("status") != "OK":
        continue
    ad = ROOT / "raw" / rid / row["attempt"] if row["attempt"].startswith("attempt") else ROOT / "raw" / rid / f"attempt{row['attempt']}"
    rec = ex.load_run(ad)
    s, m, diag = ex.extract(ad, rec, man[row["change_id"]])
    n += 1
    for k in ("T1_disruption_area", "T2_peak_disruption", "T3_disruption_duration", "T1_upper_undetermined_as_broken",
              "detour_area", "r_final", "n_fib_state_changes", "fib_settle_s"):
        check(f"{rid}: {k} reproduced exactly", float(row[k]) == float(m[k]), (row[k], m[k]))
    checks = ex.validity_checks(s, m, diag, rec, man[row["change_id"]])
    check(f"{rid}: every amended validity check holds", all(checks.values()), {k: v for k, v in checks.items() if not v})
    check(f"{rid}: 10 ms merge sensitivity computed", m["T1_merge10ms"] >= 0.0, m["T1_merge10ms"])
check("all 4 valid smoke runs recomputed", n == 4, n)
check("preserved smoke results untouched by the recomputation",
      before == {p: p.stat().st_mtime for p in ROOT.rglob("*") if p.is_file()})
print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
