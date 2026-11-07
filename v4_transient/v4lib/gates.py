"""Gate machinery for the V4 transient pilot. NO threshold or rule value lives in this file.

Every threshold and rule comes from a decisions document that has passed v4lib.decisions.validate(). evaluate()
refuses anything else. Frozen structure implemented here: pre-registration §7 (G1), §8 (G3 on the frozen variance
components), §10 (G2 on the frozen baselines), §11 (G5 metric), §12 (validity guard, D7), §16 (decision order).

Interpretations needed to make the gates computable that are NOT D1-D9 values are listed in MACHINERY_RULES
(and docs/D1-D9-DECISION-SCHEMA.md §4) so they can be reviewed before approval.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd

from .decisions import BASELINE_IDS, validate

PRIMARY = "T1_disruption_area"
PASS, KILL, FAIL, NOT_EVALUABLE, NOT_TESTED = "PASS", "KILL", "FAIL", "NOT_EVALUABLE", "NOT_TESTED"

MACHINERY_RULES = [
    "R1: a gate or rule whose inputs are missing or undefined is NOT_EVALUABLE, and NOT_EVALUABLE yields NO-GO.",
    "R2: with D2 denominator 'all_population_changes', a change with fewer valid replicates than D7 counts as not "
    "above the floor (it is never imputed).",
    "R3: floor comparisons are strict (value > floor), as written in pre-registration §6.",
    "R4: the 'every no-op T1 = 0' condition is evaluated over all valid no-op runs pooled, for every floor statistic.",
    "R5: with 'max_per_topology_noop', a change or positive control whose topology has no valid no-op run is "
    "NOT_EVALUABLE.",
    "R6: 'mean_plus_k_sd_all_noop' uses sd with ddof=1 and needs at least 2 valid no-op values.",
    "R7: probe-loss floors use the same D1 statistic, comparator and zero handling on D1.probe_metric, with "
    "D1.probe_minimum_resolution_floor.",
    "R8: positive controls are compared with the T1 floor only (the D1 statistic; the own-topology floor for "
    "'max_per_topology_noop').",
    "R9: G2 unit 'change_means' uses the change means of D7-eligible changes; unit 'runs' uses all valid "
    "population runs.",
    "R10: G3 uses variance components over all valid population runs (pre-registration §8), not restricted by D7.",
    "R11: G5 uses the recorded wall_s of every population run's final attempt, valid or not (pre-registration §11).",
    "R12: the validity-guard denominator is the number of population runs in the frozen run plan; runs never "
    "executed count as invalid.",
    "R13: ML results never enter the decision (pre-registration §16).",
]


def _finite(x: Any) -> bool:
    try:
        return x is not None and not isinstance(x, bool) and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _floor(noop: pd.DataFrame, col: str, d1: Dict[str, Any], resolution_floor: Optional[float]) -> Dict[str, Any]:
    if col not in noop:
        return {"evaluable": False, "column": col, "note": f"column {col} absent"}
    vals = noop[["topology", col]].copy()
    vals[col] = pd.to_numeric(vals[col], errors="coerce")
    vals = vals.dropna()
    if vals.empty:
        return {"evaluable": False, "column": col, "note": f"no valid no-op value for {col}"}
    lower = None
    if d1["all_noop_zero_handling"] == "minimum_resolution_floor" \
            and d1.get("minimum_resolution_floor_scope") == "lower_bound_always":
        lower = float(resolution_floor)
    out: Dict[str, Any] = {"evaluable": True, "column": col, "n_noop_values": int(len(vals)), "global": None,
                           "per_topology": None, "all_noop_zero": bool((vals[col] == 0).all()),
                           "resolution_lower_bound": lower}
    if out["all_noop_zero"]:                                                     # R4
        out["global"] = 0.0 if d1["all_noop_zero_handling"] == "floor_is_zero" else float(resolution_floor)
        return out
    stat = d1["floor_statistic"]
    if stat == "max_all_noop":
        out["global"] = float(vals[col].max())
    elif stat == "mean_plus_k_sd_all_noop":
        if len(vals) < 2:                                                        # R6
            return {"evaluable": False, "column": col, "note": "mean_plus_k_sd needs at least 2 valid no-op values"}
        out["global"] = float(vals[col].mean() + d1["k_sd"] * vals[col].std(ddof=1))
    else:
        out["per_topology"] = {str(k): float(v) for k, v in vals.groupby("topology")[col].max().items()}
    if lower is not None:                                                        # D1 scope 'lower_bound_always'
        if out["global"] is not None:
            out["empirical_floor"] = out["global"]
            out["global"] = max(out["global"], lower)
        else:
            out["empirical_floor_per_topology"] = dict(out["per_topology"])
            out["per_topology"] = {k: max(v, lower) for k, v in out["per_topology"].items()}
    return out


def _floor_for(floor: Dict[str, Any], topology: Any) -> Optional[float]:
    if not floor.get("evaluable"):
        return None
    if floor.get("global") is not None:
        return floor["global"]
    return (floor.get("per_topology") or {}).get(str(topology))                  # R5: None when absent


def _stat(series: pd.Series, comparator: str) -> float:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return float("nan")
    return float(s.median() if comparator == "replicate_median" else s.mean())


def evaluate(inputs: Dict[str, Any], decisions_doc: Dict[str, Any],
             protocol_defects: Optional[List[str]] = None) -> Dict[str, Any]:
    """inputs:
         runs                     DataFrame, one row per PLANNED run (final attempt): run_id, change_id, kind,
                                  topology, valid (bool), T1_disruption_area, wall_s, optional probe columns
         variance_T1              pre-registration §8 variance components on T1 (analyze_pilot.variance_components)
         baselines                {"change_means": {...}, "runs": {...}} as produced by analyze_pilot.baselines_on
         host_timing              {statistic: {"rho", "p"}} (analyze_pilot.perm_spearman)
         planned_population_runs  int, from the frozen run plan
    """
    problems = validate(decisions_doc)
    if problems:
        raise ValueError("refusing to evaluate gates with invalid decisions: " + "; ".join(problems))
    d = decisions_doc["decisions"]
    d1, d2, d3 = d["D1_noise_floor"], d["D2_G1_measurable"], d["D3_G3_repeatable"]
    d4, d5, d6 = d["D4_G4_host_invariance"], d["D5_G2_analytic_reducibility"], d["D6_G5_cost"]
    d7, d8, d9 = d["D7_min_valid_replicates"], d["D8_validity_guard"], d["D9_positive_control_sensitivity"]

    runs = inputs["runs"].copy()
    runs["valid"] = runs["valid"].fillna(False).astype(bool)
    pop_all = runs[runs.kind == "population"]
    valid = runs[runs.valid]
    pop = valid[valid.kind == "population"]
    noop = valid[valid.kind == "control_noop"]
    pos_all = runs[runs.kind == "control_positive"]
    out: Dict[str, Any] = {"machinery_rules": list(MACHINERY_RULES)}

    # validity guard (D8) --------------------------------------------------------------------------------------
    planned = int(inputs["planned_population_runs"])
    share = len(pop) / planned if planned else None
    thr8 = d8["min_valid_population_run_share"]
    out["validity_guard"] = {"valid_population_runs": int(len(pop)), "planned_population_runs": planned,
                             "share": share, "threshold_min_share": thr8,
                             "outcome": NOT_EVALUABLE if share is None else (PASS if share >= thr8 else FAIL)}

    # D7 eligibility ---------------------------------------------------------------------------------------------
    m = d7["min_valid_replicates_per_change"]
    counts = pop.groupby("change_id").size()
    all_changes = sorted(pop_all.change_id.unique())
    eligible = sorted(c for c in all_changes if int(counts.get(c, 0)) >= m)
    out["D7_eligibility"] = {"min_valid_replicates": m, "n_population_changes": len(all_changes),
                             "eligible_changes": eligible, "n_eligible": len(eligible),
                             "ineligible_valid_counts": {c: int(counts.get(c, 0)) for c in all_changes
                                                         if c not in eligible}}

    # D1 floors ----------------------------------------------------------------------------------------------------
    floors = {"T1": _floor(noop, PRIMARY, d1, d1["minimum_resolution_floor"])}
    if d1["metrics"] == "T1_and_probe_loss":
        floors["probe"] = _floor(noop, d1["probe_metric"], d1, d1["probe_minimum_resolution_floor"])  # R7
    out["noise_floor"] = floors

    # G1 (D1, D2) --------------------------------------------------------------------------------------------------
    denom = all_changes if d2["denominator"] == "all_population_changes" else eligible
    rows, unknown, n_above = [], False, 0
    for cid in denom:
        sub = pop[pop.change_id == cid]
        row: Dict[str, Any] = {"change_id": cid, "n_valid": int(len(sub))}
        if cid not in eligible:                                                                     # R2
            row.update(above=False, note="fewer valid replicates than D7; counted as not above (never imputed)")
            rows.append(row)
            continue
        topo = sub.topology.iloc[0]
        f1, v1 = _floor_for(floors["T1"], topo), _stat(sub[PRIMARY], d1["per_change_comparator"])
        row.update(T1_statistic=v1, T1_floor=f1)
        if f1 is None or not _finite(v1):
            row["note"] = "T1 floor or statistic undefined"
            unknown = True
            rows.append(row)
            continue
        above = v1 > f1                                                                              # R3
        if d1["metrics"] == "T1_and_probe_loss":
            fp = _floor_for(floors["probe"], topo)
            vp = _stat(sub[d1["probe_metric"]], d1["per_change_comparator"]) if d1["probe_metric"] in sub else float("nan")
            row.update(probe_statistic=vp, probe_floor=fp)
            if fp is None or not _finite(vp):
                row["note"] = "probe floor or statistic undefined"
                unknown = True
                rows.append(row)
                continue
            above = (above and vp > fp) if d1["probe_combination"] == "both_above_required" else (above or vp > fp)
        row["above"] = bool(above)
        n_above += int(above)
        rows.append(row)
    g1: Dict[str, Any] = {"denominator": d2["denominator"], "n_denominator": len(denom), "n_above": n_above,
                          "threshold_kill_if_share_below": d2["kill_if_share_above_floor_below"], "per_change": rows}
    if not floors["T1"].get("evaluable") or unknown or not denom:
        g1.update(share_above=None, outcome=NOT_EVALUABLE)
    else:
        g1["share_above"] = n_above / len(denom)
        g1["outcome"] = KILL if g1["share_above"] < d2["kill_if_share_above_floor_below"] else PASS
    out["G1_measurable"] = g1

    # G2 (D5) --------------------------------------------------------------------------------------------------------
    bl = (inputs.get("baselines") or {}).get(d5["unit"])
    g2: Dict[str, Any] = {"unit": d5["unit"], "aggregator": d5["aggregator"], "ci_rule": d5["ci_rule"],
                          "cross_validation": d5["cross_validation"],
                          "threshold_kill_if_value_at_least": d5["kill_if_r2_at_least"]}
    cand = [b for b in BASELINE_IDS
            if isinstance(bl, dict) and isinstance(bl.get(b), dict) and _finite(bl[b].get("loto_r2"))]
    if d5["aggregator"] == "max_over_B2_B6":
        name = max(cand, key=lambda b: float(bl[b]["loto_r2"])) if cand else None
    else:
        name = d5["named_baseline"] if d5["named_baseline"] in cand else None
    value = None
    if name is not None:
        r = bl[name]
        if d5["ci_rule"] == "point_estimate":
            value = float(r["loto_r2"])
        else:
            ci = r.get("bootstrap_ci") or [None]
            value = float(ci[0]) if _finite(ci[0]) else None
    if name is None or value is None:
        g2.update(baseline=name, value=None, outcome=NOT_EVALUABLE, note="baseline result not computable for this unit")
    else:
        g2.update(baseline=name, loto_r2=float(bl[name]["loto_r2"]), bootstrap_ci=bl[name].get("bootstrap_ci"),
                  value=value, outcome=KILL if value >= d5["kill_if_r2_at_least"] else PASS)
        if g2["outcome"] == KILL:
            g2["note"] = "G2 KILL is also a scientific NO-GO for the ML contribution (pre-registration §16)"
    out["G2_not_reducible"] = g2

    # G3 (D3) --------------------------------------------------------------------------------------------------------
    vc = inputs.get("variance_T1") or {}
    g3: Dict[str, Any] = {"threshold_kill_if_within_share_above": d3["kill_if_within_share_above"],
                          "zero_within_share_clause": d3["zero_within_share_clause"],
                          "zero_total_variance_handling": d3["zero_total_variance_handling"],
                          "variance_components": vc}

    def clause():
        c = d3["zero_within_share_clause"]
        if c == "kills_independently":
            return KILL, "within-change share is 0: kills independently (D3)"
        if c == "report_only":
            return PASS, "within-change share is 0: reported without effect (D3)"
        if g2["outcome"] == NOT_EVALUABLE:
            return NOT_EVALUABLE, "within-change share is 0 and G2 is not evaluable"
        return (KILL if g2["outcome"] == KILL else PASS), "within-change share is 0: kills only if G2 kills (D3)"

    if vc.get("total_variance_zero") is True:
        h = d3["zero_total_variance_handling"]
        if h == "kill":
            g3.update(outcome=KILL, note="total variance is 0 (D3: kill)")
        elif h == "no_kill_report_undefined":
            g3.update(outcome=PASS, note="total variance is 0; within share undefined (D3: no kill)")
        else:
            o, note = clause()
            g3.update(outcome=o, note="total variance is 0, treated as within share 0: " + note)
    elif not _finite(vc.get("within_share")):
        g3.update(outcome=NOT_EVALUABLE, note="variance components not estimable")
    else:
        ws = float(vc["within_share"])
        if ws > d3["kill_if_within_share_above"]:
            g3.update(outcome=KILL, note="within-change share above threshold (noise)")
        elif ws == 0:
            o, note = clause()
            g3.update(outcome=o, note=note)
        else:
            g3.update(outcome=PASS)
    out["G3_repeatable"] = g3

    # G5 (D6) --------------------------------------------------------------------------------------------------------
    walls = pd.to_numeric(pop_all["wall_s"], errors="coerce").dropna() if "wall_s" in pop_all else pd.Series(dtype=float)
    med = float(walls.median()) if len(walls) else None                                              # R11
    out["G5_cost"] = {"median_wall_s": med, "n_runs_with_wall_s": int(len(walls)),
                      "threshold_kill_if_median_above_s": d6["kill_if_median_wall_s_above"],
                      "outcome": NOT_EVALUABLE if med is None else
                      (KILL if med > d6["kill_if_median_wall_s_above"] else PASS)}

    # G4 (D4) --------------------------------------------------------------------------------------------------------
    h4 = d4["untested_handling"]
    g4: Dict[str, Any] = {"second_host_available": d4["second_host_available_for_this_pilot"], "metric": d4["metric"],
                          "tolerance": d4["tolerance"], "n_changes_on_second_host": d4["n_changes_on_second_host"],
                          "untested_handling": h4}
    if h4 == "cap_at_GO_WITH_FIXES":
        g4.update(outcome=NOT_TESTED, effect="GO_WITH_FIXES")
    elif h4 == "NO_GO_until_tested":
        g4.update(outcome=NOT_TESTED, effect="NO_GO")
    else:
        ht = inputs.get("host_timing") or {}
        prox, unknown4, failed = [], False, False
        for s in d4["proxy_statistics"]:
            r = ht.get(s) or {}
            rho, p = r.get("rho"), r.get("p")
            if not _finite(rho) or not _finite(p):
                unknown4 = True
                prox.append({"statistic": s, "rho": rho, "p": p, "note": "not estimable"})
                continue
            fails = abs(float(rho)) > d4["proxy_kill_if_abs_rho_above"] and float(p) < d4["proxy_kill_requires_p_below"]
            failed |= fails
            prox.append({"statistic": s, "rho": float(rho), "p": float(p), "fails": bool(fails)})
        g4["proxy"] = prox
        if unknown4:
            g4.update(outcome=NOT_EVALUABLE, effect="NO_GO")                                           # R1
        elif failed:
            g4.update(outcome="PROXY_FAIL", effect="NO_GO" if d4["proxy_fail_handling"] == "NO_GO" else "GO_WITH_FIXES")
        else:
            g4.update(outcome="PROXY_PASS", effect=None if d4["proxy_pass_counts_as_tested"] else "GO_WITH_FIXES")
    out["G4_host_invariant"] = g4

    # D9 positive controls ---------------------------------------------------------------------------------------------
    pos_valid = pos_all[pos_all.valid]
    prow, unknown9, n_pos_above = [], False, 0
    for _, r in pos_all.iterrows():
        row = {"run_id": r["run_id"], "topology": r["topology"], "valid": bool(r["valid"])}
        if not r["valid"]:
            row["above"] = False if d9["invalid_positive_control_handling"] == "counts_as_not_above" else None
            prow.append(row)
            continue
        f, v = _floor_for(floors["T1"], r["topology"]), r.get(PRIMARY)                               # R8
        if f is None or not _finite(v):
            row["note"] = "floor or T1 undefined"
            unknown9 = True
            prow.append(row)
            continue
        above = float(v) > f
        row.update(T1=float(v), floor=f, above=bool(above))
        n_pos_above += int(above)
        prow.append(row)
    need = d9["min_positive_controls_above_floor"]
    if d9["invalid_positive_control_handling"] == "excluded_from_count":
        need_eff = min(need, len(pos_valid))
        ok9 = len(pos_valid) > 0 and n_pos_above >= need_eff
    else:
        need_eff = need
        ok9 = n_pos_above >= need
    out["D9_positive_controls"] = {"n_planned": int(len(pos_all)), "n_valid": int(len(pos_valid)),
                                   "n_above": n_pos_above, "required": need, "required_effective": need_eff,
                                   "handling": d9["invalid_positive_control_handling"], "per_run": prow,
                                   "outcome": NOT_EVALUABLE if (unknown9 or len(pos_all) == 0) else (PASS if ok9 else FAIL)}

    # decision (pre-registration §16) ----------------------------------------------------------------------------------
    nogo, fixes = [], []
    if out["validity_guard"]["outcome"] != PASS:
        nogo.append(f"validity guard {out['validity_guard']['outcome']}")
    for key in ("G1_measurable", "G2_not_reducible", "G3_repeatable", "G5_cost"):
        o = out[key]["outcome"]
        if o == KILL:
            nogo.append(f"{key} KILL")
        elif o == NOT_EVALUABLE:
            nogo.append(f"{key} NOT_EVALUABLE (R1)")
    if out["D9_positive_controls"]["outcome"] != PASS:
        nogo.append(f"positive-control sensitivity {out['D9_positive_controls']['outcome']}")
    if g4["effect"] == "NO_GO":
        nogo.append(f"G4 {g4['outcome']} (D4 untested_handling={h4})")
    elif g4["effect"] == "GO_WITH_FIXES":
        fixes.append(f"G4 {g4['outcome']} (D4 untested_handling={h4})")
    defects = [str(x) for x in (protocol_defects or [])]
    if defects:
        fixes.append(f"{len(defects)} documented protocol defect(s)")
    decision = "NO-GO" if nogo else ("GO-WITH-FIXES" if fixes else "GO")
    out["decision"] = {"decision": decision, "no_go_reasons": nogo, "go_with_fixes_reasons": fixes,
                       "protocol_defects": defects, "ml_affects_decision": False,
                       "large_corpus_started": False,
                       "note": "No outcome starts the large corpus automatically (pre-registration §16)."}
    return out
