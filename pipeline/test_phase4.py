"""Controls for Phase 4: labels, leakage, statistics, conformal.

The model-fitting parts need scikit-learn and are skipped if it is absent; the
parts that decide what the numbers MEAN -- the label mapping, the exclusion
accounting, the leakage filter, the conformal quantile -- never are, because
those are where the optimistic defects live.

    python pipeline/test_phase4.py
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np                                             # noqa: E402
import pandas as pd                                            # noqa: E402
from nrl import phase4 as P                                    # noqa: E402

FAIL = []
try:
    import sklearn                                             # noqa: F401
    HAVE_SK = True
except ImportError:
    HAVE_SK = False


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAIL.append(label)
        if detail:
            print(f"         {detail}")


def main() -> int:
    print("CHECK 1 -- B4: the outcome-to-label mapping")
    check("HARMFUL -> 1", P.LABEL_MAP["HARMFUL"] == 1)
    check("SAFE -> 0", P.LABEL_MAP["SAFE"] == 0)
    check("NO_CONVERGENCE -> 1 (frozen harm definition, primary analysis)",
          P.LABEL_MAP["NO_CONVERGENCE"] == 1,
          "it was silently 0, i.e. SAFE -- optimistic in direction")
    check("UNDETERMINED is NOT in the label map",
          "UNDETERMINED" not in P.LABEL_MAP,
          "an undecidable measurement is not a safe one")
    check("EXECUTION_FAILED is NOT in the label map",
          "EXECUTION_FAILED" not in P.LABEL_MAP)
    check("the sensitivity map excludes NO_CONVERGENCE instead of counting it",
          "NO_CONVERGENCE" not in P.LABEL_MAP_SENSITIVITY
          and P.LABEL_MAP_SENSITIVITY["HARMFUL"] == 1)

    print("\nCHECK 2 -- Manski bounds bracket the undecidable rows")
    df = pd.DataFrame({"outcome_harm_v1":
                       ["HARMFUL"] * 20 + ["SAFE"] * 70 + ["UNDETERMINED"] * 10})
    b = P.manski_bounds(df, P.LABEL_MAP)
    check("p_min counts only observed harm", b["p_min"] == 0.20, str(b))
    check("p_max counts every undecidable row as harmful", b["p_max"] == 0.30,
          str(b))
    check("width is reported in points", b["width_points"] == 10.0, str(b))
    clean = P.manski_bounds(
        pd.DataFrame({"outcome_harm_v1": ["HARMFUL"] * 2 + ["SAFE"] * 8}),
        P.LABEL_MAP)
    check("with nothing undecidable the bracket collapses to a point",
          clean["p_min"] == clean["p_max"] == 0.2, str(clean))

    print("\nCHECK 3 -- the leakage filter REPORTS what it removed")
    df2 = pd.DataFrame({
        "chg_lines_added": [1, 2], "cov_spec_n_properties": [5, 5],
        "g_n_bridges_after": [1, 0],
        "prov_fault_family_BANNED": ["a", "b"],
        "chg_repair_hint": [0, 1],            # contains 'repair_' -> banned
        "outcome_harm_v1": ["SAFE", "HARMFUL"]})
    kept, removed = P.feature_columns(df2, "A+")
    check("a banned provenance column is removed",
          "prov_fault_family_BANNED" not in kept)
    check("the removal is REPORTED, not silent", len(removed) > 0, str(removed))
    check("chg_repair_hint is caught by substring", "chg_repair_hint" in removed,
          str(removed))
    check("legitimate features survive",
          "chg_lines_added" in kept and "g_n_bridges_after" in kept, str(kept))
    check("tier A excludes graph features, tier A+ includes them",
          "g_n_bridges_after" not in P.feature_columns(df2, "A")[0]
          and "g_n_bridges_after" in kept)

    print("\nCHECK 3b -- primary dataset is explicitly PASS-conditioned")
    original_load = P.load
    try:
        P.load = lambda _pilot: {
            "meta": pd.DataFrame({
                "candidate_id": ["P1", "F1"],
                "incident_id": ["I1", "I2"],
                "topology": ["t1", "t1"],
                "prov_fault_family_BANNED": ["f", "f"],
                "chg_lines_added": [1, 2],
            }),
            "p2": pd.DataFrame({
                "candidate_id": ["P1", "F1"],
                "incident_id": ["I1", "I2"],
                "batfish_spec_verdict": ["PASS", "FAIL"],
            }),
            "outcomes": pd.DataFrame({
                "candidate_id": ["P1", "F1"],
                "outcome_harm_v1": ["SAFE", "HARMFUL"],
            }),
        }
        primary, audit = P.build_dataset(Path("unused"))
        controls, control_audit = P.build_fail_control_dataset(Path("unused"))
        check("primary dataset contains PASS rows only",
              set(primary.batfish_spec_verdict) == {"PASS"}, str(primary))
        check("primary dataset excludes FAIL outcome rows",
              set(primary.candidate_id) == {"P1"}, str(primary))
        check("FAIL controls remain separately available",
              set(controls.batfish_spec_verdict) == {"FAIL"}
              and control_audit["population_verdict"] == "FAIL")
        check("primary audit records the conditioning verdict",
              audit["population_verdict"] == "PASS")
    finally:
        P.load = original_load

    print("\nCHECK 4 -- effective n counts distinct rows, not rows")
    X = np.array([[1.0, 2.0]] * 9 + [[3.0, 4.0]])
    check("nine identical rows count once", P.effective_n(X) == 2,
          f"got {P.effective_n(X)} -- RC-cost_norm_1..9 collapse like this")

    print("\nCHECK 5 -- Wilson and Clopper-Pearson")
    lo, hi = P.wilson(0, 150)
    check("Wilson at 0/150 has a lower bound of exactly 0", lo == 0.0)
    cp = P.clopper_pearson_upper(0, 150)
    check("exact upper bound for 0/150 is close to the rule of three (2%)",
          0.015 < cp < 0.021, f"{cp}")
    check("exact bound is TIGHTER than 3/n", cp < 3 / 150, f"{cp} vs {3/150}")
    check("more samples give a tighter bound",
          P.clopper_pearson_upper(0, 300) < cp)

    print("\nCHECK 6 -- Brier/Murphy decomposition is an identity")
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 400).round(2)
    y = (rng.uniform(size=400) < p).astype(int)
    d = P.brier_murphy(y, p)
    check("brier == reliability - resolution + uncertainty",
          abs(d["brier"] - d["identity_check"]) < 1e-6, str(d))
    perfect = P.brier_murphy(np.array([1, 1, 0, 0]), np.array([1., 1., 0., 0.]))
    check("a perfect forecast has zero reliability term",
          perfect["reliability"] == 0.0, str(perfect))

    print("\nCHECK 7 -- calibration metrics have power")
    good = P.ece(y, p)
    bad = P.ece(y, np.clip(p + 0.3, 0, 1))
    check("ECE rises when forecasts are shifted off calibration", bad > good,
          f"{good} -> {bad}")
    zs_good = P.spiegelhalter_z(y, p)
    zs_bad = P.spiegelhalter_z(y, np.clip(p + 0.3, 0, 1))
    check("Spiegelhalter z rejects a miscalibrated forecast",
          zs_bad["p_value"] < 0.05 <= zs_good["p_value"],
          f"good={zs_good} bad={zs_bad}")

    print("\nCHECK 8 -- clustered bootstrap is WIDER than the naive one")
    # 20 incidents x 20 candidates, label mostly constant within an incident
    # (which is the real structure) but not perfectly separable, so AUC varies
    # across resamples and the two intervals can differ at all.
    g = np.repeat(np.arange(20), 20)
    base = np.repeat(rng.integers(0, 2, 20), 20)
    flip = rng.uniform(size=len(base)) < 0.15
    yy = np.where(flip, 1 - base, base)
    ss = base * 0.5 + rng.uniform(0, 0.5, len(yy))
    lo_c, hi_c = P.clustered_bootstrap(yy, ss, g, P.auc_roc, n=300)
    lo_n, hi_n = P.clustered_bootstrap(yy, ss, np.arange(len(yy)),
                                       P.auc_roc, n=300)
    check("resampling incidents gives a wider CI than resampling candidates",
          (hi_c - lo_c) > (hi_n - lo_n),
          f"clustered={hi_c - lo_c:.4f} naive={hi_n - lo_n:.4f} -- if this "
          f"fails the clustering correction is doing nothing")

    print("\nCHECK 9 -- hierarchical conformal: the alpha floor is real")
    # The floor is alpha >= 1/(K+1). At K=20 that is 0.0476, so alpha=0.05 is
    # supported -- just. alpha=0.04 is not. The plan said "20 incidents cannot
    # support alpha much below 0.05", which is right; "0.05 is unsupportable"
    # would have been wrong, and this check is what settles it.
    cal = pd.DataFrame({"incident_id": np.repeat(np.arange(20), 5)})
    risk = rng.uniform(size=100)
    r04 = P.conformal_threshold(cal, risk, 0.04)
    check("alpha=0.04 with 20 clusters is VACUOUS (below the 1/(K+1) floor)",
          r04["vacuous"], f"{r04}")
    check("the vacuous result reports the alpha floor 1/(K+1)",
          abs(r04["alpha_floor"] - 1 / 21) < 1e-3, str(r04))
    r05 = P.conformal_threshold(cal, risk, 0.05)
    check("alpha=0.05 with 20 clusters is supported, but only just",
          (not r05["vacuous"]) and r05["quantile_rank"] == 20, str(r05))
    r10 = P.conformal_threshold(cal, risk, 0.10)
    check("alpha=0.10 with 20 clusters IS supported", not r10["vacuous"],
          str(r10))
    cal40 = pd.DataFrame({"incident_id": np.repeat(np.arange(40), 5)})
    r05b = P.conformal_threshold(cal40, rng.uniform(size=200), 0.05)
    check("alpha=0.05 becomes supported at 40 clusters", not r05b["vacuous"],
          f"{r05b} -- this is why the plan splits 120/40/40 by incident")
    check("the score is the MAX within a cluster, not the mean",
          "max-per-cluster" in r10.get("method", ""), r10.get("method"))

    print("\nCHECK 9b -- conformal protocol uses disjoint incident partitions")
    split_df = pd.DataFrame({
        "incident_id": np.repeat(np.arange(200), 2),
        "topology": np.repeat(np.arange(20), 20),
    })
    split = P.conformal_incident_split(split_df, seed=7)
    train_ids = set(split["train_incidents"])
    cal_ids = set(split["calibration_incidents"])
    test_ids = set(split["test_incidents"])
    check("conformal split has 120/40/40 incidents",
          (len(train_ids), len(cal_ids), len(test_ids)) == (120, 40, 40))
    check("train/calibration incidents are disjoint", not train_ids & cal_ids)
    check("train/test incidents are disjoint", not train_ids & test_ids)
    check("calibration/test incidents are disjoint", not cal_ids & test_ids)
    check("conformal split is topology-stratified",
          split_df.loc[split["train_mask"]].groupby("topology").size().nunique() == 1
          and split_df.loc[split["calibration_mask"]].groupby("topology").size().nunique() == 1
          and split_df.loc[split["test_mask"]].groupby("topology").size().nunique() == 1)

    print("\nCHECK 10 -- autonomy-risk curve is monotone in coverage")
    yy2 = (rng.uniform(size=300) < 0.4).astype(int)
    rr = yy2 * 0.6 + rng.uniform(0, 0.4, 300)
    curve = P.autonomy_risk_curve(yy2, rr, np.arange(300))
    cov = [c["coverage"] for c in curve]
    check("coverage increases with the threshold", cov == sorted(cov))
    check("harm among the lowest-risk slice is below the base rate",
          curve[0]["realised_harm_rate"] < yy2.mean(),
          f"{curve[0]} vs base {yy2.mean():.3f}")

    print("\nCHECK 11 -- within-incident selection")
    d = pd.DataFrame({"incident_id": np.repeat(np.arange(30), 4),
                      "y_harmful": np.tile([0, 1, 1, 1], 30)})
    perfect_risk = np.tile([0.1, 0.9, 0.9, 0.9], 30)
    r = P.within_incident_ranking(d, perfect_risk)
    check("a perfect ranker always picks the safe candidate",
          r["top1_selected_harm_rate"] == 0.0, str(r))
    check("regret against the oracle is zero", r["regret_vs_oracle"] == 0.0)
    check("it beats random choice", r["improvement_vs_random"] > 0, str(r))
    inverted = P.within_incident_ranking(d, 1 - perfect_risk)
    check("NEGATIVE CONTROL: an inverted ranker always picks a harmful one",
          inverted["top1_selected_harm_rate"] == 1.0, str(inverted))

    print("\nCHECK 12 -- models (needs scikit-learn)")
    if not HAVE_SK:
        print("  [SKIP] scikit-learn not installed in this interpreter.")
        print("         Install it before Phase 4: pip install scikit-learn")
    else:
        Xg = rng.normal(size=(400, 6))
        yg = (Xg[:, 0] + rng.normal(0, 0.4, 400) > 0).astype(int)
        gg = np.repeat(np.arange(40), 10)
        for nm, f in P.model_zoo().items():
            res = P.nested_cv(Xg, yg, gg, f, k_outer=4)
            ok = ~np.isnan(res["oof_calibrated"])
            a = P.auc_roc(yg[ok], res["oof_calibrated"][ok])
            check(f"{nm}: learns a learnable signal (AUC > 0.7)", a > 0.7,
                  f"AUC={a:.3f}")
        res = P.nested_cv(Xg, rng.integers(0, 2, 400), gg,
                          P.model_zoo()["gbt"], k_outer=4)
        ok = ~np.isnan(res["oof_calibrated"])
        a = P.auc_roc(rng.integers(0, 2, 400)[ok], res["oof_calibrated"][ok])
        check("NEGATIVE CONTROL: random labels give ~chance AUC", 0.35 < a < 0.65,
              f"AUC={a:.3f} on noise -- if this is high, the CV leaks")

    print("\n" + "=" * 62)
    print("ALL PHASE 4 CHECKS PASSED" if not FAIL else "FAILED")
    for f_ in FAIL:
        print(f"   {f_}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
