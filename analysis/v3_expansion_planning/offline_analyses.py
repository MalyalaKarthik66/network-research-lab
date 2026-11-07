"""EXPLORATORY post-result analyses for expansion planning. Not confirmatory.

    ./.venv/Scripts/python.exe analysis/v3_expansion_planning/offline_analyses.py

Everything here was run AFTER the v3 gates were seen. Nothing in this file may be
used to change a v3 gate, threshold or verdict. Its only purpose is to decide
what a future, separately pre-registered experiment should look like.

Sections: 1 feature-set ablation incl. P06 (topology-cluster CIs, paired deltas)
          2 incremental information inside mechanism x P06 cells
          3 learning curves: topologies, candidates, mechanisms
          4 model zoo with NESTED topology-grouped selection
          5 uncertainty: split-conformal, Mondrian-by-mechanism, CQR
          6 operational triage: recall@budget, AUC/PR-AUC, per-topology regret
          7 scorecard extras
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import (ExtraTreesRegressor, HistGradientBoostingRegressor,
                              RandomForestRegressor)
from sklearn.linear_model import Ridge
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import nrl.phase4 as P

OUT = Path(__file__).resolve().parent / "offline_analyses.json"
T0 = time.time()
R = {"status": "EXPLORATORY, post-result; cannot change any v3 gate"}


def say(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


def r2(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = ((a - a.mean()) ** 2).sum()
    return float(1 - ((a - b) ** 2).sum() / d) if d > 0 else float("nan")


def hgb():
    return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=300, max_leaf_nodes=15,
                                         l2_regularization=1.0, random_state=0)


# ---------------------------------------------------------------------------
L = P.load(REPO / "data/pilot-v3")
df = L["meta"].merge(L["p2"], on=["candidate_id", "incident_id"], how="inner")
man = pd.DataFrame(json.loads((REPO / "data/pilot-v3/manifest.json").read_text())["candidates"])
tgt = pd.read_csv(REPO / "analysis/v3_claude_final/r_three_way.csv")
df = (df.merge(man[["candidate_id", "mechanism", "repair_class", "repair_id", "predicted_severity"]],
               on="candidate_id")
        .merge(tgt[["candidate_id", "golden_flows", "broken", "rerouted", "r_rib"]], on="candidate_id")
        .sort_values("candidate_id").reset_index(drop=True))
y = df.r_rib.to_numpy(float)
n = len(y)
topo = df.topology.to_numpy()
mech = df.mechanism.to_numpy()
T = np.array(sorted(set(topo)))
TIX = {t: np.flatnonzero(topo == t) for t in T}
cols, _ = P.feature_columns(df, "C")
X, live, _ = P.matrix(df, cols)
col = {c: i for i, c in enumerate(live)}
CFG = [c for c in live if c.startswith(("chg_", "cov_"))]
GRAPH = [c for c in live if c.startswith("g_")]
ORACLE = [c for c in live if c.startswith("verdict_")]
BFB = [c for c in live if c not in CFG + GRAPH + ORACLE]
MECH, P06 = ["chg_touches_cost"], ["verdict_P06"]
assert set(CFG + GRAPH + ORACLE + BFB) == set(live) and "chg_touches_cost" in live
R["feature_groups"] = {"config_change": CFG, "graph": GRAPH, "batfish_tierB": BFB, "oracle_only": ORACLE}
say(f"n={n} topologies={len(T)} groups: cfg {len(CFG)} graph {len(GRAPH)} bfB {len(BFB)} oracle {ORACLE}")


def Xof(c):
    return X[:, [col[x] for x in c]]


rng0 = np.random.default_rng(0)
BOOT = [np.concatenate([TIX[t] for t in rng0.choice(T, len(T))]) for _ in range(2000)]


def loto(Xm, factory=hgb, train_filter=None):
    pred = np.full(n, np.nan)
    for gi, g in enumerate(T):
        te, tr = TIX[g], np.flatnonzero(topo != g)
        if train_filter is not None:
            tr = train_filter(gi, g, tr)
        pred[te] = factory().fit(Xm[tr], y[tr]).predict(Xm[te])
    return pred


def lookup(keys, train_filter=None):
    key = np.array(["|".join(map(str, t)) for t in zip(*keys)])
    pred = np.zeros(n)
    for gi, g in enumerate(T):
        te, tr = TIX[g], np.flatnonzero(topo != g)
        if train_filter is not None:
            tr = train_filter(gi, g, tr)
        means = pd.Series(y[tr]).groupby(key[tr]).mean().to_dict()
        pred[te] = [means.get(k, y[tr].mean()) for k in key[te]]
    return pred


def metrics(p):
    per = [r2(y[TIX[t]], p[TIX[t]]) for t in T]
    bs = [r2(y[i], p[i]) for i in BOOT]
    return {"pooled_r2": r2(y, p), "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "per_fold_mean": float(np.mean(per)), "per_fold_sd": float(np.std(per, ddof=1)),
            "per_fold_min": float(np.min(per)), "mae": float(np.abs(y - p).mean()),
            "rmse": float(np.sqrt(((y - p) ** 2).mean())), "spearman": float(spearmanr(p, y).correlation)}


def delta(pa, pb):
    d = np.array([r2(y[i], pa[i]) - r2(y[i], pb[i]) for i in BOOT])
    return {"delta_r2": r2(y, pa) - r2(y, pb), "ci": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "share_boot_le_0": float((d <= 0).mean())}


# ===========================================================================
say("1. feature-set ablation")
kP06, kMech = X[:, col["verdict_P06"]], X[:, col["chg_touches_cost"]]
preds = {
    "lookup: mechanism": lookup([kMech]),
    "lookup: P06": lookup([kP06]),
    "lookup: mechanism x P06": lookup([kMech, kP06]),
    "lookup: repair_class": lookup([df.repair_class.to_numpy()]),
}
sets = {
    "mechanism only": MECH, "P06 only": P06, "P06 + mechanism": P06 + MECH,
    "config-change only": CFG, "graph only": GRAPH, "Batfish Tier B only": BFB,
    "Batfish all (Tier B + oracle-only)": BFB + ORACLE,
    "non-Batfish (config + graph)": CFG + GRAPH, "Batfish B + graph": BFB + GRAPH,
    "Batfish B + config": BFB + CFG, "P06 + mechanism + graph": P06 + MECH + GRAPH,
    "Tier B = full minus all oracle-only": CFG + GRAPH + BFB,
    "full minus P06": [c for c in live if c != "verdict_P06"], "full (Tier C)": live,
}
for name, c in sets.items():
    preds[name] = loto(Xof(c))
preds["analytic severity model (not a feature; reference)"] = df.predicted_severity.to_numpy(float)
R["ablation"] = {k: metrics(v) for k, v in preds.items()}
for k, v in R["ablation"].items():
    say(f"   {k:52s} R2 {v['pooled_r2']:7.4f} [{v['ci'][0]:.3f},{v['ci'][1]:.3f}] MAE {v['mae']:.4f}")
LK = preds["lookup: mechanism x P06"]
pairs = [("full (Tier C)", "lookup: mechanism x P06"), ("Tier B = full minus all oracle-only", "lookup: mechanism x P06"),
         ("full (Tier C)", "full minus P06"), ("full (Tier C)", "Tier B = full minus all oracle-only"),
         ("Tier B = full minus all oracle-only", "non-Batfish (config + graph)"),
         ("P06 + mechanism + graph", "lookup: mechanism x P06"), ("full (Tier C)", "P06 + mechanism + graph"),
         ("non-Batfish (config + graph)", "lookup: mechanism")]
R["paired_deltas"] = {f"{a} MINUS {b}": delta(preds[a], preds[b]) for a, b in pairs}
for k, v in R["paired_deltas"].items():
    say(f"   d {k:90s} {v['delta_r2']:+.4f} [{v['ci'][0]:+.3f},{v['ci'][1]:+.3f}] P(<=0) {v['share_boot_le_0']:.3f}")

# ===========================================================================
say("2. incremental information inside mechanism x P06 cells")
cell = np.array([f"{int(a)}|{int(b)}" for a, b in zip(kMech, kP06)])
R["within_cells"] = {}
for name in ("full (Tier C)", "Tier B = full minus all oracle-only", "non-Batfish (config + graph)"):
    p = preds[name]
    frac = 1 - ((y - p) ** 2).sum() / ((y - LK) ** 2).sum()
    bs = [1 - ((y[i] - p[i]) ** 2).sum() / ((y[i] - LK[i]) ** 2).sum() for i in BOOT]
    per_cell = {}
    for c_ in sorted(set(cell)):
        ix = np.flatnonzero(cell == c_)
        per_cell[c_] = {"n": len(ix), "r_sd": float(y[ix].std()),
                        "spearman_within": float(spearmanr(p[ix], y[ix]).correlation),
                        "r2_vs_loto_cell_mean": r2(y[ix], p[ix]) if False else
                        float(1 - ((y[ix] - p[ix]) ** 2).sum() / ((y[ix] - LK[ix]) ** 2).sum())}
    R["within_cells"][name] = {"lookup_residual_variance_explained": float(frac),
                               "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                               "cells": per_cell}
    say(f"   {name:40s} explains {frac:.3f} [{np.percentile(bs, 2.5):.3f},{np.percentile(bs, 97.5):.3f}] "
        f"of lookup residual SSE; cells {json.dumps({k: round(v['spearman_within'], 2) for k, v in per_cell.items()})}")

# ===========================================================================
say("3. learning curves")


def f_topo(k, draw):
    def f(gi, g, tr):
        rest = np.array([t for t in T if t != g])
        pick = np.random.default_rng(1000 * draw + gi).choice(rest, k, replace=False)
        return tr[np.isin(topo[tr], pick)]
    return f


def f_cand(frac, draw):
    def f(gi, g, tr):
        rng = np.random.default_rng(2000 * draw + gi)
        keep = []
        for t in sorted(set(topo[tr])):
            ix = tr[topo[tr] == t]
            keep.append(rng.choice(ix, max(1, int(round(frac * len(ix)))), replace=False))
        return np.concatenate(keep)
    return f


XB, XC = Xof(CFG + GRAPH + BFB), X
rf300 = lambda: RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=0, n_jobs=-1)
LC = {"topologies": {}, "candidates": {}}
for k in (2, 4, 7, 9, 11):
    draws = 1 if k == 11 else 20
    row = {m: [] for m in ("tierB_hgb", "tierC_hgb", "tierC_rf", "lookup_mech_x_P06")}
    for d in range(draws):
        f = f_topo(k, d)
        row["tierB_hgb"].append(r2(y, loto(XB, hgb, f)))
        row["tierC_hgb"].append(r2(y, loto(XC, hgb, f)))
        row["tierC_rf"].append(r2(y, loto(XC, rf300, f)))
        row["lookup_mech_x_P06"].append(r2(y, lookup([kMech, kP06], f)))
    LC["topologies"][k] = {m: {"mean": float(np.mean(v)), "sd": float(np.std(v)), "p10": float(np.percentile(v, 10)),
                               "p90": float(np.percentile(v, 90))} for m, v in row.items()}
    say(f"   train topologies {k:2d}: " + "  ".join(f"{m} {LC['topologies'][k][m]['mean']:.3f}±{LC['topologies'][k][m]['sd']:.3f}" for m in row))
for frac in (0.2, 0.4, 0.6, 0.8, 1.0):
    draws = 1 if frac == 1.0 else 20
    row = {m: [] for m in ("tierB_hgb", "tierC_hgb", "lookup_mech_x_P06")}
    for d in range(draws):
        f = f_cand(frac, d)
        row["tierB_hgb"].append(r2(y, loto(XB, hgb, f)))
        row["tierC_hgb"].append(r2(y, loto(XC, hgb, f)))
        row["lookup_mech_x_P06"].append(r2(y, lookup([kMech, kP06], f)))
    LC["candidates"][frac] = {m: {"mean": float(np.mean(v)), "sd": float(np.std(v))} for m, v in row.items()}
    say(f"   train candidates {frac:.0%} of 11 topologies: " + "  ".join(f"{m} {LC['candidates'][frac][m]['mean']:.3f}±{LC['candidates'][frac][m]['sd']:.3f}" for m in row))
LC["mechanisms"] = {}
for m in ("blackhole", "cost"):
    idx = np.flatnonzero(mech == m)
    both = loto(XC, hgb)
    only = loto(XC, hgb, lambda gi, g, tr, m=m: tr[mech[tr] == m])
    LC["mechanisms"][m] = {"trained_on_both_r2_within": r2(y[idx], both[idx]),
                           "trained_on_own_only_r2_within": r2(y[idx], only[idx])}
    say(f"   {m}: within-mechanism R2 trained on both {LC['mechanisms'][m]['trained_on_both_r2_within']:.3f}, "
        f"own only {LC['mechanisms'][m]['trained_on_own_only_r2_within']:.3f}")
R["learning_curves"] = LC

# ===========================================================================
say("4. model zoo, nested topology-grouped selection")
ZOO = {
    "hgb": hgb,
    "rf": lambda: RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=0, n_jobs=-1),
    "extratrees": lambda: ExtraTreesRegressor(n_estimators=300, min_samples_leaf=2, random_state=0, n_jobs=-1),
    "ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
    "knn5": lambda: make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=5, weights="distance")),
}
R["model_zoo"] = {}
for tier, Xm in (("tierB", XB), ("tierC", XC)):
    outer = {m: np.full(n, np.nan) for m in ZOO}
    chosen, nested = [], np.full(n, np.nan)
    for gi, g in enumerate(T):
        te, tr = TIX[g], np.flatnonzero(topo != g)
        inner = {}
        for m, fac in ZOO.items():
            ip = np.full(n, np.nan)
            for h in T:
                if h == g:
                    continue
                ite, itr = TIX[h], tr[topo[tr] != h]
                ip[ite] = fac().fit(Xm[itr], y[itr]).predict(Xm[ite])
            inner[m] = r2(y[tr], ip[tr])
            outer[m][te] = fac().fit(Xm[tr], y[tr]).predict(Xm[te])
        best = max(inner, key=inner.get)
        chosen.append(best)
        nested[te] = outer[best][te]
    ens = np.mean([outer["hgb"], outer["rf"], outer["extratrees"]], axis=0)
    R["model_zoo"][tier] = {"each_model_outer_descriptive": {m: metrics(p) for m, p in outer.items()},
                            "nested_selected": metrics(nested), "selection_counts": pd.Series(chosen).value_counts().to_dict(),
                            "prespecified_ensemble_hgb_rf_et": metrics(ens)}
    say(f"   {tier}: " + "  ".join(f"{m} {R['model_zoo'][tier]['each_model_outer_descriptive'][m]['pooled_r2']:.3f}" for m in ZOO)
        + f"  | nested {R['model_zoo'][tier]['nested_selected']['pooled_r2']:.3f} chose {R['model_zoo'][tier]['selection_counts']}"
        + f"  | ensemble {R['model_zoo'][tier]['prespecified_ensemble_hgb_rf_et']['pooled_r2']:.3f}")

# ===========================================================================
say("5. uncertainty: split-conformal inside LOTO")


def conformal(Xm, tier):
    out = {}
    lvl = (0.2, 0.1, 0.05)
    lo = {k: {a: np.full(n, np.nan) for a in lvl} for k in ("absolute", "mondrian_mechanism")}
    hi = {k: {a: np.full(n, np.nan) for a in lvl} for k in lo}
    cq_lo, cq_hi = np.full(n, np.nan), np.full(n, np.nan)
    for gi, g in enumerate(T):
        te = TIX[g]
        trmask = topo != g
        inner = P.grouped_folds(topo[trmask], 4, seed=gi + 1)
        calm = np.isin(topo, inner[0]) & trmask
        fit = trmask & ~calm
        m = hgb().fit(Xm[fit], y[fit])
        pc, pt = m.predict(Xm[calm]), m.predict(Xm[te])
        res = np.abs(y[calm] - pc)
        for a in lvl:
            def q(v):
                k_ = int(np.ceil((len(v) + 1) * (1 - a)))
                return np.inf if k_ > len(v) else np.sort(v)[k_ - 1]
            qa = q(res)
            lo["absolute"][a][te], hi["absolute"][a][te] = np.clip(pt - qa, 0, 1), np.clip(pt + qa, 0, 1)
            for mv in (0.0, 1.0):
                cm = X[calm, col["chg_touches_cost"]] == mv
                tm = X[te, col["chg_touches_cost"]] == mv
                qm = q(res[cm]) if cm.sum() else qa
                lo["mondrian_mechanism"][a][te[tm]] = np.clip(pt[tm] - qm, 0, 1)
                hi["mondrian_mechanism"][a][te[tm]] = np.clip(pt[tm] + qm, 0, 1)
        qlo = HistGradientBoostingRegressor(loss="quantile", quantile=0.05, max_iter=300, learning_rate=0.05,
                                            max_leaf_nodes=15, random_state=0).fit(Xm[fit], y[fit])
        qhi = HistGradientBoostingRegressor(loss="quantile", quantile=0.95, max_iter=300, learning_rate=0.05,
                                            max_leaf_nodes=15, random_state=0).fit(Xm[fit], y[fit])
        s = np.maximum(qlo.predict(Xm[calm]) - y[calm], y[calm] - qhi.predict(Xm[calm]))
        k_ = int(np.ceil((len(s) + 1) * 0.9))
        qs = np.inf if k_ > len(s) else np.sort(s)[k_ - 1]
        cq_lo[te] = np.clip(qlo.predict(Xm[te]) - qs, 0, 1)
        cq_hi[te] = np.clip(qhi.predict(Xm[te]) + qs, 0, 1)

    def summ(l, h):
        cov = (y >= l) & (y <= h)
        return {"coverage": float(cov.mean()), "mean_width": float((h - l).mean()),
                "coverage_blackhole": float(cov[mech == "blackhole"].mean()),
                "coverage_cost": float(cov[mech == "cost"].mean()),
                "width_blackhole": float((h - l)[mech == "blackhole"].mean()),
                "width_cost": float((h - l)[mech == "cost"].mean()),
                "worst_topology_coverage": float(min(cov[TIX[t]].mean() for t in T))}
    for kind in lo:
        for a in lvl:
            out[f"{kind}_{int((1 - a) * 100)}"] = summ(lo[kind][a], hi[kind][a])
    out["cqr_90"] = summ(cq_lo, cq_hi)
    for k, v in out.items():
        say(f"   {tier} {k:26s} coverage {v['coverage']:.3f} width {v['mean_width']:.3f} "
            f"(bh {v['coverage_blackhole']:.2f}/{v['width_blackhole']:.3f}, cost {v['coverage_cost']:.2f}/{v['width_cost']:.3f}) "
            f"worst topology {v['worst_topology_coverage']:.2f}")
    return out


R["conformal"] = {"tierB": conformal(XB, "tierB"), "tierC": conformal(XC, "tierC")}

# ===========================================================================
say("6. operational triage")
perm = np.random.default_rng(0).permutation(n)
tiebreak = np.empty(n)
tiebreak[perm] = np.arange(n) * 1e-9
scores = {"tierB_model": preds["Tier B = full minus all oracle-only"], "tierC_model": preds["full (Tier C)"],
          "lookup_mech_x_P06": LK, "batfish_oracle_fail_count": X[:, col["verdict_P06"]] + X[:, col["verdict_P11"]],
          "non_batfish_model": preds["non-Batfish (config + graph)"],
          "analytic_severity_model_reference": df.predicted_severity.to_numpy(float)}
TRI = {}
for tau in (0.10, 0.20):
    pos = y >= tau
    TRI[tau] = {"n_positive": int(pos.sum()), "prevalence": float(pos.mean())}
    for s, v in scores.items():
        sc = v + tiebreak
        order = np.argsort(-sc)
        rec = {}
        for q_ in (0.1, 0.2, 0.3, 0.5):
            top = order[:int(round(q_ * n))]
            rec[q_] = {"recall": float(pos[top].sum() / pos.sum()), "precision": float(pos[top].mean()),
                       "missed": int(pos.sum() - pos[top].sum())}
        TRI[tau][s] = {"auc_roc": float(roc_auc_score(pos, sc)), "pr_auc": float(average_precision_score(pos, sc)),
                       "recall_at_budget": rec}
        say(f"   tau {tau:.2f} {s:36s} AUC {TRI[tau][s]['auc_roc']:.3f} PR-AUC {TRI[tau][s]['pr_auc']:.3f} "
            f"recall@20% {rec[0.2]['recall']:.2f} @30% {rec[0.3]['recall']:.2f} @50% {rec[0.5]['recall']:.2f}")
    TRI[tau]["random_expected"] = {"auc_roc": 0.5, "pr_auc": float(pos.mean()), "recall_at_budget": {q_: q_ for q_ in (0.1, 0.2, 0.3, 0.5)}}
REG = {}
for s, v in scores.items():
    regs, sps, rand = [], [], []
    for t in T:
        ix = TIX[t]
        pick = ix[np.argmin(v[ix] + tiebreak[ix])]
        regs.append(y[pick] - y[ix].min())
        rand.append(y[ix].mean() - y[ix].min())
        sps.append(spearmanr(v[ix], y[ix]).correlation if np.std(v[ix]) > 0 else np.nan)
    REG[s] = {"mean_top1_regret": float(np.mean(regs)), "random_expected_regret": float(np.mean(rand)),
              "mean_within_topology_spearman": float(np.nanmean(sps))}
    say(f"   {s:36s} safest-change regret {REG[s]['mean_top1_regret']:.4f} (random {REG[s]['random_expected_regret']:.4f}) "
        f"within-topology Spearman {REG[s]['mean_within_topology_spearman']:.3f}")
R["triage"] = {"thresholds_are_arbitrary_engineering_choices": True, "by_threshold": TRI, "per_topology_selection": REG}

# ===========================================================================
say("7. scorecard extras")


def frac_ce(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def binned_abs_err(p):
    return float(np.mean([abs(y[b].mean() - p[b].mean()) for b in np.array_split(np.argsort(p, kind="stable"), 4)]))


R["scorecard_extras"] = {
    "n_candidates": n, "n_topologies": len(T), "n_mechanisms": 2, "distinct_r": int(len(np.unique(np.round(y, 6)))),
    "zero_fraction": float((y == 0).mean()), "r_mean": float(y.mean()), "r_median": float(np.median(y)),
    "r_max": float(y.max()), "r_sd_blackhole": float(y[mech == "blackhole"].std()), "r_sd_cost": float(y[mech == "cost"].std()),
    "fractional_cross_entropy": {k: frac_ce(preds[k]) for k in ("full (Tier C)", "Tier B = full minus all oracle-only", "lookup: mechanism x P06")},
    "binned_abs_calibration_error_4bins": {k: binned_abs_err(preds[k]) for k in ("full (Tier C)", "Tier B = full minus all oracle-only", "lookup: mechanism x P06")},
    "constant_mean_fractional_ce": frac_ce(np.full(n, y.mean())),
}
say(json.dumps(R["scorecard_extras"], indent=1))
OUT.write_text(json.dumps(R, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)), encoding="utf-8")
say(f"wrote {OUT}")
