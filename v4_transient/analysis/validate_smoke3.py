"""Engineering smoke 3 validation (amendments A4 and A5). ENGINEERING ONLY: no pilot gate is evaluated and no
threshold is set from these values. The acceptance criteria were fixed before smoke 3 existed
(docs/V4-LAUNCH-AUDIT-2.md §4, Git commit b165c23); the D1 resolution bound and the D6 runtime threshold are read from
the frozen config/pilot_decisions.json, never restated here.

    ./.venv/Scripts/python.exe v4_transient/analysis/extract_runs.py --plan smoke3
    ./.venv/Scripts/python.exe v4_transient/analysis/validate_smoke3.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from nrl import topologies_v3 as T3                                 # noqa: E402

from v4lib.fib import parse_link_lines                              # noqa: E402
from v4lib.labops import RUNNER_EXEC_MODE                           # noqa: E402

spec_ = importlib.util.spec_from_file_location("run_pilot", V4 / "pilot" / "run_pilot.py")
rp = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(rp)

ROOT = V4 / "results" / "smoke3"
OLD = V4 / "results" / "smoke2"
results = []


def check(group, name, cond, detail=None):
    results.append({"group": group, "check": name, "pass": bool(cond), "detail": detail})
    print(f"{'PASS' if cond else 'FAIL'}  [{group}] {name}" + ("" if cond or detail is None else f"  -- {detail}"))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
changes = {c["change_id"]: c for c in man["changes"]}
plan = json.loads((V4 / "manifests" / "run_plan_smoke3.json").read_text())["runs"]
validity = json.loads((ROOT / "validity.json").read_text())["runs"]
metrics = {r["run_id"]: r for r in csv.DictReader((ROOT / "run_metrics.csv").open(encoding="utf-8"))}
old_metrics = {r["run_id"]: r for r in csv.DictReader((OLD / "run_metrics.csv").open(encoding="utf-8"))}
bfc = json.loads((V4 / "manifests" / "batfish_check.json").read_text())
dec = json.loads((V4 / "config" / "pilot_decisions.json").read_text())["decisions"]
RES_FLOOR = float(dec["D1_noise_floor"]["minimum_resolution_floor"])
RUNTIME_MAX = float(dec["D6_G5_cost"]["kill_if_median_wall_s_above"])
code_now = rp.code_digest()
final = {}

for run in plan:
    rid, ch = run["run_id"], changes[run["change_id"]]
    spec = T3.resolve(ch["topology"])
    check("batfish", f"{rid}: admitted by the Batfish gate", rp.batfish_gate(bfc, ch)[0])
    recs = rp.attempts(ROOT, rid)
    check("execution", f"{rid}: has a final attempt with status OK", bool(recs) and recs[-1].get("status") == "OK",
          [x.get("status") for x in recs])
    check("execution", f"{rid}: any earlier attempt failed before the change was applied",
          all(not x.get("change_applied") for x in recs[:-1]), [x.get("status") for x in recs])
    if not recs or "run_id" not in recs[-1]:
        continue
    rec = final[rid] = recs[-1]
    check("provenance", f"{rid}: code hashed at run time equals the committed code on disk",
          rec.get("code_sha256") == code_now,
          sorted(k for k in code_now if (rec.get("code_sha256") or {}).get(k) != code_now[k]))
    check("provenance", f"{rid}: runner exec mode {rec.get('runner_exec_mode')}", rec.get("runner_exec_mode") == RUNNER_EXEC_MODE)
    if rec.get("status") != "OK":
        continue
    check("execution", f"{rid}: teardown OK and no cleanup error", rec.get("teardown_ok") is True and not rec.get("cleanup_errors"),
          rec.get("cleanup_errors"))
    v = validity.get(rid, {})
    failing = [k for k, ok in (v.get("checks") or {}).items() if not ok]
    check("validity", f"{rid}: all {len(v.get('checks') or {})} run-validity checks pass (§12, A3)",
          v.get("measurable") is True and not failing and len(v.get("checks") or {}) == 13, (failing, v.get("diagnostics")))
    m = metrics.get(rid, {})
    check("replay", f"{rid}: replay checked against in-transient FIB polls (>= 1 unambiguous poll, 0 mismatches)",
          num(m.get("intermediate_checks")) >= 1 and num(m.get("intermediate_mismatches")) == 0,
          (m.get("intermediate_checks"), m.get("intermediate_skipped"), m.get("intermediate_mismatches")))
    adir = ROOT / "raw" / rid / f"attempt{rec['attempt']}"
    if ch["kind"].startswith("control_positive"):
        node = next(iter(ch["push_plan"]))
        iface = next(c.split()[1] for c in ch["push_plan"][node] if c.startswith("interface "))
        peer = next(((b, bi) if a == node else (a, ai)) for (a, ai, aa, b, bi, ba, *_rest) in spec.links
                    if (a, ai) == (node, iface) or (b, bi) == (node, iface))
        own = parse_link_lines((adir / "fib_monitor" / f"{node}.log").read_text().splitlines(), with_ts=True)
        oth = parse_link_lines((adir / "fib_monitor" / f"{peer[0]}.log").read_text().splitlines(), with_ts=True)
        check("link-state", f"{rid}: administrative-down event of {node}:{iface} captured",
              any(e["dev"] == iface and not e["admin_up"] for e in own))
        check("link-state", f"{rid}: carrier-loss event of peer {peer[0]}:{peer[1]} captured",
              any(e["dev"] == peer[1] and e["admin_up"] and not e["carrier"] for e in oth))
    if ch["kind"] == "control_noop":
        check("null", f"{rid}: no-op control produces no FIB state change and no link event (instrument null)",
              num(m.get("n_fib_state_changes")) == 0 and num(m.get("n_link_events")) == 0,
              (m.get("n_fib_state_changes"), m.get("n_link_events")))

# ---- engineering floor and the A4 hard stop (docs/V4-LAUNCH-AUDIT-2.md §3-§4) ---------------------------------------
noop_ids = [r["run_id"] for r in plan if changes[r["change_id"]]["kind"] == "control_noop"]
noop_t1 = [num(metrics.get(rid, {}).get("T1_disruption_area")) for rid in noop_ids if validity.get(rid, {}).get("measurable")]
check("floor", f"every smoke-3 no-op run valid ({len(noop_t1)}/{len(noop_ids)})", len(noop_t1) == len(noop_ids) > 0)
floor = max([RES_FLOOR] + [t for t in noop_t1 if not math.isnan(t)])
print(f"   engineering floor = max(D1 resolution bound {RES_FLOOR:.6g}, valid no-op T1 {noop_t1}) = {floor:.6g}")
hard_stop = {}
for r in plan:
    ch = changes[r["change_id"]]
    if ch["kind"] != "control_positive":
        continue
    rid = r["run_id"]
    ok_valid = validity.get(rid, {}).get("measurable") is True
    t1 = num(metrics.get(rid, {}).get("T1_disruption_area"))
    hard_stop[rid] = {"amendment": ch.get("amendment"), "valid": ok_valid, "T1": t1, "floor": floor,
                      "above": bool(ok_valid and t1 > floor)}
    check("hard-stop", f"{rid} ({ch['topology']}{', A4 replacement' if ch.get('amendment') else ''}): valid and T1 "
                       f"{t1:.6g} > engineering floor {floor:.6g}", ok_valid and t1 > floor)

# ---- predictions stated before smoke 3: structural zeros (docs/V4-LAUNCH-AUDIT-2.md §1, §4) ---------------------------
for r in plan:
    ch = changes[r["change_id"]]
    rid = r["run_id"]
    if not (ch["kind"] == "control_positive_retired" or ch["mechanism"] == "blackhole") or not validity.get(rid, {}).get("measurable"):
        continue
    t1 = num(metrics.get(rid, {}).get("T1_disruption_area"))
    ts = list(csv.DictReader((ROOT / "timeseries" / f"{rid}.csv").open(encoding="utf-8")))
    peak = max(num(x["broken_total"]) for x in ts)
    check("prediction", f"{rid} ({ch['kind']}, {ch['mechanism']}): T1 = 0 and peak broken_total {peak:.6f} = "
                        f"r_broken_exact {ch['features']['r_broken_exact']:.6f} (r_rerouted_exact = 0)",
          ch["features"]["r_rerouted_exact"] == 0 and t1 == 0 and abs(peak - ch["features"]["r_broken_exact"]) < 1e-6)

# ---- runtime (the D6 metric on the smoke-3 population sample; engineering projection, not G5) -----------------------
pop_runs = [r["run_id"] for r in plan if changes[r["change_id"]]["kind"] == "population"]
walls = {rid: final[rid].get("wall_s") for rid in pop_runs if rid in final}
by_topo = {}
for rid, w in walls.items():
    by_topo.setdefault(changes[rid.split("-", 1)[1].split(".")[0]]["topology"], []).append(w)
med = statistics.median(walls.values()) if len(walls) == len(pop_runs) and all(w is not None for w in walls.values()) else None
print(f"   population wall_s (final attempts): {walls}; median {med}; by topology {by_topo}")
check("runtime", f"median wall_s of the {len(pop_runs)} population final attempts ({med}) <= frozen D6 threshold "
                 f"{RUNTIME_MAX:g} s", med is not None and med <= RUNTIME_MAX)


def phases(rec):
    if not rec or rec.get("t_end") is None:
        return None
    tws = rec["t_wall_start"]
    return {"wall_s": rec["wall_s"], "convergence_s": rec.get("convergence_wall_s"),
            "pre_change_overhead_s": round(rec["t_baseline_start"] - tws - (rec.get("convergence_wall_s") or 0), 2),
            "baseline_plus_observation_s": round(rec["t_end"] - rec["t_baseline_start"], 2),
            "post_window_s": round(tws + rec["wall_s"] - rec["t_end"], 2)}


comparison = {}
for r in plan:
    rid, old_rid = r["run_id"], r["run_id"].replace("SMOKE3-", "SMOKE2-")
    new_m, old_m = metrics.get(rid, {}), old_metrics.get(old_rid)
    old_recs = rp.attempts(OLD, old_rid)
    comparison[rid] = {
        "smoke2_run": old_rid if old_m else None,
        "T1": {"smoke2": num(old_m["T1_disruption_area"]) if old_m else None, "smoke3": num(new_m.get("T1_disruption_area"))},
        "T2": {"smoke2": num(old_m["T2_peak_disruption"]) if old_m else None, "smoke3": num(new_m.get("T2_peak_disruption"))},
        "valid": {"smoke2": (old_m or {}).get("valid"), "smoke3": new_m.get("valid")},
        "phases": {"smoke2": phases(old_recs[-1]) if old_recs else None, "smoke3": phases(final.get(rid))}}

check("scope", "20x5 pilot has NOT started (no results/pilot, no pilot ledger)",
      not (V4 / "results" / "pilot").exists() and not (V4 / "logs" / "pilot_ledger.jsonl").exists())
summary = {"checks": len(results), "passed": sum(r["pass"] for r in results),
           "failed": [f"[{r['group']}] {r['check']}" for r in results if not r["pass"]],
           "engineering_floor": floor, "hard_stop": hard_stop,
           "population_median_wall_s": med, "population_wall_s_by_topology": by_topo,
           "interpretation": "ENGINEERING VALIDATION ONLY -- smoke 3 values are not evidence for any pilot gate"}
(ROOT / "SMOKE3-VALIDATION.json").write_text(json.dumps({"summary": summary, "results": results,
                                                          "smoke2_vs_smoke3_same_scenarios": comparison},
                                                         indent=2, default=str), encoding="utf-8", newline="\n")
print(json.dumps({k: summary[k] for k in ("checks", "passed", "failed", "engineering_floor", "population_median_wall_s")},
                 indent=1))
sys.exit(0 if not summary["failed"] else 1)
