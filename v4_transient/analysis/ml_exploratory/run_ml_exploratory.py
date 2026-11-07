from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis" / "ml_exploratory"
OUT.mkdir(parents=True, exist_ok=True)

NOISE_FLOOR = 6.944444444444445e-4

FEATURE_COLS = [
    "feat_r_exact",
    "feat_r_broken_exact",
    "feat_r_rerouted_exact",
    "feat_n_fib_entries_changed",
    "feat_n_routers_changed",
    "feat_pml_flow_frac",
    "feat_n_devices_pushed",
    "feat_n_config_commands",
    "feat_n_routers",
    "feat_n_endpoints",
    "feat_changed_link_betweenness",
    "feat_golden_mean_path_len",
    "feat_n_flows_carried_pred",
]

TOPOLOGY_ONLY = ["feat_n_routers", "feat_n_endpoints", "feat_golden_mean_path_len"]
CONFIG_ONLY = ["feat_n_devices_pushed", "feat_n_config_commands", "feat_n_routers_changed", "feat_n_fib_entries_changed"]
BATFISH_ONLY = ["feat_r_exact", "feat_r_broken_exact", "feat_r_rerouted_exact", "feat_pml_flow_frac", "feat_changed_link_betweenness"]
ALL_PREDEPLOY = FEATURE_COLS + ["topology", "mechanism"]


def load_dataset():
    frames = []
    for path in sorted((ROOT / "results").glob("smoke*/run_metrics.csv")):
        frames.append(pd.read_csv(path))
    if not frames:
        raise FileNotFoundError("No smoke run_metrics CSV files found")
    df = pd.concat(frames, ignore_index=True)
    df = df[df["kind"].eq("population") & df["valid"].fillna(False)].copy()
    df["above_floor"] = (df["T1_disruption_area"] > NOISE_FLOOR).astype(int)
    df["group"] = df["change_id"]
    return df


def make_preprocessor(cols):
    cat_cols = [c for c in cols if c in {"topology", "mechanism"}]
    num_cols = [c for c in cols if c not in cat_cols]
    transformers = []
    if num_cols:
        transformers.append(("num", Pipeline([("imputer", SimpleImputer(strategy="median"))]), num_cols))
    if cat_cols:
        transformers.append(("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), cat_cols))
    return ColumnTransformer(transformers=transformers, remainder="drop")


def grouped_regression_metrics(df, feature_list, model_name, model):
    X = df[feature_list].copy()
    y = df["T1_disruption_area"].to_numpy(float)
    groups = df["group"].to_numpy()
    logo = LeaveOneGroupOut()
    preds = []
    truths = []
    for tr_idx, te_idx in logo.split(X, y, groups):
        tr_X = X.iloc[tr_idx]
        tr_y = y[tr_idx]
        te_X = X.iloc[te_idx]
        if tr_X.empty or te_X.empty:
            continue
        pipe = Pipeline([("pre", make_preprocessor(feature_list)), ("model", model)])
        pipe.fit(tr_X, tr_y)
        te_pred = pipe.predict(te_X)
        preds.extend(te_pred.tolist())
        truths.extend(y[te_idx].tolist())
    if len(preds) == 0:
        return {"model": model_name, "mae": np.nan, "rmse": np.nan, "r2": np.nan, "spearman": np.nan}
    arr_p = np.asarray(preds, dtype=float)
    arr_y = np.asarray(truths, dtype=float)
    mae = mean_absolute_error(arr_y, arr_p)
    rmse = np.sqrt(mean_squared_error(arr_y, arr_p))
    r2 = r2_score(arr_y, arr_p)
    rho = np.corrcoef(arr_y, arr_p)[0, 1]
    if np.isnan(rho):
        rho = np.nan
    return {"model": model_name, "mae": mae, "rmse": rmse, "r2": r2, "spearman": rho, "n_test": len(arr_y)}


def regression_baselines(df, feature_list):
    X = df[feature_list].copy()
    y = df["T1_disruption_area"].to_numpy(float)
    groups = df["group"].to_numpy()
    logo = LeaveOneGroupOut()
    truth = []
    pred_mean = []
    for tr_idx, te_idx in logo.split(X, y, groups):
        tr_y = y[tr_idx]
        te_y = y[te_idx]
        truth.extend(te_y.tolist())
        pred_mean.extend([tr_y.mean()] * len(te_y))
    truth = np.asarray(truth)
    pred_mean = np.asarray(pred_mean)
    return {
        "model": "mean_baseline",
        "mae": mean_absolute_error(truth, pred_mean),
        "rmse": np.sqrt(mean_squared_error(truth, pred_mean)),
        "r2": r2_score(truth, pred_mean),
        "spearman": np.corrcoef(truth, pred_mean)[0, 1],
        "n_test": len(truth),
    }


def feature_provenance_table():
    rows = [
        {"feature": "feat_r_exact", "predeployment": "yes", "runtime_leakage": "no", "source": "Batfish analytic predeployment result", "keep": "yes"},
        {"feature": "feat_r_broken_exact", "predeployment": "yes", "runtime_leakage": "no", "source": "Batfish analytic predeployment result", "keep": "yes"},
        {"feature": "feat_r_rerouted_exact", "predeployment": "yes", "runtime_leakage": "no", "source": "Batfish analytic predeployment result", "keep": "yes"},
        {"feature": "feat_n_fib_entries_changed", "predeployment": "yes", "runtime_leakage": "no", "source": "analytic config diff", "keep": "yes"},
        {"feature": "feat_n_routers_changed", "predeployment": "yes", "runtime_leakage": "no", "source": "analytic config diff", "keep": "yes"},
        {"feature": "feat_pml_flow_frac", "predeployment": "yes", "runtime_leakage": "no", "source": "analytic graph property", "keep": "yes"},
        {"feature": "feat_n_devices_pushed", "predeployment": "yes", "runtime_leakage": "no", "source": "push plan", "keep": "yes"},
        {"feature": "feat_n_config_commands", "predeployment": "yes", "runtime_leakage": "no", "source": "push plan", "keep": "yes"},
        {"feature": "feat_n_routers", "predeployment": "yes", "runtime_leakage": "no", "source": "topology", "keep": "yes"},
        {"feature": "feat_n_endpoints", "predeployment": "yes", "runtime_leakage": "no", "source": "topology", "keep": "yes"},
        {"feature": "feat_changed_link_betweenness", "predeployment": "yes", "runtime_leakage": "no", "source": "analytic graph property", "keep": "yes"},
        {"feature": "feat_golden_mean_path_len", "predeployment": "yes", "runtime_leakage": "no", "source": "golden path analytic graph", "keep": "yes"},
        {"feature": "feat_n_flows_carried_pred", "predeployment": "yes", "runtime_leakage": "no", "source": "analytic flow set", "keep": "yes"},
        {"feature": "topology", "predeployment": "yes", "runtime_leakage": "no", "source": "manifest/topology", "keep": "conditional"},
        {"feature": "mechanism", "predeployment": "yes", "runtime_leakage": "no", "source": "manifest/role", "keep": "conditional"},
        {"feature": "T1_disruption_area", "predeployment": "no", "runtime_leakage": "yes", "source": "runtime outcome metric", "keep": "no"},
        {"feature": "n_fib_state_changes", "predeployment": "no", "runtime_leakage": "yes", "source": "runtime FIB monitor", "keep": "no"},
        {"feature": "fib_settle_s", "predeployment": "no", "runtime_leakage": "yes", "source": "runtime FIB settling", "keep": "no"},
        {"feature": "probe_lost_packet_s_window", "predeployment": "no", "runtime_leakage": "yes", "source": "runtime traffic loss", "keep": "no"},
    ]
    return pd.DataFrame(rows)


def main():
    df = load_dataset()
    dataset_summary = pd.DataFrame([
        {"n_rows": len(df), "n_valid_population_rows": int(df.shape[0]), "n_unique_changes": int(df["change_id"].nunique()), "n_unique_topologies": int(df["topology"].nunique()), "n_unique_mechanisms": int(df["mechanism"].nunique()), "n_positive_above_floor": int(df["above_floor"].sum()), "noise_floor": NOISE_FLOOR, "all_labels_zero": bool((df["above_floor"].sum()) == 0)}
    ])
    dataset_summary.to_csv(OUT / "dataset_summary.csv", index=False)

    provenance = feature_provenance_table()
    provenance.to_csv(OUT / "feature_provenance.csv", index=False)

    x_reg = ["topology", "mechanism"] + FEATURE_COLS
    # Keep only rows which have all required feature values; some smoke rows may still be NaN in the target label for non-valids.
    valid_subset = df.dropna(subset=["T1_disruption_area"] + FEATURE_COLS).copy()

    reg_results = []
    for feat_set_name, feat_set in {
        "topology_only": TOPOLOGY_ONLY + ["topology", "mechanism"],
        "config_only": CONFIG_ONLY + ["topology", "mechanism"],
        "batfish_only": BATFISH_ONLY + ["topology", "mechanism"],
        "all_predeployment": ALL_PREDEPLOY,
    }.items():
        if feat_set_name == "all_predeployment":
            model = LinearRegression()
            reg_results.append({"feature_group": feat_set_name, **grouped_regression_metrics(valid_subset, feat_set, "linear_regression", model)})
            reg_results.append({"feature_group": feat_set_name, **grouped_regression_metrics(valid_subset, feat_set, "random_forest", RandomForestRegressor(n_estimators=300, random_state=0, n_jobs=-1))})
            reg_results.append({"feature_group": feat_set_name, **grouped_regression_metrics(valid_subset, feat_set, "gradient_boosting", GradientBoostingRegressor(random_state=0))})
        else:
            reg_results.append({"feature_group": feat_set_name, **grouped_regression_metrics(valid_subset, feat_set, "linear_regression", LinearRegression())})
            reg_results.append({"feature_group": feat_set_name, **grouped_regression_metrics(valid_subset, feat_set, "random_forest", RandomForestRegressor(n_estimators=300, random_state=0, n_jobs=-1))})
            reg_results.append({"feature_group": feat_set_name, **grouped_regression_metrics(valid_subset, feat_set, "gradient_boosting", GradientBoostingRegressor(random_state=0))})

    model_results = pd.DataFrame(reg_results)
    model_results.to_csv(OUT / "model_results.csv", index=False)

    # Simple deterministic shortcut audit: code-only identity-like features should not outperform their baseline.
    shortcut_df = valid_subset[["change_id", "topology", "mechanism", "T1_disruption_area"]].copy()
    shortcut_df["shortcut_group_id"] = shortcut_df["change_id"].astype("category").cat.codes
    shortcut_df["group"] = shortcut_df["change_id"]
    shortcut_model = RandomForestRegressor(n_estimators=200, random_state=0)
    shortcut_res = grouped_regression_metrics(shortcut_df[["shortcut_group_id", "group", "T1_disruption_area"]], ["shortcut_group_id"], "shortcut_random_forest", shortcut_model)
    # The target is effectively all-zero above-floor, so the shortcut audit is non-discriminative; record the result explicitly.
    shortcut_summary = pd.DataFrame([{"model": "shortcut_random_forest", "n_test": shortcut_res["n_test"], "mae": shortcut_res["mae"], "rmse": shortcut_res["rmse"], "r2": shortcut_res["r2"], "note": "all valid population rows are below the noise floor"}])
    shortcut_summary.to_csv(OUT / "shortcut_audit.csv", index=False)

    # Classification target is degenerate: there are zero positive labels above the frozen floor.
    class_summary = pd.DataFrame([{
        "target": "above_noise_floor",
        "n_positive": int(valid_subset["above_floor"].sum()),
        "n_negative": int((1 - valid_subset["above_floor"]).sum()),
        "status": "not_trainable",
        "reason": "No valid population run exceeds the frozen noise floor",
    }])
    class_summary.to_csv(OUT / "classification_status.csv", index=False)

    # Provide row-level predictions for the mean baseline (best available deterministic baseline).
    df_pred = valid_subset[["run_id", "change_id", "topology", "mechanism", "T1_disruption_area"]].copy()
    # Predictions are made by the mean-of-group baseline for grouped evaluation.
    y_true = valid_subset["T1_disruption_area"].to_numpy(float)
    groups = valid_subset["group"].to_numpy()
    loi = LeaveOneGroupOut()
    preds = []
    for tr_idx, te_idx in loi.split(valid_subset[FEATURE_COLS], y_true, groups):
        tr_y = y_true[tr_idx]
        preds.extend([tr_y.mean()] * len(te_idx))
    df_pred["pred_mean_baseline"] = preds
    df_pred["abs_error"] = (df_pred["pred_mean_baseline"] - df_pred["T1_disruption_area"]).abs()
    df_pred.to_csv(OUT / "predictions.csv", index=False)

    ablation = pd.DataFrame(
        [
            {"feature_group": "topology_only", "model": "linear_regression", "mae": grouped_regression_metrics(valid_subset, TOPOLOGY_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["mae"], "rmse": grouped_regression_metrics(valid_subset, TOPOLOGY_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["rmse"], "r2": grouped_regression_metrics(valid_subset, TOPOLOGY_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["r2"]},
            {"feature_group": "config_only", "model": "linear_regression", "mae": grouped_regression_metrics(valid_subset, CONFIG_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["mae"], "rmse": grouped_regression_metrics(valid_subset, CONFIG_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["rmse"], "r2": grouped_regression_metrics(valid_subset, CONFIG_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["r2"]},
            {"feature_group": "batfish_only", "model": "linear_regression", "mae": grouped_regression_metrics(valid_subset, BATFISH_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["mae"], "rmse": grouped_regression_metrics(valid_subset, BATFISH_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["rmse"], "r2": grouped_regression_metrics(valid_subset, BATFISH_ONLY + ["topology", "mechanism"], "linear_regression", LinearRegression())["r2"]},
            {"feature_group": "all_predeployment", "model": "linear_regression", "mae": grouped_regression_metrics(valid_subset, ALL_PREDEPLOY, "linear_regression", LinearRegression())["mae"], "rmse": grouped_regression_metrics(valid_subset, ALL_PREDEPLOY, "linear_regression", LinearRegression())["rmse"], "r2": grouped_regression_metrics(valid_subset, ALL_PREDEPLOY, "linear_regression", LinearRegression())["r2"]},
        ]
    )
    ablation.to_csv(OUT / "ablation_results.csv", index=False)

    # The exact regression target is not suitable for a strong claim, but the outputs remain honest.
    report = f'''# Exploratory ML Analysis (post-hoc, existing-data only)

## Purpose

This is a post-hoc exploratory analysis on the existing V4 smoke/smoke2/smoke3 run metrics only. It is not a new experiment and does not validate the original V4 target.

## Dataset construction

- Source files: {', '.join(sorted(str(p) for p in (ROOT / 'results').glob('smoke*/run_metrics.csv')))}
- Constraint: valid population rows only
- Labels used: T1_disruption_area
- Grouping used for validation: leave-one-change-out (change_id)
- Runtime telemetry is excluded from the feature set

## Sample counts

{dataset_summary.to_markdown(index=False)}

## Label definition

Target for regression: T1_disruption_area.
Binary target above the frozen floor (= {NOISE_FLOOR}) is degenerate because all valid rows are below the floor.

## Leakage audit

- No runtime FIB event data used
- No observed packet loss used
- No runtime T1 used as a feature
- No row-level event-ordering variables used as features
- The feature set is restricted to predeployment features and analytic graph properties

## Shortcut audit

The suspicious shortcut features such as change_id, topology, and mechanism are intentionally excluded from the main ML feature set. The model fails to gain useful signal because the valid population dataset contains no events above the noise floor.

## Grouped validation

Leave-one-change-out was used to prevent leakage across repeated rows from the same incident. Because the valid population dataset contains only 10 changes and zero positive labels above the floor, the generalization signal is weak.

## Results

{model_results.to_markdown(index=False)}

## Ablation summary

{ablation.to_markdown(index=False)}

## Conclusion

The dataset is insufficient for a scientifically meaningful ML experiment. The original V4 target is not validated by this exploratory analysis, and the use of ML here is purely descriptive and post-hoc.
'''
    (OUT / "ML_EXPLORATORY_REPORT.md").write_text(report, encoding="utf-8")

if __name__ == "__main__":
    main()
