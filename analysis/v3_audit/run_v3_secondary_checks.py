"""Additional frozen v3 checks: recoverability and transfer stress tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "analysis" / "v3_audit"
PILOT = ROOT / "data" / "pilot-v3"


def load_df():
    from nrl.phase4 import feature_columns, load
    measured = pd.read_csv(OUT / "measured_blast_radius.csv")
    measured["r"] = pd.to_numeric(measured["r"], errors="coerce")
    measured = measured[measured.r.notna()]
    d = load(PILOT)
    df = d["meta"].merge(d["p2"], on=["candidate_id", "incident_id"])
    df = df.merge(measured[["candidate_id", "r"]], on="candidate_id")
    manifest = json.loads((PILOT / "manifest.json").read_text(encoding="utf-8"))
    provenance = pd.DataFrame(manifest["candidates"])[
        ["candidate_id", "mechanism", "repair_class"]]
    df = df.merge(provenance, on="candidate_id")
    full, _ = feature_columns(df, "C")
    return df, full


def numeric_matrix(df, cols):
    x = df[cols].copy()
    for col in cols:
        if x[col].dtype == object:
            x[col] = x[col].map({"PASS": 0.0, "FAIL": 1.0, True: 1.0, False: 0.0})
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.fillna(0.0)
    keep = [c for c in cols if x[c].std() > 0]
    return x[keep].to_numpy(float), keep


def r2(y, p):
    den = np.sum((y - y.mean()) ** 2)
    return float(1 - np.sum((y - p) ** 2) / den) if den else None


def recoverability(df, cols, target):
    x, kept = numeric_matrix(df, cols)
    y = df[target].to_numpy()
    classes = sorted(set(y))
    scores = {}
    for cls in classes:
        yy = (y == cls).astype(int)
        if yy.min() == yy.max():
            continue
        clf = RandomForestClassifier(n_estimators=500, random_state=0, class_weight="balanced", min_samples_leaf=2)
        clf.fit(x, yy)
        scores[str(cls)] = float(roc_auc_score(yy, clf.predict_proba(x)[:, 1]))
    return {"features": kept, "in_sample_auc_upper_bound": scores,
            "worst_case_auc_upper_bound": max(scores.values()) if scores else None}


def grouped_recoverability(df, cols, target):
    x, kept = numeric_matrix(df, cols)
    y = df[target].to_numpy()
    groups = df.topology.to_numpy()
    scores = {}
    for cls in sorted(set(y)):
        truth = (y == cls).astype(int)
        pred = np.full(len(df), np.nan)
        for group in sorted(set(groups)):
            test, train = groups == group, groups != group
            if truth[train].min() == truth[train].max():
                continue
            clf = RandomForestClassifier(n_estimators=500, random_state=0,
                                          class_weight="balanced", min_samples_leaf=2)
            clf.fit(x[train], truth[train])
            pred[test] = clf.predict_proba(x[test])[:, 1]
        valid = np.isfinite(pred)
        if valid.any() and len(set(truth[valid])) == 2:
            scores[str(cls)] = float(roc_auc_score(truth[valid], pred[valid]))
    return {"features": kept, "group": "topology", "oof_auc": scores,
            "worst_case_oof_auc": max(scores.values()) if scores else None}


def shortcut_loto(df):
    cols = [c for c in df.columns if c.startswith("chg_")]
    x, kept = numeric_matrix(df, cols)
    y = df.r.to_numpy(float)
    groups = df.topology.to_numpy()
    p = np.full(len(df), np.nan)
    for group in sorted(set(groups)):
        te = groups == group
        tr = ~te
        fit = RandomForestRegressor(n_estimators=500, random_state=0, min_samples_leaf=2)
        fit.fit(x[tr], y[tr])
        p[te] = fit.predict(x[te])
    return {"features": kept, "r2": r2(y, p), "mae": float(np.mean(abs(y - p))), "rmse": float(np.sqrt(np.mean((y-p)**2)))}


def mechanism_holdout(df, cols):
    x, kept = numeric_matrix(df, cols)
    y = df.r.to_numpy(float)
    m = df.mechanism.to_numpy()
    result = {}
    for held in sorted(set(m)):
        tr, te = m != held, m == held
        fit = RandomForestRegressor(n_estimators=500, random_state=0, min_samples_leaf=2)
        fit.fit(x[tr], y[tr])
        p = fit.predict(x[te])
        result[held] = {"n": int(te.sum()), "r2": r2(y[te], p), "mae": float(np.mean(abs(y[te] - p)))}
    return result


def main():
    df, full = load_df()
    result = {
        "shortcut_only_random_forest_loto": shortcut_loto(df),
        "mechanism_recoverability": recoverability(df, full, "mechanism"),
        "mechanism_recoverability_grouped": grouped_recoverability(df, full, "mechanism"),
        "repair_class_recoverability": recoverability(df, full, "prov_repair_class_BANNED"),
        "repair_class_recoverability_grouped": grouped_recoverability(df, full, "repair_class"),
        "mechanism_holdout": mechanism_holdout(df, full),
        "note": "Recoverability values are in-sample upper bounds; features are the exact full predeployment Tier C set. No predicted severity feature.",
    }
    (OUT / "v3_secondary_checks.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
