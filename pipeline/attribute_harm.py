"""Why did each verification-passing repair still cause harm?

    python pipeline/attribute_harm.py --pilot data/pilot-v2

A rate is a number. "30% of verified changes still caused harm" invites the
reply "so what should I do about it?" A decomposition is a finding:

    18 points  (a) specification incompleteness -- Batfish KNEW, nobody asked
     9 points  (b) model scope  -- true only during reconvergence
     3 points  (c) model vs device -- steady-state disagreement

Each of those points at a different remedy, and only (b) and (c) argue for a
predictive risk layer at all; (a) argues for writing more properties. The data
needed is already collected, so this costs no compute.

THE ATTRIBUTION RULE, pre-registered in docs/ANALYSIS-PLAN.md
-------------------------------------------------------------
For a candidate that PASSED the SPEC gate and measured HARMFUL, look at the
property (or properties) it broke:

  (a) SPECIFICATION INCOMPLETENESS
      Batfish reported that property as FAIL. It is an oracle-only property,
      so the SPEC gate never consulted it. The verifier was right and was not
      asked. No verifier improvement fixes this; a bigger spec does.

  (b) MODEL SCOPE
      Batfish reported the property as PASS, and the violation is visible in
      the transient telemetry -- the candidate flapped, or was unreachable
      during convergence -- or the run failed to converge. Batfish models
      converged steady state by design, so this is out of scope, not an error.

  (c) MODEL VS DEVICE
      Batfish reported the property as PASS and the violation persists at
      converged steady state with no transient signal. The model and the
      running daemon disagree about the same question. This is the smallest
      and most interesting category.

  UNATTRIBUTED
      Anything that matches none of the above, reported rather than forced
      into a bucket. A decomposition that always sums to 100% by construction
      is not a measurement.
"""
from __future__ import annotations
import argparse, csv, json, sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl.properties import PROPERTIES                          # noqa: E402
from nrl.phase4 import wilson                                  # noqa: E402

SPEC_PIDS = {p["pid"] for p in PROPERTIES if p["in_spec"]}
ORACLE_ONLY = {p["pid"] for p in PROPERTIES if not p["in_spec"]}


def load_csv(p: Path):
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def attribute(cand_id, violated, bf_row, summary_row) -> tuple:
    """(category, reason). See the module docstring for the frozen rule."""
    if not violated:
        return "NONE", "no property in G regressed"

    tr_flap = str(summary_row.get("transient_flapped", "")).lower() == "true"
    tr_out = str(summary_row.get("transient_outage_after_reachable", "")
                 ).lower() == "true"
    no_conv = summary_row.get("run_status") == "NO_CONVERGENCE"

    bf_failed = [p for p in violated
                 if bf_row.get(f"verdict_{p}") == "FAIL"]
    bf_passed = [p for p in violated
                 if bf_row.get(f"verdict_{p}") == "PASS"]

    # (a) the verifier said FAIL on a property the spec never asked about
    if bf_failed and all(p in ORACLE_ONLY for p in bf_failed):
        return "a_spec_incompleteness", (
            f"Batfish reported {','.join(bf_failed)} FAIL; oracle-only, so the "
            f"SPEC gate never consulted it")

    # (b) out of the model's scope: it is a timing phenomenon
    if no_conv:
        return "b_model_scope", "did not converge within the policy"
    if (tr_flap or tr_out) and bf_passed:
        return "b_model_scope", (
            f"Batfish PASS on {','.join(bf_passed)}; harm visible in the "
            f"transient window (flap={tr_flap}, outage={tr_out})")

    # (c) steady-state disagreement between the model and the daemon
    if bf_passed:
        return "c_model_vs_device", (
            f"Batfish PASS on {','.join(bf_passed)}; violation persists at "
            f"converged steady state with no transient signal")

    if bf_failed:
        return "a_spec_incompleteness_mixed", (
            f"Batfish FAIL on {','.join(bf_failed)}, which includes a SPEC "
            f"property -- check the gate arithmetic")
    return "unattributed", "no Batfish verdict recorded for the violated property"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    a = ap.parse_args()
    root = (REPO / a.pilot).resolve()

    bf = {r["candidate_id"]: r for r in
          load_csv(root / "phase2" / "batfish_summary.csv")}
    oc = load_csv(root / "phase3" / "containerlab_outcomes.csv")
    summ = {r["run_id"]: r for r in
            load_csv(root / "phase3" / "containerlab_summary.csv")}

    passed = [o for o in oc
              if bf.get(o["candidate_id"], {}).get("batfish_spec_verdict") == "PASS"]
    harmful = [o for o in passed if o["outcome_harm_v1"] in
               ("HARMFUL", "NO_CONVERGENCE")]

    print("=" * 74)
    print("WHY DID VERIFICATION-PASSING REPAIRS STILL CAUSE HARM?")
    print(f"  candidates passing the SPEC gate : {len(passed)}")
    print(f"  of those, harmful in the emulator: {len(harmful)}")
    print("=" * 74)
    if not harmful:
        print("nothing to attribute")
        return 0

    rows, cats = [], Counter()
    for o in harmful:
        cid = o["candidate_id"]
        violated = [p for p in (o.get("violations_vs_golden") or "").split(";")
                    if p]
        cat, why = attribute(cid, violated, bf.get(cid, {}), summ.get(cid, {}))
        cats[cat] += 1
        rows.append({"candidate_id": cid, "incident_id": o["incident_id"],
                     "violated": violated, "category": cat, "reason": why})

    n = len(harmful)
    print(f"\n{'category':<30} {'n':>5} {'share':>8} {'95% CI':>18}")
    for cat, k in cats.most_common():
        lo, hi = wilson(k, n)
        print(f"{cat:<30} {k:>5} {k / n:>8.3f} {f'[{lo:.3f}, {hi:.3f}]':>18}")

    rec = cats.get("a_spec_incompleteness", 0)
    print(f"\n  recoverable by a wider specification : {rec}/{n} "
          f"({rec / n:.1%})")
    print(f"  requires execution to detect          : {n - rec}/{n} "
          f"({(n - rec) / n:.1%})")
    print("  Only the second number argues for a learned risk layer.")
    if cats.get("unattributed"):
        print(f"\n  {cats['unattributed']} case(s) UNATTRIBUTED -- reported "
              f"rather than forced into a bucket.")

    out = root / "phase4"
    out.mkdir(exist_ok=True)
    (out / "harm_attribution.json").write_text(json.dumps(
        {"n_spec_pass": len(passed), "n_harmful": n,
         "categories": dict(cats), "cases": rows,
         "rule": "docs/ANALYSIS-PLAN.md, pre-registered"},
        indent=2), encoding="utf-8")
    print(f"\nwrote {out / 'harm_attribution.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
