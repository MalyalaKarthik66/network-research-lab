"""Pilot analysis. Implements docs/PILOT-PREREGISTRATION.md §15 (statistics), §14 (baselines) and, once D1-D9 are
approved, the gates and decision of §6-§12 and §16 via v4lib/gates.py.

    ./.venv/Scripts/python.exe v4_transient/analysis/analyze_pilot.py --plan smoke   # engineering validation only
    ./.venv/Scripts/python.exe v4_transient/analysis/analyze_pilot.py --plan pilot

What this script deliberately does NOT do:
  * it contains no gate threshold, no noise-floor rule and no G2 unit/aggregator. Gate verdicts are computed only
    when v4lib.decisions.check_approval passes, from the approved config/pilot_decisions.json;
  * it does not compute every candidate option's verdict after data exist (that would invite choosing post hoc);
  * for --plan smoke it computes nothing gate-related at all (§17).
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))
warnings.filterwarnings("ignore")

import matplotlib                                                    # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                      # noqa: E402
import numpy as np                                                   # noqa: E402
import pandas as pd                                                  # noqa: E402
from scipy.stats import spearmanr                                    # noqa: E402
from sklearn.ensemble import RandomForestRegressor                  # noqa: E402
from sklearn.linear_model import LinearRegression                   # noqa: E402

from v4lib import decisions as DEC                                   # noqa: E402
from v4lib import gates as GATES                                     # noqa: E402
from v4lib.analytic import FEATURE_COLUMNS                           # noqa: E402

TARGETS = ["T1_disruption_area", "T2_peak_disruption", "T3_disruption_duration"]
PRIMARY = "T1_disruption_area"
DESCRIPTIVE = TARGETS + ["T1_upper_undetermined_as_broken", "T1_merge10ms", "detour_area", "probe_lost_packet_s_window",
                         "fib_settle_s"]
BASELINES = {                                                        # §14, frozen
    "B2_r_exact": ["feat_r_exact"],
    "B3_fib_entries_changed": ["feat_n_fib_entries_changed"],
    "B4_microloop_potential": ["feat_pml_flow_frac"],
    "B5_combined_analytic": ["feat_r_exact", "feat_n_fib_entries_changed", "feat_pml_flow_frac", "feat_n_devices_pushed"],
    "B6_graph_analytic": ["feat_changed_link_betweenness", "feat_golden_mean_path_len", "feat_n_routers"],
}
assert tuple(BASELINES) == DEC.BASELINE_IDS
SEED = 20260914


def r2(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    d = ((y - y.mean()) ** 2).sum()
    return float(1 - ((y - p) ** 2).sum() / d) if d > 0 else float("nan")


def variance_components(df, col):
    """§8: one-way random-effects ANOVA, method of moments, unequal replicates via n0."""
    g = df.groupby("change_id")[col]
    k = g.count()
    k = k[k > 0]
    G, N = len(k), int(k.sum())
    if G < 2 or (k < 2).all():
        return {"note": "not estimable (fewer than 2 changes or no change with 2+ replicates)"}
    s2 = g.var(ddof=1).reindex(k.index)
    msw = float(((k - 1) * s2.fillna(0)).sum() / (k - 1).sum())
    means = g.mean().reindex(k.index)
    grand = float(df[col].mean())
    msb = float((k * (means - grand) ** 2).sum() / (G - 1))
    n0 = float((N - (k ** 2).sum() / N) / (G - 1))
    var_b = max((msb - msw) / n0, 0.0)
    tot = var_b + msw
    und = float("nan")
    return {"MSW": msw, "MSB": msb, "n0": n0, "within_var": msw, "between_var": var_b,
            "within_share": msw / tot if tot > 0 else und, "icc1": var_b / tot if tot > 0 else und,
            "reliability_mean_of_5": var_b / (var_b + msw / 5) if (var_b + msw / 5) > 0 else und,
            "n_changes": G, "n_runs": N, "total_variance_zero": bool(tot == 0)}


def loto(X, y, groups, make):
    pred = np.full(len(y), np.nan)
    for g in sorted(set(groups)):
        te, tr = groups == g, groups != g
        if tr.sum():
            pred[te] = make(X[tr], y[tr], X[te])
    return pred


def fit_lin(Xtr, ytr, Xte):
    return LinearRegression().fit(Xtr, ytr).predict(Xte)


def fit_mean(Xtr, ytr, Xte):
    return np.full(len(Xte), ytr.mean())


def fit_rf(Xtr, ytr, Xte):
    return RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=0, n_jobs=-1).fit(Xtr, ytr).predict(Xte)


def perm_spearman(x, y, rng, n=2000):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 4 or np.std(x) == 0 or np.std(y) == 0:
        return {"rho": None, "p": None, "n": int(len(x)), "note": "not estimable"}
    rho = spearmanr(x, y).correlation
    null = [spearmanr(x, rng.permutation(y)).correlation for _ in range(n)]
    return {"rho": float(rho), "p": float((np.sum(np.abs(null) >= abs(rho)) + 1) / (n + 1)), "n": int(len(x))}


def change_bootstrap(change_ids, rng, n=2000):
    """§15 change-level bootstrap: draw changes with replacement and keep every row of each drawn change.
    On a change-mean table (one row per change, sorted) this is the same draw as resampling rows."""
    ids = np.asarray(change_ids)
    uniq = sorted(set(ids.tolist()))
    blocks = [np.flatnonzero(ids == c) for c in uniq]
    return [np.concatenate([blocks[i] for i in rng.choice(len(uniq), len(uniq), replace=True)]) for _ in range(n)]


def baselines_on(df_unit, y_col, rng):
    """§14 baselines, leave-one-topology-out, on one unit table (rows = change means or runs)."""
    if len(df_unit) < 4 or df_unit.topology.nunique() < 2 or df_unit[y_col].std() == 0:
        return {"note": "not computable (too few rows/topologies or zero variance)"}
    y = df_unit[y_col].to_numpy(float)
    groups = df_unit.topology.to_numpy()
    mech = df_unit.mechanism.to_numpy()
    preds = {"B0_constant": loto(np.zeros((len(y), 1)), y, groups, fit_mean)}
    b1 = np.full(len(y), np.nan)
    for g in sorted(set(groups)):
        te, tr = groups == g, groups != g
        means = pd.Series(y[tr]).groupby(mech[tr]).mean()
        b1[te] = [means.get(m, y[tr].mean()) for m in mech[te]]
    preds["B1_mechanism_lookup"] = b1
    for name, cols in BASELINES.items():
        preds[name] = loto(df_unit[cols].to_numpy(float), y, groups, fit_lin)
    Xml = np.column_stack([df_unit[[f"feat_{c}" for c in FEATURE_COLUMNS]].to_numpy(float),
                           pd.get_dummies(df_unit.mechanism).to_numpy(float)])
    preds["ML_random_forest"] = loto(Xml, y, groups, fit_rf)
    boots = change_bootstrap(df_unit.change_id.to_numpy(), rng)
    out = {}
    for k, p in preds.items():
        bs = [r2(y[b], p[b]) for b in boots]
        out[k] = {"loto_r2": r2(y, p), "mae": float(np.nanmean(np.abs(y - p))),
                  "bootstrap_ci": [float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))],
                  "predictions": p.tolist()}
    for name in BASELINES:
        d = [r2(y[b], preds["ML_random_forest"][b]) - r2(y[b], preds[name][b]) for b in boots]
        out[name]["ml_minus_this"] = {"delta_r2": out["ML_random_forest"]["loto_r2"] - out[name]["loto_r2"],
                                     "bootstrap_ci": [float(np.nanpercentile(d, 2.5)), float(np.nanpercentile(d, 97.5))]}
    out["_note"] = ("change-level bootstrap (whole changes resampled); predictions are LOTO over only 4 topology "
                    "clusters, so the CI is weak and descriptive (pre-registration §15); no gate uses it under D5")
    return out


def gate_inputs(root, runs, pop, chg, out, decisions_doc):
    """Assemble v4lib.gates inputs. Rules R9 and R12 of gates.MACHINERY_RULES are applied here."""
    man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
    plan_runs = json.loads((V4 / "manifests" / "run_plan_pilot.json").read_text())["runs"]
    info = {c["change_id"]: c for c in man["changes"]}
    have = set(runs.run_id)
    missing = pd.DataFrame([{"run_id": r["run_id"], "change_id": r["change_id"], "kind": info[r["change_id"]]["kind"],
                             "topology": info[r["change_id"]]["topology"], "status": "NOT_RUN", "valid": False}
                            for r in plan_runs if r["run_id"] not in have])
    runs_gate = pd.concat([runs, missing], ignore_index=True) if len(missing) else runs
    m = decisions_doc["decisions"]["D7_min_valid_replicates"]["min_valid_replicates_per_change"]
    counts = pop.groupby("change_id").size()
    eligible = sorted(c for c, n in counts.items() if n >= m)
    baselines = {"change_means": baselines_on(chg[chg.change_id.isin(eligible)].reset_index(drop=True), PRIMARY,
                                              np.random.default_rng(SEED)),
                 "runs": baselines_on(pop.reset_index(drop=True), PRIMARY, np.random.default_rng(SEED))}
    return {"runs": runs_gate, "variance_T1": out["variance_components"][PRIMARY], "baselines": baselines,
            "host_timing": out["host_timing"],
            "planned_population_runs": sum(1 for r in plan_runs if info[r["change_id"]]["kind"] == "population")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", choices=["smoke", "pilot"], required=True)
    a = ap.parse_args()
    rng = np.random.default_rng(SEED)
    root = V4 / "results" / a.plan
    plots = V4 / "plots" / a.plan
    plots.mkdir(parents=True, exist_ok=True)
    runs = pd.read_csv(root / "run_metrics.csv")
    runs["valid"] = runs["valid"].fillna(False).astype(str).str.lower().isin(["true", "1"])
    out = {"plan": a.plan,
           "status": ("ENGINEERING VALIDATION ONLY -- no gate or scientific interpretation (pre-registration §17)"
                      if a.plan == "smoke" else "pilot analysis; gate verdicts only from approved D1-D9 decisions"),
           "n_runs_planned": int(len(runs))}
    valid = runs[runs.valid]
    pop = valid[valid.kind == "population"].copy()
    noop = valid[valid.kind == "control_noop"].copy()
    posc = valid[valid.kind == "control_positive"].copy()
    out["validity"] = {"planned_by_kind": runs.groupby("kind").size().to_dict(),
                       "valid_by_kind": valid.groupby("kind").size().to_dict(),
                       "status_counts": runs.groupby("status").size().to_dict()}

    stats = {}
    for t in DESCRIPTIVE:
        if t not in pop or pop.empty:
            continue
        g = pop.groupby("change_id")[t]
        s = pd.DataFrame({"mean": g.mean(), "median": g.median(), "sd": g.std(ddof=1), "min": g.min(),
                          "max": g.max(), "n_valid": g.count()})
        s["cv"] = np.where(s["mean"] > 0, s["sd"] / s["mean"], np.nan)
        stats[t] = s
        s.to_csv(root / f"per_change_{t}.csv")
    out["per_change"] = {t: s.reset_index().to_dict("records") for t, s in stats.items()}

    chg = None
    if a.plan == "pilot":
        out["variance_components"] = {t: variance_components(pop, t) for t in TARGETS}
        out["distribution"] = {t: {"run_zero_share": float((pop[t] == 0).mean()), "run_mean": float(pop[t].mean()),
                                   "run_median": float(pop[t].median()), "run_max": float(pop[t].max())} for t in TARGETS}
        out["noop_controls_T1"] = noop[["run_id", "topology", PRIMARY]].to_dict("records")
        out["positive_controls"] = posc[["run_id", "topology"] + TARGETS].to_dict("records")
        chg = pop.groupby("change_id").agg(**{PRIMARY: (PRIMARY, "mean"), "topology": ("topology", "first"),
                                               "mechanism": ("mechanism", "first"),
                                               **{f"feat_{c}": (f"feat_{c}", "first") for c in FEATURE_COLUMNS}}).reset_index()
        out["baselines_change_means"] = baselines_on(chg, PRIMARY, rng)
        out["baselines_runs"] = baselines_on(pop, PRIMARY, rng)
        pop["resid"] = pop[PRIMARY] - pop.groupby("change_id")[PRIMARY].transform("mean")
        out["host_timing"] = {"resid_vs_order": perm_spearman(pop.order, pop.resid, rng),
                              "resid_vs_loadavg1": perm_spearman(pop.loadavg1_before, pop.resid, rng),
                              "resid_vs_wallclock": perm_spearman(pop.t_wall_start, pop.resid, rng),
                              "noop_T1_vs_order": perm_spearman(noop.order, noop[PRIMARY], rng),
                              "probe_vs_T1": perm_spearman(pop.get("probe_lost_packet_s_window"), pop[PRIMARY], rng),
                              "convergence_s": valid.convergence_s.describe().to_dict()}
        walls = runs[(runs.kind == "population")].wall_s
        out["runtime"] = {"median_wall_s_population_final_attempt": float(walls.median()),
                          "describe": walls.describe().to_dict()}
        ok, why, dec_doc, appr = DEC.load_approved(V4)
        if not ok:
            out["gates"] = f"NOT EVALUATED: {why} (pre-registration §19; docs/D1-D9-DECISION-SCHEMA.md)"
        else:
            defects_p = root / "PROTOCOL-DEFECTS.json"
            defects = json.loads(defects_p.read_text()) if defects_p.exists() else []
            out["gates"] = GATES.evaluate(gate_inputs(root, runs, pop, chg, out, dec_doc), dec_doc, defects)
            out["gates"]["approval"] = {k: appr.get(k) for k in ("approved_by", "approved_utc", "prereg_sha256",
                                                                 "decisions_sha256")}

    ts_dir = root / "timeseries"

    def load_ts(rid):
        f = ts_dir / f"{rid}.csv"
        return pd.read_csv(f) if f.exists() else None

    def step(ts, col, grid):
        t = ts.t_rel.to_numpy(float)
        v = ts[col].fillna(0).to_numpy(float)
        idx = np.searchsorted(t, grid, side="right") - 1
        return np.where(idx >= 0, v[np.clip(idx, 0, len(v) - 1)], v[0])

    produced = []
    if not pop.empty:
        mechs = sorted(pop.mechanism.unique())
        fig, axes = plt.subplots(1, len(mechs), figsize=(5 * len(mechs), 3.6), squeeze=False)
        for ax, m in zip(axes[0], mechs):
            sub = pop[pop.mechanism == m]
            row = sub.iloc[int((sub[PRIMARY] - sub[PRIMARY].median()).abs().to_numpy().argmin())]
            ts = load_ts(row.run_id)
            if ts is None:
                continue
            H = max(5.0, float(row.T3_disruption_duration) + 2.0, float(row.fib_settle_s) + 1.0)
            grid = np.linspace(-1, H, 2000)
            for col, lab in (("broken_excess", "broken (transient excess)"), ("detour", "transient detour"),
                             ("rerouted_vs_golden", "rerouted vs golden"), ("undetermined", "undetermined")):
                ax.step(grid, step(ts, col, grid), where="post", label=lab)
            ax.axvline(0, color="k", lw=0.8, ls="--")
            ax.set_title(f"{m}: {row.run_id}", fontsize=9)
            ax.set_xlabel("seconds from first push"); ax.set_ylabel("fraction of carried flows")
        axes[0][0].legend(fontsize=7)
        fig.tight_layout(); fig.savefig(plots / "1_representative_curves.png", dpi=130); plt.close(fig)
        produced.append("1_representative_curves.png")

        ids = pop.sort_values(["mechanism", "change_id", "replicate"]).run_id.tolist()
        H = float(min(30.0, max(5.0, pop.T3_disruption_duration.max() + 2, pop.fib_settle_s.max() + 1)))
        grid = np.linspace(0, H, 600)
        mat = [step(t_, "broken_excess", grid) if (t_ := load_ts(r)) is not None else np.full(len(grid), np.nan) for r in ids]
        fig, ax = plt.subplots(figsize=(9, max(3, len(ids) * 0.12)))
        im = ax.imshow(np.array(mat), aspect="auto", extent=[0, H, len(ids), 0], cmap="magma")
        ax.set_yticks(np.arange(len(ids)) + 0.5); ax.set_yticklabels(ids, fontsize=5)
        ax.set_xlabel("seconds from first push"); ax.set_title("transient excess broken-flow fraction per run")
        fig.colorbar(im, ax=ax, label="fraction")
        fig.tight_layout(); fig.savefig(plots / "2_disruption_heatmap.png", dpi=150); plt.close(fig)
        produced.append("2_disruption_heatmap.png")

        s = stats[PRIMARY].sort_values("mean")
        fig, ax = plt.subplots(figsize=(max(6, len(s) * 0.5 + 2), 4))
        for i, cid in enumerate(s.index):
            vals = pop[pop.change_id == cid][PRIMARY]
            ax.scatter(np.full(len(vals), i) + rng.uniform(-0.12, 0.12, len(vals)), vals, s=16, alpha=0.7)
            ax.errorbar(i, s.loc[cid, "mean"], yerr=0 if np.isnan(s.loc[cid, "sd"]) else s.loc[cid, "sd"], fmt="k_", capsize=4)
        if not noop.empty:
            ax.scatter(np.full(len(noop), len(s)) + rng.uniform(-0.12, 0.12, len(noop)), noop[PRIMARY], marker="x", c="grey",
                       label="no-op controls")
            ax.legend(fontsize=7)
        ax.set_xticks(range(len(s) + (0 if noop.empty else 1)))
        ax.set_xticklabels(list(s.index) + ([] if noop.empty else ["no-op"]), rotation=70, fontsize=7)
        ax.set_ylabel("T1 disruption area (flow-fraction·s)"); ax.set_title("replicates (points), mean ± sd (bars)")
        fig.tight_layout(); fig.savefig(plots / "3_replicate_consistency.png", dpi=130); plt.close(fig)
        produced.append("3_replicate_consistency.png")

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(pop[PRIMARY], bins=30, alpha=0.6, label="runs")
        ax.hist(stats[PRIMARY]["mean"], bins=30, alpha=0.6, label="change means")
        if not noop.empty:
            ax.plot(noop[PRIMARY], np.zeros(len(noop)), "r|", ms=20, label="no-op controls")
        ax.set_xlabel("T1 disruption area"); ax.legend(); ax.set_title("distribution of T1")
        fig.tight_layout(); fig.savefig(plots / "4_distribution.png", dpi=130); plt.close(fig)
        produced.append("4_distribution.png")

    bl = out.get("baselines_change_means")
    if isinstance(bl, dict) and "note" not in bl:
        chg_y = chg[PRIMARY].to_numpy(float)
        names = [k for k in bl if not k.startswith("_")]
        best = max(BASELINES, key=lambda k: -np.inf if np.isnan(bl[k]["loto_r2"]) else bl[k]["loto_r2"])
        sd = stats[PRIMARY]["sd"].reindex(chg.change_id).fillna(0).to_numpy()
        lim = [float(np.nanmin([chg_y.min(), np.nanmin(bl[best]["predictions"])])),
               float(np.nanmax([chg_y.max(), np.nanmax(bl[best]["predictions"])]))]
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.errorbar(bl[best]["predictions"], chg_y, yerr=sd, fmt="o", capsize=3)
        ax.plot(lim, lim, "k--", lw=0.8)
        ax.set_xlabel(f"{best} LOTO prediction (highest descriptive R² among B2-B6)")
        ax.set_ylabel("change-mean T1 (± sd)")
        fig.tight_layout(); fig.savefig(plots / "5_analytic_vs_measured.png", dpi=130); plt.close(fig)
        produced.append("5_analytic_vs_measured.png")
        g = out.get("gates") if isinstance(out.get("gates"), dict) else None
        if g and g["G1_measurable"]["outcome"] == "PASS" and g["G3_repeatable"]["outcome"] != "KILL":
            fig, ax = plt.subplots(figsize=(5, 5))
            ax.errorbar(bl["ML_random_forest"]["predictions"], chg_y, yerr=sd, fmt="o", capsize=3)
            ax.plot(lim, lim, "k--", lw=0.8)
            ax.set_xlabel("RandomForest LOTO prediction (feasibility only)")
            ax.set_ylabel("change-mean T1 (± sd)")
            fig.tight_layout(); fig.savefig(plots / "6_ml_vs_measured.png", dpi=130); plt.close(fig)
            produced.append("6_ml_vs_measured.png")
        else:
            why6 = ("gates not evaluated (D1-D9 not approved)" if not g else
                    f"G1 {g['G1_measurable']['outcome']}, G3 {g['G3_repeatable']['outcome']}")
            (plots / "6_ml_vs_measured.NOT_PRODUCED.txt").write_text(
                f"Not produced: ML plot is shown only when G1 passes and G3 does not kill ({why6}).\n", encoding="utf-8")
        fig, ax = plt.subplots(figsize=(9, 4))
        vals = [bl[k]["loto_r2"] for k in names]
        err = [[max(bl[k]["loto_r2"] - bl[k]["bootstrap_ci"][0], 0) for k in names],
               [max(bl[k]["bootstrap_ci"][1] - bl[k]["loto_r2"], 0) for k in names]]
        ax.bar(range(len(names)), vals, yerr=err, capsize=3, color=["#999"] * (len(names) - 1) + ["#c44"])
        ax.axhline(0, color="k", lw=0.6)
        ax.set_xticks(range(len(names))); ax.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel("LOTO R² on change-mean T1 (row bootstrap 95% CI)")
        ax.set_title("baselines vs ML feasibility (descriptive; the G2 rule is D5)")
        fig.tight_layout(); fig.savefig(plots / "7_baseline_vs_ml.png", dpi=130); plt.close(fig)
        produced.append("7_baseline_vs_ml.png")
    out["plots_produced"] = produced
    (root / "analysis.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8", newline="\n")
    print(json.dumps({k: out[k] for k in ("plan", "status", "validity", "plots_produced")}, indent=1, default=str))


if __name__ == "__main__":
    main()
