"""WHERE does the generator's signature live in X?

    python pipeline/diagnose_shortcut.py --pilot data/pilot-v2

audit_dataset.py section 3 asks WHETHER repair_class is recoverable from the
features. If it is, any learned result on y_harmful is that shortcut wearing a
different hat, because repair_class largely determines harm.

This asks WHERE. It removes one feature group at a time and re-measures, and
it fits a single feature at a time, so the answer is either "one column is a
near-perfect operator tag, drop it" or "the signature is distributed and no
subset of these features is clean". Those two findings have completely
different consequences and the difference is a two-minute run.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np                                             # noqa: E402
import pandas as pd                                            # noqa: E402
from nrl.phase4 import auc_roc, model_zoo, nested_cv           # noqa: E402


def load_phase2(root: Path) -> pd.DataFrame:
    """Batfish's own outputs, if Phase 2 has run.

    These are the OPEN question. chg_/cov_/g_ describe the EDIT, and the audit
    found they describe the operator that made it. Tier B and Tier C describe
    the AFTER NETWORK as Batfish sees it -- parse health, RIB and adjacency
    counts, and its verdicts on the oracle-only properties. docs/LEAKAGE.md has
    always treated those as eligible, and they are what an operator actually has
    before deploying. Whether they carry the same generator signature cannot be
    known until Phase 2 exists, and it decides whether a usable risk score
    exists at all.
    """
    f = root / "phase2" / "batfish_summary.csv"
    if not f.exists():
        return None
    return pd.read_csv(f)


def load(root: Path) -> pd.DataFrame:
    man = json.loads((root / "manifest.json").read_text())
    rows = []
    for c in man["candidates"]:
        m = json.loads((root / "candidates" / c["candidate_id"]
                        / "meta.json").read_text())
        r = {"incident_id": c["incident_id"], "topology": c["topology"],
             "repair_class": c["repair_class"], "repair_id": c["repair_id"]}
        r.update({f"chg_{k}": v for k, v in m["change_stats"].items()
                  if not isinstance(v, list)})
        r.update({f"cov_{k}": v for k, v in m["spec_coverage"].items()})
        r.update(m.get("graph_features") or {})
        rows.append(r)
    return pd.DataFrame(rows)


#: the same encoding phase4.matrix() uses. PASS/FAIL was missing here, so the
#: Tier C verdict columns coerced to NaN, filled to 0.0, went zero-variance and
#: were dropped -- and the tier reported `nan`, which reads as "clean" and means
#: "never measured". Silent coercion into a constant is the same shape as every
#: other defect in this project's log.
_ENCODE = {True: 1.0, False: 0.0, "True": 1.0, "False": 0.0,
           "PASS": 0.0, "FAIL": 1.0}


def numeric(df, cols):
    X = df[list(cols)].copy()
    lost = []
    for c in cols:
        before = X[c].notna().sum()
        if X[c].dtype == object:
            X[c] = X[c].map(_ENCODE)
        X[c] = pd.to_numeric(X[c], errors="coerce")
        if before and X[c].notna().sum() == 0:
            lost.append(c)
    if lost:
        vals = {c: sorted(set(map(str, df[c].dropna().unique()))[:4])
                for c in lost}
        raise SystemExit(
            f"BLOCKED: {len(lost)} column(s) became entirely NaN under the "
            f"encoding and would have been silently dropped as constant:\n"
            f"         {vals}\n"
            f"         Add their values to _ENCODE. A tier that reports `nan` "
            f"because its columns vanished is not a clean tier, it is an "
            f"unmeasured one.")
    X = X.fillna(0.0)
    keep = [c for c in cols if X[c].std() > 0]
    return X[keep].to_numpy(dtype=float), keep


def recoverability(df, cols, groups, label="") -> float:
    """Worst-case one-vs-rest AUC for repair_class over `cols`."""
    if not cols:
        return float("nan")
    X, kept = numeric(df, cols)
    if not kept:
        return float("nan")
    worst = 0.0
    for cls in sorted(df.repair_class.unique()):
        y = (df.repair_class == cls).astype(int).to_numpy()
        res = nested_cv(X, y, groups, model_zoo()["gbt"], k_outer=4)
        s = res["oof_calibrated"]
        ok = ~np.isnan(s)
        if ok.sum() < 20:
            continue
        a = auc_roc(y[ok], s[ok])
        if a == a:
            worst = max(worst, a)
    return worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    args = ap.parse_args()
    root = (REPO / args.pilot).resolve()
    df = load(root)
    groups = df.incident_id.to_numpy()

    chg = [c for c in df.columns if c.startswith("chg_")]
    cov = [c for c in df.columns if c.startswith("cov_")]
    gph = [c for c in df.columns if c.startswith("g_")]
    allf = chg + cov + gph

    print("=" * 74)
    print("WHERE IS THE GENERATOR SIGNATURE?")
    print("  worst-case one-vs-rest AUC for repair_class. 0.5 = clean,")
    print("  1.0 = the features ARE the operator label.")
    print("=" * 74)

    print("\nGROUP ABLATION -- what each group can recover on its own")
    for name, cols in (("chg_ (config diff)", chg),
                       ("cov_ (spec coverage)", cov),
                       ("g_   (graph, Tier A+)", gph),
                       ("ALL", allf)):
        print(f"  {name:24s} n={len(cols):3d}  worst AUC = "
              f"{recoverability(df, cols, groups):.3f}")

    print("\nLEAVE-ONE-GROUP-OUT -- does removing a group help?")
    for name, cols in (("without chg_", cov + gph),
                       ("without cov_", chg + gph),
                       ("without g_", chg + cov)):
        print(f"  {name:24s} n={len(cols):3d}  worst AUC = "
              f"{recoverability(df, cols, groups):.3f}")

    p2 = load_phase2(root)
    if p2 is None:
        print("\nTIER B / C -- skipped, Phase 2 has not run.")
        print("  Re-run this the moment phase2/batfish_summary.csv exists.")
        print("  Those features describe the AFTER NETWORK, not the edit, and")
        print("  whether they are also contaminated decides whether any usable")
        print("  risk score exists.")
    else:
        m = df.copy()
        man = json.loads((root / "manifest.json").read_text())
        m["candidate_id"] = [c["candidate_id"] for c in man["candidates"]]
        # merge on BOTH keys: the meta frame and the Phase 2 summary each
        # carry incident_id, and merging on candidate_id alone renames them to
        # incident_id_x / incident_id_y, so the grouping column disappears.
        keys = ["candidate_id"] + (["incident_id"]
                                   if "incident_id" in p2.columns else [])
        j = m.merge(p2, on=keys, how="inner")
        tierb = [c for c in ("parse_warning_rows", "init_issue_rows",
                             "undefined_reference_rows", "unused_structure_rows",
                             "nodes_parsed", "interfaces_total",
                             "interfaces_active", "ip_owner_rows",
                             "layer3_edge_rows", "route_rows",
                             "ospf_session_rows", "ospf_sessions_established",
                             "loop_rows", "multipath_inconsistency_rows",
                             "subnet_multipath_inconsistency_rows",
                             "diff_vs_incident_rows") if c in j.columns]
        tierc = [c for c in j.columns if c.startswith("verdict_")]
        g2 = j.incident_id.to_numpy()
        print(f"\nTIER B / C -- Batfish outputs (n={len(j)})")
        for name, cols in (("B (batfish metrics)", tierb),
                           ("C (oracle-only verdicts)", tierc),
                           ("B + C", tierb + tierc)):
            if not cols:
                continue
            X_, kept_ = numeric(j, cols)
            r = recoverability(j, cols, g2)
            print(f"  {name:26s} n={len(cols):3d} live={len(kept_):3d}  "
                  f"worst AUC = {r:.3f}"
                  + ("   <-- NOT MEASURED" if r != r else ""))
        print("  Under 0.85 here means there IS a usable feature space, even")
        print("  though the config diff is unusable. Over it means the whole")
        print("  learned arm is measuring the generator and the paper is the")
        print("  measurement study.")

    print("\nSINGLE FEATURES -- is one column an operator tag?")
    X, kept = numeric(df, allf)
    singles = []
    for i, c in enumerate(kept):
        worst = 0.0
        for cls in sorted(df.repair_class.unique()):
            y = (df.repair_class == cls).astype(int).to_numpy()
            a = auc_roc(y, X[:, i])
            a = max(a, 1 - a) if a == a else 0.0
            worst = max(worst, a)
        singles.append((worst, c))
    singles.sort(reverse=True)
    for a, c in singles[:12]:
        print(f"  {a:.3f}  {c}")
    print("\n  A single feature at ~1.0 is a tag and can be dropped.")
    print("  A long tail at 0.8-0.95 means the signature is DISTRIBUTED and")
    print("  no subset of these features is clean -- which is a finding about")
    print("  synthetic repair corpora, not a bug to patch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
