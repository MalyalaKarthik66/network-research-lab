# Phase 3 data dictionary

Ground truth from the running emulator. **No model, no features, no final
label.** Phase 4 does that.

Field classes: **EXEC** (execution/infrastructure), **MEASURE** (observed network
behaviour), **EVIDENCE** (raw supporting output), **META**, **DERIVED**
(mechanical application of a frozen definition).

## Files

| File | Grain | Rows |
|---|---|---|
| `containerlab_summary.csv` | one per lab run | 61 |
| `containerlab_measurements.csv` | one per (run, property) | 732 |
| `containerlab_deltas.csv` | one per (candidate, property) | 600 |
| `containerlab_outcomes.csv` | one per candidate | 50 |
| `run_metadata.json` | one object | — |
| `runs/<id>/…` | raw evidence per run | — |

61 runs = golden + 10 incidents (Phase 3 **BEFORE** state) + 50 candidates
(**AFTER** state).

## containerlab_summary.csv

**Identity / EXEC** — `run_id`, `kind` (golden/incident/candidate), `lab`,
`run_status`, `run_error`, `wall_seconds`, `teardown_ok`.

`run_status` vocabulary, deliberately not collapsed:

| Value | Meaning |
|---|---|
| `OK` | deployed, converged, measured |
| `NO_CONVERGENCE` | deployed and measured, but the RIB never stabilised |
| `DEPLOY_FAILED` | Containerlab could not bring the lab up |
| `CONTAINERS_MISSING` | deploy returned success, containers absent |
| `STAGING_FAILED` | artifact hash mismatch — **nothing was deployed** |
| `ERROR` | unexpected harness exception |

Only the first two produced measurements from a real network. The rest carry
twelve ERROR placeholder rows so a failed run occupies exactly as many rows as a
successful one — absence must never be mistakable for success.

**Convergence / MEASURE** — `converged`, `convergence_seconds`,
`convergence_polls`. Convergence (harm definition v1.1.0) requires **all three** of: 45 s elapsed,
no OSPF neighbour in a transitional state, and RIB byte-stability across 3
consecutive polls 5 s apart. Timeout 180 s.

It is deliberately *not* "all expected adjacencies Full": a faulted network
legitimately never brings every adjacency up, so that criterion would time out
every incident lab by construction. The 45 s floor exists because the other two
conditions are trivially true before OSPF starts — see the v1.1.0 rationale in
`docs/HARM-DEFINITION.md`.

**Same-artifact / EXEC** — `staging_status`, `staging_files_verified`,
`runtime_config_match`, `runtime_config_problems`, `runtime_address_match`.

These are the Phase 3 half of the same-artifact guarantee. Staging re-hashes
every file against `pilot.lock.json` before deploying. After convergence,
`show running-config` from each container is compared to the nrl model —
hostname, per-interface OSPF area and cost, admin state, every static route —
and `ip addr` is compared to the interfaces file. If either drifts, the emulator
ran something Batfish did not analyse and the row is void.

**Network state / MEASURE** — `ospf_full_adjacency_pairs`,
`interfaces_down_count`, `holds_P01`…`holds_P12`, `status_P01`…`status_P12`,
`properties_measured`, `properties_errored`.

## containerlab_measurements.csv

`run_id`, `kind`, `property_id`, `property_kind`, `in_spec`, `status`, `holds`,
`error`, `seconds`, `extra_json`.

**`holds` is empty if and only if `status == "ERROR"`.** An execution failure is
never a property violation. `extra_json` carries per-kind detail unflattened:
packet loss and RTT for reachability, observed hop path for path properties,
adjacency counts, which nodes lack a route, which interfaces are down.

## containerlab_deltas.csv — the BEFORE/AFTER core

One row per (candidate, property), carrying all three states:

| Column | Meaning |
|---|---|
| `golden_holds` / `golden_status` | the healthy reference network |
| `before_holds` / `before_status` | the broken incident network |
| `after_holds` / `after_status` | the network with the repair applied |
| `repaired_by_candidate` | failed BEFORE, holds AFTER |
| `regressed_vs_golden` | held in golden, fails AFTER — **this is harm** |
| `regressed_vs_before` | held even while broken, fails AFTER |
| `undetermined` | any of the three states errored |

Harm is measured against **golden**, not against the broken state: a repair is
supposed to restore health, so the question is "is the network as good as it
was", not "is it better than broken".

## containerlab_outcomes.csv — DERIVED

`candidate_id`, `incident_id`, `run_status`, `golden_properties_in_G`,
`violations_vs_golden`, `violation_count`, `spec_violations_vs_golden`,
`undetermined_properties`, `outcome_harm_v1`, `harm_definition_version`,
`label`.

`outcome_harm_v1` ∈ {`SAFE`, `HARMFUL`, `NO_CONVERGENCE`, `UNDETERMINED`,
`EXECUTION_FAILED`}. It is a **mechanical application** of
`docs/HARM-DEFINITION.md` v1.0.0 to the stored per-property outcomes, fully
recomputable from `containerlab_deltas.csv` — not a modelling decision.
`UNDETERMINED` exists so a measurement failure is never quietly counted as SAFE.

**`label` is null for all 50.** Choosing the target is Phase 4's job.

## Raw evidence — `runs/<id>/`

`run.json`, `measurements.json` (with every ping, nc and traceroute captured
verbatim), `convergence.json` (full poll history), `artifact_runtime_check.json`,
`clab_deploy.json`, `clab_destroy.json`, `listeners.json`, and
`state/<node>.<command>.json` — RIB, OSPF neighbours, OSPF interfaces, interface
state and `show running-config` per router.

## P12 is scoped to the artifact

FRR reports every interface in the container namespace: the four configured
ones, plus `eth0` (Containerlab management), plus Containerlab's transient veth
staging stubs (`clab-<random hex>`). P12 counts only interfaces defined in the
artifact. `extra.ignored_non_artifact_interfaces` records what was skipped.

This is required for comparability, not convenience: Batfish evaluates P12 over
the interfaces in the configuration and has no representation of `eth0` or a
veth stub, so an unscoped emulator measurement is not comparing like with like.

## Known limits

1. **This is an emulator.** Real routing daemons, no hardware forwarding plane, no TCAM, no line-rate traffic, idealised link timing. The measurement is *static verifier vs running emulator*, and that belongs in the paper's limitations.
2. **P01≡P02 and P03≡P04 in this topology.** There are no packet filters — FRR route filters are not packet filters — so ICMP and TCP reachability cannot differ. The SPEC nominally has 5 properties but only about 3 independent ones. That shrinks its effective coverage and should be stated rather than discovered by a reviewer.
3. **Loop detection is traceroute-based** (a hop repeating ≥3 times, or hitting the hop limit), not a proof. Batfish's `detectLoops` is the exact one; these two can disagree, and where they do it is a finding, not a bug.
4. **One measurement per lab.** No repeats, so nothing here estimates run-to-run variance. Worth adding before scaling past the pilot.
