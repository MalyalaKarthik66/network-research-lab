# D1–D9 decision schema — how the pilot's open scientific decisions are recorded, validated and approved

**Status (2026-09-14): D1–D9 are FROZEN, before any pilot run.**
- **Values:** `config/pilot_decisions.json`, written by `tools/freeze_pilot_decisions.py`, with rationales. The
  final values are summarised in pre-registration §19.
- **Approval:** `manifests/PREREG-APPROVAL.json` and `manifests/PREREG-FROZEN-RECORD.json`, written by
  `tools/write_prereg_approval.py`.
- **Starting the pilot:** requires the explicit command
  `run_pilot.py --plan pilot --confirm-pilot START-20x5-PILOT`. It has not been run.

The tables below keep the plan's original proposals for reference ("PROPOSED" is the plan's wording). None is a
code default. The decided values live only in the decisions file.

## 1. Files

| file | role |
|---|---|
| `v4lib/decisions.py` | the schema (`SPEC`), blank `template()`, `validate()`, `json_schema()`, `check_approval()` |
| `config/pilot_decisions.TEMPLATE.json` | generated blank document: every value `null`, every status `UNFROZEN — REQUIRES DECISION BEFORE PILOT` |
| `config/pilot_decisions.schema.json` | generated JSON Schema (structural; the full rules live in `validate()`) |
| **`config/pilot_decisions.json`** | **the frozen D1–D9 values** (written by `tools/freeze_pilot_decisions.py`) |
| **`manifests/PREREG-APPROVAL.json`** | **links the approved pre-registration and decisions by SHA-256** (written by `tools/write_prereg_approval.py`) |
| `manifests/PREREG-FROZEN-RECORD.json` | freeze record: all three hashes, the D1 resolution-floor derivation, prior draft hashes |
| `v4lib/gates.py` | evaluates G1–G5, the validity guard and the positive-control rule from validated decisions |
| `tools/write_decision_template.py` | regenerates the template and schema; never writes the decisions file |

## 2. Blocking rules (enforced by `run_pilot.py --plan pilot`, re-checked before every attempt)

The runner refuses unless **all** of these hold (`v4lib/decisions.check_approval`):

1. **Approval file.** `manifests/PREREG-APPROVAL.json` exists, with `approved: true` and non-empty
   `approved_by` and `approved_utc`.
2. **Pre-registration hash.** `prereg_sha256` equals the SHA-256 of `docs/PILOT-PREREGISTRATION.md` as amended.
3. **Decisions hash.** `decisions_file` points inside `v4_transient/` to an existing file, and `decisions_sha256`
   equals its SHA-256.
4. **Decisions document is valid** (`validate()` returns no problems):
   - the top level has `schema_version = v4-pilot-decisions-1`, `status = FROZEN`, and `decided_by` /
     `decided_utc` set;
   - all nine blocks D1–D9 are present, and no unknown keys exist;
   - each block has `status = FROZEN`, a non-empty `rationale`, and no unknown field;
   - every applicable field is set, has the right type, and is in range or in its option list;
   - every non-applicable conditional field is `null`;
   - the D1 floor-statistic/comparator pair is one of the pre-registration §6 options;
   - `second_host_available_for_this_pilot` is `false` (a two-host G4 is not implemented);
   - no string anywhere contains "UNFROZEN" (case-insensitive), including in rationales.
5. **Pre-registration fully decided.** No section of the pre-registration other than the §0 legend still
   contains the `UNFROZEN — REQUIRES DECISION BEFORE PILOT` marker, in headings or inline.

Approval file schema:

```json
{
  "approved": true,
  "approved_by": "<name>",
  "approved_utc": "<ISO-8601 UTC>",
  "prereg_file": "docs/PILOT-PREREGISTRATION.md",
  "prereg_sha256": "<SHA-256 of the amended pre-registration>",
  "decisions_file": "config/pilot_decisions.json",
  "decisions_sha256": "<SHA-256 of config/pilot_decisions.json>"
}
```

## 3. Fields that require an explicit scientific value

"When" means the field is required only under that condition; otherwise it must be `null`. Every block also
requires `status: "FROZEN"` and a `rationale`.

### D1_noise_floor — pre-registration §6 (no plan proposal exists)

| field | allowed values | when |
|---|---|---|
| `floor_statistic` | `max_all_noop` · `max_per_topology_noop` · `mean_plus_k_sd_all_noop` | always |
| `k_sd` | number > 0 | `floor_statistic = mean_plus_k_sd_all_noop` |
| `per_change_comparator` | `replicate_median` · `replicate_mean` | always |
| `metrics` | `T1_only` · `T1_and_probe_loss` | always |
| `probe_metric` | `probe_loss_frac_window` · `probe_lost_packet_s_window` | `metrics = T1_and_probe_loss` |
| `probe_combination` | `both_above_required` · `either_above_sufficient` | `metrics = T1_and_probe_loss` |
| `all_noop_zero_handling` | `floor_is_zero` · `minimum_resolution_floor` | always |
| `minimum_resolution_floor` | number ≥ 0 (T1 units) | `all_noop_zero_handling = minimum_resolution_floor` |
| `probe_minimum_resolution_floor` | number ≥ 0 (probe-metric units) | both of the above |
| `minimum_resolution_floor_scope` | `only_when_all_noop_zero` · `lower_bound_always` (floor = max(empirical floor, resolution floor)) | `all_noop_zero_handling = minimum_resolution_floor` |

Allowed (statistic, comparator) pairs, from the §6 table:
- (a) max + median;
- (b) max + mean;
- (c) per-topology max + median;
- (d) mean + k·sd with median or mean.

### D2_G1_measurable — §7

| field | allowed | plan status |
|---|---|---|
| `kill_if_share_above_floor_below` | number in (0, 1] | **PROPOSED / UNFROZEN: 0.30** |
| `denominator` | `all_population_changes` · `changes_meeting_D7` | not proposed |

### D3_G3_repeatable — §8 (the calculation is frozen)

| field | allowed | plan status |
|---|---|---|
| `kill_if_within_share_above` | number in [0, 1) | **PROPOSED / UNFROZEN: 0.80** |
| `zero_within_share_clause` | `kills_only_if_G2_kills` · `kills_independently` · `report_only` | ambiguous in plan ("= 0 with G2 failing") |
| `zero_total_variance_handling` | `kill` · `no_kill_report_undefined` · `apply_zero_within_share_clause` | not addressed in plan; the option list is the implementer's, review it |

### D4_G4_host_invariance — §9

| field | allowed | when / plan status |
|---|---|---|
| `metric` | `median_abs_diff_change_mean_T1` · `median_abs_diff_change_mean_T1_over_pooled_within_sd` | no metric fixed in plan |
| `tolerance` | number ≥ 0 | **no value in plan** |
| `n_changes_on_second_host` | integer 1–20 | not in plan |
| `second_host_available_for_this_pilot` | must be `false` (the pilot has one host) | — |
| `untested_handling` | `cap_at_GO_WITH_FIXES` · `NO_GO_until_tested` · `single_host_proxy` | §9 options (a)(b)(c) |
| `proxy_statistics` | non-empty subset of `resid_vs_order`, `resid_vs_loadavg1`, `resid_vs_wallclock` | `single_host_proxy` |
| `proxy_kill_if_abs_rho_above` | number in [0, 1) | `single_host_proxy` |
| `proxy_kill_requires_p_below` | number in (0, 1] | `single_host_proxy` |
| `proxy_fail_handling` | `NO_GO` · `GO_WITH_FIXES` | `single_host_proxy` |
| `proxy_pass_counts_as_tested` | true · false | `single_host_proxy` |

### D5_G2_analytic_reducibility — §10 (baselines frozen in §14)

| field | allowed | when / plan status |
|---|---|---|
| `unit` | `change_means` · `runs` | not fixed |
| `aggregator` | `max_over_B2_B6` · `single_named_baseline` | not fixed |
| `named_baseline` | `B2_r_exact` … `B6_graph_analytic` | `aggregator = single_named_baseline` |
| `cross_validation` | `leave_one_topology_out` (the only option) | explicit confirmation required |
| `kill_if_r2_at_least` | number ≤ 1 | **PROPOSED / UNFROZEN: 0.90** |
| `ci_rule` | `point_estimate` · `lower_95_bootstrap_bound` | not fixed |

### D6_G5_cost — §11 (the metric is frozen)

| field | allowed | plan status |
|---|---|---|
| `kill_if_median_wall_s_above` | number > 0 (seconds) | **PROPOSED / UNFROZEN: 180** |

### D7_min_valid_replicates — §12

| field | allowed | plan status |
|---|---|---|
| `min_valid_replicates_per_change` | 3 · 4 · 5 | candidates listed only |

### D8_validity_guard — §12

| field | allowed | plan status |
|---|---|---|
| `min_valid_population_run_share` | number in (0, 1] | **candidates 0.90 / 0.80, UNFROZEN** |

### D9_positive_control_sensitivity — §16

| field | allowed | plan status |
|---|---|---|
| `min_positive_controls_above_floor` | 3 · 4 | candidates listed only |
| `invalid_positive_control_handling` | `counts_as_not_above` (need n_above ≥ minimum) · `excluded_from_count` (need valid > 0 and n_above ≥ min(minimum, n_valid)) | not in plan; the option list is the implementer's, review it |

## 4. Machinery rules that are NOT D1–D9 values — review before approval

Making the gates computable required the following interpretations (`v4lib/gates.MACHINERY_RULES`). They are
reported with every evaluation. They are conservative where a choice existed, but they are implementer
interpretations. If any is unacceptable, amend it before the pilot.

- **R1:** a gate whose inputs are missing or undefined is NOT_EVALUABLE, and that yields **NO-GO**.
- **R2:** with denominator `all_population_changes`, a change with fewer valid replicates than D7 counts as
  not above the floor. It is never imputed.
- **R3:** floor comparisons are strict (`>`), as §6 writes them.
- **R4:** "every no-op T1 = 0" is evaluated over all valid no-op runs pooled.
- **R5:** with `max_per_topology_noop`, a topology with no valid no-op run makes its changes and positive
  controls NOT_EVALUABLE.
- **R6:** `mean_plus_k_sd` uses sd with ddof = 1 and needs at least 2 no-op values.
- **R7:** probe floors use the same statistic, comparator and zero handling on the chosen probe metric.
- **R8:** positive controls are compared with the T1 floor only.
- **R9:** the G2 `change_means` unit uses D7-eligible changes; the `runs` unit uses all valid population runs.
- **R10:** G3 uses all valid population runs (§8), with no D7 restriction.
- **R11:** G5 uses the recorded `wall_s` of every population run's final attempt, valid or not (§11).
- **R12:** the validity-guard denominator is the planned population runs; runs never executed count as invalid.
- **R13:** ML never enters the decision.

## 5. Finalisation procedure (completed 2026-09-14, before any pilot run; kept for the record)

The steps below were carried out with `tools/freeze_pilot_decisions.py` and `tools/write_prereg_approval.py`. The
runner additionally requires `--confirm-pilot START-20x5-PILOT`.

1. Copy `config/pilot_decisions.TEMPLATE.json` to `config/pilot_decisions.json` and fill in every applicable
   field, the rationales, `decided_by` and `decided_utc`. Set every status to `FROZEN`.
2. Amend `docs/PILOT-PREREGISTRATION.md`:
   - replace each `UNFROZEN — REQUIRES DECISION BEFORE PILOT` marker in §6–§12 and §16 with the decided text;
   - log each change in §18 with the UTC date and decider;
   - leave only the §0 legend carrying the marker.
3. Write `manifests/PREREG-APPROVAL.json` with the SHA-256 of both files.
4. Before any pilot run:
   - `tests/test_decisions.py`, `test_gates.py` and `test_runner.py` must still pass;
   - `v4lib/decisions.check_approval` must return `ok`;
   - `tests/test_decisions.py` asserts that no approved decisions file exists today, so update that single
     assertion in the same amendment.
5. Only then may `run_pilot.py --plan pilot` be started, and only on explicit instruction.
