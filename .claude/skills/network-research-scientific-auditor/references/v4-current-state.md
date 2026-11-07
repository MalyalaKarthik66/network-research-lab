# V4 current state — snapshot of 2026-09-15 (HEAD `d2c0cf0`)

**Re-verify everything here. Values are copied from the repository at that commit.**

## 1. Frozen design (prereg `v4_transient/docs/PILOT-PREREGISTRATION.md`)

**Topologies (§20).** 4 frozen v3 designs, with topology identity never a feature:
- `t05_ring6`
- `t13_bowtie7`
- `t14_ladder8`
- `t15_campus12`

**Population.** 5 changes per topology = **20**, each Batfish SPEC-PASS under suite 1.1.0 (P01, P02, P05, P07,
P08). Roles:

| role | change | selection |
|---|---|---|
| cost-hi | one link, cost ×20 at both ends | highest analytic r |
| cost-mid | same | r closest to the median of the rest |
| drain-hi | every link of one router, cost ×20 | highest r |
| drain-lo | same | lowest non-zero r |
| bh | router-loopback /32 static blackhole | highest r |

**Runs.** 5 fresh-deployment replicates of each change, shuffled with seed 20260914. The run plan
`manifests/run_plan_pilot.json` has 114 runs.

**Controls.**
- **No-op:** 10 controls, re-pushing an unchanged `ip ospf cost` (3/3/2/2 per topology).
- **Positive:** 4 controls, a **shutdown of the highest-betweenness link on one end**. They are SPEC-FAIL by
  design, outside the population, one run each.

**Instrument (A3).**
- Per-router `ip -ts monitor link route nexthop` plus route, link and nexthop-object snapshots.
- The replay applies kernel link semantics:
  - admin down flushes everything through the device;
  - carrier loss flushes nexthop-object routes;
  - nexthop-less routes on a carrier-down device discard;
  - ECMP keeps only usable members (can miss a partial loss, never invents one).
- Cross-checked against in-transient poll dumps and the final FIB.

**Protocol.**
- 10 s pre-change baseline.
- Observation after t0: at least 20 s, a 10 s quiet period, at most 90 s.
- Poll every 2 s.
- Convergence detection via `nrl.clab` (45 s floor, 180 s nominal timeout, which is NOT a hard wall cap).

**Validity (§12, 13 checks).** One retry, and only before the change is applied.

**Features (§14).** Config-derived only:
- r_exact, r_broken_exact, r_rerouted_exact
- n_fib_entries_changed, n_routers_changed
- pml_flow_frac
- n_devices_pushed, n_config_commands
- n_routers, n_endpoints
- changed_link_betweenness, golden_mean_path_len
- mechanism one-hot

**Baselines.** B0/B1 descriptive; B2–B6 OLS, leave-one-topology-out. The RandomForest is feasibility-only and
never part of the decision.

## 2. D1–D9 as frozen (`config/pilot_decisions.json`, sha `579b0338…`; prereg §19)

| D | gate | frozen rule |
|---|---|---|
| D1 | noise floor | maximum T1 over valid no-op runs (pooled); per-change **replicate median** compared with `>`; T1 only; lower bound 0.05 s / 72 flows = **6.944e-4**, applied always |
| D2 | G1 measurable | KILL if < **30 %** of all 20 population changes are above the floor; D7-ineligible changes count as not above |
| D3 | G3 repeatable | KILL if within-change variance share > **0.50** (one-way ANOVA, method of moments); share exactly 0 kills only if G2 kills; zero total variance kills |
| D4 | G4 host invariance | untested on one host, which **caps the outcome at GO-WITH-FIXES**; metric = median absolute change-mean difference / pooled within-sd, tolerance 1.0, all 20 changes on a second host |
| D5 | G2 analytic reducibility | on change means (D7-eligible), take the **maximum** LOTO R² over B2–B6, point estimate; KILL if ≥ **0.80** |
| D6 | G5 cost | KILL if median `wall_s` of population final attempts > **180 s** |
| D7 | valid replicates | ≥ **4 of 5** |
| D8 | validity guard | ≥ **90 %** of 100 planned population runs valid |
| D9 | positive controls | **4 of 4** valid AND T1 > D1 floor; an invalid control counts as not above |

**Gate machinery** is `v4lib/gates.py`, with rules R1–R13; NOT_EVALUABLE yields NO-GO.

**Proposals vs decisions.** The plan's proposals (`docs/V4-PIVOT-AND-EXPANSION-PLAN.md` §43) were G1 30 %, G2 0.90,
G3 0.80, G5 180 s. D3 and D5 were made **stricter by amendment** (0.50 and 0.80), not in the original draft.

## 3. Chronology and provenance (Git is the only independent anchor)

| when / commit | event |
|---|---|
| 2026-09-14 13:24Z | prereg draft sha `2090aa2f…`; D1–D9 UNFROZEN |
| 13:31–13:39Z | smoke 1 (t05 cost-hi, drain-hi), engineering only |
| 13:41Z | §20 amendment, sha `a07c770a…` |
| 17:05Z | D1–D9 decided by Claude under the owner's delegation, **after smoke 1 existed**; smoke 1 cannot compute D1/G1–G3 statistics |
| `399b39b` 2026-09-15 | first Git commit of V4, including launch audit 1 (FINAL NO-GO: B1, shutdown invisible to route-event replay) |
| `4056099` | **Amendment A3**: link-state instrument, validity checks 7–13, no retry after change, fresh settle poll, T1_merge10ms, estimand, freeze |
| `702f1a0` | smoke 2 (9 labs) results; B1 marked resolved |
| `0cd6896` | first freeze (platform-dependent artifact digest; superseded) |
| `c1369ee`, `d2c0cf0` | digest fix, and a freeze anchored to `c1369ee`; approval sha of prereg A3 `a2d4a8b9…` |

**Previous Claude thread's final claim.** It said "FINAL GO" after d2c0cf0.
- **What it verified:** engineering validity, replay consistency, the freeze, and V2/V3 isolation.
- **What it did not verify:** positive-control signal magnitude. It explicitly avoided inspecting it.
- **Status:** **superseded** by the independent audit below.

## 4. Engineering smoke 2 — known values (ENGINEERING ONLY; not pilot evidence)

Source: `v4_transient/results/smoke2/SMOKE2-VALIDATION.json` (82/82 engineering checks), raw data in
`results/smoke2/raw/`.

| run | kind / topology | T1 | T1_merge10ms | T2 | FIB states | link events | wall_s |
|---|---|---|---|---|---|---|---|
| V4P-01 | positive t05_ring6 | **0.0** | 0.0 | **0.0** | 18 | 2 | 204.35 |
| V4P-02 | positive t13_bowtie7 | 4.97e-3 | 4.44e-3 | 0.444 | 39 | 2 | 262.47 |
| V4P-03 | positive t14_ladder8 | 5.73e-3 | 4.55e-3 | 0.455 | 67 | 2 | 239.54 |
| V4P-04 | positive t15_campus12 | **0.0** | 0.0 | **0.0** | 151 | 2 | 219.36 |
| V4N-01 | no-op t05 | 0.0 | 0.0 | 0.0 | 0 | 0 | 141.59 |
| V4C-05 | bh t05 | 0.0 | 0.0 | 0.0 | 1 | 0 | 151.02 |
| V4C-10 | bh t13 | 0.0 | 0.0 | 0.0 | 1 | 0 | 236.50 |
| V4C-11 | cost-hi t14 | 1.21e-4 | 0.0 | 0.218 | 57 | 0 | 227.51 (retry; attempt 1 NO_CONVERGENCE, 1,329 s) |
| V4C-18 | drain-hi t15 | 2.13e-4 | 0.0 | 0.190 | 105 | 0 | 420.56 |

**Implications. These are warnings, NOT gate evaluations, and must never motivate threshold changes.**
- **D9.** Two positive controls show no transient at all. If this reproduces in the pilot, D9 FAILS, so the pilot
  is NO-GO by construction and would be wasted compute.
- **G1/D1.** The non-zero population T1 values (1.2e-4, 2.1e-4) are below the D1 floor (6.944e-4), and vanish under
  the 10 ms merge. Blackhole changes give T1 = 0: their broken flows are steady-state and excluded by
  construction.
- **G5.** Population median wall time is 232.0 s (lower middle 227.51 s), against 180 s.
- **Convergence overrun.** A pre-change `NO_CONVERGENCE` took 1,317 s: the frozen `nrl.clab` loop checks its 180 s
  timeout only between polls.

## 5. Open questions the next audit must answer from raw evidence

Treat these as hypotheses to test; none is established.

**Why do V4P-01 and V4P-04 show T1 = T2 = 0?**
- **Timing: zebra re-installs before the flush.** Zebra/ospfd may install replacement routes before (or in the same
  instant as) the kernel's link-down flush. Compare route-event timestamps with the link-event timestamp in
  `results/smoke2/raw/SMOKE2-V4P-0{1,4}.rep1/attempt1/fib_monitor/*.log`.
- **Carrier-loss side not flushed.** Check the peer router's log: are its nhid routes flushed and re-installed with
  a gap, or replaced first?
- **ECMP rule hides partial loss.** The conservative rule may hide loss on redundant topologies (campus): a flow is
  broken only if ALL members are unusable. Is the shut link inside ECMP groups?
- **Flows broken in the final state are excluded.** Is every transiently broken flow also broken in the final state,
  so that r_broken_exact > 0? Check `features.r_broken_exact` for V4P-01/04 in `manifests/pilot_manifest.json`.
- **Positive-control construction.** A shutdown of the highest-betweenness link may have loss-free local
  repair/ECMP on these topologies. Is it a valid "known disruption"?
- **Instrument bug.** Compare the replay against `fib_polls.json` dumps taken inside the transient, and against the
  timeseries CSV. Do states exist where the replay should show broken flows?
- **Kernel/FRR ordering.** Are there link-down notifications before or after route deletion events, and does
  `event_order` handle identical timestamps correctly?

**G5.** Which phases drive wall time: deploy, convergence, capture_state or teardown? Is the smoke-1 → smoke-2
increase from topology size, A3 polling cost, or host load? Diagnose it; do not re-threshold.
