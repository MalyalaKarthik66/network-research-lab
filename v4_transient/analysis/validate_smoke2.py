"""Engineering smoke 2 validation (amendment A3). ENGINEERING ONLY: checks that the instrument measures what the
protocol says, on real labs. No gate, no threshold and no scientific interpretation; target values are reported
descriptively and nothing here depends on their size.

    ./.venv/Scripts/python.exe v4_transient/analysis/extract_runs.py --plan smoke2
    ./.venv/Scripts/python.exe v4_transient/analysis/validate_smoke2.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from nrl import topologies_v3 as T3                                 # noqa: E402

from v4lib.fib import parse_link_lines                              # noqa: E402

spec_ = importlib.util.spec_from_file_location("run_pilot", V4 / "pilot" / "run_pilot.py")
rp = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(rp)

ROOT = V4 / "results" / "smoke2"
results = []


def check(group, name, cond, detail=None):
    results.append({"group": group, "check": name, "pass": bool(cond), "detail": detail})
    print(f"{'PASS' if cond else 'FAIL'}  [{group}] {name}" + ("" if cond or detail is None else f"  -- {detail}"))


man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
changes = {c["change_id"]: c for c in man["changes"]}
plan = json.loads((V4 / "manifests" / "run_plan_smoke2.json").read_text())["runs"]
validity = json.loads((ROOT / "validity.json").read_text())["runs"]
metrics = {r["run_id"]: r for r in csv.DictReader((ROOT / "run_metrics.csv").open(encoding="utf-8"))}
bfc = json.loads((V4 / "manifests" / "batfish_check.json").read_text())
code_now = rp.code_digest()
descriptive = {}

for run in plan:
    rid, ch = run["run_id"], changes[run["change_id"]]
    spec = T3.resolve(ch["topology"])
    check("batfish", f"{rid}: admitted by the Batfish gate", rp.batfish_gate(bfc, ch)[0])
    recs = rp.attempts(ROOT, rid)
    check("execution", f"{rid}: has a final attempt with status OK", bool(recs) and recs[-1].get("status") == "OK",
          [x.get("status") for x in recs])
    check("execution", f"{rid}: any earlier attempt failed before the change was applied",
          all(not x.get("change_applied") for x in recs[:-1]), [x.get("status") for x in recs])
    if not recs or recs[-1].get("status") != "OK":
        continue
    rec = recs[-1]
    check("provenance", f"{rid}: code hashed at run time equals the committed code on disk",
          rec.get("code_sha256") == code_now, sorted(k for k in code_now if (rec.get("code_sha256") or {}).get(k) != code_now[k]))
    check("provenance", f"{rid}: protocol version {rec.get('protocol_version')}", rec.get("protocol_version") == "transient-1.1.0")
    check("execution", f"{rid}: teardown OK and no cleanup error", rec.get("teardown_ok") is True and not rec.get("cleanup_errors"),
          rec.get("cleanup_errors"))
    v = validity.get(rid, {})
    failing = [k for k, ok in (v.get("checks") or {}).items() if not ok]
    check("validity", f"{rid}: all {len(v.get('checks') or {})} run-validity checks pass (§12, A3)",
          v.get("measurable") is True and not failing, (failing, v.get("diagnostics")))
    m = metrics.get(rid, {})
    check("replay", f"{rid}: replay checked against in-transient FIB polls (>= 1 unambiguous poll, 0 mismatches)",
          int(float(m.get("intermediate_checks") or 0)) >= 1 and int(float(m.get("intermediate_mismatches") or 1)) == 0,
          (m.get("intermediate_checks"), m.get("intermediate_skipped"), m.get("intermediate_mismatches")))
    adir = ROOT / "raw" / rid / f"attempt{rec['attempt']}"
    if ch["kind"] == "control_positive":
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
              int(float(m.get("n_fib_state_changes") or -1)) == 0 and int(float(m.get("n_link_events") or -1)) == 0,
              (m.get("n_fib_state_changes"), m.get("n_link_events")))
    descriptive[rid] = {k: m.get(k) for k in ("kind", "topology", "role", "T1_disruption_area", "T1_merge10ms",
                                               "T2_peak_disruption", "T3_disruption_duration", "n_fib_state_changes",
                                               "n_link_events", "intermediate_checks", "intermediate_skipped",
                                               "wall_s", "observation_s")}

check("scope", "20x5 pilot has NOT started (no results/pilot)", not (V4 / "results" / "pilot").exists())
summary = {"checks": len(results), "passed": sum(r["pass"] for r in results),
           "failed": [f"[{r['group']}] {r['check']}" for r in results if not r["pass"]],
           "interpretation": "ENGINEERING VALIDATION ONLY -- smoke 2 values are not evidence for any pilot gate"}
(ROOT / "SMOKE2-VALIDATION.json").write_text(json.dumps({"summary": summary, "results": results,
                                                          "descriptive_engineering_values": descriptive}, indent=2, default=str),
                                              encoding="utf-8", newline="\n")
print(json.dumps(summary, indent=1))
sys.exit(0 if not summary["failed"] else 1)
