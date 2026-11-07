"""Offline v3 measured blast-radius audit.

Reads only data/pilot-v3 Phase 3 raw RIB evidence and frozen topology metadata.
Writes derived results under analysis/v3_audit; never writes to the corpus.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nrl import flowmatrix as fm
from nrl.topologies_v3 import resolve as resolve_v3

PILOT = ROOT / "data" / "pilot-v3"
P3 = PILOT / "phase3"
OUT = ROOT / "analysis" / "v3_audit"


def load_route_state(run_id: str, spec):
    state = {}
    run_dir = P3 / "runs" / run_id
    for node in sorted(spec.routers):
        path = run_dir / "state" / f"{node}.route.json"
        if not path.exists():
            return None, f"missing {path.relative_to(ROOT)}"
        try:
            state[node] = {"route": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"cannot read {path.name}: {exc}"
    return state, None


def all_flows(spec):
    endpoints = fm.endpoints(spec)
    return [
        {
            "flow_id": f"{src['name']}->{dst['name']}",
            "src_name": src["name"],
            "dst_name": dst["name"],
            "src_addr": src["addr"],
            "dst_addr": dst["addr"],
        }
        for src in endpoints
        for dst in endpoints
        if src["addr"] != dst["addr"]
    ]


def paths(run_id, spec, flows):
    state, error = load_route_state(run_id, spec)
    if error:
        return None, error
    return fm.measure_paths(state, spec, flows), None


def compare(candidate_paths, golden_paths):
    undecidable_terms = {"NO_RIB", "UNKNOWN_NH", "MAX_HOPS"}
    broken_terms = {"NO_ROUTE", "LOOP", "BLACKHOLE"}
    golden_carried = []
    broken = []
    rerouted = []
    undetermined = []
    for flow_id, golden in golden_paths.items():
        if golden["term"] != "OK":
            continue
        golden_carried.append(flow_id)
        candidate = candidate_paths.get(flow_id)
        if candidate is None or candidate["term"] in undecidable_terms:
            undetermined.append(flow_id)
        elif candidate["term"] in broken_terms:
            broken.append(flow_id)
        elif (candidate["path"], candidate["term"]) != (golden["path"], golden["term"]):
            rerouted.append(flow_id)
    decidable = len(golden_carried) - len(undetermined)
    hurt = len(broken) + len(rerouted)
    return {
        "golden_carried_flows": len(golden_carried),
        "broken_flows": len(broken),
        "rerouted_flows": len(rerouted),
        "undetermined_flows": len(undetermined),
        "decidable_flows": decidable,
        "r": round(hurt / decidable, 6) if decidable else None,
        "r_min": round(hurt / len(golden_carried), 6) if golden_carried else None,
        "r_max": round((hurt + len(undetermined)) / len(golden_carried), 6) if golden_carried else None,
        "broken_flow_ids": ";".join(sorted(broken)),
        "rerouted_flow_ids": ";".join(sorted(rerouted)),
        "undetermined_flow_ids": ";".join(sorted(undetermined)),
    }


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((PILOT / "manifest.json").read_text(encoding="utf-8"))
    candidates = {row["candidate_id"]: row for row in manifest["candidates"]}
    summary = list(csv.DictReader((P3 / "containerlab_summary.csv").open(newline="", encoding="utf-8")))
    status_by_id = {row["run_id"]: row["run_status"] for row in summary}
    candidate_ids = sorted(candidates)

    golden_paths = {}
    rows = []
    target_errors = []
    for topology in sorted({row["topology"] for row in candidates.values()}):
        spec = resolve_v3(topology)
        flows = all_flows(spec)
        golden_id = f"golden-{topology}"
        measured, error = paths(golden_id, spec, flows)
        if error:
            target_errors.append({"run_id": golden_id, "reason": error})
        else:
            golden_paths[topology] = measured

    for candidate_id in candidate_ids:
        meta = candidates[candidate_id]
        spec = resolve_v3(meta["topology"])
        flows = all_flows(spec)
        row = {
            "candidate_id": candidate_id,
            "incident_id": meta["incident_id"],
            "topology": meta["topology"],
            "mechanism": meta["mechanism"],
            "predicted_severity": meta["predicted_severity"],
            "run_status": status_by_id.get(candidate_id),
            "reason_excluded": "",
        }
        if row["run_status"] != "OK":
            row["reason_excluded"] = row["run_status"] or "missing summary row"
        elif meta["topology"] not in golden_paths:
            row["reason_excluded"] = "missing golden RIB evidence"
        else:
            measured, error = paths(candidate_id, spec, flows)
            if error:
                row["reason_excluded"] = error
                target_errors.append({"run_id": candidate_id, "reason": error})
            else:
                row.update(compare(measured, golden_paths[meta["topology"]]))
        rows.append(row)

    fields = sorted({key for row in rows for key in row})
    with (OUT / "measured_blast_radius.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    scored = [row for row in rows if row.get("r") not in (None, "")]
    values = [float(row["r"]) for row in scored]
    summary_out = {
        "total_candidates": len(rows),
        "decidable_candidates": len(scored),
        "excluded_candidates": len(rows) - len(scored),
        "terminal_failures": sum(row.get("run_status") in {"ERROR", "LAB_INVALID"} for row in rows),
        "no_convergence": sum(row.get("run_status") == "NO_CONVERGENCE" for row in rows),
        "undetermined_flow_candidates": sum(int(row.get("undetermined_flows", 0) or 0) > 0 for row in scored),
        "distinct_r_values": len(set(values)),
        "zero_fraction": sum(value == 0 for value in values) / len(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "median": quantile(values, 0.5),
        "quantiles": {str(q): quantile(values, q) for q in (0.0, 0.25, 0.5, 0.75, 1.0)},
        "per_mechanism": {},
        "per_topology": {},
        "target_errors": target_errors,
        "source": "data/pilot-v3/phase3/runs/*/state/*.route.json",
        "predicted_severity_used_as_feature": False,
    }
    for key, group_key in (("per_mechanism", "mechanism"), ("per_topology", "topology")):
        groups = {}
        for row in scored:
            groups.setdefault(row[group_key], []).append(float(row["r"]))
        summary_out[key] = {
            group: {
                "n": len(vals),
                "distinct": len(set(vals)),
                "zero_fraction": sum(v == 0 for v in vals) / len(vals),
                "mean": sum(vals) / len(vals),
                "min": min(vals),
                "max": max(vals),
            }
            for group, vals in sorted(groups.items())
        }
    (OUT / "measured_blast_radius_summary.json").write_text(
        json.dumps(summary_out, indent=2), encoding="utf-8")
    print(json.dumps(summary_out, indent=2))


if __name__ == "__main__":
    main()
