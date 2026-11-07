"""How much of the residual risk would MORE PROPERTIES have removed?

    python pipeline/spec_sweep.py --pilot data/pilot-v2

THE OBJECTION THIS ANSWERS
--------------------------
"Your specification is five properties. Config2Spec mines near-complete
specifications automatically. Your false-pass rate measures the weakness of a
hand-written spec, not a property of verification."

That is correct as stated and fatal if unanswered. The answer is to stop
treating specification strength as a constant. Phase 2 records Batfish's
verdict on ALL twelve properties and Phase 3 measures all twelve, so the SPEC
can be redefined after the fact as any subset and the false-pass rate
recomputed -- at zero additional compute. If residual risk decays to zero as
the spec grows, the honest finding is "write more properties". If it plateaus
above zero, there is risk specification cannot remove, and that is the paper.

THE STATISTICS, AND WHY IT IS NOT A SUBSET SWEEP
------------------------------------------------
All three external reviews independently flagged the original design -- every
subset of every size -- as an uncorrected multiple-comparisons exercise over
heavily correlated resamples of the same candidates. Two of them proposed
Bonferroni or FDR.

Correction is the wrong instrument. The multiplicity is removed by
construction instead:

  * ONE pre-registered nested sequence. Oracle-only properties are added to
    SPEC one at a time in ascending property id -- an order fixed in
    docs/ANALYSIS-PLAN.md before any label existed, not chosen after seeing
    the curve. Eight points, |SPEC| = 5..12.
  * ONE confirmatory test: P(harm|PASS) under SPEC-5 versus SPEC-12, by
    clustered permutation over incidents. Every other point on the curve is
    descriptive and labelled as such.
  * The band is a clustered bootstrap resampling INCIDENTS, because candidates
    within an incident are not independent.
  * The random-subset variant is a sensitivity analysis, reported separately,
    to show how much the curve depends on the ordering rule.
"""
from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np                                             # noqa: E402
from nrl.properties import PROPERTIES                          # noqa: E402
from nrl.phase4 import wilson, LABEL_MAP                       # noqa: E402

SPEC_PIDS = [p["pid"] for p in PROPERTIES if p["in_spec"]]
#: FROZEN ORDER. Pre-registered in docs/ANALYSIS-PLAN.md. Ascending property
#: id, chosen because it is the one ordering that cannot have been picked to
#: make the curve look a particular way.
ORACLE_ORDER = sorted(p["pid"] for p in PROPERTIES if not p["in_spec"])


def load_csv(p: Path):
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rate_for_spec(rows, spec_pids):
    """P(harm | PASS) when SPEC is exactly `spec_pids`.

    A candidate PASSES that spec iff Batfish said PASS for every property in
    it. Harm is the frozen Containerlab outcome and does not change.
    """
    passed = [r for r in rows
              if all(r.get(f"verdict_{p}") == "PASS" for p in spec_pids)]
    decidable = [r for r in passed if r["outcome_harm_v1"] in LABEL_MAP]
    harmful = [r for r in decidable if LABEL_MAP[r["outcome_harm_v1"]] == 1]
    return len(harmful), len(decidable), len(passed)


def clustered_permutation_p(rows, spec_a, spec_b, n=2000, seed=0):
    """Null: the two specs' false-pass rates are exchangeable across incidents.

    Permuting incidents, not candidates -- candidates in one incident share a
    fault and most of their config, so permuting them understates the variance.
    """
    rng = np.random.default_rng(seed)
    ha, da, _ = rate_for_spec(rows, spec_a)
    hb, db, _ = rate_for_spec(rows, spec_b)
    if da == 0 or db == 0:
        return float("nan"), None
    obs = abs(ha / da - hb / db)
    by_inc = {}
    for r in rows:
        by_inc.setdefault(r["incident_id"], []).append(r)
    incs = sorted(by_inc)
    hits = 0
    for _ in range(n):
        swap = rng.random(len(incs)) < 0.5
        sub = []
        for flip, i in zip(swap, incs):
            for r in by_inc[i]:
                rr = dict(r)
                if flip:                       # swap this incident's spec labels
                    for pa, pb in zip(spec_a, spec_b):
                        rr[f"verdict_{pa}"], rr[f"verdict_{pb}"] = (
                            r.get(f"verdict_{pb}"), r.get(f"verdict_{pa}"))
                sub.append(rr)
        h1, d1, _ = rate_for_spec(sub, spec_a)
        h2, d2, _ = rate_for_spec(sub, spec_b)
        if d1 and d2 and abs(h1 / d1 - h2 / d2) >= obs:
            hits += 1
    return (hits + 1) / (n + 1), obs


def bootstrap_band(rows, spec_pids, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    by_inc = {}
    for r in rows:
        by_inc.setdefault(r["incident_id"], []).append(r)
    incs = sorted(by_inc)
    vals = []
    for _ in range(n):
        pick = rng.choice(len(incs), size=len(incs), replace=True)
        sub = [r for i in pick for r in by_inc[incs[i]]]
        h, d, _ = rate_for_spec(sub, spec_pids)
        if d:
            vals.append(h / d)
    if not vals:
        return (float("nan"), float("nan"))
    return (round(float(np.percentile(vals, 2.5)), 4),
            round(float(np.percentile(vals, 97.5)), 4))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--sensitivity", action="store_true",
                    help="also run the random-subset variant (exploratory)")
    a = ap.parse_args()
    root = (REPO / a.pilot).resolve()
    p2 = load_csv(root / "phase2" / "batfish_summary.csv")
    oc = {r["candidate_id"]: r for r in
          load_csv(root / "phase3" / "containerlab_outcomes.csv")}
    rows = []
    for r in p2:
        o = oc.get(r["candidate_id"])
        if not o:
            continue
        r = dict(r)
        r["outcome_harm_v1"] = o["outcome_harm_v1"]
        rows.append(r)

    print("=" * 74)
    print("SPECIFICATION-COMPLETENESS SWEEP")
    print(f"  candidates with both a Batfish verdict and an outcome: {len(rows)}")
    print(f"  frozen SPEC        : {SPEC_PIDS}")
    print(f"  pre-registered add order: {ORACLE_ORDER}")
    print("=" * 74)
    if not rows:
        print("no rows -- Phase 2 and Phase 3 must both have run")
        return 2

    print(f"\n{'|SPEC|':>6} {'added':>6} {'passed':>7} {'decidable':>10} "
          f"{'harmful':>8} {'P(harm|PASS)':>13} {'95% CI (clustered)':>22}")
    curve = []
    for k in range(len(ORACLE_ORDER) + 1):
        spec = SPEC_PIDS + ORACLE_ORDER[:k]
        h, d, p = rate_for_spec(rows, spec)
        rate = h / d if d else float("nan")
        lo, hi = bootstrap_band(rows, spec, a.bootstrap)
        wlo, whi = wilson(h, d)
        added = ORACLE_ORDER[k - 1] if k else "-"
        print(f"{len(spec):>6} {added:>6} {p:>7} {d:>10} {h:>8} "
              f"{rate:>13.4f} {f'[{lo:.3f}, {hi:.3f}]':>22}")
        curve.append({"spec_size": len(spec), "spec": spec, "added": added,
                      "n_passed": p, "n_decidable": d, "n_harmful": h,
                      "false_pass_rate": round(rate, 4) if d else None,
                      "boot_ci": [lo, hi], "wilson_ci": [wlo, whi]})

    print("\nCONFIRMATORY TEST (the only one; everything above is descriptive)")
    full = SPEC_PIDS + ORACLE_ORDER
    pv, obs = clustered_permutation_p(rows, SPEC_PIDS, full,
                                      n=min(a.bootstrap, 2000))
    print(f"  H0: P(harm|PASS) is the same under SPEC-{len(SPEC_PIDS)} and "
          f"SPEC-{len(full)}")
    print(f"  observed difference : {obs:.4f}" if obs is not None else
          "  observed difference : n/a")
    print(f"  clustered permutation p = {pv}")

    first, last = curve[0], curve[-1]
    if first["false_pass_rate"] is not None and last["false_pass_rate"] is not None:
        print(f"\n  recoverable by widening the spec : "
              f"{first['false_pass_rate'] - last['false_pass_rate']:.4f}")
        print(f"  IRREDUCIBLE (survives the full oracle): "
              f"{last['false_pass_rate']:.4f}")
        print("  The second number is the one that argues for a learned risk")
        print("  layer. The first argues for writing more properties.")

    out = root / "phase4"
    out.mkdir(exist_ok=True)
    (out / "spec_sweep.json").write_text(json.dumps({
        "spec_pids": SPEC_PIDS, "oracle_order": ORACLE_ORDER,
        "pre_registered": "docs/ANALYSIS-PLAN.md",
        "curve": curve,
        "confirmatory": {"comparison": f"SPEC-{len(SPEC_PIDS)} vs SPEC-{len(full)}",
                         "observed_difference": obs, "p_value": pv,
                         "test": "clustered permutation over incidents"},
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out / 'spec_sweep.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
