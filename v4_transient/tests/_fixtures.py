"""TEST FIXTURES ONLY.

The numbers below are arbitrary synthetic values chosen solely to exercise code paths. They are NOT scientific
decisions, were not derived from any smoke-test or pilot data, deliberately avoid the plan's proposed values, and
must never be copied into config/pilot_decisions.json.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from v4lib import decisions as DEC                                   # noqa: E402

FIXTURE_TAG = "TEST FIXTURE - NOT A SCIENTIFIC DECISION"


def fixture_decisions():
    doc = DEC.template()
    doc["status"] = "FROZEN"
    doc["decided_by"] = FIXTURE_TAG
    doc["decided_utc"] = "1970-01-01T00:00:00Z"
    d = doc["decisions"]
    for k in d:
        d[k]["status"] = "FROZEN"
        d[k]["rationale"] = FIXTURE_TAG
    d["D1_noise_floor"].update(floor_statistic="max_all_noop", per_change_comparator="replicate_median",
                               metrics="T1_only", all_noop_zero_handling="floor_is_zero")
    d["D2_G1_measurable"].update(kill_if_share_above_floor_below=0.5, denominator="all_population_changes")
    d["D3_G3_repeatable"].update(kill_if_within_share_above=0.6, zero_within_share_clause="report_only",
                                 zero_total_variance_handling="kill")
    d["D4_G4_host_invariance"].update(metric="median_abs_diff_change_mean_T1", tolerance=0.123,
                                      n_changes_on_second_host=7, second_host_available_for_this_pilot=False,
                                      untested_handling="cap_at_GO_WITH_FIXES")
    d["D5_G2_analytic_reducibility"].update(unit="change_means", aggregator="max_over_B2_B6",
                                            cross_validation="leave_one_topology_out", kill_if_r2_at_least=0.75,
                                            ci_rule="point_estimate")
    d["D6_G5_cost"].update(kill_if_median_wall_s_above=150.0)
    d["D7_min_valid_replicates"].update(min_valid_replicates_per_change=4)
    d["D8_validity_guard"].update(min_valid_population_run_share=0.85)
    d["D9_positive_control_sensitivity"].update(min_positive_controls_above_floor=3,
                                                invalid_positive_control_handling="counts_as_not_above")
    return doc
