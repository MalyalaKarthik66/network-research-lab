"""Independent v3 LOTO and gate recomputation.

This evaluator does not import analysis/v3_audit/run_v3_ml_audit.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "analysis" / "v3_independent"
PILOT = ROOT / "data" / "pilot-v3"


def build_frame():
    from nrl.phase4 import feature_columns, load
    measured = pd.read_csv(ROOT / "analysis" / "v3_audit" / "measured_blast_radius.csv")
    measured["r"] = pd.to_numeric(measured["r"], errors="coerce")
    measured = measured.dropna(subset=["r"])
    loaded = load(PILOT)
    frame = loaded["meta"].merge(loaded["p2"], on=["candidate_id", "incident_id"], how="inner")
    frame = frame.merge(measured[["candidate_id", "r"]], on="candidate_id", how="inner")
    manifest = json.loads((PILOT / "manifest.json").read_text(encoding="utf-8"))
    provenance = pd.DataFrame(manifest["candidates"])[["candidate_id", "mechanism", "repair_class"]]
    frame = frame.merge(provenance, on="candidate_id", how="inner")
    features, removed = feature_columns(frame, "C")
    return frame, features, removed


def numeric(frame, columns):
    matrix = frame[columns].copy()
    for column in columns:
        if matrix[column].dtype == object:
            matrix[column] = matrix[column].map({"PASS": 0.0, "FAIL": 1.0, True: 1.0, False: 0.0})
        matrix[column] = pd.to_numeric(matrix[column], errors="coerce")
    matrix = matrix.fillna(0.0)
    kept = [column for column in columns if matrix[column].std() > 0]
    return matrix[kept].to_numpy(float), kept


def metrics(y, prediction):
    y, prediction = np.asarray(y), np.asarray(prediction)
    denominator = np.sum((y - y.mean()) ** 2)
    return {"r2": float(1 - np.sum((y - prediction) ** 2) / denominator),
            "mae": float(np.mean(np.abs(y - prediction))),
            "rmse": float(np.sqrt(np.mean((y - prediction) ** 2)))}


def fit_model():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=300,
        max_leaf_nodes=15, l2_regularization=1.0, random_state=0)


def loto(frame, columns, mechanism=None):
    from sklearn.ensemble import HistGradientBoostingRegressor
    data = frame if mechanism is None else frame[frame.mechanism == mechanism].copy()
    x, kept = numeric(data, columns)
    y = data.r.to_numpy(float)
    groups = data.topology.to_numpy()
    prediction = np.full(len(data), np.nan)
    folds = []
    for topology in sorted(set(groups)):
        test = groups == topology
        train = ~test
        estimator = fit_model()
        estimator.fit(x[train], y[train])
        prediction[test] = estimator.predict(x[test])
        folds.append({"topology": topology, "n": int(test.sum()), **metrics(y[test], prediction[test])})
    valid = np.isfinite(prediction)
    result = {"features": kept, "y": y, "prediction": prediction, "groups": groups,
              "folds": folds, "n": int(valid.sum()), **metrics(y[valid], prediction[valid])}
    result["mean_fold_r2"] = float(np.mean([row["r2"] for row in folds]))
    result["median_fold_r2"] = float(np.median([row["r2"] for row in folds]))
    result["mean_fold_mae"] = float(np.mean([row["mae"] for row in folds]))
    result["mean_fold_rmse"] = float(np.mean([row["rmse"] for row in folds]))
    return result


def bootstrap(result, n=2000):
    rng = np.random.default_rng(20260913)
    groups = np.array(sorted(set(result["groups"])))
    values = []
    for _ in range(n):
        sample = rng.choice(groups, size=len(groups), replace=True)
        indices = np.concatenate([np.flatnonzero(result["groups"] == g) for g in sample])
        values.append(metrics(result["y"][indices], result["prediction"][indices])["r2"])
    return {"n": n, "unit": "topology", "lower": float(np.quantile(values, .025)),
            "median": float(np.quantile(values, .5)), "upper": float(np.quantile(values, .975))}


def baseline(frame, mechanism):
    data = frame[frame.mechanism == mechanism].copy()
    y = data.r.to_numpy(float)
    groups = data.topology.to_numpy()
    prediction = np.zeros(len(data))
    for topology in sorted(set(groups)):
        test = groups == topology
        train = ~test
        prediction[test] = y[train].mean()
    return {"n": len(y), **metrics(y, prediction)}


def grouped_calibration(frame, columns):
    from sklearn.model_selection import GroupKFold
    x, kept = numeric(frame, columns)
    y = frame.r.to_numpy(float)
    prediction = np.full(len(frame), np.nan)
    for train, test in GroupKFold(5).split(x, y, groups=frame.incident_id):
        estimator = fit_model()
        estimator.fit(x[train], y[train])
        prediction[test] = estimator.predict(x[test])
    slope, intercept = np.polyfit(prediction, y, 1)
    order = np.argsort(prediction)
    bins = []
    for indices in np.array_split(order, 4):
        bins.append({"n": len(indices), "predicted_mean": float(prediction[indices].mean()),
                     "observed_mean": float(y[indices].mean()),
                     "within_0_05": bool(abs(prediction[indices].mean() - y[indices].mean()) <= .05)})
    return {"features": kept, **metrics(y, prediction), "slope": float(slope),
            "intercept": float(intercept), "bins": bins,
            "bins_passing": sum(row["within_0_05"] for row in bins)}


def main():
    frame, columns, removed = build_frame()
    full = loto(frame, columns)
    within = {m: loto(frame, columns, m) for m in sorted(frame.mechanism.unique())}
    baselines = {m: baseline(frame, m) for m in sorted(frame.mechanism.unique())}
    result = {
        "n": len(frame), "features": full["features"], "removed": removed,
        "predicted_severity_used": False,
        "loto": {k: v for k, v in full.items() if k not in {"y", "prediction", "groups"}},
        "bootstrap": bootstrap(full),
        "within": {},
        "baseline": baselines,
        "grouped_five_fold_calibration": grouped_calibration(frame, columns),
    }
    for mechanism, value in within.items():
        result["within"][mechanism] = {
            "loto": {k: v for k, v in value.items() if k not in {"y", "prediction", "groups"}},
            "improvement_over_baseline": value["r2"] - baselines[mechanism]["r2"],
            "folds": value["folds"],
        }
    (OUT / "independent_ml.json").write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    print(json.dumps(result, indent=2, default=float))


if __name__ == "__main__":
    main()
