"""Frozen v3 predicted-vs-measured corpus validation and target gates."""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "analysis" / "v3_audit"


def pearson(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    a = [x - mx for x in xs]
    b = [y - my for y in ys]
    den = math.sqrt(sum(v * v for v in a) * sum(v * v for v in b))
    return sum(x * y for x, y in zip(a, b)) / den if den else None


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def main():
    rows = list(csv.DictReader((OUT / "measured_blast_radius.csv").open(newline="", encoding="utf-8")))
    rows = [r for r in rows if r.get("r") not in (None, "")]
    pred = [float(r["predicted_severity"]) for r in rows]
    measured = [float(r["r"]) for r in rows]
    errors = [abs(a - b) for a, b in zip(pred, measured)]
    mean_y = sum(measured) / len(measured)
    ss_tot = sum((y - mean_y) ** 2 for y in measured)
    ss_res = sum((y - yhat) ** 2 for y, yhat in zip(measured, pred))
    result = {
        "n": len(rows),
        "mae": sum(errors) / len(errors),
        "rmse": math.sqrt(ss_res / len(rows)),
        "r2": 1 - ss_res / ss_tot if ss_tot else None,
        "pearson": pearson(pred, measured),
        "spearman": pearson(rank(pred), rank(measured)),
        "stop_fix_mae_gt_0_10": sum(errors) / len(errors) > 0.10,
        "largest_errors": sorted([
            {"candidate_id": r["candidate_id"], "mechanism": r["mechanism"],
             "predicted": float(r["predicted_severity"]), "measured": float(r["r"]),
             "absolute_error": abs(float(r["predicted_severity"]) - float(r["r"]))}
            for r in rows], key=lambda x: -x["absolute_error"])[:15],
        "by_mechanism": {},
        "target_degeneracy": {
            "distinct_r": len(set(measured)),
            "distinct_passes": len(set(measured)) >= 20,
            "max_value_fraction": max(Counter(measured).values()) / len(measured),
            "one_value_passes": max(Counter(measured).values()) / len(measured) <= 0.70,
        },
    }
    for mechanism in sorted({r["mechanism"] for r in rows}):
        group = [r for r in rows if r["mechanism"] == mechanism]
        p = [float(r["predicted_severity"]) for r in group]
        y = [float(r["r"]) for r in group]
        err = [abs(a - b) for a, b in zip(p, y)]
        result["by_mechanism"][mechanism] = {
            "n": len(group), "mae": sum(err) / len(err),
            "rmse": math.sqrt(sum((a - b) ** 2 for a, b in zip(p, y)) / len(y)),
            "pearson": pearson(p, y), "spearman": pearson(rank(p), rank(y)),
            "distinct_measured": len(set(y)), "zero_fraction": sum(v == 0 for v in y) / len(y),
        }
    (OUT / "predicted_vs_measured.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
