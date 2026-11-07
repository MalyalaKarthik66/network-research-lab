"""§8 gates on measured r under amendment 12.4 (docs/ANALYSIS-PLAN-V3.md). Run once.

    ./.venv/Scripts/python.exe analysis/v3_claude_final/final_gates_12_4.py

Analysis only. Implements 12.4.3 exactly; every choice is cited there. Writes
final_gates_12_4.json next to this file and records the git commit it ran from.
"""
from __future__ import annotations

import json
import subprocess
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, xlogy
from scipy.stats import beta as beta_dist
from sklearn.ensemble import (HistGradientBoostingRegressor, RandomForestRegressor,
                              HistGradientBoostingClassifier)
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import KFold

import nrl.phase4 as P

OUT = Path(__file__).resolve().parent / "final_gates_12_4.json"
PILOT = REPO / "data" / "pilot-v3"
EPS = 1e-6
B = P.BOOTSTRAP_RESAMPLES           # 2000


def say(*a):
    print(*a, flush=True)


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def estimator():
    return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=300, max_leaf_nodes=15,
                                         l2_regularization=1.0, random_state=0)


def r2(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    d = ((y - y.mean()) ** 2).sum()
    return float(1 - ((y - p) ** 2).sum() / d) if d > 0 else float("nan")


# ---------------------------------------------------------------------------
# provenance: refuse to run from a tree where 12.4 is not committed
# ---------------------------------------------------------------------------
plan = (REPO / "docs/ANALYSIS-PLAN-V3.md").read_text(encoding="utf-8")
assert "## 12.4 Calibration is not executable as written" in plan, "amendment 12.4 missing"
dirty = git("status", "--porcelain", "--", "docs/ANALYSIS-PLAN-V3.md",
            "analysis/v3_claude_final/final_gates_12_4.py")
assert not dirty, f"12.4 plan or this script is uncommitted:\n{dirty}"
HEAD = git("rev-parse", "HEAD")
RESULT = {"commit": HEAD, "amendment": "ANALYSIS-PLAN-V3.md 12.4"}
say(f"commit {HEAD}")

# ---------------------------------------------------------------------------
# data, through the frozen loader
# ---------------------------------------------------------------------------
L = P.load(PILOT)
df = L["meta"].merge(L["p2"], on=["candidate_id", "incident_id"], how="inner")
man = pd.DataFrame(json.loads((PILOT / "manifest.json").read_text())["candidates"])
tgt = pd.read_csv(REPO / "analysis/v3_claude_final/r_three_way.csv")
df = (df.merge(man[["candidate_id", "mechanism", "repair_class", "repair_id", "predicted_severity"]],
               on="candidate_id")
        .merge(tgt[["candidate_id", "golden_flows", "broken", "rerouted", "r_rib"]], on="candidate_id")
        .sort_values("candidate_id").reset_index(drop=True))
assert len(df) == 151
y = df.r_rib.to_numpy(float)
k = (df.broken + df.rerouted).to_numpy(float)
n = df.golden_flows.to_numpy(float)
topo = df.topology.to_numpy()
mech = df.mechanism.to_numpy()
T = sorted(set(topo))
assert len(T) == 12 and df.groupby("incident_id").topology.nunique().max() == 1

# ---------------------------------------------------------------------------
say("\n=== STOP-AND-FIX and degeneracy (§8) ===")
oc = L["outcomes"].set_index("candidate_id").loc[df.candidate_id]
spec_dis = float((oc.spec_violations_vs_golden.notna().to_numpy()
                  != (df.batfish_spec_verdict != "PASS").to_numpy()).mean())
mae_pred = float(np.abs(df.predicted_severity - y).mean())
distinct = int(len(np.unique(np.round(y, 6))))
mode_share = float(pd.Series(np.round(y, 6)).value_counts(normalize=True).iloc[0])
stop_fix = {"spec_disagreement": spec_dis, "spec_ok": spec_dis <= 0.10,
            "mae_pred_vs_measured": mae_pred, "mae_ok": mae_pred <= 0.10,
            "distinct_r": distinct, "mode_share": mode_share,
            "degenerate": distinct < 20 or mode_share > 0.70}
say(json.dumps(stop_fix, indent=1))
RESULT["stop_fix"] = stop_fix


# ---------------------------------------------------------------------------
def loto(X, idx=None, factory=estimator):
    idx = np.arange(len(y)) if idx is None else np.asarray(idx)
    pred = np.full(len(y), np.nan)
    per = []
    for g in sorted(set(topo[idx])):
        te, tr = idx[topo[idx] == g], idx[topo[idx] != g]
        pred[te] = factory().fit(X[tr], y[tr]).predict(X[te])
        per.append(r2(y[te], pred[te]))
    return pred, per


# ---- calibrators (12.4.3) ---------------------------------------------------
def design(s, kind):
    s = np.clip(np.asarray(s, float), EPS, 1 - EPS)
    if kind == "platt":
        return (np.log(s) - np.log1p(-s))[:, None]
    return np.column_stack([np.log(s), -np.log1p(-s)])


def loss(p, idx, weight):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    if weight == "candidate":
        f = y[idx]
        return float(-(xlogy(f, p) + xlogy(1 - f, 1 - p)).mean())
    return float(-(xlogy(k[idx], p) + xlogy(n[idx] - k[idx], 1 - p)).sum() / n[idx].sum())


def fit_cal(s, idx, kind, weight):
    Z = design(s, kind)
    th0 = np.r_[np.ones(Z.shape[1]), 0.0]
    obj = lambda th: loss(expit(Z @ th[:-1] + th[-1]), idx, weight)
    res = minimize(obj, th0, method="BFGS")
    if not np.isfinite(res.fun):
        res = minimize(obj, th0, method="Nelder-Mead", options={"maxiter": 20000})
    return {"kind": kind, "theta": res.x, "loss": float(res.fun), "converged": bool(res.success)}


def apply_cal(c, s):
    Z = design(s, c["kind"])
    return expit(Z @ c["theta"][:-1] + c["theta"][-1])


def nested_loto_calibration(X, weight="candidate", seed_offset=0):
    raw = np.full(len(y), np.nan)
    cal = np.full(len(y), np.nan)
    folds = []
    for gi, g in enumerate(T):
        te = topo == g
        tr = ~te
        inner = P.grouped_folds(topo[tr], 4, seed=seed_offset + gi + 1)
        calm = np.isin(topo, inner[0]) & tr
        fit = tr & ~calm
        assert calm.sum() >= 10
        m = estimator().fit(X[fit], y[fit])
        cidx = np.flatnonzero(calm)
        s_cal = m.predict(X[cidx])
        pl = fit_cal(s_cal, cidx, "platt", weight)
        be = fit_cal(s_cal, cidx, "beta", weight)
        chosen = be if be["loss"] < pl["loss"] else pl        # ties -> Platt
        raw[te] = m.predict(X[te])
        cal[te] = apply_cal(chosen, raw[te])
        s_, i_ = np.polyfit(cal[te], y[te], 1)
        folds.append({"test": g, "cal_topologies": sorted(inner[0].tolist()),
                      "n_fit": int(fit.sum()), "n_cal": int(calm.sum()), "n_test": int(te.sum()),
                      "loss_platt": pl["loss"], "loss_beta": be["loss"], "chosen": chosen["kind"],
                      "converged": pl["converged"] and be["converged"],
                      "params": chosen["theta"].tolist(), "raw_clipped": int((raw[te] < EPS).sum()),
                      "slope": float(s_), "intercept": float(i_)})
    return raw, cal, folds


def criterion3(pred):
    slope, icpt = np.polyfit(pred, y, 1)
    order = np.argsort(pred, kind="stable")
    bins = np.array_split(order, 4)
    member = np.full(len(y), -1)
    for b, ix in enumerate(bins):
        member[ix] = b
    tix = {t: np.flatnonzero(topo == t) for t in T}
    rng = np.random.default_rng(0)
    boot = [[] for _ in range(4)]
    slopes = []
    for _ in range(B):
        pick = rng.choice(T, size=len(T), replace=True)
        ii = np.concatenate([tix[t] for t in pick])
        slopes.append(np.polyfit(pred[ii], y[ii], 1)[0])
        for b in range(4):
            sel = ii[member[ii] == b]
            if len(sel):
                boot[b].append(y[sel].mean())
    rows = []
    for b, ix in enumerate(bins):
        lo, hi = np.percentile(boot[b], [2.5, 97.5])
        pm, om = float(pred[ix].mean()), float(y[ix].mean())
        kk, nn = int(k[ix].sum()), int(n[ix].sum())
        cp_lo = 0.0 if kk == 0 else float(beta_dist.ppf(.025, kk, nn - kk + 1))
        cp_hi = 1.0 if kk == nn else float(beta_dist.ppf(.975, kk + 1, nn - kk))
        rows.append({"n": len(ix), "pred_mean": pm, "obs_mean": om, "boot_lo": float(lo),
                     "boot_hi": float(hi), "boot_resamples_used": len(boot[b]),
                     "pass": bool(lo <= pm <= hi),
                     "literal_flow_CP": [cp_lo, cp_hi], "literal_pass": bool(cp_lo <= pm <= cp_hi),
                     "claim_pm05": bool(abs(om - pm) <= 0.05)})
    passing = sum(r["pass"] for r in rows)
    return {"slope": float(slope), "intercept": float(icpt),
            "slope_ci": [float(np.percentile(slopes, 2.5)), float(np.percentile(slopes, 97.5))],
            "bins": rows, "bins_passing": passing,
            "literal_bins_passing": sum(r["literal_pass"] for r in rows),
            "claim_pm05_bins": sum(r["claim_pm05"] for r in rows),
            "pass": bool(0.8 <= slope <= 1.2 and abs(icpt) <= 0.05 and passing >= 3)}


# ---- shortcut and baselines -------------------------------------------------
qidx = df.repair_id.str.extract(r"_q(\d+)$")[0].astype(float).fillna(-1).to_numpy()
order_idx = df.candidate_id.str[2:].astype(float).to_numpy()


def cell_lookup(keys):
    key = np.array(["|".join(map(str, t)) for t in zip(*keys)])
    p = np.zeros(len(y))
    for i in range(len(y)):
        tr = (topo != topo[i]) & (key == key[i])
        p[i] = y[tr].mean() if tr.any() else y[topo != topo[i]].mean()
    return p


def oof_auc(X, lab):
    s = np.full(len(lab), np.nan)
    for g in T:
        te = topo == g
        s[te] = HistGradientBoostingClassifier(max_depth=3, random_state=0).fit(
            X[~te], lab[~te]).predict_proba(X[te])[:, 1]
    a = roc_auc_score(lab, s)
    return float(max(a, 1 - a))


# ===========================================================================
for tier in ("B", "C"):
    cols, removed = P.feature_columns(df, tier)
    X, live, _ = P.matrix(df, cols)
    assert not removed and not [c for c in live if any(s in c for s in P.BANNED_SUBSTRINGS)]
    say("\n" + "=" * 78 + f"\nTIER {tier}  ({len(live)} live features)\n" + "=" * 78)
    R = {"features": live}

    # criterion 1
    pred, per = loto(X)
    ci = P.clustered_bootstrap(y, pred, topo, r2, n=B, seed=0)
    c1 = {"per_fold_mean": float(np.mean(per)), "per_fold_sd": float(np.std(per, ddof=1)),
          "pooled": r2(y, pred), "pooled_ci": list(ci)}
    c1["pass"] = bool(c1["per_fold_mean"] >= 0.40 and c1["pooled"] >= 0.40 and ci[0] > 0)
    say(f"C1 LOTO  per-fold {c1['per_fold_mean']:.4f}±{c1['per_fold_sd']:.4f}  pooled {c1['pooled']:.4f} "
        f"CI {ci}  -> {'PASS' if c1['pass'] else 'FAIL'}")
    R["c1"] = c1

    # criterion 2
    c2 = {}
    for m in ("blackhole", "cost"):
        idx = np.flatnonzero(mech == m)
        pw, _ = loto(X, idx)
        base = np.array([y[idx][topo[idx] != topo[i]].mean() for i in idx])
        c2[m] = {"model": r2(y[idx], pw[idx]), "baseline": r2(y[idx], base)}
        c2[m]["gain"] = c2[m]["model"] - c2[m]["baseline"]
    c2["pass"] = bool(all(c2[m]["gain"] >= 0.15 for m in ("blackhole", "cost")))
    say(f"C2 within  blackhole {c2['blackhole']['model']:.4f} vs {c2['blackhole']['baseline']:.4f} "
        f"({c2['blackhole']['gain']:+.4f})  cost {c2['cost']['model']:.4f} vs {c2['cost']['baseline']:.4f} "
        f"({c2['cost']['gain']:+.4f})  -> {'PASS' if c2['pass'] else 'FAIL'}")
    R["c2"] = c2

    # criterion 3, amended
    raw, cal, folds = nested_loto_calibration(X)
    c3 = criterion3(cal)
    c3["folds"] = folds
    c3["chosen"] = pd.Series([f["chosen"] for f in folds]).value_counts().to_dict()
    c3["per_fold_slope_mean"] = float(np.mean([f["slope"] for f in folds]))
    c3["per_fold_slope_sd"] = float(np.std([f["slope"] for f in folds], ddof=1))
    c3["r2_calibrated"] = r2(y, cal)
    c3["r2_raw_nested"] = r2(y, raw)
    say(f"C3 calibration (12.4)  chosen {c3['chosen']}  all converged "
        f"{all(f['converged'] for f in folds)}  R2 raw(8-topology fit) {c3['r2_raw_nested']:.4f} "
        f"calibrated {c3['r2_calibrated']:.4f}")
    say(f"   slope {c3['slope']:.4f} (cluster CI {c3['slope_ci'][0]:.3f}–{c3['slope_ci'][1]:.3f})  "
        f"intercept {c3['intercept']:+.4f}  per-fold slope {c3['per_fold_slope_mean']:.3f}±{c3['per_fold_slope_sd']:.3f}")
    for i, b in enumerate(c3["bins"]):
        say(f"   bin {i + 1} n={b['n']}  predicted {b['pred_mean']:.4f}  observed {b['obs_mean']:.4f}  "
            f"topology-bootstrap [{b['boot_lo']:.4f}, {b['boot_hi']:.4f}]  {'pass' if b['pass'] else 'FAIL'}"
            f"   | literal flow CP [{b['literal_flow_CP'][0]:.4f}, {b['literal_flow_CP'][1]:.4f}] "
            f"{'pass' if b['literal_pass'] else 'FAIL'}")
    say(f"   bins {c3['bins_passing']}/4 -> criterion 3 {'PASS' if c3['pass'] else 'FAIL'}   "
        f"[literal pre-registered interval: {c3['literal_bins_passing']}/4; ±0.05 claim: {c3['claim_pm05_bins']}/4]")
    R["c3"] = c3

    # sensitivity: reported, cannot change the verdict (12.4.4)
    sens = []
    for s in range(1, 11):
        _, cs, _ = nested_loto_calibration(X, "candidate", seed_offset=1000 * s)
        g = criterion3(cs)
        sens.append({"seed_offset": 1000 * s, "slope": g["slope"], "intercept": g["intercept"],
                     "bins": g["bins_passing"], "pass": g["pass"]})
    _, cf, _ = nested_loto_calibration(X, "flows")
    gf = criterion3(cf)
    R["c3_sensitivity"] = {"inner_seeds": sens,
                           "flow_weighted_loss": {"slope": gf["slope"], "intercept": gf["intercept"],
                                                  "bins": gf["bins_passing"], "pass": gf["pass"]}}
    say(f"   sensitivity, 10 inner seeds: pass {sum(x['pass'] for x in sens)}/10  slope "
        f"{min(x['slope'] for x in sens):.3f}–{max(x['slope'] for x in sens):.3f}  bins "
        f"{sorted(x['bins'] for x in sens)}")
    say(f"   sensitivity, flow-weighted loss: slope {gf['slope']:.3f} icpt {gf['intercept']:+.3f} "
        f"bins {gf['bins_passing']}/4 -> {'pass' if gf['pass'] else 'fail'}")

    # criterion 4, §7.3 as worded
    chg = X[:, [live.index(c) for c in live if c.startswith("chg_")]]
    ident = np.column_stack([(mech == "cost").astype(float),
                             df.repair_class.map({"correct": 0, "incomplete": 1, "regressive": 2}).to_numpy(float),
                             pd.Categorical(df.repair_id).codes.astype(float), qidx, order_idx])
    ps, _ = loto(np.column_stack([ident, chg]),
                 factory=lambda: RandomForestRegressor(n_estimators=500, min_samples_leaf=2,
                                                       random_state=0, n_jobs=-1))
    c4 = {"shortcut": r2(y, ps), "full": c1["pooled"]}
    c4["gap"] = c4["full"] - c4["shortcut"]
    c4["pass"] = bool(c4["gap"] > 0.05)
    say(f"C4 shortcut (§7.3 wording) {c4['shortcut']:.4f} vs full {c4['full']:.4f} gap {c4['gap']:+.4f} "
        f"-> {'PASS' if c4['pass'] else 'FAIL'}")
    R["c4"] = c4

    # NO-GO recoverability clause
    R["mechanism_recoverability_auc"] = oof_auc(X, (mech == "cost").astype(int))
    R["verdict"] = ("GO under amendment 12.4 (pre-registered §8.3 failed)"
                    if all(R[c]["pass"] for c in ("c1", "c2", "c3", "c4")) else
                    "NOT GO: " + ", ".join(c for c in ("c1", "c2", "c3", "c4") if not R[c]["pass"]))
    say(f"mechanism LOTO-AUC {R['mechanism_recoverability_auc']:.3f}\nTIER {tier} VERDICT: {R['verdict']}")
    RESULT[f"tier_{tier}"] = R

# ---------------------------------------------------------------------------
say("\n" + "=" * 78 + "\nMANDATORY SAME-TABLE REPORTING (12.4.5)\n" + "=" * 78)
Xc, livec, _ = P.matrix(df, P.feature_columns(df, "C")[0])
p06 = Xc[:, livec.index("verdict_P06")]
rep = {"lookup_mechanism": r2(y, cell_lookup([mech])),
       "lookup_P06": r2(y, cell_lookup([p06])),
       "lookup_mechanism_x_P06": r2(y, cell_lookup([mech, p06]))}
for a_, b_ in (("cost", "blackhole"), ("blackhole", "cost")):
    tr, te = mech == a_, mech == b_
    pr = estimator().fit(Xc[tr], y[tr]).predict(Xc[te])
    rep[f"lomo_{a_}_to_{b_}"] = {"r2": r2(y[te], pr), "mae": float(np.abs(y[te] - pr).mean()),
                                 "train_mean_mae": float(np.abs(y[te] - y[tr].mean()).mean()),
                                 "framing": "interpolation (fair test)" if a_ == "cost" else "extrapolation ~4.6x (stress)"}
perm = np.random.default_rng(0).permutation(T)
p4 = np.full(len(y), np.nan)
for i in range(4):
    te = np.isin(topo, perm[i::4])
    p4[te] = estimator().fit(Xc[~te], y[~te]).predict(Xc[te])
rep["grouped_4fold_by_topology"] = r2(y, p4)
pk = np.full(len(y), np.nan)
for tr, te in KFold(5, shuffle=True, random_state=0).split(Xc):
    pk[te] = estimator().fit(Xc[tr], y[tr]).predict(Xc[te])
rep["random_5fold"] = r2(y, pk)
rep["random_minus_loto"] = rep["random_5fold"] - RESULT["tier_C"]["c1"]["pooled"]
rep["not_executed"] = ["§6.4 transfer to 8 held-out topologies", "§6.5 auxiliary shutdown/exact arm"]
for kk_, v in rep.items():
    say(f"  {kk_}: {v}")
RESULT["reporting"] = rep

OUT.write_text(json.dumps(RESULT, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)),
               encoding="utf-8")
say(f"\nwrote {OUT}")
