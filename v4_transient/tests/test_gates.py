"""Offline tests of the gate machinery on SYNTHETIC tables. No smoke-test or pilot data are read.
The decision values come from tests/_fixtures.py and are arbitrary test fixtures, not scientific decisions.
    ./.venv/Scripts/python.exe v4_transient/tests/test_gates.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4)); sys.path.insert(0, str(HERE.parent))

import pandas as pd                                                  # noqa: E402

from v4lib import decisions as DEC                                   # noqa: E402
from v4lib import gates as G                                         # noqa: E402
from _fixtures import fixture_decisions                              # noqa: E402

fails = 0
TOPOS = ["tA", "tB", "tC", "tD"]
CHANGES = [f"C{i:02d}" for i in range(1, 21)]


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


def build(pop_t1=0.2, noop_t1=0.01, pos_values=None, invalid=(), wall=100.0, noop_topos=None, pop_values=None,
          noop_values=None, pop_probe=0.1, noop_probe=0.01, pos_invalid=()):
    rows = []
    for i, c in enumerate(CHANGES):
        for rep in range(1, 6):
            v = pop_values[rep - 1] if pop_values else pop_t1
            rows.append({"run_id": f"{c}.rep{rep}", "change_id": c, "kind": "population", "topology": TOPOS[i % 4],
                         "valid": (c, rep) not in set(invalid), "T1_disruption_area": v, "wall_s": wall,
                         "probe_loss_frac_window": pop_probe})
    for j, t in enumerate(noop_topos or [TOPOS[j % 4] for j in range(10)]):
        rows.append({"run_id": f"N{j}", "change_id": f"N{j}", "kind": "control_noop", "topology": t, "valid": True,
                     "T1_disruption_area": noop_values[j] if noop_values else noop_t1, "wall_s": wall,
                     "probe_loss_frac_window": noop_probe})
    for j, t in enumerate(TOPOS):
        rows.append({"run_id": f"P{j}", "change_id": f"P{j}", "kind": "control_positive", "topology": t,
                     "valid": j not in set(pos_invalid), "T1_disruption_area": (pos_values or [0.5] * 4)[j],
                     "wall_s": wall, "probe_loss_frac_window": 0.5})
    return pd.DataFrame(rows)


def inputs(runs, within=0.3, total_zero=False, bl=None, ht=None):
    return {"runs": runs, "variance_T1": {"within_share": within, "total_variance_zero": total_zero},
            "baselines": bl or {"change_means": {b: {"loto_r2": 0.2, "bootstrap_ci": [0.0, 0.4]} for b in DEC.BASELINE_IDS},
                                "runs": {b: {"loto_r2": 0.1, "bootstrap_ci": [0.0, 0.3]} for b in DEC.BASELINE_IDS}},
            "host_timing": ht or {s: {"rho": 0.05, "p": 0.7} for s in DEC.HOST_PROXY_STATISTICS},
            "planned_population_runs": 100}


def ev(runs=None, doc=None, defects=None, **kw):
    return G.evaluate(inputs(runs if runs is not None else build(), **kw), doc or fixture_decisions(), defects)


def dec(doc_mut=None):
    doc = fixture_decisions()
    if doc_mut:
        doc_mut(doc["decisions"])
    assert DEC.validate(doc) == [], DEC.validate(doc)
    return doc


# refusal of invalid decisions
for label, bad in (("blank template", DEC.template()), ("one decision removed", {**fixture_decisions(), "decisions": {
        k: v for k, v in fixture_decisions()["decisions"].items() if k != "D6_G5_cost"}})):
    try:
        G.evaluate(inputs(build()), bad)
        check(f"evaluate refuses {label}", False)
    except ValueError:
        check(f"evaluate refuses {label}", True)

r = ev()
check("baseline scenario: every testable gate passes", all(r[k]["outcome"] == "PASS" for k in
      ("G1_measurable", "G2_not_reducible", "G3_repeatable", "G5_cost", "validity_guard", "D9_positive_controls")), r["decision"])
check("untested G4 with cap -> GO-WITH-FIXES, never GO", r["decision"]["decision"] == "GO-WITH-FIXES", r["decision"])
check("ML never affects the decision; large corpus never started", r["decision"]["ml_affects_decision"] is False
      and r["decision"]["large_corpus_started"] is False)

check("G1 KILL when changes sit below the floor -> NO-GO",
      ev(build(pop_t1=0.005))["G1_measurable"]["outcome"] == "KILL" and ev(build(pop_t1=0.005))["decision"]["decision"] == "NO-GO")
check("floor comparison is strict (equal is not above)", ev(build(pop_t1=0.01))["G1_measurable"]["n_above"] == 0)

bl_high = {"change_means": {**{b: {"loto_r2": 0.2, "bootstrap_ci": [0.0, 0.4]} for b in DEC.BASELINE_IDS},
                            "B5_combined_analytic": {"loto_r2": 0.95, "bootstrap_ci": [0.5, 0.99]}},
           "runs": {b: {"loto_r2": 0.1, "bootstrap_ci": [0.0, 0.3]} for b in DEC.BASELINE_IDS}}
r = ev(bl=bl_high)
check("G2 max aggregator picks strongest baseline and KILLs on point estimate",
      r["G2_not_reducible"]["baseline"] == "B5_combined_analytic" and r["G2_not_reducible"]["outcome"] == "KILL")
check("G2 KILL -> NO-GO", r["decision"]["decision"] == "NO-GO")
r = ev(bl=bl_high, doc=dec(lambda d: d["D5_G2_analytic_reducibility"].update(ci_rule="lower_95_bootstrap_bound")))
check("G2 lower-bound rule uses the CI lower bound", r["G2_not_reducible"]["value"] == 0.5 and r["G2_not_reducible"]["outcome"] == "PASS")
r = ev(bl=bl_high, doc=dec(lambda d: d["D5_G2_analytic_reducibility"].update(aggregator="single_named_baseline", named_baseline="B2_r_exact")))
check("G2 single named baseline is honoured", r["G2_not_reducible"]["baseline"] == "B2_r_exact" and r["G2_not_reducible"]["outcome"] == "PASS")
r = ev(bl=bl_high, doc=dec(lambda d: d["D5_G2_analytic_reducibility"].update(unit="runs")))
check("G2 unit 'runs' reads the run-level baselines", r["G2_not_reducible"]["value"] == 0.1)
r = ev(bl={"change_means": {"note": "not computable"}, "runs": {}})
check("G2 not computable -> NOT_EVALUABLE -> NO-GO", r["G2_not_reducible"]["outcome"] == "NOT_EVALUABLE" and r["decision"]["decision"] == "NO-GO")

check("G3 KILL above within-share threshold", ev(within=0.7)["G3_repeatable"]["outcome"] == "KILL")
check("G3 within share 0, report_only -> PASS", ev(within=0.0)["G3_repeatable"]["outcome"] == "PASS")
d_ind = dec(lambda d: d["D3_G3_repeatable"].update(zero_within_share_clause="kills_independently"))
check("G3 within share 0, kills_independently -> KILL", ev(within=0.0, doc=d_ind)["G3_repeatable"]["outcome"] == "KILL")
d_g2 = dec(lambda d: d["D3_G3_repeatable"].update(zero_within_share_clause="kills_only_if_G2_kills"))
check("G3 within share 0, kills_only_if_G2_kills with G2 PASS -> PASS", ev(within=0.0, doc=d_g2)["G3_repeatable"]["outcome"] == "PASS")
check("G3 within share 0, kills_only_if_G2_kills with G2 KILL -> KILL",
      ev(within=0.0, doc=d_g2, bl=bl_high)["G3_repeatable"]["outcome"] == "KILL")
check("G3 total variance 0 with 'kill' -> KILL", ev(within=float("nan"), total_zero=True)["G3_repeatable"]["outcome"] == "KILL")
d_nk = dec(lambda d: d["D3_G3_repeatable"].update(zero_total_variance_handling="no_kill_report_undefined"))
check("G3 total variance 0 with 'no_kill_report_undefined' -> PASS",
      ev(within=float("nan"), total_zero=True, doc=d_nk)["G3_repeatable"]["outcome"] == "PASS")
check("G3 not estimable -> NOT_EVALUABLE", ev(within=None)["G3_repeatable"]["outcome"] == "NOT_EVALUABLE")

check("G5 KILL above median wall threshold", ev(build(wall=200.0))["G5_cost"]["outcome"] == "KILL")

inv = [(c, rep) for c in CHANGES[:4] for rep in range(1, 6)]
r = ev(build(invalid=inv))
check("validity guard FAIL when too few valid population runs", r["validity_guard"]["outcome"] == "FAIL" and r["validity_guard"]["share"] == 0.8)
check("D7: changes without enough valid replicates are ineligible", r["D7_eligibility"]["n_eligible"] == 16)
check("G1 denominator 'all_population_changes' counts ineligible changes as not above", r["G1_measurable"]["share_above"] == 16 / 20)
r = ev(build(invalid=inv), doc=dec(lambda d: d["D2_G1_measurable"].update(denominator="changes_meeting_D7")))
check("G1 denominator 'changes_meeting_D7' uses eligible changes only", r["G1_measurable"]["share_above"] == 1.0)

r = ev(build(noop_topos=["tA", "tB", "tC"] * 3 + ["tA"]),
       doc=dec(lambda d: d["D1_noise_floor"].update(floor_statistic="max_per_topology_noop")))
check("per-topology floor with a topology lacking no-op runs -> NOT_EVALUABLE -> NO-GO",
      r["G1_measurable"]["outcome"] == "NOT_EVALUABLE" and r["decision"]["decision"] == "NO-GO")
r = ev(build(noop_values=[0.01, 0.02, 0.03, 0.04] * 2 + [0.01, 0.02]),
       doc=dec(lambda d: d["D1_noise_floor"].update(floor_statistic="max_per_topology_noop")))
check("per-topology floor = per-topology maximum", r["noise_floor"]["T1"]["per_topology"] == {"tA": 0.01, "tB": 0.02, "tC": 0.03, "tD": 0.04},
      r["noise_floor"]["T1"])

r = ev(build(noop_t1=0.0, pop_t1=0.0))
check("all no-op zero, floor_is_zero: zero-disruption changes are not above -> G1 KILL", r["noise_floor"]["T1"]["global"] == 0.0
      and r["G1_measurable"]["outcome"] == "KILL")
d_res = dec(lambda d: d["D1_noise_floor"].update(all_noop_zero_handling="minimum_resolution_floor", minimum_resolution_floor=0.05,
                                                 minimum_resolution_floor_scope="only_when_all_noop_zero"))
r = ev(build(noop_t1=0.0, pop_t1=0.02), doc=d_res)
check("all no-op zero, minimum_resolution_floor applies the decided floor", r["noise_floor"]["T1"]["global"] == 0.05
      and r["G1_measurable"]["outcome"] == "KILL")
r = ev(build(noop_t1=0.01, pop_t1=0.03), doc=d_res)
check("scope only_when_all_noop_zero: bound not applied when no-op T1 is positive",
      r["noise_floor"]["T1"]["global"] == 0.01 and r["G1_measurable"]["outcome"] == "PASS")
d_lb = dec(lambda d: d["D1_noise_floor"].update(all_noop_zero_handling="minimum_resolution_floor", minimum_resolution_floor=0.05,
                                                minimum_resolution_floor_scope="lower_bound_always"))
r = ev(build(noop_t1=0.01, pop_t1=0.03), doc=d_lb)
check("scope lower_bound_always: floor = max(no-op max, bound)", r["noise_floor"]["T1"]["global"] == 0.05
      and r["noise_floor"]["T1"]["empirical_floor"] == 0.01 and r["G1_measurable"]["outcome"] == "KILL")
r = ev(build(noop_t1=0.08, pop_t1=0.09), doc=d_lb)
check("scope lower_bound_always: empirical floor above the bound is kept", r["noise_floor"]["T1"]["global"] == 0.08
      and r["G1_measurable"]["outcome"] == "PASS")
r = ev(build(noop_values=[0.01, 0.02, 0.03, 0.09] * 2 + [0.01, 0.02]),
       doc=dec(lambda d: d["D1_noise_floor"].update(floor_statistic="max_per_topology_noop", all_noop_zero_handling="minimum_resolution_floor",
                                                    minimum_resolution_floor=0.05, minimum_resolution_floor_scope="lower_bound_always")))
check("scope lower_bound_always with per-topology floors", r["noise_floor"]["T1"]["per_topology"] == {"tA": 0.05, "tB": 0.05, "tC": 0.05, "tD": 0.09})
r = ev(build(pos_values=[0.5, 0.5, 0.5, 0.03], noop_t1=0.01), doc=d_lb)
check("positive controls are compared with the bounded floor", r["D9_positive_controls"]["n_above"] == 3)

# the frozen decisions themselves drive the machinery end to end on synthetic data (no smoke or pilot values)
import json as _json                                                   # noqa: E402
real = _json.loads((V4 / DEC.DECISIONS_REL).read_text(encoding="utf-8"))
r = G.evaluate(inputs(build()), real)
check("frozen decisions evaluate on synthetic data", r["decision"]["decision"] in ("NO-GO", "GO-WITH-FIXES", "GO"))
check("frozen decisions: GO is unreachable while G4 is untested", r["G4_host_invariant"]["outcome"] == "NOT_TESTED"
      and r["decision"]["decision"] != "GO")

d_k = dec(lambda d: d["D1_noise_floor"].update(floor_statistic="mean_plus_k_sd_all_noop", k_sd=2.0))
r = ev(build(noop_values=[0.01, 0.03] * 5, pop_t1=0.03), doc=d_k)
fl = r["noise_floor"]["T1"]["global"]
check("mean + k*sd floor computed with ddof=1", abs(fl - (0.02 + 2.0 * pd.Series([0.01, 0.03] * 5).std(ddof=1))) < 1e-12, fl)
check("mean + k*sd: change below floor not above", r["G1_measurable"]["n_above"] == 0)

d_mean = dec(lambda d: d["D1_noise_floor"].update(per_change_comparator="replicate_mean"))
check("comparator median: [0,0,0,1,1] is not above", ev(build(pop_values=[0, 0, 0, 1, 1]))["G1_measurable"]["n_above"] == 0)
check("comparator mean: [0,0,0,1,1] is above", ev(build(pop_values=[0, 0, 0, 1, 1]), doc=d_mean)["G1_measurable"]["n_above"] == 20)

d_both = dec(lambda d: d["D1_noise_floor"].update(metrics="T1_and_probe_loss", probe_metric="probe_loss_frac_window",
                                                  probe_combination="both_above_required"))
d_either = dec(lambda d: d["D1_noise_floor"].update(metrics="T1_and_probe_loss", probe_metric="probe_loss_frac_window",
                                                    probe_combination="either_above_sufficient"))
check("probe both_above_required: T1 above but probe below -> not above", ev(build(pop_probe=0.005), doc=d_both)["G1_measurable"]["n_above"] == 0)
check("probe either_above_sufficient: T1 above -> above", ev(build(pop_probe=0.005), doc=d_either)["G1_measurable"]["n_above"] == 20)

check("positive controls: 2 of 4 above with minimum 3 -> FAIL -> NO-GO",
      ev(build(pos_values=[0.5, 0.5, 0.005, 0.005]))["D9_positive_controls"]["outcome"] == "FAIL"
      and ev(build(pos_values=[0.5, 0.5, 0.005, 0.005]))["decision"]["decision"] == "NO-GO")
check("positive controls: 3 of 4 above with minimum 3 -> PASS", ev(build(pos_values=[0.5, 0.5, 0.5, 0.005]))["D9_positive_controls"]["outcome"] == "PASS")
check("positive controls: invalid run counts as not above", ev(build(pos_values=[0.5, 0.5, 0.005, 0.5], pos_invalid=[3]))["D9_positive_controls"]["outcome"] == "FAIL")
d_exc = dec(lambda d: d["D9_positive_control_sensitivity"].update(invalid_positive_control_handling="excluded_from_count"))
check("positive controls: excluded_from_count lowers requirement to valid count",
      ev(build(pos_values=[0.5, 0.5, 0.5, 0.005], pos_invalid=[3]), doc=d_exc)["D9_positive_controls"]["outcome"] == "PASS")

d_ng = dec(lambda d: d["D4_G4_host_invariance"].update(untested_handling="NO_GO_until_tested"))
check("G4 NO_GO_until_tested -> NO-GO", ev(doc=d_ng)["decision"]["decision"] == "NO-GO")


def proxy(fail_handling="GO_WITH_FIXES", counts=True):
    return dec(lambda d: d["D4_G4_host_invariance"].update(untested_handling="single_host_proxy",
                                                            proxy_statistics=list(DEC.HOST_PROXY_STATISTICS),
                                                            proxy_kill_if_abs_rho_above=0.55, proxy_kill_requires_p_below=0.01,
                                                            proxy_fail_handling=fail_handling, proxy_pass_counts_as_tested=counts))


check("G4 proxy pass counted as tested, everything else passes -> GO", ev(doc=proxy())["decision"]["decision"] == "GO")
check("G4 proxy pass NOT counted as tested -> GO-WITH-FIXES", ev(doc=proxy(counts=False))["decision"]["decision"] == "GO-WITH-FIXES")
bad_ht = {s: {"rho": 0.9, "p": 0.001} for s in DEC.HOST_PROXY_STATISTICS}
check("G4 proxy fail with GO_WITH_FIXES handling -> GO-WITH-FIXES", ev(doc=proxy(), ht=bad_ht)["decision"]["decision"] == "GO-WITH-FIXES")
check("G4 proxy fail with NO_GO handling -> NO-GO", ev(doc=proxy("NO_GO"), ht=bad_ht)["decision"]["decision"] == "NO-GO")
check("G4 proxy not estimable -> NO-GO", ev(doc=proxy(), ht={s: {"rho": None, "p": None} for s in DEC.HOST_PROXY_STATISTICS})["decision"]["decision"] == "NO-GO")
check("documented protocol defect prevents GO", ev(doc=proxy(), defects=["probe log truncated"])["decision"]["decision"] == "GO-WITH-FIXES")
check("machinery rules are reported with every evaluation", len(ev()["machinery_rules"]) == len(G.MACHINERY_RULES))

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
