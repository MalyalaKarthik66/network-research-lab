"""Independent corpus metrics and Phase-3 cross-file count audit."""
from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "data" / "pilot-v3"
P3 = PILOT / "phase3"
R = ROOT / "analysis" / "v3_audit" / "measured_blast_radius.csv"


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return result


def corr(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    denominator = math.sqrt(sum(x * x for x in da) * sum(x * x for x in db))
    return sum(x * y for x, y in zip(da, db)) / denominator


def main():
    measured = list(csv.DictReader(R.open(newline="", encoding="utf-8")))
    scored = [row for row in measured if row.get("r") not in (None, "")]
    predicted = [float(row["predicted_severity"]) for row in scored]
    actual = [float(row["r"]) for row in scored]
    errors = [a - b for a, b in zip(actual, predicted)]
    mean_actual = sum(actual) / len(actual)
    result = {
        "n": len(scored),
        "mae": sum(abs(x) for x in errors) / len(errors),
        "rmse": math.sqrt(sum(x * x for x in errors) / len(errors)),
        "pearson": corr(predicted, actual),
        "spearman": corr(ranks(predicted), ranks(actual)),
        "max_abs_error": max(abs(x) for x in errors),
        "mae_threshold_0_10_pass": sum(abs(x) for x in errors) / len(errors) <= .10,
        "target": {
            "distinct": len(set(actual)),
            "zero_fraction": sum(x == 0 for x in actual) / len(actual),
            "min": min(actual), "max": max(actual),
            "mean": mean_actual,
            "median": sorted(actual)[len(actual) // 2],
            "quantiles": {str(q): sorted(actual)[round((len(actual) - 1) * q)] for q in (0, .25, .5, .75, 1)},
        },
    }
    summary = list(csv.DictReader((P3 / "containerlab_summary.csv").open(newline="", encoding="utf-8")))
    measurements = list(csv.DictReader((P3 / "containerlab_measurements.csv").open(newline="", encoding="utf-8")))
    deltas = list(csv.DictReader((P3 / "containerlab_deltas.csv").open(newline="", encoding="utf-8")))
    outcomes = list(csv.DictReader((P3 / "containerlab_outcomes.csv").open(newline="", encoding="utf-8")))
    result["cross_file_counts"] = {
        "summary": len(summary), "measurements": len(measurements),
        "deltas": len(deltas), "outcomes": len(outcomes),
        "summary_status": dict(Counter(row["run_status"] for row in summary)),
        "summary_kind": dict(Counter(row["kind"] for row in summary)),
        "outcome_status": dict(Counter(row["outcome_harm_v1"] for row in outcomes)),
        "measurement_rows_per_run": dict(Counter(Counter(row["run_id"] for row in measurements).values())),
        "delta_rows_per_candidate": dict(Counter(Counter(row["candidate_id"] for row in deltas).values())),
        "unique_summary_ids": len({row["run_id"] for row in summary}),
        "unique_outcome_ids": len({row["candidate_id"] for row in outcomes}),
        "unique_delta_ids": len({row["candidate_id"] for row in deltas}),
    }
    (ROOT / "analysis" / "v3_independent" / "independent_metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
