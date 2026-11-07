"""Phase 4: assemble the dataset, model the residual risk, calibrate, bound it.

    python pipeline/run_phase4.py --pilot data/pilot-v2

Reads Phases 1-3 and writes ONLY to <pilot>/phase4/. It never modifies a
Phase 1-3 file and never re-runs a lab.

The protocol is frozen in docs/ANALYSIS-PLAN.md and this script implements it
rather than choosing it. In particular the split structure, the calibrator
selection rule, the bin count, the single confirmatory test and the stop rules
were all fixed before any label existed; anything this script prints that is
not in that document is exploratory and is labelled so.

Order of output, which is also the order of the paper:
  1. the population, and what was excluded from it (with Manski bounds)
  2. the verification study      -- no model involved
  3. selection                   -- can we rank within an incident?
  4. calibration                 -- does the number mean what it says?
  5. control                     -- the autonomy-risk curve and the bound
  6. the learning curve          -- would more data have helped?
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np                                             # noqa: E402
from nrl import phase4 as P                                    # noqa: E402


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wj(p: Path, o):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, indent=2, default=str) + "\n",
                 newline="\n", encoding="utf-8")


def hr(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def spec_widening_rule(df):
    """Non-learned baseline: HARMFUL iff Batfish reports ANY oracle-only
    property failing. In pilot-v1 this beat every learned model. If it wins
    again, THAT is the paper's result and the conclusion is 'widen the
    specification', not 'train a model'."""
    cols = [f"verdict_{p}" for p in P.ORACLE_ONLY if f"verdict_{p}" in df.columns]
    if not cols:
        return None
    return (df[cols] == "FAIL").any(axis=1).astype(float).to_numpy()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. No default: a "
                         "default silently pointed every command at the old "
                         "pilot.")
    ap.add_argument("--tiers", default="A,A+,B,C")
    ap.add_argument("--alpha", default="0.05,0.10",
                    help="conformal risk levels to attempt")
    ap.add_argument("--no-learning-curve", action="store_true")
    a = ap.parse_args()
    root = (REPO / a.pilot).resolve()
    out = root / "phase4"
    P._require_sklearn()

    # ---- 1. population -------------------------------------------------
    hr("1. POPULATION")
    df, audit = P.build_dataset(root)
    sens_df, sens_audit = P.build_dataset(root, sensitivity=True)
    for k in ("n_joined", "n_spec_pass", "n_spec_fail", "outcome_counts",
              "n_modelling", "n_harmful", "n_safe", "base_rate",
              "n_excluded", "excluded_rate", "excluded_by_outcome"):
        if k in audit:
            print(f"  {k:24s} {audit[k]}")
    mb = audit["manski_bounds"]
    print(f"\n  MANSKI BOUNDS on P(harm|PASS): [{mb['p_min']}, {mb['p_max']}] "
          f"width {mb['width_points']} points over n={mb['n']}")
    if mb["width_points"] > 10:
        print("  *** STOP RULE: width > 10 points. The undecidable outcomes are")
        print("  *** too many to support a rate. Fix the harness (see")
        print("  *** docs/ANALYSIS-PLAN.md section 12) before reporting one.")
    for by in ("topology", "prov_fault_family_BANNED"):
        key = f"excluded_rate_by_{by}"
        if key in audit:
            worst = sorted(audit[key].items(), key=lambda kv: -kv[1])[:3]
            print(f"  worst exclusion rates by {by}: {worst}")
    if not len(df):
        print("\nno modelling population -- Phase 2 and Phase 3 must both have run")
        return 2

    groups = df.incident_id.to_numpy()
    y = df.y_harmful.to_numpy()

    # ---- 2. the verification study, no model ---------------------------
    hr("2. VERIFICATION STUDY (no model involved)")
    k, n = int(y.sum()), len(y)
    lo, hi = P.wilson(k, n)
    print(f"  P(harm | Batfish SPEC PASS) = {k}/{n} = {k / n:.4f}  "
          f"Wilson 95% [{lo}, {hi}]")
    blo, bhi = P.clustered_bootstrap(y, y.astype(float), groups,
                                     lambda yy, ss: float(yy.mean()))
    print(f"  clustered bootstrap over incidents:      [{blo}, {bhi}]")
    print(f"  sensitivity (NO_CONVERGENCE excluded):   "
          f"{sens_audit.get('base_rate')} on n={sens_audit.get('n_modelling')}")
    for by, label in (("topology", "topology"),
                      ("prov_fault_family_BANNED", "fault family")):
        if by not in df.columns:
            continue
        print(f"\n  by {label}:")
        for v, g in df.groupby(by):
            kk, nn = int(g.y_harmful.sum()), len(g)
            l2, h2 = P.wilson(kk, nn)
            print(f"    {str(v):22s} {kk:4d}/{nn:4d} = {kk / nn:.3f}  [{l2}, {h2}]")

    # ---- 3. selection ---------------------------------------------------
    hr("3. SELECTION -- can we rank within an incident?")
    results = {}
    tiers = [t.strip() for t in a.tiers.split(",") if t.strip()]
    zoo = P.model_zoo()

    baselines = {"base_rate": np.full(len(y), float(y.mean()))}
    sw = spec_widening_rule(df)
    if sw is not None:
        baselines["spec_widening_rule"] = sw

    for name, s in baselines.items():
        r = P.within_incident_ranking(df, s)
        print(f"  {name:20s} top1 harm={r.get('top1_selected_harm_rate')} "
              f"random={r.get('random_choice_harm_rate')} "
              f"regret={r.get('regret_vs_oracle')}")
        results[f"selection/{name}"] = r

    # ---- 4. models, calibration ----------------------------------------
    hr("4. MODELS AND CALIBRATION")
    print(f"  protocol: nested grouped CV, 5 outer folds, grouped by incident")
    print(f"  calibrator: Platt and beta both fitted, lower log loss wins")
    print(f"  reported: PER-FOLD mean +- sd. The pooled curve is a")
    print(f"            visualisation; no inferential claim rests on it.\n")
    best = None
    primary_gbt = None
    for tier in tiers:
        cols, removed = P.feature_columns(df, tier)
        if removed:
            print(f"  [{tier}] leakage filter removed {len(removed)}: {removed}")
        X, kept, dropped = P.matrix(df, cols)
        if dropped:
            print(f"  [{tier}] zero-variance dropped {len(dropped)}: "
                  f"{dropped[:6]}{'...' if len(dropped) > 6 else ''}")
        print(f"  [{tier}] {len(kept)} live features, effective n = "
              f"{P.effective_n(X)} of {len(X)} rows")
        for mname, factory in zoo.items():
            res = P.nested_cv(X, y, groups, factory, k_outer=5)
            oof = res["oof_calibrated"]
            ok = ~np.isnan(oof)
            if ok.sum() < 20 or len(np.unique(y[ok])) < 2:
                continue
            pf = res["per_fold"]
            row = {
                "tier": tier, "model": mname,
                "n_features": len(kept), "effective_n": P.effective_n(X),
                "auc_pr_fold_mean": round(float(np.mean(
                    [f["auc_pr"] for f in pf])), 4),
                "auc_pr_fold_sd": round(float(np.std(
                    [f["auc_pr"] for f in pf])), 4),
                "auc_roc_fold_mean": round(float(np.mean(
                    [f["auc_roc"] for f in pf])), 4),
                "ece_fold_mean": round(float(np.mean(
                    [f["ece"] for f in pf])), 4),
                "pooled_auc_pr": round(P.auc_pr(y[ok], oof[ok]), 4),
                "pooled_auc_pr_ci95": P.clustered_bootstrap(
                    y[ok], oof[ok], groups[ok], P.auc_pr),
                "permutation_p": P.permutation_p(y[ok], oof[ok], P.auc_pr),
                "brier_murphy": P.brier_murphy(y[ok], oof[ok]),
                "ece_pooled": round(P.ece(y[ok], oof[ok]), 4),
                "spiegelhalter": P.spiegelhalter_z(y[ok], oof[ok]),
                "reliability_table": P.reliability_table(y[ok], oof[ok]),
                "calibrator_choices": res["calibrator_choices"],
                "calibrator_param_spread": res["calibrator_param_spread"],
                "per_fold": pf,
                "selection": P.within_incident_ranking(df.iloc[ok], oof[ok]),
            }
            results[f"model/{tier}/{mname}"] = row
            print(f"    {mname:8s} AUC-PR {row['auc_pr_fold_mean']:.3f}"
                  f"+-{row['auc_pr_fold_sd']:.3f}  "
                  f"pooled {row['pooled_auc_pr']:.3f} "
                  f"{row['pooled_auc_pr_ci95']}  p={row['permutation_p']}  "
                  f"ECE {row['ece_pooled']:.3f}  "
                  f"cal={sorted(set(row['calibrator_choices']))}")
            if mname == "gbt" and primary_gbt is None:
                primary_gbt = ((tier, mname), row, oof, ok)
            if best is None or row["pooled_auc_pr"] > best[1]["pooled_auc_pr"]:
                best = ((tier, mname), row, oof, ok)

    if best is None:
        print("\n  no model could be fitted -- too few rows or one class only")
        wj(out / "phase4_results.json",
           {"generated_utc": now(), "audit": audit, "results": results})
        return 1

    if primary_gbt is None:
        print("\n  no gradient-boosted-tree result could be fitted")
        return 1
    (btier, bmodel), brow, boof, bok = primary_gbt
    print(f"\n  primary model: tier {btier}, {bmodel}")
    print("  Read this against the base rate and the spec-widening rule above.")
    print("  Other models remain comparison baselines; they do not replace GBT.")

    # ---- 5. control ------------------------------------------------------
    hr("5. CONTROL -- autonomy-risk curve and the conformal bound")
    curve = P.autonomy_risk_curve(y[bok], boof[bok], groups[bok])
    print(f"  {'coverage':>9} {'n':>6} {'realised harm':>14} {'95% CI':>18}")
    for c in curve[::max(1, len(curve) // 8)]:
        ci = f"[{c['ci_low']}, {c['ci_high']}]"
        print(f"  {c['coverage']:>9.3f} {c['n_auto_applied']:>6} "
              f"{c['realised_harm_rate']:>14.4f} {ci:>18}")
    results["autonomy_risk_curve"] = curve

    conformal_cols, _ = P.feature_columns(df, btier)
    conformal_X, _, _ = P.matrix(df, conformal_cols)
    conformal_alpha = tuple(float(x) for x in a.alpha.split(","))
    conformal = P.conformal_protocol(
        df, conformal_X, y, zoo[bmodel], alpha=conformal_alpha)
    for level, by_cluster in conformal["alpha"].items():
        for cl, r in by_cluster.items():
            if r["vacuous"]:
                print(f"  alpha={level} clustered by {cl:11s} VACUOUS "
                      f"(K={r['n_clusters']}, floor={r.get('alpha_floor')}) "
                      f"-- {r['reason']}")
            else:
                print(f"  alpha={level} clustered by {cl:11s} "
                      f"threshold={r['threshold']:.4f} K={r['n_clusters']} "
                      f"test coverage={r['test_coverage']:.3f} "
                      f"test harm={r['test_harm_rate']}")
    results["conformal"] = conformal
    print("\n  alpha is never lowered to make a bound appear. A vacuous result")
    print("  is reported as vacuous, with the floor 1/(K+1) that caused it.")

    # ---- 6. learning curve ----------------------------------------------
    if not a.no_learning_curve:
        hr("6. LEARNING CURVE -- would more data have helped?")
        cols, _ = P.feature_columns(df, btier)
        X, _, _ = P.matrix(df, cols)
        lc = P.learning_curve(X, y, groups, zoo[bmodel])
        for r in lc:
            print(f"  n={r['n']:>5}  AUC-PR {r['auc_pr_mean']:.3f}"
                  f"+-{r['auc_pr_sd']:.3f}  ECE {r['ece_mean']:.3f}  "
                  f"({r['reps']} reps)")
        results["learning_curve"] = lc
        if len(lc) >= 2 and lc[-1]["auc_pr_mean"] - lc[0]["auc_pr_mean"] < 0.02:
            print("\n  FLAT. Per the stop rules, more data is not the answer:")
            print("  spend the remaining budget on the FAIL arm, the replicates")
            print("  and the specification sweep, and write the negative result.")

    wj(out / "phase4_results.json", {
        "generated_utc": now(), "pilot": str(root),
        "analysis_plan": "docs/ANALYSIS-PLAN.md (frozen 2026-09-02)",
        "audit": audit, "sensitivity_audit": sens_audit,
        "best": {"tier": btier, "model": bmodel},
        "results": results})
    print(f"\nwrote {out / 'phase4_results.json'}")
    print("next:  python pipeline/spec_sweep.py --pilot " + a.pilot)
    print("       python pipeline/attribute_harm.py --pilot " + a.pilot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
