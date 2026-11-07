"""Freeze the D1-D9 pilot decisions into config/pilot_decisions.json (before any pilot run).

    ./.venv/Scripts/python.exe v4_transient/tools/freeze_pilot_decisions.py

Every value was selected from docs/V4-PIVOT-AND-EXPANSION-PLAN.md, docs/PILOT-PREREGISTRATION.md and pre-existing
v3 evidence quoted in the plan. NO smoke-test or pilot measurement is read. The one derived number, the D1
resolution floor, is computed from two pre-deployment design quantities: the frozen probe interval
(pre-registration §3, v4lib.labops.PROBE_INTERVAL_S) and the smallest analytic carried-flow count of any pilot
topology (manifests/pilot_manifest.json, computed from configurations by v4lib.analytic before any lab ran).

Idempotent: if the decisions file already exists with identical decisions it is left untouched; if it differs the
tool refuses, because frozen decisions may not be changed by re-running a script.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from v4lib import decisions as DEC                                   # noqa: E402
from v4lib.labops import PROBE_INTERVAL_S                            # noqa: E402

DECIDED_BY = ("Claude (implementer), under explicit delegation from the project owner on 2026-09-14; values determined "
              "from docs/V4-PIVOT-AND-EXPANSION-PLAN.md and docs/PILOT-PREREGISTRATION.md; no smoke-test or pilot "
              "measurement consulted")

RATIONALE = {
    "D1_noise_floor": (
        "Pre-registration §6 option (a) plus a stricter lower bound. The pooled maximum over all 10 valid no-op runs is "
        "the most conservative empirical floor available: per-topology floors rest on 2-3 runs, and mean + k*sd assumes "
        "a symmetric noise distribution that 10 zero-inflated control values cannot support. The replicate median stops "
        "one spiky replicate from making a change count as measurable. T1 only, because probe loss is a secondary, "
        "descriptive instrument (§2). Lower bound = probe interval 0.05 s (§3) / 72 carried flows (the fewest of any "
        "pilot topology, t05_ring6, a design quantity from the manifest) = one flow broken for one probe interval, applied "
        "always: without it an idempotent no-op that installs no FIB change gives a floor of exactly 0, and any "
        "single-flow microsecond artefact would count as measurable. The plan leaves the floor undefined."),
    "D2_G1_measurable": (
        "Kill below 30 % (plan proposal kept). 30 % is the complement of the project's frozen degeneracy rule "
        "(ANALYSIS-PLAN-V3 §8: more than 70 % of values at a single value is degenerate), so it is not a new number. "
        "The denominator is all 20 population changes, so infrastructure losses cannot shrink it; a change with too "
        "few valid replicates counts as not above and is never imputed."),
    "D3_G3_repeatable": (
        "Stricter than the plan's 0.80. A within-change share of 0.80 is ICC(1) = 0.20, 'poor' under the conventional "
        "ICC guideline (Koo & Li 2016, J Chiropr Med 15:155-163): the reliability of a 5-replicate mean would be 0.56, "
        "and of the 3-replicate means planned for the corpus (plan §43) 0.43, capping any learned model below half the "
        "change-level variance. Killing above 0.50 (ICC below 0.50) keeps reliability at least 0.83 with 5 replicates "
        "and 0.75 with 3. 'Or = 0 with G2 failing' is read literally: a deterministic transient kills only if G2 also "
        "kills, because determinism is not the same as being computable before deployment, which is what G2 tests. "
        "Zero total variance kills: a target with no variation cannot be learned or ranked."),
    "D4_G4_host_invariance": (
        "Cannot be tested in this pilot: there is one host. Metric for the required future two-host test: median over "
        "changes of the absolute difference of change-mean T1, divided by the pooled within-change sd (scale-free). "
        "Tolerance 1.0: with no host effect, the difference of two 5-replicate means has sd sqrt(2/5) = 0.63 within-sd "
        "and a median absolute value of about 0.43 within-sd, so a host effect as large as the replicate noise itself "
        "fails. Second host: all 20 population changes. An untested G4 caps the decision at GO-WITH-FIXES: an untested "
        "gate is not a pass (so no GO) and not evidence of failure (so no automatic NO-GO). The single-host drift proxy "
        "measures drift within one host, not invariance across hosts, so it is not accepted as a substitute; it is "
        "still reported descriptively (§15)."),
    "D5_G2_analytic_reducibility": (
        "Stricter than the plan's 0.90. Pre-existing v3 evidence (plan §22): over a non-learned baseline at R2 0.794 "
        "the learned increment was +0.054 with a CI touching 0 at n = 151, and was judged not defensible. At an analytic "
        "R2 of 0.89 the residual left for any learned model on change means is at most 0.11 before replicate noise, "
        "too small for a corpus of the planned size to establish; 0.80 leaves at least 0.20. Kill on the point "
        "estimate, on change means (removes replicate noise), using the maximum over B2-B6 (the plan's 'strongest "
        "analytic baseline'): each choice makes the kill easier, never harder. Leave-one-topology-out (4 folds) is "
        "confirmed."),
    "D6_G5_cost": (
        "Plan proposal kept. Plan §38/§43 size the recommended corpus at 120 s per lab: 187 CPU-hours, about 23 h on 10 "
        "dedicated workers. At 180 s the same corpus needs about 280 CPU-hours, about 35 h on 10 dedicated workers, the "
        "upper edge of the 30-40 h run size the plan (§1 item 5) and the project brief treat as the expensive "
        "computation. Beyond 180 s the corpus exceeds that size. The plan justifies no stricter value."),
    "D7_min_valid_replicates": (
        "At least 4 of 5 valid replicates. This keeps 3 degrees of freedom for each change's sd and a median that one "
        "outlier cannot move, while one isolated infrastructure failure does not by itself remove a change. 5 of 5 "
        "would let lab flakiness masquerade as a scientific result; 3 of 5 gives a median of only 3 values."),
    "D8_validity_guard": (
        "At least 90 % of the 100 population runs valid after the one retry (the stricter candidate). v3 Phase 3 lost "
        "0 of 186 labs after retry (plan §15), so losing more than 10 % indicates a protocol or instrument problem. "
        "Losses may also concentrate in the most disruptive changes (for example NOT_SETTLED), which would bias every "
        "gate."),
    "D9_positive_control_sensitivity": (
        "All 4 positive controls must be valid and above the D1 floor; an invalid control counts as not above (the "
        "stricter candidate). Each positive control is a hard shutdown of the highest-betweenness link, the most "
        "disruptive event in the design. An instrument that misses it on any topology has a blind spot exactly where "
        "the study measures, and accepting 3 of 4 would tolerate that blind spot."),
}


def resolution_floor():
    man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text(encoding="utf-8"))
    flows = {c["topology"]: c["features"]["n_flows_carried_pred"] for c in man["changes"] if c["kind"] == "population"}
    topo = min(flows, key=lambda t: (flows[t], t))
    return PROBE_INTERVAL_S / flows[topo], flows[topo], topo


def build():
    floor, n_flows, topo = resolution_floor()
    doc = DEC.template()
    doc["status"] = "FROZEN"
    doc["decided_by"] = DECIDED_BY
    d = doc["decisions"]
    values = {
        "D1_noise_floor": dict(floor_statistic="max_all_noop", per_change_comparator="replicate_median",
                               metrics="T1_only", all_noop_zero_handling="minimum_resolution_floor",
                               minimum_resolution_floor=floor, minimum_resolution_floor_scope="lower_bound_always"),
        "D2_G1_measurable": dict(kill_if_share_above_floor_below=0.30, denominator="all_population_changes"),
        "D3_G3_repeatable": dict(kill_if_within_share_above=0.50, zero_within_share_clause="kills_only_if_G2_kills",
                                 zero_total_variance_handling="kill"),
        "D4_G4_host_invariance": dict(metric="median_abs_diff_change_mean_T1_over_pooled_within_sd", tolerance=1.0,
                                      n_changes_on_second_host=20, second_host_available_for_this_pilot=False,
                                      untested_handling="cap_at_GO_WITH_FIXES"),
        "D5_G2_analytic_reducibility": dict(unit="change_means", aggregator="max_over_B2_B6",
                                            cross_validation="leave_one_topology_out", kill_if_r2_at_least=0.80,
                                            ci_rule="point_estimate"),
        "D6_G5_cost": dict(kill_if_median_wall_s_above=180.0),
        "D7_min_valid_replicates": dict(min_valid_replicates_per_change=4),
        "D8_validity_guard": dict(min_valid_population_run_share=0.90),
        "D9_positive_control_sensitivity": dict(min_positive_controls_above_floor=4,
                                                invalid_positive_control_handling="counts_as_not_above"),
    }
    for key, vals in values.items():
        d[key]["status"] = "FROZEN"
        d[key]["rationale"] = RATIONALE[key]
        d[key].update(vals)
    return doc


def derivation():
    floor, n_flows, topo = resolution_floor()
    return {"D1_minimum_resolution_floor": {
        "formula": "PROBE_INTERVAL_S / min over pilot population topologies of analytic carried-flow count",
        "probe_interval_s": PROBE_INTERVAL_S, "min_carried_flows": n_flows, "topology": topo, "value": floor}}


def without_time(doc):
    return {k: v for k, v in doc.items() if k != "decided_utc"}


def main() -> int:
    doc = build()
    problems = DEC.validate({**doc, "decided_utc": "pending"})
    if problems:
        print("REFUSED: decisions do not validate:\n  " + "\n  ".join(problems))
        return 2
    path = V4 / DEC.DECISIONS_REL
    if path.exists():
        if without_time(json.loads(path.read_text(encoding="utf-8"))) == without_time(doc):
            print(f"{DEC.DECISIONS_REL} already frozen with identical decisions; left untouched")
            return 0
        print(f"REFUSED: {DEC.DECISIONS_REL} exists with different content; frozen decisions are not overwritten")
        return 2
    doc["decided_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    assert DEC.validate(doc) == []
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {DEC.DECISIONS_REL} (decided_utc {doc['decided_utc']}); derivation {derivation()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
