"""
PRE-FLIGHT DATASET AUDIT -- run before Phase 2/3, no Batfish, no Docker.

Answers the questions that decide whether the expensive runs are worth doing,
using only Phase 1 artifacts on disk. Every one of these is cheap to check now
and expensive to discover after 30 hours of compute.

    python pipeline/audit_dataset.py --pilot data/pilot-v2

WHAT IT ASKS

1. Does the Tier-A feature matrix have anything in it?
   Constant columns are dropped by phase4.matrix(); a tier that is mostly
   constants cannot support a model regardless of sample size.

2. EFFECTIVE n, not raw n.
   RC-cost_norm_1..9 are nine operators that differ only in an integer. If they
   produce an identical Tier-A feature vector, they are ONE point to any
   Tier-A model, however many rows the CSV has. Conformal interval width is set
   by effective n, so this number -- not 1,793 -- is the one to report.

3. Is repair_class recoverable from the features alone?
   repair_class is banned from X, but if change_stats + spec_coverage predict it
   accurately then the model can rediscover the generator's signature and any
   apparent signal on y_harmful is that shortcut wearing a different hat. This
   is the pilot-v1 "SAFE == exact_revert" failure in its next disguise, and it
   is detectable BEFORE any label exists.

4. Is any candidate byte-identical to its golden?
   repairs_v2 forbids emitting golden. This verifies the ban held rather than
   trusting the docstring.

5. Do the spec_coverage flags mean what their names say?
   spec.primary_path holds TRANSIT nodes only, so edgea/edgeb are absent from
   it in every topology -- which makes them "off primary" and therefore
   "backup path devices" to spec_coverage_features(). They are the ingress and
   egress of every SPEC property. If a large fraction of candidates touch only
   those two routers, this feature is systematically mislabelled.

6. Group structure and the planned split.
   Candidates per incident, incidents per topology, and the sizes a grouped
   3-way split would actually produce -- including how many POSITIVES the
   calibration fold would hold at an assumed harm rate.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np                                              # noqa: E402
import pandas as pd                                             # noqa: E402

from nrl.phase4 import (auc_roc, effective_n, model_zoo,        # noqa: E402
                        nested_cv)
from nrl.topologies import resolve                              # noqa: E402


def load_meta(root: Path) -> pd.DataFrame:
    man = json.loads((root / "manifest.json").read_text())
    rows = []
    for c in man["candidates"]:
        m = json.loads((root / "candidates" / c["candidate_id"]
                        / "meta.json").read_text())
        r = {"candidate_id": c["candidate_id"],
             "incident_id": c["incident_id"],
             "topology": c["topology"],
             "repair_class": c["repair_class"],
             "repair_id": c["repair_id"],
             "fault_family": c["fault_family"],
             "devices": tuple(sorted(
                 m["change_stats"].get("devices_touched_list", [])))}
        for k, v in m["change_stats"].items():
            if not isinstance(v, list):
                r[f"chg_{k}"] = v
        for k, v in m["spec_coverage"].items():
            r[f"cov_{k}"] = v
        for k, v in (m.get("graph_features") or {}).items():
            r[k] = v
        rows.append(r)
    return pd.DataFrame(rows)


def numeric(df: pd.DataFrame, cols):
    X = df[cols].copy()
    for c in cols:
        if X[c].dtype == object:
            X[c] = X[c].map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0})
        X[c] = pd.to_numeric(X[c], errors="coerce")
    return X.fillna(0.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--assumed-harm-rate", type=float, default=0.5,
                    help="pilot-v1 measured 0.50 among Batfish-PASS candidates")
    ap.add_argument("--assumed-pass-rate", type=float, default=0.48,
                    help="pilot-v1: 24 of 50 candidates passed the spec gate")
    a = ap.parse_args()
    root = (REPO / a.pilot).resolve()
    lock = json.loads((root / "pilot.lock.json").read_text())

    print("=" * 74)
    print(f"DATASET AUDIT -- {root}")
    print(f"  suite {lock.get('suite_version')}   "
          f"snapshot {str(lock.get('snapshot_digest'))[:16]}   "
          f"artifact {str(lock.get('artifact_digest'))[:16]}")
    print("=" * 74)

    df = load_meta(root)
    feat = [c for c in df.columns
            if c.startswith(("chg_", "cov_", "g_"))]
    X = numeric(df, feat)
    const = [c for c in feat if X[c].nunique() <= 1]
    live = [c for c in feat if c not in const]

    print(f"\n1. TIER-A FEATURE MATRIX  ({len(df)} candidates)")
    print(f"   declared      : {len(feat)}")
    print(f"   CONSTANT      : {len(const)}  {const}")
    print(f"     -> dropped by phase4.matrix(); they carry no information")
    print(f"   LIVE          : {len(live)}")
    for c in live:
        print(f"     {c:46s} nunique={X[c].nunique():4d} mean={X[c].mean():.3f}")

    print(f"\n2. EFFECTIVE n  (distinct Tier-A vectors)")
    key = X[live].round(6).astype(str).agg("|".join, axis=1)
    print(f"   rows                                : {len(df)}")
    print(f"   distinct feature vectors            : {key.nunique()}")
    print(f"   distinct (incident, feature vector) : "
          f"{len(set(zip(df.incident_id, key)))}")
    dup = Counter(zip(df.incident_id, key))
    worst = dup.most_common(3)
    print(f"   largest indistinguishable clusters  : "
          f"{[n for _, n in worst]}")
    print(f"   -> a Tier-A model sees {key.nunique()} distinct points, not "
          f"{len(df)}.")
    print(f"      Report this as the effective sample size. It, not the row")
    print(f"      count, sets how tight a conformal interval can be.")

    print(f"\n3. IS repair_class RECOVERABLE FROM THE FEATURES ALONE?")
    print(f"   (repair_class is banned from X. If it is predictable from X,")
    print(f"    a model can rediscover the generator instead of the network.")
    print(f"    This needs NO labels, so it can be answered before any run.)")
    try:
        import sklearn                                       # noqa: F401
    except ImportError:
        print("   [SKIP] scikit-learn not installed -- run this before Stage 1;")
        print("          it is the cheapest shortcut check in the project.")
    else:
        groups = df.incident_id.to_numpy()
        Xm = X[live].to_numpy(dtype=float)
        worst = 0.0
        for cls in sorted(df.repair_class.unique()):
            y = (df.repair_class == cls).astype(int).to_numpy()
            for nm in ("gbt", "logreg"):
                res = nested_cv(Xm, y, groups, model_zoo()[nm], k_outer=5)
                sc = res["oof_calibrated"]
                ok = ~np.isnan(sc)
                auc = auc_roc(y[ok], sc[ok])
                worst = max(worst, auc if auc == auc else 0.0)
                print(f"   {cls:11s} vs rest, {nm:7s} grouped-CV AUC-ROC = {auc:.3f}")
        print(f"   worst case: {worst:.3f}")
        print("   > 0.85 means the generator's signature is recoverable from X,")
        print("   and any Tier-A/A+ result on y_harmful must be re-read as that")
        print("   shortcut rather than as learned risk.")

    print(f"\n4. NO CANDIDATE MAY BE BYTE-IDENTICAL TO GOLDEN")
    empty = []
    for cid in df.candidate_id:
        d = root / "candidates" / cid / "diffs" / "golden_to_candidate.diff"
        if d.exists() and not d.read_text().strip():
            empty.append(cid)
    print(f"   candidates with an empty golden diff : {len(empty)}")
    if empty:
        print(f"   *** {empty[:5]} ... these ARE exact reverts. The pilot-v1")
        print(f"   *** shortcut (SAFE == 'is this the revert') is back.")
    else:
        print(f"   ok -- the repairs_v2 ban on emitting golden held.")

    print(f"\n5. spec_coverage FLAG SEMANTICS")
    only_edge = df.devices.map(lambda d: len(d) > 0 and set(d) <= {"edgea", "edgeb"})
    print(f"   candidates touching ONLY edgea/edgeb : {only_edge.sum()} "
          f"({100 * only_edge.mean():.1f}%)")
    for tn in sorted(df.topology.unique()):
        spec = resolve(tn)
        pp = list(spec.primary_path)
        print(f"   {tn:12s} primary_path={pp}  "
              f"edgea in path={'edgea' in pp}  edgeb in path={'edgeb' in pp}")
    sub = df[only_edge]
    if len(sub):
        print(f"   of those {len(sub)} candidates:")
        print(f"     change_touches_off_spec_path_device=True: "
              f"{int(sub.cov_change_touches_off_spec_path_device.sum())}")
        print(f"     spec_covers_changed_devices=True       : "
              f"{int(sub.cov_spec_covers_changed_devices.sum())}")
        print(f"   edgea/edgeb are the ingress and egress of every SPEC")
        print(f"   property. If the first number is large, the feature named")
        print(f"   'touches backup path device' is firing on the primary path.")

    print(f"\n6. GROUP STRUCTURE AND THE SPLIT")
    per_inc = Counter(df.incident_id)
    per_topo_inc = defaultdict(set)
    for _, r in df.iterrows():
        per_topo_inc[r.topology].add(r.incident_id)
    print(f"   incidents                    : {len(per_inc)}")
    print(f"   candidates per incident      : min {min(per_inc.values())} "
          f"median {int(np.median(list(per_inc.values())))} "
          f"max {max(per_inc.values())}")
    print(f"   singleton incidents (n=1)    : "
          f"{sum(1 for v in per_inc.values() if v == 1)}")
    print(f"   incidents per topology       : "
          f"{sorted(len(v) for v in per_topo_inc.values())}")
    n_pass = a.assumed_pass_rate * len(df)
    n_pos = a.assumed_harm_rate * n_pass
    print(f"\n   projected at pass={a.assumed_pass_rate} harm={a.assumed_harm_rate}:")
    print(f"     Batfish-PASS candidates (Phase 3 labs) : {n_pass:.0f}")
    print(f"     HARMFUL among them                     : {n_pos:.0f}")
    print(f"     grouped 60/20/20 by incident -> train {0.6*n_pass:.0f} / "
          f"cal {0.2*n_pass:.0f} / test {0.2*n_pass:.0f}")
    print(f"     positives in the calibration fold       : {0.2*n_pos:.0f}")
    print(f"   Conformal at alpha=0.10 needs >= 9 calibration points for the")
    print(f"   bound to be non-trivial; the binding constraint is the EFFECTIVE")
    print(f"   count from section 2, not the row count above.")
    print(f"\n   NOTE: leave-one-incident-out measures generalisation to an")
    print(f"   unseen INCIDENT, not an unseen NETWORK -- 9 other incidents from")
    print(f"   the same topology stay in train. Leave-one-topology-out is the")
    print(f"   separate, stronger claim, and both must be frozen before results.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
