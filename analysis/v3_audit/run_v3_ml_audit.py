"""Frozen v3 regression audit: LOTO, mechanism baselines, calibration, shortcut.

The target is measured r from compute_measured_r.py. Predicted severity is never
used as a feature. Main features are assembled by the existing phase4 loader and
feature filter, with Tier C as the full predeployment feature set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "analysis" / "v3_audit"
PILOT = ROOT / "data" / "pilot-v3"


def model():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(
        learning_rate=0.05, max_iter=300, max_leaf_nodes=15,
        l2_regularization=1.0, random_state=0)


def matrix(df, cols):
    x = df[list(cols)].copy()
    for col in cols:
        if x[col].dtype == object:
            x[col] = x[col].map({"PASS": 0.0, "FAIL": 1.0, True: 1.0, False: 0.0})
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.fillna(0.0)
    keep = [col for col in cols if x[col].std() > 0]
    return x[keep].to_numpy(dtype=float), keep


def r2(y, pred):
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    den = float(np.sum((y - y.mean()) ** 2))
    return float(1.0 - np.sum((y - pred) ** 2) / den) if den else None


def mae(y, pred):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(pred))))


def rmse(y, pred):
    return float(np.sqrt(np.mean((np.asarray(y) - np.asarray(pred)) ** 2)))


def loto(df, cols, subset=None):
    work = df if subset is None else df[df.mechanism == subset].copy()
    x, kept = matrix(work, cols)
    y = work.r.to_numpy(float)
    groups = work.topology.to_numpy()
    pred = np.full(len(work), np.nan)
    folds = []
    for group in sorted(set(groups)):
        test = groups == group
        train = ~test
        if train.sum() < 2 or test.sum() == 0:
            continue
        fit = model()
        fit.fit(x[train], y[train])
        pred[test] = fit.predict(x[test])
        folds.append({"topology": group, "n": int(test.sum()), "r2": r2(y[test], pred[test]),
                      "mae": mae(y[test], pred[test]), "rmse": rmse(y[test], pred[test])})
    valid = np.isfinite(pred)
    return {"n": int(valid.sum()), "features": kept, "pred": pred, "y": y,
            "groups": groups, "r2": r2(y[valid], pred[valid]),
            "mae": mae(y[valid], pred[valid]), "rmse": rmse(y[valid], pred[valid]),
            "mean_fold_r2": float(np.mean([f["r2"] for f in folds])),
            "folds": folds}


def bootstrap_loto(result, n=2000):
    rng = np.random.default_rng(20260913)
    y, pred, groups = result["y"], result["pred"], result["groups"]
    unique = np.array(sorted(set(groups)))
    values = []
    for _ in range(n):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([np.flatnonzero(groups == group) for group in sampled])
        values.append(r2(y[idx], pred[idx]))
    return {"resamples": n, "cluster": "topology", "low_2_5": float(np.quantile(values, .025)),
            "median": float(np.quantile(values, .5)), "high_97_5": float(np.quantile(values, .975))}


def calibration(result):
    valid = np.isfinite(result["pred"])
    y, pred = result["y"][valid], result["pred"][valid]
    slope, intercept = np.polyfit(pred, y, 1)
    order = np.argsort(pred)
    bins = []
    for idx in np.array_split(order, 4):
        bins.append({"n": int(len(idx)), "predicted_mean": float(pred[idx].mean()),
                     "observed_mean": float(y[idx].mean()),
                     "mse": float(np.mean((y[idx] - pred[idx]) ** 2))})
    return {"slope": float(slope), "intercept": float(intercept), "bins": bins,
            "bins_with_observed_in_predicted_interval": sum(
                abs(b["observed_mean"] - b["predicted_mean"]) <= 0.05 for b in bins)}


def _binomial_log_loss(probability, successes, trials):
    from scipy.special import xlogy
    p = np.clip(np.asarray(probability, dtype=float), 1e-9, 1.0 - 1e-9)
    successes = np.asarray(successes, dtype=float)
    failures = np.asarray(trials, dtype=float) - successes
    return float(-np.sum(xlogy(successes, p) + xlogy(failures, 1.0 - p))
                 / np.sum(trials))


def _fit_calibrator(kind, raw_probability, successes, trials):
    from scipy.optimize import minimize
    from scipy.special import expit

    raw = np.clip(np.asarray(raw_probability, dtype=float), 1e-6, 1.0 - 1e-6)
    logit = np.log(raw) - np.log1p(-raw)
    if kind == "platt":
        def transform(theta):
            return expit(theta[0] * logit + theta[1])
        initial = np.array([1.0, 0.0])
    elif kind == "beta":
        log_p = np.log(raw)
        log_not_p = np.log1p(-raw)
        def transform(theta):
            return expit(theta[0] * log_p + theta[1] * log_not_p + theta[2])
        initial = np.array([1.0, -1.0, 0.0])
    else:
        raise ValueError(f"unknown calibrator: {kind}")

    fit = minimize(lambda theta: _binomial_log_loss(
        transform(theta), successes, trials), initial, method="BFGS")
    if not fit.success:
        raise RuntimeError(f"{kind} calibration failed: {fit.message}")
    return {"kind": kind, "parameters": fit.x.tolist(), "loss": float(fit.fun)}


def _apply_calibrator(calibrator, raw_probability):
    from scipy.special import expit
    raw = np.clip(np.asarray(raw_probability, dtype=float), 1e-6, 1.0 - 1e-6)
    theta = np.asarray(calibrator["parameters"], dtype=float)
    if calibrator["kind"] == "platt":
        return expit(theta[0] * (np.log(raw) - np.log1p(-raw)) + theta[1])
    return expit(theta[0] * np.log(raw) + theta[1] * np.log1p(-raw) + theta[2])


def _exact_binomial_interval(successes, trials, alpha=0.05):
    from scipy.stats import beta
    if successes == 0:
        return 0.0, float(beta.ppf(1.0 - alpha / 2.0, 1, trials + 1))
    if successes == trials:
        return float(beta.ppf(alpha / 2.0, trials + 1, 1)), 1.0
    return (float(beta.ppf(alpha / 2.0, successes, trials - successes + 1)),
            float(beta.ppf(1.0 - alpha / 2.0, successes + 1, trials - successes)))


def nested_grouped_calibration(df, cols):
    """Nested grouped calibration using flow-count binomial log loss.

    Outer folds hold out topology groups. Within each outer training partition,
    four grouped incident folds produce calibration predictions. Platt and beta
    are fitted only to those calibration predictions; lower calibration log loss
    selects the calibrator, with ties going to Platt. The final outer-training
    model is then calibrated and evaluated once on the untouched outer test.
    """
    from sklearn.model_selection import GroupKFold

    x, kept = matrix(df, cols)
    y = df.r.to_numpy(float)
    successes = (df.broken_flows + df.rerouted_flows).to_numpy(float)
    trials = df.golden_carried_flows.to_numpy(float)
    groups = df.topology.to_numpy()
    incident_groups = df.incident_id.to_numpy()
    raw_test = np.full(len(df), np.nan)
    calibrated_test = np.full(len(df), np.nan)
    fold_rows = []
    outer = GroupKFold(n_splits=5)
    for fold, (outer_train, outer_test) in enumerate(
            outer.split(x, y, groups=groups), 1):
        inner_x = x[outer_train]
        inner_y = y[outer_train]
        inner_successes = successes[outer_train]
        inner_trials = trials[outer_train]
        inner_groups = incident_groups[outer_train]
        calibration_raw = np.full(len(outer_train), np.nan)
        inner = GroupKFold(n_splits=4)
        for inner_train, inner_calibration in inner.split(
                inner_x, inner_y, groups=inner_groups):
            fit = model()
            fit.fit(inner_x[inner_train], inner_y[inner_train])
            calibration_raw[inner_calibration] = fit.predict(inner_x[inner_calibration])
        valid_calibration = np.isfinite(calibration_raw)
        platt = _fit_calibrator("platt", calibration_raw[valid_calibration],
                                inner_successes[valid_calibration], inner_trials[valid_calibration])
        beta = _fit_calibrator("beta", calibration_raw[valid_calibration],
                               inner_successes[valid_calibration], inner_trials[valid_calibration])
        selected = "beta" if beta["loss"] < platt["loss"] else "platt"
        selected_calibrator = beta if selected == "beta" else platt
        final_fit = model()
        final_fit.fit(x[outer_train], y[outer_train])
        raw = final_fit.predict(x[outer_test])
        calibrated = _apply_calibrator(selected_calibrator, raw)
        raw_test[outer_test] = raw
        calibrated_test[outer_test] = calibrated
        fold_rows.append({
            "fold": fold,
            "test_topologies": sorted(set(groups[outer_test])),
            "outer_train_n": int(len(outer_train)),
            "outer_test_n": int(len(outer_test)),
            "inner_calibration_n": int(valid_calibration.sum()),
            "platt_calibration_log_loss": platt["loss"],
            "beta_calibration_log_loss": beta["loss"],
            "selected": selected,
            "selected_parameters": selected_calibrator["parameters"],
            "test_raw_log_loss": _binomial_log_loss(
                raw, successes[outer_test], trials[outer_test]),
            "test_calibrated_log_loss": _binomial_log_loss(
                calibrated, successes[outer_test], trials[outer_test]),
        })
    valid = np.isfinite(calibrated_test)
    slope, intercept = np.polyfit(calibrated_test[valid], y[valid], 1)
    order = np.argsort(calibrated_test[valid])
    bins = []
    for indices in np.array_split(order, 4):
        absolute = np.flatnonzero(valid)[indices]
        total_successes = int(successes[absolute].sum())
        total_trials = int(trials[absolute].sum())
        low, high = _exact_binomial_interval(total_successes, total_trials)
        predicted_mean = float(calibrated_test[absolute].mean())
        observed_fraction = total_successes / total_trials
        bins.append({
            "n_candidates": int(len(absolute)),
            "predicted_mean": predicted_mean,
            "observed_fraction": observed_fraction,
            "observed_exact_95pct_low": low,
            "observed_exact_95pct_high": high,
            "predicted_mean_inside_observed_interval": low <= predicted_mean <= high,
        })
    return {
        "protocol": "nested grouped 5-fold; outer groups=topology, inner calibration groups=incident",
        "calibrator_target": "affected flows / golden-carried flows",
        "log_loss": "binomial negative log likelihood over affected and unaffected flows",
        "n": int(valid.sum()), "features": kept,
        "folds": fold_rows,
        "calibrators_selected": {kind: sum(row["selected"] == kind for row in fold_rows)
                                  for kind in ("platt", "beta")},
        "calibration_slope": float(slope), "calibration_intercept": float(intercept),
        "bins": bins,
        "bins_passing": sum(row["predicted_mean_inside_observed_interval"] for row in bins),
        "raw_test_log_loss": _binomial_log_loss(raw_test[valid], successes[valid], trials[valid]),
        "calibrated_test_log_loss": _binomial_log_loss(
            calibrated_test[valid], successes[valid], trials[valid]),
    }


def mechanism_baseline(df, mech):
    work = df[df.mechanism == mech]
    y = work.r.to_numpy(float)
    groups = work.topology.to_numpy()
    pred = np.zeros(len(work))
    for group in sorted(set(groups)):
        test = groups == group
        train = ~test
        pred[test] = y[train].mean() if train.any() else y.mean()
    return {"n": len(y), "r2": r2(y, pred), "mae": mae(y, pred), "rmse": rmse(y, pred)}


def main():
    from nrl.phase4 import feature_columns, load
    measured = pd.read_csv(OUT / "measured_blast_radius.csv")
    measured["r"] = pd.to_numeric(measured["r"], errors="coerce")
    measured = measured[measured.r.notna()].copy()
    loaded = load(PILOT)
    df = loaded["meta"].merge(loaded["p2"], on=["candidate_id", "incident_id"], how="inner")
    df = df.merge(measured[["candidate_id", "r", "mechanism", "predicted_severity",
                            "golden_carried_flows", "broken_flows", "rerouted_flows"]],
                  on="candidate_id", how="inner")
    for column in ("golden_carried_flows", "broken_flows", "rerouted_flows"):
        df[column] = pd.to_numeric(df[column], errors="raise")
    cols_c, removed = feature_columns(df, "C")
    cols_shortcut = [c for c in df.columns if c.startswith("chg_")]
    full = loto(df, cols_c)
    shortcut = loto(df, cols_shortcut)
    within = {mech: loto(df, cols_c, mech) for mech in sorted(df.mechanism.unique())}
    baselines = {mech: mechanism_baseline(df, mech) for mech in sorted(df.mechanism.unique())}
    result = {
        "n": len(df), "full_features": full["features"], "removed_by_filter": removed,
        "predicted_severity_in_features": False,
        "full_loto": {k: v for k, v in full.items() if k not in {"pred", "y", "groups"}},
        "full_bootstrap_ci": bootstrap_loto(full),
        "shortcut_only_loto": {k: v for k, v in shortcut.items() if k not in {"pred", "y", "groups"}},
        "shortcut_bootstrap_ci": bootstrap_loto(shortcut),
        "shortcut_r2_gap": full["r2"] - shortcut["r2"],
        "calibration": calibration(full),
        "nested_grouped_calibration": nested_grouped_calibration(df, cols_c),
        "within_mechanism": {}, "mechanism_mean_baseline": baselines,
    }
    for mech, value in within.items():
        result["within_mechanism"][mech] = {
            "loto": {k: v for k, v in value.items() if k not in {"pred", "y", "groups"}},
            "bootstrap_ci": bootstrap_loto(value),
            "beats_baseline_by_r2": value["r2"] - baselines[mech]["r2"],
        }
    (OUT / "v3_ml_audit.json").write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    print(json.dumps(result, indent=2, default=float))


if __name__ == "__main__":
    main()
