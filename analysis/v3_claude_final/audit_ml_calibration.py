"""Independent re-test of the v3 ML protocol and the §8.3 calibration gate.

    ./.venv/Scripts/python.exe analysis/v3_claude_final/audit_ml_calibration.py

Analysis only. Reads the frozen corpus through the FROZEN nrl.phase4 loader,
feature filter and matrix, and takes the target from r_three_way.csv (measured
r reproduced three ways by reproduce_r.py). Writes one JSON next to this file.
No corpus, plan, label or feature file is written.
"""
from __future__ import annotations

import json
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

import nrl.phase4 as P

OUT = Path(__file__).resolve().parent / "audit_ml_calibration.json"
PILOT = REPO / "data" / "pilot-v3"
RESULT = {}


def say(*a):
    print(*a, flush=True)


def hgb():
    # the estimator both Copilot scripts used; the frozen plan names no regressor
    return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=300, max_leaf_nodes=15,
                                         l2_regularization=1.0, random_state=0)


def rf():
    return RandomForestRegressor(n_estimators=500, min_samples_leaf=2, random_state=0, n_jobs=-1)


def r2(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    d = ((y - y.mean()) ** 2).sum()
    return float(1 - ((y - p) ** 2).sum() / d) if d > 0 else float("nan")


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
y = df.r_rib.to_numpy(float)
k = (df.broken + df.rerouted).to_numpy(float)
n = df.golden_flows.to_numpy(float)
assert np.allclose(k / n, y, atol=1e-6)
topo = df.topology.to_numpy()
mech = df.mechanism.to_numpy()
cols, removed = P.feature_columns(df, "C")
X, live, dropped = P.matrix(df, cols)
say(f"rows {len(df)}  tier C {len(cols)}  removed-by-ban {removed}  live {len(live)}")
RESULT["features_live"] = live

# ---------------------------------------------------------------------------
say("\n=== 0. STOP-AND-FIX and degeneracy clauses (§8) ===")
oc = L["outcomes"].set_index("candidate_id").loc[df.candidate_id]
spec_measured_fail = oc.spec_violations_vs_golden.notna().to_numpy()
spec_pred_fail = (df.batfish_spec_verdict != "PASS").to_numpy()
dis = float((spec_measured_fail != spec_pred_fail).mean())
mae_pred = float(np.abs(df.predicted_severity - y).mean())
mode_share = float(pd.Series(np.round(y, 6)).value_counts(normalize=True).iloc[0])
say(f"  SPEC verdict disagreement Batfish vs lab: {dis:.3%} (limit 10%)  "
    f"[lab SPEC violations: {int(spec_measured_fail.sum())}]")
say(f"  predicted vs measured r MAE (manifest, 4dp): {mae_pred:.6f} (limit 0.10)")
say(f"  distinct r {len(np.unique(np.round(y, 6)))} (>=20)  largest single-value share {mode_share:.3f} (<=0.70)")
RESULT["stop_fix"] = {"spec_disagreement": dis, "mae_pred_vs_measured": mae_pred, "mode_share": mode_share}

# ---------------------------------------------------------------------------
say("\n=== 1. Leakage ===")
bad = [c for c in live if any(s in c for s in P.BANNED_SUBSTRINGS)]
say(f"  live features matching a banned substring: {bad}")
ps = df.predicted_severity.to_numpy(float)
single = []
for j, c in enumerate(live):
    x = X[:, j]
    single.append((np.corrcoef(x, y)[0, 1] ** 2, np.corrcoef(x, ps)[0, 1] ** 2, c))
single.sort(reverse=True)
say(f"  max single-feature R^2 with predicted severity: {max(s[1] for s in single):.3f}")
for a, b, c in single[:6]:
    say(f"     R2(meas r) {a:.3f}  R2(pred sev) {b:.3f}  {c}")
RESULT["leak"] = {"banned_in_live": bad, "max_r2_with_predicted_severity": max(s[1] for s in single),
                  "top": [[c, a, b] for a, b, c in single[:10]]}
# no row of a held-out topology in its training fold, and incident == topology
assert df.groupby("incident_id").topology.nunique().max() == 1
assert df.groupby("topology").incident_id.nunique().max() == 1
say("  incident_id <-> topology is 1:1 (so incident grouping == topology grouping)")


# ---------------------------------------------------------------------------
def loto(Xm, yy, groups, factory, idx=None):
    idx = np.arange(len(yy)) if idx is None else np.asarray(idx)
    pred = np.full(len(yy), np.nan)
    folds = {}
    for g in sorted(set(groups[idx])):
        te = idx[groups[idx] == g]
        tr = idx[groups[idx] != g]
        assert not set(groups[tr]) & {g}
        pred[te] = factory().fit(Xm[tr], yy[tr]).predict(Xm[te])
        folds[g] = r2(yy[te], pred[te])
    return pred, folds


say("\n=== 2. PRIMARY: 12-fold LOTO on measured r (§6.1: per-fold mean±sd primary) ===")
pred_loto, folds = loto(X, y, topo, hgb)
fv = np.array(list(folds.values()))
rng = np.random.default_rng(20260914)
T = np.array(sorted(set(topo)))
boot = []
for _ in range(2000):
    ii = np.concatenate([np.flatnonzero(topo == t) for t in rng.choice(T, len(T))])
    boot.append(r2(y[ii], pred_loto[ii]))
ci = [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))]
say(f"  per-fold R2 mean {fv.mean():.4f} sd {fv.std(ddof=1):.4f} min {fv.min():.4f} ({min(folds, key=folds.get)})")
say(f"  pooled R2 {r2(y, pred_loto):.6f}  topology-cluster bootstrap 95% CI [{ci[0]:.4f}, {ci[1]:.4f}]")
pred_rf, folds_rf = loto(X, y, topo, rf)
say(f"  estimator sensitivity, RF: pooled {r2(y, pred_rf):.4f} per-fold mean {np.mean(list(folds_rf.values())):.4f}")
RESULT["loto"] = {"per_fold": folds, "per_fold_mean": fv.mean(), "per_fold_sd": fv.std(ddof=1),
                  "pooled": r2(y, pred_loto), "ci": ci, "rf_pooled": r2(y, pred_rf)}

say("\n=== 3. WITHIN-MECHANISM (§6.3: fit and evaluate separately; criterion 2) ===")
for m in ("blackhole", "cost"):
    idx = np.flatnonzero(mech == m)
    pr, _ = loto(X, y, topo, hgb, idx)
    base = np.array([y[idx][topo[idx] != topo[i]].mean() for i in idx])
    a, b = r2(y[idx], pr[idx]), r2(y[idx], base)
    say(f"  {m:9s} n={len(idx)}  separate LOTO model R2 {a:.4f}  per-mechanism mean (LOTO) {b:.4f}  "
        f"gain {a - b:+.4f} (need >=0.15)   | full model on subset {r2(y[idx], pred_loto[idx]):.4f}")
    RESULT[f"within_{m}"] = {"model": a, "baseline": b, "gain": a - b}

say("\n=== 4. §7.2 association table on MEASURED r ===")
qidx = df.repair_id.str.extract(r"_q(\d+)$")[0].astype(float).fillna(-1)
order = df.candidate_id.str[2:].astype(int)


def cat_r2(s):
    return r2(y, pd.Series(y).groupby(s.to_numpy()).transform("mean").to_numpy())


assoc = {"topology": cat_r2(df.topology), "repair_class": cat_r2(df.repair_class),
         "mechanism": cat_r2(df.mechanism), "repair_id": cat_r2(df.repair_id),
         "quantile_index": cat_r2(qidx), "generation_order(linear)": np.corrcoef(order, y)[0, 1] ** 2}
for c in [c for c in live if c.startswith("chg_")]:
    assoc[c] = np.corrcoef(X[:, live.index(c)], y)[0, 1] ** 2
for kk, v in assoc.items():
    say(f"  {v:.4f}  {kk}")
RESULT["assoc_in_sample"] = assoc

say("\n=== 5. §7.3 SHORTCUT-ONLY: RF on identity + provenance + diff-shape, LOTO ===")
ident = pd.DataFrame({
    "mechanism": (df.mechanism == "cost").astype(float),
    "repair_class": df.repair_class.map({"correct": 0, "incomplete": 1, "regressive": 2}).astype(float),
    "repair_id": pd.Categorical(df.repair_id).codes.astype(float),
    "quantile_index": qidx, "generation_order": order.astype(float),
})
chg = pd.DataFrame(X[:, [live.index(c) for c in live if c.startswith("chg_")]])
for label, M in [("identity+provenance+diff-shape (plan wording)", pd.concat([ident, chg], axis=1)),
                 ("identity+provenance only", ident), ("chg_ only (Copilot)", chg)]:
    pr, _ = loto(M.to_numpy(float), y, topo, rf)
    say(f"  {label:48s} R2 {r2(y, pr):.4f}   gap to full {r2(y, pred_loto) - r2(y, pr):+.4f} (need >0.05)")
    RESULT[f"shortcut::{label}"] = r2(y, pr)
say("  (topology identity omitted: under LOTO the held-out code is unseen, so it cannot carry signal)")

say("\n=== 6. §7.1 recoverability and the NO-GO 'tracking across ablations' clause ===")


def oof_auc(Xm, lab):
    s = np.full(len(lab), np.nan)
    for g in T:
        te, tr = topo == g, topo != g
        s[te] = HistGradientBoostingClassifier(max_depth=3, random_state=0).fit(Xm[tr], lab[tr]).predict_proba(Xm[te])[:, 1]
    a = roc_auc_score(lab, s)
    return max(a, 1 - a)


mlab = (mech == "cost").astype(int)
tiers = {}
for tier in ("A", "A+", "B", "C"):
    c_t, _ = P.feature_columns(df, tier)
    Xt, lt, _ = P.matrix(df, c_t)
    pr, _ = loto(Xt, y, topo, hgb)
    wins = []
    for m in ("blackhole", "cost"):
        idx = np.flatnonzero(mech == m)
        pw, _ = loto(Xt, y, topo, hgb, idx)
        wins.append(r2(y[idx], pw[idx]))
    tiers[tier] = {"n_feat": len(lt), "mech_auc": oof_auc(Xt, mlab), "loto_r2": r2(y, pr),
                   "within_bh": wins[0], "within_cost": wins[1]}
    say(f"  tier {tier:2s} feats {len(lt):2d}  mechanism LOTO-AUC {tiers[tier]['mech_auc']:.3f}  "
        f"LOTO R2 {tiers[tier]['loto_r2']:.4f}  within bh {wins[0]:.3f} cost {wins[1]:.3f}")
mech_only = np.array([y[(topo != topo[i]) & (mech == mech[i])].mean() for i in range(len(y))])
say(f"  mechanism-only (LOTO group mean) R2 {r2(y, mech_only):.4f}")
RESULT["ablation"] = tiers
RESULT["mechanism_only_r2"] = r2(y, mech_only)

say("\n=== 7. Amendment 12.1.3 secondary splits ===")
for a_, b_ in (("cost", "blackhole"), ("blackhole", "cost")):
    tr, te = mech == a_, mech == b_
    pr = hgb().fit(X[tr], y[tr]).predict(X[te])
    const = np.full(te.sum(), y[tr].mean())
    say(f"  LOMO {a_:9s}->{b_:9s} R2 {r2(y[te], pr):8.3f}  MAE {np.abs(y[te] - pr).mean():.4f}  "
        f"(train-mean MAE {np.abs(y[te] - const).mean():.4f}; test sd {y[te].std():.4f})")
    RESULT[f"lomo_{a_}_to_{b_}"] = {"r2": r2(y[te], pr), "mae": float(np.abs(y[te] - pr).mean())}
perm = np.random.default_rng(0).permutation(T)
f4 = [perm[i::4] for i in range(4)]
p4 = np.full(len(y), np.nan)
fr = []
for g in f4:
    te = np.isin(topo, g)
    p4[te] = hgb().fit(X[~te], y[~te]).predict(X[te])
    fr.append(r2(y[te], p4[te]))
say(f"  grouped 4-fold by topology: pooled {r2(y, p4):.4f} per-fold {np.mean(fr):.4f}±{np.std(fr, ddof=1):.4f}")
from sklearn.model_selection import KFold
pk = np.full(len(y), np.nan)
for tr, te in KFold(5, shuffle=True, random_state=0).split(X):
    pk[te] = hgb().fit(X[tr], y[tr]).predict(X[te])
say(f"  random 5-fold: {r2(y, pk):.4f}   gap to LOTO {r2(y, pk) - r2(y, pred_loto):+.4f}")
RESULT["grouped4"] = r2(y, p4)
RESULT["random_cv_gap"] = r2(y, pk) - r2(y, pred_loto)

# ===========================================================================
say("\n" + "=" * 78 + "\nCALIBRATION\n" + "=" * 78)


def cp(kk, nn, alpha=0.05):
    lo = 0.0 if kk == 0 else beta_dist.ppf(alpha / 2, kk, nn - kk + 1)
    hi = 1.0 if kk == nn else beta_dist.ppf(1 - alpha / 2, kk + 1, nn - kk)
    return float(lo), float(hi)


def gate(pred, label, verbose=True):
    """Every defensible reading of §8.3 on one prediction vector."""
    slope, icpt = np.polyfit(pred, y, 1)
    order_ = np.argsort(pred, kind="stable")
    rows = []
    for b in np.array_split(order_, 4):
        kk, nn = int(k[b].sum()), int(n[b].sum())
        lo, hi = cp(kk, nn)
        pm, om_flow, om_cand = pred[b].mean(), kk / nn, y[b].mean()
        pm_w = float((pred[b] * n[b]).sum() / nn)          # flow-weighted predicted
        # candidate is the independent unit: bootstrap candidates in the bin
        bs = [y[np.random.default_rng(s).choice(b, len(b))].mean() for s in range(2000)]
        clo, chi = np.quantile(bs, [.025, .975])
        # topology-clustered: resample topologies inside the bin
        tb = sorted(set(topo[b]))
        bst = []
        rg = np.random.default_rng(1)
        for _ in range(2000):
            ii = np.concatenate([b[topo[b] == t] for t in rg.choice(tb, len(tb))])
            bst.append(y[ii].mean())
        tlo, thi = np.quantile(bst, [.025, .975])
        rows.append(dict(n_cand=len(b), flows=nn, pred_mean=pm, pred_mean_flow_w=pm_w,
                         obs_flow=om_flow, obs_cand=om_cand, cp_lo=lo, cp_hi=hi,
                         cand_lo=clo, cand_hi=chi, topo_lo=tlo, topo_hi=thi))
    R = {
        "slope": float(slope), "intercept": float(icpt),
        "slope_ok": bool(0.8 <= slope <= 1.2), "intercept_ok": bool(abs(icpt) <= 0.05),
        # Copilot pass 2: unweighted predicted mean inside pooled Clopper-Pearson
        "bins_CP_predmean_in_obs": sum(r["cp_lo"] <= r["pred_mean"] <= r["cp_hi"] for r in rows),
        # same interval, like-for-like flow-weighted predicted mean
        "bins_CP_flowweighted": sum(r["cp_lo"] <= r["pred_mean_flow_w"] <= r["cp_hi"] for r in rows),
        # §6.2 headline claim: says 10% -> observed 5-15%
        "bins_pm05_band": sum(abs(r["obs_cand"] - r["pred_mean"]) <= 0.05 for r in rows),
        "bins_candidate_bootstrap": sum(r["cand_lo"] <= r["pred_mean"] <= r["cand_hi"] for r in rows),
        "bins_topology_bootstrap": sum(r["topo_lo"] <= r["pred_mean"] <= r["topo_hi"] for r in rows),
        "bins": rows,
    }
    if verbose:
        say(f"\n--- {label} ---")
        say(f"  slope {slope:.4f} [{'ok' if R['slope_ok'] else 'FAIL'}]  intercept {icpt:+.4f} "
            f"[{'ok' if R['intercept_ok'] else 'FAIL'}]")
        say("  bin  n  flows  pred(unw) pred(flow-w) obs(flow) obs(cand) | CP interval (±half) | cand-boot | topo-boot")
        for i, r in enumerate(rows):
            say(f"   {i + 1}  {r['n_cand']:2d}  {r['flows']:5d}  {r['pred_mean']:.4f}   {r['pred_mean_flow_w']:.4f}    "
                f"{r['obs_flow']:.4f}   {r['obs_cand']:.4f} | [{r['cp_lo']:.4f},{r['cp_hi']:.4f}] "
                f"(±{(r['cp_hi'] - r['cp_lo']) / 2:.4f}) | [{r['cand_lo']:.3f},{r['cand_hi']:.3f}] | "
                f"[{r['topo_lo']:.3f},{r['topo_hi']:.3f}]")
        say(f"  bins passing:  CP/unweighted-pred {R['bins_CP_predmean_in_obs']}/4   "
            f"CP/flow-weighted-pred {R['bins_CP_flowweighted']}/4   ±0.05 {R['bins_pm05_band']}/4   "
            f"candidate-bootstrap {R['bins_candidate_bootstrap']}/4   topology-bootstrap {R['bins_topology_bootstrap']}/4")
    return R


# ---- binomial-likelihood Platt / beta: what v2 §5 becomes on a fraction -----
def nll(p, kk, nn, weight):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    if weight == "flows":        # flows as Bernoulli trials (Copilot)
        return float(-(xlogy(kk, p) + xlogy(nn - kk, 1 - p)).sum() / nn.sum())
    f = kk / nn                  # fractional logit: one candidate, one unit
    return float(-(xlogy(f, p) + xlogy(1 - f, 1 - p)).mean())


def feats(s, kind):
    s = np.clip(np.asarray(s, float), 1e-6, 1 - 1e-6)
    if kind == "platt":
        return np.column_stack([np.log(s) - np.log1p(-s)])
    return np.column_stack([np.log(s), -np.log1p(-s)])   # frozen BetaCalibrator design


def fit_cal(s, kk, nn, kind, weight):
    Z = feats(s, kind)
    th0 = np.r_[np.ones(Z.shape[1]), 0.0]
    obj = lambda th: nll(expit(Z @ th[:-1] + th[-1]), kk, nn, weight)
    r = minimize(obj, th0, method="BFGS")
    return {"kind": kind, "theta": r.x, "loss": float(r.fun)}


def apply_cal(c, s):
    Z = feats(s, c["kind"])
    return expit(Z @ c["theta"][:-1] + c["theta"][-1])


def pick(s, kk, nn, weight):
    pl, be = fit_cal(s, kk, nn, "platt", weight), fit_cal(s, kk, nn, "beta", weight)
    return (be if be["loss"] < pl["loss"] else pl), pl["loss"], be["loss"]


# frozen classes literally cannot take a continuous y -- record it
try:
    P.PlattCalibrator().fit(np.array([.1, .2, .3]), np.array([.05, .2, .31]))
    frozen_ok = True
except Exception as e:   # noqa: BLE001
    frozen_ok = f"{type(e).__name__}: {str(e)[:90]}"
say(f"\n  frozen nrl.phase4.PlattCalibrator on continuous y: {frozen_ok}")
RESULT["frozen_calibrator_on_continuous_y"] = str(frozen_ok)
say(f"  raw LOTO predictions <= 0.001 (clipped to 1e-6 before logit): {(pred_loto <= 1e-3).sum()}   "
    f"negative: {(pred_loto < 0).sum()}   measured zeros: {(y == 0).sum()}")

G = {}
G["C1 raw LOTO (primary model, uncalibrated)"] = gate(pred_loto, "C1 raw 12-fold LOTO predictions, no recalibration")

# ---- C2: reproduce Copilot's nested calibration by importing their code ----
sys.path.insert(0, str(REPO / "analysis" / "v3_audit"))
import run_v3_ml_audit as CO   # noqa: E402

cdf = df.rename(columns={"r_rib": "r", "golden_flows": "golden_carried_flows",
                         "broken": "broken_flows", "rerouted": "rerouted_flows"})
cop = CO.nested_grouped_calibration(cdf, cols)
say(f"\n  Copilot nested (imported, rerun on my target): slope {cop['calibration_slope']:.6f} "
    f"intercept {cop['calibration_intercept']:.6f} bins {cop['bins_passing']}/4 "
    f"selected {cop['calibrators_selected']}  raw test LL {cop['raw_test_log_loss']:.6f} "
    f"cal test LL {cop['calibrated_test_log_loss']:.6f}")
RESULT["copilot_nested_rerun"] = {kk_: cop[kk_] for kk_ in ("calibration_slope", "calibration_intercept",
                                                            "bins_passing", "calibrators_selected",
                                                            "raw_test_log_loss", "calibrated_test_log_loss")}


# rebuild their raw/calibrated vectors so every gate reading can be applied
def copilot_vectors(weight):
    from sklearn.model_selection import GroupKFold
    raw = np.full(len(y), np.nan)
    cal = np.full(len(y), np.nan)
    inc = df.incident_id.to_numpy()
    for otr, ote in GroupKFold(5).split(X, y, groups=topo):
        cr = np.full(len(otr), np.nan)
        for itr, ical in GroupKFold(4).split(X[otr], y[otr], groups=inc[otr]):
            cr[ical] = hgb().fit(X[otr][itr], y[otr][itr]).predict(X[otr][ical])
        c, _, _ = pick(cr, k[otr], n[otr], weight)
        raw[ote] = hgb().fit(X[otr], y[otr]).predict(X[ote])
        cal[ote] = apply_cal(c, raw[ote])
    return raw, cal


raw5, cal5 = copilot_vectors("flows")
G["C2 Copilot nested 5-fold, raw"] = gate(raw5, "C2a Copilot outer 5-fold, RAW (before calibrator)")
G["C2 Copilot nested 5-fold, calibrated (flows NLL)"] = gate(cal5, "C2b Copilot outer 5-fold, beta/Platt CALIBRATED (flow-weighted NLL)")
_, cal5c = copilot_vectors("candidate")
G["C2 Copilot nested 5-fold, calibrated (candidate NLL)"] = gate(cal5c, "C2c same, calibrator fitted with per-candidate fractional NLL")


# ---- C3: faithful port of the FROZEN nrl.phase4.nested_cv to a regression ---
def frozen_port(weight):
    folds_ = P.grouped_folds(df.incident_id.to_numpy(), 5, 0)
    groups = df.incident_id.to_numpy()
    raw = np.full(len(y), np.nan)
    cal = np.full(len(y), np.nan)
    per = []
    for gi, tg in enumerate(folds_):
        te = np.isin(groups, tg)
        tr = ~te
        inner = P.grouped_folds(groups[tr], 4, gi + 1)
        calm = np.isin(groups, inner[0]) & tr
        fit = tr & ~calm
        m = hgb().fit(X[fit], y[fit])
        c, lp, lb = pick(m.predict(X[calm]), k[calm], n[calm], weight)
        raw[te] = m.predict(X[te])
        cal[te] = apply_cal(c, raw[te])
        s_, i_ = np.polyfit(cal[te], y[te], 1)
        per.append({"fold": gi, "test": sorted(set(topo[te])), "cal_topos": sorted(set(topo[calm])),
                    "n_fit": int(fit.sum()), "n_cal": int(calm.sum()), "n_test": int(te.sum()),
                    "chosen": c["kind"], "ll_platt": lp, "ll_beta": lb,
                    "r2_raw": r2(y[te], raw[te]), "r2_cal": r2(y[te], cal[te]),
                    "slope": float(s_), "intercept": float(i_)})
    return raw, cal, per


for weight in ("flows", "candidate"):
    raw_f, cal_f, per = frozen_port(weight)
    say(f"\n  frozen-port nested_cv ({weight} NLL) per-fold:")
    for p_ in per:
        say(f"    fold {p_['fold']} test {p_['test']} cal-fold {p_['cal_topos']} n fit/cal/test "
            f"{p_['n_fit']}/{p_['n_cal']}/{p_['n_test']}  chose {p_['chosen']}  R2 raw {p_['r2_raw']:.3f} "
            f"cal {p_['r2_cal']:.3f}  slope {p_['slope']:.3f} icpt {p_['intercept']:+.3f}")
    sl = np.array([p_["slope"] for p_ in per])
    ic = np.array([p_["intercept"] for p_ in per])
    say(f"    per-fold slope {sl.mean():.3f}±{sl.std(ddof=1):.3f}   intercept {ic.mean():+.3f}±{ic.std(ddof=1):.3f}")
    G[f"C3 frozen-port nested_cv raw ({weight})"] = gate(raw_f, f"C3a frozen nested_cv port, RAW ({weight})",
                                                         verbose=(weight == "flows"))
    G[f"C3 frozen-port nested_cv calibrated ({weight})"] = gate(cal_f, f"C3b frozen nested_cv port, CALIBRATED ({weight} NLL)")
    RESULT[f"frozen_port_per_fold_{weight}"] = per


# ---- C4: calibration nested INSIDE the primary LOTO split -------------------
def loto_nested(weight, n_cal_topos=3, seed=0):
    cal = np.full(len(y), np.nan)
    raw = np.full(len(y), np.nan)
    chosen = []
    for gi, g in enumerate(T):
        te = topo == g
        rest = np.array([t for t in T if t != g])
        calt = np.random.default_rng(seed + gi).choice(rest, n_cal_topos, replace=False)
        calm = np.isin(topo, calt)
        fit = ~te & ~calm
        m = hgb().fit(X[fit], y[fit])
        c, _, _ = pick(m.predict(X[calm]), k[calm], n[calm], weight)
        raw[te] = m.predict(X[te])
        cal[te] = apply_cal(c, raw[te])
        chosen.append(c["kind"])
    return raw, cal, chosen


raw_l, cal_l, ch = loto_nested("flows")
say(f"\n  LOTO-nested calibrator choices: {pd.Series(ch).value_counts().to_dict()}")
G["C4 LOTO-nested raw (8-topology fit)"] = gate(raw_l, "C4a LOTO outer, 8 fit / 3 calibrate, RAW")
G["C4 LOTO-nested calibrated"] = gate(cal_l, "C4b LOTO outer, 8 fit / 3 calibrate, CALIBRATED")

# ---- pseudo-replication: how narrow the flow-count interval is by design ----
say("\n--- pseudo-replication diagnostic (C1 bins) ---")
b1 = G["C1 raw LOTO (primary model, uncalibrated)"]["bins"]
for i, r in enumerate(b1):
    say(f"  bin {i + 1}: flow-count CP half-width ±{(r['cp_hi'] - r['cp_lo']) / 2:.4f}   "
        f"candidate-bootstrap half-width ±{(r['cand_hi'] - r['cand_lo']) / 2:.4f}   "
        f"topology-bootstrap half-width ±{(r['topo_hi'] - r['topo_lo']) / 2:.4f}   "
        f"ratio cand/CP {((r['cand_hi'] - r['cand_lo']) / (r['cp_hi'] - r['cp_lo'])):.1f}x")
# a model that is perfectly calibrated on average but has any residual spread:
# the oracle predictor itself (analytic severity, MAE 2e-5) -- does IT pass?
G["C0 analytic oracle predicted_severity"] = gate(ps, "C0 the analytic Dijkstra (MAE 2e-5) scored by the same gate")

say("\n" + "=" * 78 + "\nCALIBRATION SUMMARY  (slope / intercept / bins under each interval reading)\n" + "=" * 78)
say(f"{'prediction vector':58s} slope   icpt    CP  CPw ±.05 cand topo")
for kk_, R in G.items():
    say(f"{kk_:58s} {R['slope']:.3f} {R['intercept']:+.3f}   {R['bins_CP_predmean_in_obs']}   "
        f"{R['bins_CP_flowweighted']}   {R['bins_pm05_band']}    {R['bins_candidate_bootstrap']}    "
        f"{R['bins_topology_bootstrap']}")
RESULT["calibration"] = {kk_: {x: v for x, v in R.items()} for kk_, R in G.items()}
OUT.write_text(json.dumps(RESULT, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)),
               encoding="utf-8")
say(f"\nwrote {OUT}")
