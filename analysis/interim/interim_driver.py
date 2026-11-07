"""INTERIM (EXPLORATORY) diagnostic at Stage 3 partial completion.

    python analysis/interim/interim_driver.py --pilot data/pilot-v2

This is NOT the confirmatory analysis. docs/ANALYSIS-PLAN.md preamble: anything
not written in that file is exploratory and must be reported as exploratory.
This driver adds no methodology. Every estimator, split, calibrator, metric and
bound below is called out of `nrl.phase4`, which is the frozen implementation.

What it adds over `pipeline/run_phase4.py`, and why each addition is necessary:

1.  THE GATE ON THE RIGHT POPULATION. ANALYSIS-PLAN 14.2 requires the
    `repair_class` recoverability measurement "at Stage 2's n (~150 PASS)".
    `pipeline/diagnose_shortcut.py` measures it over the whole manifest --
    all 1,479 candidates, including the 675 Batfish-FAIL ones -- because it
    reads manifest + phase2 and never opens phase3. That is a different
    population from the one a model trains on, and its answer cannot change
    when more labs run. Section 2 below re-measures it on the exact
    PASS-conditioned modelling rows, grouped by incident.

2.  THE SHORTCUT CEILING. `repair_class` has three levels and one of them
    ("correct") contains zero harmful cases, so the generator variable alone
    separates the label almost perfectly. Section 2c scores that oracle
    directly. It is the number every learned model has to be read against: a
    model that merely matches it has recovered the operator, not the risk.

3.  CONFORMAL IS SKIPPED, LOUDLY. `conformal_incident_split` hard-requires
    exactly 200 incidents in a 120/40/40 topology-stratified split. At the
    interim incident count that split does not exist. ANALYSIS-PLAN 10: alpha
    is never lowered to make a bound appear. Section 7 records the refusal
    rather than fabricating coverage.

4.  ISOLATED OUTPUT. `run_phase4.py` writes into `<pilot>/phase4/` and has no
    --out. Everything here lands under analysis/interim/ and nothing under
    data/ is opened for writing.

5.  THE FAULT-FAMILY BREAKDOWN THAT run_phase4 SILENTLY DROPS. `meta` and
    `batfish_summary` both carry `prov_fault_family_BANNED`, so the merge in
    build_dataset suffixes it to `_x`/`_y`. Every `if by in df.columns` guard
    downstream therefore misses it, and the per-family exclusion and harm
    tables required by ANALYSIS-PLAN 2 never print. Resolved locally here;
    the frozen code is not touched.

Read-only with respect to data/. Writes only analysis/interim/.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np                                              # noqa: E402
import pandas as pd                                             # noqa: E402
import nrl.phase4 as P                                          # noqa: E402

OUT = Path(__file__).resolve().parent
GATE_THRESHOLD = 0.85            # ANALYSIS-PLAN 14.2
CONFORMAL_REQUIRED_INCIDENTS = 200


# ---------------------------------------------------------------------------
# reporting helpers
# ---------------------------------------------------------------------------
_LOG: list[str] = []


def say(s: str = "") -> None:
    print(s)
    _LOG.append(s)


def hr(t: str) -> None:
    say("\n" + "=" * 78)
    say(t)
    say("=" * 78)


def family_col(df: pd.DataFrame) -> str | None:
    for c in ("prov_fault_family_BANNED", "prov_fault_family_BANNED_x"):
        if c in df.columns:
            return c
    return None


# ---------------------------------------------------------------------------
# feature sets
# ---------------------------------------------------------------------------
def feature_sets(df: pd.DataFrame) -> dict[str, list[str]]:
    """Frozen tiers, plus the group ablations that answer 'does anything
    survive when the shortcut-carrying groups are removed?'

    The ablations are not arbitrary column removal. chg_/cov_/g_ are the three
    groups diagnose_shortcut identified as carrying the generator signature;
    b_/c_ are Batfish's own outputs about the AFTER network. Splitting on that
    boundary is the question ANALYSIS-PLAN 14.2 asks.
    """
    a = [c for c in df.columns if c.startswith(("chg_", "cov_"))]
    chg = [c for c in df.columns if c.startswith("chg_")]
    cov = [c for c in df.columns if c.startswith("cov_")]
    gph = [c for c in df.columns if c.startswith("g_")]
    b = [c for c in ("parse_warning_rows", "init_issue_rows",
                     "undefined_reference_rows", "unused_structure_rows",
                     "nodes_parsed", "interfaces_total", "interfaces_active",
                     "ip_owner_rows", "layer3_edge_rows", "route_rows",
                     "ospf_session_rows", "ospf_sessions_established",
                     "loop_rows", "multipath_inconsistency_rows",
                     "subnet_multipath_inconsistency_rows",
                     "diff_vs_incident_rows") if c in df.columns]
    c = [f"verdict_{p}" for p in P.ORACLE_ONLY if f"verdict_{p}" in df.columns]
    return {
        "A": a, "A+": a + gph, "B": a + gph + b, "C": a + gph + b + c,
        "chg_only": chg, "cov_only": cov, "g_only": gph,
        "B_only": b, "C_only": c, "B+C_only": b + c,
        "no_chg": cov + gph + b + c,
        "no_g": a + b + c,
        "no_chg_no_g": cov + b + c,
    }


def guarded(df: pd.DataFrame, cols: list[str]):
    """Apply the frozen leakage filter, then build the matrix.

    feature_columns() is whitelist-driven and cannot see an ad-hoc column list,
    so the ban check is applied explicitly here. It must never fire; if it does,
    that is a defect and the run stops.
    """
    banned = [c for c in cols if any(s in c for s in P.BANNED_SUBSTRINGS)]
    if banned:
        raise SystemExit(f"BLOCKED: banned columns reached X: {banned}")
    return P.matrix(df, cols)


# ---------------------------------------------------------------------------
# 2. the gate
# ---------------------------------------------------------------------------
def recoverability(df, cols, groups, target: str) -> dict:
    """Worst-case one-vs-rest AUC for `target`, incident-grouped nested CV.

    Same estimator and protocol as pipeline/diagnose_shortcut.py. The only
    change is the population: these are the PASS-conditioned modelling rows.
    """
    if not cols:
        return {"worst_auc": None, "n_features": 0, "per_class": {}}
    X, kept, _ = guarded(df, cols)
    if not kept:
        return {"worst_auc": None, "n_features": len(cols), "per_class": {}}
    per, worst = {}, 0.0
    for cls in sorted(df[target].dropna().unique()):
        y = (df[target] == cls).astype(int).to_numpy()
        if y.sum() < 5 or (1 - y).sum() < 5:
            continue
        res = P.nested_cv(X, y, groups, P.model_zoo()["gbt"], k_outer=4)
        s = res["oof_calibrated"]
        ok = ~np.isnan(s)
        if ok.sum() < 20 or len(np.unique(y[ok])) < 2:
            continue
        a = P.auc_roc(y[ok], s[ok])
        if a == a:
            per[str(cls)] = round(float(a), 4)
            worst = max(worst, a)
    return {"worst_auc": round(float(worst), 4) if per else None,
            "n_features": len(cols), "n_live": len(kept), "per_class": per}


def shortcut_ceiling(df) -> dict:
    """How much of the label does the generator variable alone explain?

    Scores each row by the empirical harm rate of its repair_class -- the best
    any model could do if all it ever learned was to recover repair_class.
    Reported as the ceiling that a learned result has to beat to mean anything.
    """
    rc = df.prov_repair_class_BANNED
    y = df.y_harmful.to_numpy()
    rate = df.groupby(rc).y_harmful.mean()
    s = rc.map(rate).to_numpy(dtype=float)
    tab = (df.groupby(rc).y_harmful.agg(["sum", "count", "mean"])
           .rename(columns={"sum": "harmful", "count": "n",
                            "mean": "harm_rate"}))
    return {"auc_roc": round(float(P.auc_roc(y, s)), 4),
            "auc_pr": round(float(P.auc_pr(y, s)), 4),
            "by_class": {str(k): {"harmful": int(v.harmful), "n": int(v.n),
                                  "harm_rate": round(float(v.harm_rate), 4)}
                         for k, v in tab.iterrows()},
            "note": "score = empirical harm rate of the row's repair_class. "
                    "This is an ORACLE: repair_class is banned from X. It is "
                    "the ceiling a model reaches by recovering the operator "
                    "rather than the risk."}


# ---------------------------------------------------------------------------
# 3-4. models
# ---------------------------------------------------------------------------
def evaluate(df, X, y, groups, factory, label: str) -> dict | None:
    res = P.nested_cv(X, y, groups, factory, k_outer=5)
    oof = res["oof_calibrated"]
    ok = ~np.isnan(oof)
    if ok.sum() < 20 or len(np.unique(y[ok])) < 2:
        return None
    pf = res["per_fold"]
    return {
        "label": label,
        "n_rows": int(len(y)), "effective_n": P.effective_n(X),
        "auc_pr_fold_mean": round(float(np.mean([f["auc_pr"] for f in pf])), 4),
        "auc_pr_fold_sd": round(float(np.std([f["auc_pr"] for f in pf])), 4),
        "auc_roc_fold_mean": round(float(np.mean([f["auc_roc"] for f in pf])), 4),
        "auc_roc_fold_sd": round(float(np.std([f["auc_roc"] for f in pf])), 4),
        "ece_fold_mean": round(float(np.mean([f["ece"] for f in pf])), 4),
        "pooled_auc_pr": round(float(P.auc_pr(y[ok], oof[ok])), 4),
        "pooled_auc_pr_ci95": P.clustered_bootstrap(y[ok], oof[ok],
                                                    groups[ok], P.auc_pr),
        "pooled_auc_roc": round(float(P.auc_roc(y[ok], oof[ok])), 4),
        "pooled_auc_roc_ci95": P.clustered_bootstrap(y[ok], oof[ok],
                                                     groups[ok], P.auc_roc),
        "permutation_p": P.permutation_p(y[ok], oof[ok], P.auc_pr),
        "brier_murphy": P.brier_murphy(y[ok], oof[ok]),
        "ece_pooled": round(float(P.ece(y[ok], oof[ok])), 4),
        "spiegelhalter": P.spiegelhalter_z(y[ok], oof[ok]),
        "reliability_table": P.reliability_table(y[ok], oof[ok]),
        "calibrator_choices": res["calibrator_choices"],
        "calibrator_param_spread": res["calibrator_param_spread"],
        "per_fold": pf,
        "selection": P.within_incident_ranking(df.iloc[ok], oof[ok]),
        "_oof": oof, "_ok": ok,
    }


def strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--bootstrap", type=int, default=P.BOOTSTRAP_RESAMPLES)
    a = ap.parse_args()
    P.BOOTSTRAP_RESAMPLES = a.bootstrap
    root = (REPO / a.pilot).resolve()
    P._require_sklearn()
    t0 = time.time()
    results: dict = {}

    say("INTERIM EXPLORATORY DIAGNOSTIC -- NOT THE CONFIRMATORY ANALYSIS")
    say("methodology: docs/ANALYSIS-PLAN.md (frozen 2026-09-02), unmodified")
    say(f"bootstrap resamples: {P.BOOTSTRAP_RESAMPLES}")

    # ---- 1. population ---------------------------------------------------
    hr("1. POPULATION")
    df, audit = P.build_dataset(root)
    sdf, saudit = P.build_dataset(root, sensitivity=True)
    for k in ("n_joined", "n_spec_pass", "n_spec_fail", "outcome_counts",
              "n_modelling", "n_harmful", "n_safe", "base_rate",
              "n_excluded", "excluded_rate", "excluded_by_outcome"):
        if k in audit:
            say(f"  {k:22s} {audit[k]}")
    mb = audit["manski_bounds"]
    say(f"  manski P(harm|PASS)    [{mb['p_min']}, {mb['p_max']}] "
        f"width {mb['width_points']} pts  (stop rule: >10)")
    say(f"  sensitivity (NO_CONV excluded)  n={saudit['n_modelling']} "
        f"base={saudit['base_rate']}")

    groups = df.incident_id.to_numpy()
    y = df.y_harmful.to_numpy()
    fam = family_col(df)
    say(f"  incidents {df.incident_id.nunique()}   topologies "
        f"{df.topology.nunique()}   fault families "
        f"{df[fam].nunique() if fam else 'n/a'}")

    k, n = int(y.sum()), len(y)
    lo, hi = P.wilson(k, n)
    blo, bhi = P.clustered_bootstrap(y, y.astype(float), groups,
                                     lambda yy, ss: float(yy.mean()))
    say(f"\n  P(harm | Batfish SPEC PASS) = {k}/{n} = {k / n:.4f}")
    say(f"    Wilson 95%                 [{lo}, {hi}]")
    say(f"    clustered bootstrap 95%    [{blo}, {bhi}]")
    results["population"] = {"audit": audit, "sensitivity_audit": saudit,
                             "p_harm_given_pass": round(k / n, 4),
                             "wilson95": [lo, hi],
                             "clustered_bootstrap95": [blo, bhi]}

    # exclusion + harm by stratum (the breakdown run_phase4 silently drops)
    for by, lab in ((("topology"), "topology"), (fam, "fault family")):
        if not by:
            continue
        say(f"\n  harm rate by {lab}:")
        rows = []
        for v, g in df.groupby(by):
            kk, nn = int(g.y_harmful.sum()), len(g)
            l2, h2 = P.wilson(kk, nn)
            rows.append({str(lab): str(v), "harmful": kk, "n": nn,
                         "rate": round(kk / nn, 4), "wilson95": [l2, h2]})
        for r in sorted(rows, key=lambda r: -r["rate"]):
            say(f"    {r[str(lab)]:22s} {r['harmful']:3d}/{r['n']:3d} = "
                f"{r['rate']:.3f}  [{r['wilson95'][0]}, {r['wilson95'][1]}]")
        results[f"harm_by_{lab.replace(' ', '_')}"] = rows

    # ---- 2. THE GATE -----------------------------------------------------
    hr("2. SHORTCUT / RECOVERABILITY GATE -- ON THE PASS POPULATION")
    say("  ANALYSIS-PLAN 14.2. worst-case one-vs-rest AUC for repair_class,")
    say("  incident-grouped nested CV, measured on the modelling rows only.")
    say(f"  threshold {GATE_THRESHOLD}: >= means the leak reaches the tier and")
    say("  the learned arm is not reportable as a risk model on this corpus.")

    sets = feature_sets(df)
    gate = {}
    say(f"\n  {'feature set':14s} {'nfeat':>6} {'live':>5}  {'worst AUC':>9}   "
        f"per-class")
    for name in ("A", "A+", "B", "C", "chg_only", "cov_only", "g_only",
                 "B_only", "C_only", "B+C_only", "no_chg", "no_g",
                 "no_chg_no_g"):
        r = recoverability(df, sets[name], groups, "prov_repair_class_BANNED")
        gate[name] = r
        w = r["worst_auc"]
        flag = "" if w is None else ("  <-- GATE FAILS" if w >= GATE_THRESHOLD
                                     else "  ok")
        say(f"  {name:14s} {r['n_features']:6d} {r.get('n_live', 0):5d}  "
            f"{('n/a' if w is None else f'{w:.3f}'):>9}   "
            f"{r['per_class']}{flag}")
    results["gate_recoverability_pass_population"] = gate

    # 2b. can fault_family be recovered too?
    if fam:
        r = recoverability(df, sets["C"], groups, fam)
        say(f"\n  fault_family recoverability from tier C: "
            f"worst AUC {r['worst_auc']}")
        results["gate_fault_family_recoverability"] = r

    # 2c. the ceiling
    hr("2c. SHORTCUT CEILING -- what repair_class alone buys")
    ceil = shortcut_ceiling(df)
    for cls, v in ceil["by_class"].items():
        say(f"  repair_class={cls:12s} {v['harmful']:3d}/{v['n']:3d} harmful "
            f"= {v['harm_rate']:.4f}")
    say(f"\n  ORACLE repair_class score: AUC-ROC {ceil['auc_roc']:.4f}   "
        f"AUC-PR {ceil['auc_pr']:.4f}")
    say("  Any model at or below this has not been shown to do anything the")
    say("  generator variable does not already do.")
    results["shortcut_ceiling"] = ceil

    # ---- 3. baselines ----------------------------------------------------
    hr("3. NON-LEARNED BASELINES")
    base = {}
    br = np.full(len(y), float(y.mean()))
    base["base_rate"] = {"auc_pr": round(float(P.auc_pr(y, br)), 4),
                         "brier": P.brier_murphy(y, br).get("brier"),
                         "selection": P.within_incident_ranking(df, br)}
    say(f"  base_rate            AUC-PR {base['base_rate']['auc_pr']:.4f} "
        f"(= prevalence)  Brier {base['base_rate']['brier']}")

    cols_c = [f"verdict_{p}" for p in P.ORACLE_ONLY
              if f"verdict_{p}" in df.columns]
    if cols_c:
        sw = (df[cols_c] == "FAIL").any(axis=1).astype(float).to_numpy()
        sel = P.within_incident_ranking(df, sw)
        tp = int(((sw == 1) & (y == 1)).sum()); fp = int(((sw == 1) & (y == 0)).sum())
        fn = int(((sw == 0) & (y == 1)).sum()); tn = int(((sw == 0) & (y == 0)).sum())
        base["spec_widening_rule"] = {
            "auc_pr": round(float(P.auc_pr(y, sw)), 4),
            "auc_roc": round(float(P.auc_roc(y, sw)), 4),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / max(1, tp + fp), 4),
            "recall": round(tp / max(1, tp + fn), 4),
            "balanced_accuracy": round(
                0.5 * (tp / max(1, tp + fn) + tn / max(1, tn + fp)), 4),
            "selection": sel,
            "ci95_auc_pr": P.clustered_bootstrap(y, sw, groups, P.auc_pr)}
        b = base["spec_widening_rule"]
        say(f"  spec_widening_rule   AUC-PR {b['auc_pr']:.4f} "
            f"{b['ci95_auc_pr']}  AUC-ROC {b['auc_roc']:.4f}")
        say(f"                       TP {tp} FP {fp} FN {fn} TN {tn}  "
            f"precision {b['precision']:.3f} recall {b['recall']:.3f} "
            f"balanced-acc {b['balanced_accuracy']:.3f}")
        say("  FINAL-PLAN 9: if this beats every learned model, THAT is the")
        say("  result and the conclusion is 'widen the specification'.")
    results["baselines"] = base

    # ---- 4. models -------------------------------------------------------
    hr("4. LEARNED MODELS -- nested grouped 5-fold, grouped by incident")
    say("  3 sub-folds fit / 1 fits the calibrator / 1 held out.")
    say("  Platt and beta both fitted; lower inner log loss wins.")
    say("  PER-FOLD mean +- sd is primary; the pooled curve is a visualisation.")
    zoo = P.model_zoo()
    models, best_gbt = {}, None
    for tier in ("A", "A+", "B", "C"):
        cols, removed = P.feature_columns(df, tier)
        X, kept, dropped = guarded(df, cols)
        say(f"\n  [{tier}] {len(kept)} live features "
            f"({len(dropped)} zero-variance dropped), "
            f"effective n = {P.effective_n(X)} of {len(X)} rows"
            + (f", leakage filter removed {removed}" if removed else ""))
        say(f"  {'model':9s} {'AUC-PR fold':>14s} {'pooled AUC-PR':>14s} "
            f"{'95% CI':>18s} {'p':>7s} {'ECE':>6s} {'AUC-ROC':>8s}")
        for mname, factory in zoo.items():
            r = evaluate(df, X, y, groups, factory, f"{tier}/{mname}")
            if r is None:
                say(f"  {mname:9s} -- could not be fitted")
                continue
            models[f"{tier}/{mname}"] = r
            ci = f"[{r['pooled_auc_pr_ci95'][0]}, {r['pooled_auc_pr_ci95'][1]}]"
            say(f"  {mname:9s} {r['auc_pr_fold_mean']:.3f}+-"
                f"{r['auc_pr_fold_sd']:.3f}   {r['pooled_auc_pr']:>13.3f} "
                f"{ci:>18} {r['permutation_p']:>7} {r['ece_pooled']:>6.3f} "
                f"{r['pooled_auc_roc']:>8.3f}")
            if mname == "gbt":
                if best_gbt is None or r["pooled_auc_pr"] > best_gbt["pooled_auc_pr"]:
                    best_gbt = r
    results["models"] = {k: strip(v) for k, v in models.items()}

    # ---- 5. shortcut-controlled ablations --------------------------------
    hr("5. DOES THE SIGNAL SURVIVE SHORTCUT CONTROL? (gbt)")
    say("  Same estimator and protocol; only the feature set changes.")
    say(f"  {'feature set':14s} {'AUC-PR':>8s} {'95% CI':>18s} {'p':>7s} "
        f"{'ECE':>6s}  {'repair_class AUC':>16s}")
    abl = {}
    for name in ("A+", "C", "B_only", "C_only", "B+C_only",
                 "no_chg", "no_g", "no_chg_no_g"):
        cols = sets[name]
        if not cols:
            continue
        X, kept, _ = guarded(df, cols)
        if not kept:
            continue
        r = evaluate(df, X, y, groups, zoo["gbt"], f"abl/{name}")
        if r is None:
            continue
        gw = gate.get(name, {}).get("worst_auc")
        abl[name] = {**strip(r), "repair_class_worst_auc": gw}
        ci = f"[{r['pooled_auc_pr_ci95'][0]}, {r['pooled_auc_pr_ci95'][1]}]"
        say(f"  {name:14s} {r['pooled_auc_pr']:>8.3f} {ci:>18} "
            f"{r['permutation_p']:>7} {r['ece_pooled']:>6.3f}  "
            f"{('n/a' if gw is None else f'{gw:.3f}'):>16}")
    results["ablations"] = abl

    # ---- 6. selection + autonomy ----------------------------------------
    hr("6. SELECTION AND AUTONOMY (primary GBT)")
    if best_gbt is not None:
        sel = best_gbt["selection"]
        say(f"  primary model: {best_gbt['label']}")
        say(f"  incidents with >=2 candidates : {sel.get('n_incidents_with_2plus')}")
        say(f"  incidents scorable (mixed)    : {sel.get('n_incidents_scorable')}")
        say(f"  top-1 selected harm rate      : {sel.get('top1_selected_harm_rate')}")
        say(f"  random choice harm rate       : {sel.get('random_choice_harm_rate')}")
        say(f"  oracle best harm rate         : {sel.get('oracle_best_harm_rate')}")
        say(f"  regret vs oracle              : {sel.get('regret_vs_oracle')}")
        say(f"  improvement vs random         : {sel.get('improvement_vs_random')}")
        say(f"  mean within-incident AUC      : {sel.get('mean_within_incident_auc')}")
        oof, ok = best_gbt["_oof"], best_gbt["_ok"]
        curve = P.autonomy_risk_curve(y[ok], oof[ok], groups[ok])
        say(f"\n  {'coverage':>9} {'n':>5} {'realised harm':>14} {'95% CI':>18}")
        for c in curve[::max(1, len(curve) // 8)]:
            say(f"  {c['coverage']:>9.3f} {c['n_auto_applied']:>5} "
                f"{c['realised_harm_rate']:>14.4f} "
                f"{'[%s, %s]' % (c['ci_low'], c['ci_high']):>18}")
        results["autonomy_risk_curve"] = curve
        results["primary_gbt"] = strip(best_gbt)

    # ---- 7. conformal: refused -------------------------------------------
    hr("7. CONFORMAL RISK CONTROL -- NOT ATTEMPTED")
    n_inc = int(df.incident_id.nunique())
    say(f"  incidents available: {n_inc}; protocol requires exactly "
        f"{CONFORMAL_REQUIRED_INCIDENTS} in a 120/40/40 topology-stratified "
        f"split.")
    say("  ANALYSIS-PLAN 10: alpha is never lowered to make a bound appear,")
    say("  and a split that does not exist is not made to exist by shrinking")
    say("  it. Conformal waits for the full planned dataset.")
    results["conformal"] = {"attempted": False, "n_incidents": n_inc,
                            "required": CONFORMAL_REQUIRED_INCIDENTS,
                            "reason": "120/40/40 grouped split unavailable"}

    # ---- 8. learning curve ------------------------------------------------
    hr("8. LEARNING CURVE (sampled by incident)")
    if best_gbt is not None:
        tier = best_gbt["label"].split("/")[0]
        cols, _ = P.feature_columns(df, tier)
        X, _, _ = guarded(df, cols)
        lc = P.learning_curve(X, y, groups, zoo["gbt"])
        for r in lc:
            say(f"  n={r['n']:>4}  AUC-PR {r['auc_pr_mean']:.3f}"
                f"+-{r['auc_pr_sd']:.3f}  ECE {r['ece_mean']:.3f} "
                f"({r['reps']} reps)")
        results["learning_curve"] = lc
        if len(lc) >= 2 and lc[-1]["auc_pr_mean"] - lc[0]["auc_pr_mean"] < 0.02:
            say("\n  FLAT between the smallest and largest point.")

    # ---- write -----------------------------------------------------------
    results["meta"] = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "INTERIM / EXPLORATORY -- not the confirmatory analysis",
        "analysis_plan": "docs/ANALYSIS-PLAN.md (frozen 2026-09-02), unmodified",
        "pilot": str(root), "wall_seconds": round(time.time() - t0, 1),
        "gate_threshold": GATE_THRESHOLD,
    }
    (OUT / "interim_results.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8")
    (OUT / "interim_report.txt").write_text("\n".join(_LOG), encoding="utf-8")
    say(f"\nwrote {OUT / 'interim_results.json'}")
    say(f"wrote {OUT / 'interim_report.txt'}")
    say(f"wall {results['meta']['wall_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
