"""Quality checks on the Phase 4 analysis.

    python3 pipeline/verify_phase4.py

Checks the ANALYSIS, not the network: leakage, grouping, statistical hygiene,
determinism, and that Phases 1-3 were not modified.
"""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nrl.phase4 import BANNED_SUBSTRINGS, feature_columns   # noqa: E402

# PILOT/P4 are set in main() from --pilot. They used to be module constants
# pointing at pilot-v1, which is the defect that once ran every command against
# the old pilot and printed success. Same class as B1 in verify_phase3.py.
PILOT: Path = None
P4: Path = None
FAIL, PASSED = [], 0


def check(label, ok, detail=""):
    global PASSED
    if ok: PASSED += 1; print(f"  [PASS] {label}")
    else:
        FAIL.append((label, detail)); print(f"  [FAIL] {label}")
        if detail: print(f"         {detail}")
    return ok


def main() -> int:
    global PILOT, P4
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. No default, "
                         "deliberately.")
    args = ap.parse_args()
    PILOT = Path(args.pilot)
    if not PILOT.is_absolute():
        PILOT = (REPO / PILOT).resolve()
    P4 = PILOT / "phase4"
    print(f"verifying {P4}\n")
    print(f"verifying {P4}\n")
    if not P4.exists():
        print("no phase4 directory -- run pipeline/run_phase4.py"); return 2

    print("CHECK 1 -- outputs exist and load")
    need = ["modelling_dataset.csv", "model_results.csv", "disagreements.csv",
            "p05_audit.csv", "run_metadata.json", "autonomy_risk_curve.svg"]
    ok = all(check(f"{n} present", (P4 / n).exists()) for n in need)
    if not ok: return 1
    ds = pd.read_csv(P4 / "modelling_dataset.csv")
    res = pd.read_csv(P4 / "model_results.csv")
    meta = json.loads((P4 / "run_metadata.json").read_text())

    print("\nCHECK 2 -- modelling population matches Phase 2/3")
    check("24 candidates in the modelling population", len(ds) == 24, f"got {len(ds)}")
    check("12 harmful / 12 safe", int(ds.y_harmful.sum()) == 12
          and int((1 - ds.y_harmful).sum()) == 12,
          f"{int(ds.y_harmful.sum())} harmful")
    check("all are batfish_spec_verdict == PASS",
          (ds.batfish_spec_verdict == "PASS").all())

    print("\nCHECK 3 -- LEAKAGE GATE")
    for tier in ("A", "B", "C"):
        cols = feature_columns(ds, tier)
        leaked = [c for c in cols if any(b in c for b in BANNED_SUBSTRINGS)]
        check(f"tier {tier} feature set contains no banned column", not leaked,
              f"leaked: {leaked}")
    check("no outcome/label column can reach X",
          not [c for c in feature_columns(ds, "C")
               if c in ("y_harmful", "outcome_harm_v1")])

    print("\nCHECK 4 -- grouping and statistical hygiene")
    check("leave-one-incident-out grouping recorded",
          "incident" in str(meta.get("grouping", "")).lower(),
          str(meta.get("grouping")))
    check("every model result carries a bootstrap CI",
          res.auc_roc_ci95.notna().all())
    check("every model result carries a permutation p-value",
          res.permutation_p_auc_roc.notna().all())
    check("a majority baseline was evaluated",
          (res.model == "majority-baseline").any())
    check("the exact_revert ablation was run",
          (res.ablation == "excl-exact_revert").any())

    print("\nCHECK 5 -- Phases 1-3 untouched")
    lock = json.loads((PILOT / "pilot.lock.json").read_text())
    check("artifact digest recorded and matches the pilot on disk",
          meta.get("artifact_digest") == lock.get("artifact_digest"))
    bad = [k for k, v in lock["sha256"].items()
           if (PILOT / k).exists()
           and hashlib.sha256((PILOT / k).read_bytes()).hexdigest() != v]
    check("no Phase 1 artifact file was modified", not bad,
          f"{len(bad)} changed: {bad[:3]}")
    check("phase4 wrote nothing into phase2/ or phase3/",
          not any(p.stat().st_mtime > (P4 / "run_metadata.json").stat().st_mtime
                  for d in ("phase2", "phase3")
                  for p in (PILOT / d).rglob("*") if p.is_file()))

    print("\nCHECK 6 -- honest reporting")
    best = res[(res.ablation == "all-24") & (res.model != "majority-baseline")]
    check("no model is reported without its confidence interval",
          best.auc_roc_ci95.notna().all())
    wide = best.auc_roc_ci95.astype(str).str.contains("0.4|0.3|0.2").any()
    check("at least one reported CI overlaps chance (honesty check: at n=24 "
          "it must)", wide,
          "if no CI overlaps 0.5 at this sample size, suspect the metric")
    check("the non-learned spec-widening baseline is recorded",
          "spec_widening_rule" in meta)

    print("\nCHECK 7 -- determinism")
    r = subprocess.run([sys.executable, str(REPO / "pipeline" / "run_phase4.py")],
                       capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        check("re-run succeeds", False, r.stderr[-400:])
    else:
        res2 = pd.read_csv(P4 / "model_results.csv")
        same = res[["tier", "model", "ablation", "auc_roc", "auc_pr"]].equals(
            res2[["tier", "model", "ablation", "auc_roc", "auc_pr"]])
        check("a re-run reproduces every metric exactly", same,
              "seeds are fixed; any drift means hidden randomness")

    print(f"\n{'=' * 70}\n{PASSED} passed, {len(FAIL)} failed")
    for l, d in FAIL: print(f"  FAILED: {l}\n          {d}")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
