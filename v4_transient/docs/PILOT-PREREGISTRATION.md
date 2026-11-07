# PILOT PRE-REGISTRATION — V4 transient-disruption feasibility pilot

- **Written:** 2026-09-14 (UTC), before any pilot run, and before any smoke-test **measurement** was inspected.
  The only smoke-test output looked at before this document was written was one `clab_deploy.json`
  status field, confirming non-root Containerlab deploy works.
- **Supersedes:** the earlier draft `PREREGISTRATION-PILOT.md` from the same day, removed so that only one
  pre-registration exists.
- **Scope:** this document governs only the 20 × 5 pilot in `v4_transient/`. It changes nothing in v2/v3.
- **Status (2026-09-14):** all decisions D1–D9 are **FROZEN**, before any pilot run (§18, §19). The values are
  in `config/pilot_decisions.json`, and the approval is in `manifests/PREREG-APPROVAL.json`. The pilot has
  **not** been run.
- **Amendment A3 (2026-09-15, before any pilot run):**
  - fixes the FIB instrument for link-state changes and closes further validity gaps (§1, §2, §3, §5, §12, §13,
    §17, §20);
  - D1–D9 values are unchanged;
  - logged in §18 and anchored in Git.
- **Amendments A4 and A5 (2026-09-15, after engineering smoke 2, before any pilot run; not part of the original
  pre-registration):**
  - A4 replaces the two positive controls whose shutdown link was a cut edge (T1 = 0 by construction) under a
    configuration-only rule, with a hard stop against further replacement;
  - A5 parallelizes runner work outside the observation window (cost only);
  - the research question, T1 and every D1–D9 value are unchanged;
  - logged in §18, anchored in Git; launch audit 2 is `docs/V4-LAUNCH-AUDIT-2.md`.

## 0. Status labels and how this document becomes binding

| label | meaning |
|---|---|
| **FROZEN** | fixed now, before observing any pilot result; may not change after pilot data exist |
| **UNFROZEN — REQUIRES DECISION BEFORE PILOT** | the plan only *proposes* a value, or specifies nothing; no value is chosen here |

**Gate thresholds were not taken from the plan unexamined.**
- `docs/V4-PIVOT-AND-EXPANSION-PLAN.md` §43 proposes G1 30 %, G2 0.90, G3 80 % and G5 180 s, and names a
  "noise floor" and a "tolerance" without defining them.
- Each was examined and decided in §§6–12 and §16 (D1–D9), with a rationale drawn only from the plan, this
  design and pre-existing v3 evidence.
- Where a proposal was scientifically inadequate, the stricter formulation was adopted and flagged.

**The pilot cannot start until all of the following hold** (enforced by `pilot/run_pilot.py --plan pilot`):
1. every `UNFROZEN — REQUIRES DECISION BEFORE PILOT` marker in this file has been replaced by a decision,
   recorded in the Amendment log (§18) with date and decider;
2. `manifests/PREREG-APPROVAL.json` exists with `"approved": true` and the SHA-256 of this file as finally amended;
3. the smoke-test engineering validation (§17) has passed;
4. the operator gives the explicit start command `--confirm-pilot START-20x5-PILOT`.

**The smoke test is engineering validation only.** None of its numbers were used to choose or adjust any
threshold, target or rule in this document.

---

## 1. Primary transient target — FROZEN

**T1 — transient disruption area**, in units of flow-fraction × seconds. Defined in three steps.

**1. Flow set.** Every ordered pair of endpoints (router loopbacks and hosts) whose golden forwarding
walk ends OK. This is the same flow set as v3's r (`v4lib/targets.flows`).

**2. Instantaneous state.**
- At t0 and after every kernel FIB event, the per-router IPv4 main-table FIB is reconstructed (`v4lib/fib.replay`)
  from:
  - the snapshot at monitor start (routes, link states, nexthop objects);
  - every monitored route and link event, in timestamp order.
- *(Amended A3)* Kernel link semantics are applied, because the kernel does not report them as route events
  (verified in `audit/2026-09-15-instrument-unit-checks/`):
  - an administratively down device flushes every route and next hop through it;
  - loss of carrier flushes the nexthop objects on the device, together with every route installed through them
    (FRR's protocol routes);
  - a route without a nexthop object whose every next hop is on a carrier-down device stays selected but discards
    traffic (BLACKHOLE);
  - an ECMP route keeps only its usable next hops.
- Each flow is walked with the frozen `nrl.flowmatrix.forwarding_path`.
- **Golden state** = the reconstructed state before the first event.
- **Final state** = the reconstructed state after the last event.

**3. Per-flow classification at time t.**
- **BROKEN:** terminal NO_ROUTE, LOOP or BLACKHOLE.
- **broken_excess(t)** = the fraction of carried flows that are BROKEN at t **and not BROKEN in the final state**.

**T1** = ∫ broken_excess(t) dt from t0 to t_end, integrated piecewise-constant (each value holds until
the next FIB event).
- **t0** = host clock at the start of the first device's configuration push.
- **t_end** = host clock when observation stops (§4).

**Why this is primary** (decided before data):
- Steady-state damage, which Batfish computes exactly, is subtracted by construction.
- It combines breadth (share of flows) with duration.
- Peak ignores duration, and duration ignores breadth.

**The primary target will not be replaced after pilot data exist**, including if it turns out degenerate.
A degenerate primary target is a pilot result, not a reason to switch targets.

## 2. Secondary targets — FROZEN (descriptive only; none can become primary)

| id | definition |
|---|---|
| T2 peak disruption | max over t ≥ t0 of broken_excess(t) |
| T3 disruption duration | end time (relative to t0) of the last interval with broken_excess(t) > θ, **θ = 0**; 0 if never |
| detour_area / detour_peak | area / max of the fraction of carried flows delivered on a path that is neither the golden nor the final path |
| T1_upper (sensitivity) | T1 computed with transiently UNDETERMINED flows counted as broken (§12) |
| T1_merge10ms (sensitivity, A3) | T1 with event timestamps rounded up to a 10 ms grid, so cross-router event orderings finer than 10 ms cannot create or remove transient states |
| probe_loss_frac_window | ICMP probe packets lost / sent in [t0, t_end), over the 6 host↔host pairs |
| probe_lost_packet_s_window | lost probe packets × probe interval |
| fib_settle_s | time of the last FIB event relative to t0 |
| first_fib_change_s | time of the first FIB event relative to t0 |
| n_fib_state_changes | number of distinct FIB event timestamps after the golden state |
| ospf_transitional_polls | OSPF neighbour polls showing any non-Full neighbour |
| r_final | steady-state affected fraction in the final state (validity use only, §11) |

**Why θ = 0:** it is the only duration threshold that needs no tuning. If a different θ is wanted, it
must be amended in §18 before the pilot.

## 3. Instruments and probe frequency — FROZEN

| instrument | setting |
|---|---|
| FIB monitor (primary; A3) | `ip -ts monitor link route nexthop` in every router container, event-driven. Microsecond timestamps from the shared WSL kernel clock (container TZ UTC, checked per run) |
| FIB snapshots (A3) | `ip -4 route show table main`, `ip -o link show` and `ip nexthop show`, per router, in one exec, at monitor start and after observation |
| packet probes (secondary) | busybox `ping -i 0.05 -W 1` over all 6 ordered host↔host pairs. Count = ceil((10 + 90 + 30) / 0.05) = 2,600. Send time of packet k = the midpoint of the probe-launch call + k × 0.05 s |
| OSPF neighbour poller | `show ip ospf neighbor json` on every router, cadence 2.0 s (low, to limit observer load) |
| FIB log polling (A3) | every 2.0 s. One exec per router reads the monitor log and dumps routes, links and nexthop objects. Used for settle detection and for the in-transient replay cross-check (§12). |
| capability evidence | `tools/capability_probe.sh` |

## 4. Measurement window — FROZEN

| parameter | value |
|---|---|
| pre-change baseline (instruments running, nothing pushed) | 10.0 s |
| change application | one `vtysh -c "configure terminal" -c …` per device; devices in sorted name order; t0 = start of the first push |
| minimum observation after t0 | 20.0 s |
| quiet period required after the last FIB event **and** after push end | 10.0 s |
| maximum observation after t0 | 90.0 s |

## 5. Convergence and settling definitions — FROZEN

- **Pre-change convergence:** frozen `nrl.clab.wait_for_convergence`. Converged when:
  - ≥ 45 s have elapsed since polling began;
  - no OSPF neighbour is in a non-Full state;
  - the FRR RIB has been byte-identical for 3 consecutive 5-s polls.

  Timeout 180 s, which gives `NO_CONVERGENCE`.
- **Pre-change binding check:** frozen `nrl.clab.verify_ospf_binding` against the golden scenario.
  A failure gives `LAB_INVALID` (S-020 race).
- **Post-change settled:** all three of the following hold at a poll:
  - t − t0 ≥ 20 s;
  - t − max(last route or link event, push end) ≥ 10 s;
  - the latest error-free OSPF poll that *started after* that last activity shows no non-Full neighbour (A3).

  If not reached by t0 + 90 s, observation stops and the run is `NOT_SETTLED`.

## 6. Noise-floor definition — FROZEN (D1, decided before the pilot; stricter than the plan)

**What the plan says:** §43 names a "no-change noise floor" but does not define it.

**What the pilot provides:** 10 no-change control labs (3, 3, 2, 2 per topology). Each re-pushes one
unchanged `ip ospf cost`.

Options considered in the draft of this document:

| option | floor | per-change comparator |
|---|---|---|
| (a) | maximum T1 over all valid no-op runs | replicate **median** T1 > floor |
| (b) | maximum T1 over all valid no-op runs | replicate **mean** T1 > floor |
| (c) | per-topology maximum of no-op T1 | replicate median T1 > own-topology floor |
| (d) | no-op mean + k × sd (k to be chosen) | replicate median or mean |

**Decision D1:**
- **Floor statistic:** option (a), the maximum T1 over all valid no-op control runs, pooled across topologies.
- **Comparator:** a change is above the floor if the **median** T1 of its valid replicates is strictly
  greater than the floor.
- **Metric:** T1 only. Probe loss remains a secondary, descriptive instrument (§2).
- **Resolution lower bound (stricter than the plan, applied always):**
  - The floor is never below **0.05 s / 72 flows = 6.944 × 10⁻⁴ flow-fraction·s**. That is one carried flow
    broken for one probe interval (§3), in the pilot topology with the fewest carried flows (t05_ring6,
    72 flows, an analytic design quantity from `manifests/pilot_manifest.json`).
  - Floor = max(maximum no-op T1, 6.944 × 10⁻⁴). It applies whether or not every no-op T1 is 0.

**Rationale:**
- **Why pooled maximum:** over 10 controls it is the most conservative empirical floor available.
  - Per-topology floors would rest on 2–3 runs.
  - Mean + k·sd assumes a symmetric noise distribution that 10 zero-inflated control values cannot support.
- **Why median:** one spiky replicate cannot make a change count as measurable.
- **Why the resolution bound:** an idempotent no-op installs no FIB change, so the empirical floor could be
  exactly 0. Without the bound, any single-flow microsecond artefact would count as "measurable". The bound
  ties measurability to the finest packet-level resolution the protocol has.

## 7. G1 — measurable — FROZEN (D2)

- **Plan text (proposal):** kill if "< 30 % of non-control changes above the floor".
- **Decision D2:** kill if fewer than **30 %** of the **20 population changes** are above the D1 floor.
  - The denominator is always all 20 changes.
  - A change with fewer valid replicates than D7 counts as not above the floor. It is never imputed
    (machinery rule R2).
- **Rationale:**
  - 30 % is the complement of the project's frozen degeneracy rule (ANALYSIS-PLAN-V3 §8: a target with more than
    70 % of values at a single value is degenerate), so the proposal is kept and is not a new number.
  - Using all 20 changes stops infrastructure losses from shrinking the denominator.

## 8. G3 — repeatable — calculation FROZEN, threshold FROZEN (D3; stricter than the plan)

**Calculation (FROZEN).** On the primary target T1, over valid population runs:

- One-way random-effects ANOVA, method of moments, with change as the group.
- With g changes, N runs, and k_i valid replicates in change i:
  - MSW = Σ_i (k_i − 1) s_i² / Σ_i (k_i − 1)
  - MSB = Σ_i k_i (mean_i − grand mean)² / (g − 1)
  - n0 = (N − Σ_i k_i² / N) / (g − 1)
  - σ²_between = max((MSB − MSW) / n0, 0)
  - σ²_within = MSW
- **within-change share** = σ²_within / (σ²_within + σ²_between)
- **ICC(1)** = σ²_between / (σ²_within + σ²_between)
- **reliability of a 5-replicate mean** = σ²_between / (σ²_between + σ²_within / 5)
- The same statistics are reported for T2 and T3, descriptively.

**Decision D3:**
- **Threshold:** kill if the within-change share is **> 0.50**, i.e. ICC(1) < 0.50. The plan proposed 0.80.
- **Why the plan value is inadequate:**
  - A within share of 0.80 is ICC(1) = 0.20, "poor" under the conventional ICC guideline (Koo & Li 2016,
    *J Chiropr Med* 15:155–163).
  - At ICC 0.20, the reliability of a 5-replicate mean is 0.56, and of the 3-replicate means planned for the
    v4 corpus (plan §43) it is 0.43. That caps any learned model below half of the change-level variance before
    features are considered.
  - ICC ≥ 0.50 keeps reliability ≥ 0.83 with 5 replicates and ≥ 0.75 with 3.
- **The plan's "or = 0 with G2 failing":** read literally. A within-change share of exactly 0 (deterministic
  target) kills only if G2 also kills. Determinism is not the same as being computable before deployment,
  and G2 tests the latter.
- **Total variance 0 (all T1 identical):** kill. A target with no variation cannot be learned or ranked.

## 9. G4 — host-invariant — FROZEN (D4); NOT TESTABLE IN THIS PILOT

- **Plan text (proposal):** kill if "median absolute difference > pre-registered tolerance" for the
  same change on two machines.
- **Hard fact:** this pilot has exactly **one** host (WSL2, 16 vCPU, 7.6 GB). **G4 cannot be measured
  in this pilot.**

**Decision D4:**
- **Metric** (for the required future two-host test): the median over changes of
  |change-mean T1 on host A − change-mean T1 on host B|, divided by the pooled within-change sd (σ_within, §8).
  It is scale-free, so the tolerance does not depend on the unknown magnitude of T1.
- **Tolerance:** **1.0** pooled within-change sd.
  - With no host effect, the difference of two 5-replicate means has sd √(2/5)·σ_within ≈ 0.63 σ_within, so the
    median absolute difference is ≈ 0.43 σ_within.
  - A host effect as large as the replicate noise itself fails.
- **Second host:** all **20** population changes, 5 replicates each (the same design as this pilot).
- **In this pilot:** G4 is **NOT TESTED**, and an untested G4 **caps the decision at GO-WITH-FIXES**. The
  required fix, before any corpus, is the two-host test above.
- **Rationale:**
  - An untested gate is not a pass, so GO is impossible.
  - It is also not evidence of failure, so an automatic NO-GO would confuse the absence of a test with a
    negative result.
  - The single-host drift proxy measures drift within one host, not invariance across hosts, so it is not
    accepted as a substitute. It is still reported descriptively (§15).

## 10. G2 — not reducible by an analytic baseline — FROZEN (D5; stricter than the plan)

**Decision D5:**
- **Unit of analysis:** the change means of T1, over D7-eligible changes.
- **Aggregator:** the maximum LOTO R² over B2–B6 (the plan's "strongest analytic baseline"). Baselines are
  frozen in §14.
- **Cross-validation:** leave-one-topology-out, 4 folds (confirmed).
- **Threshold:** kill if that R² is **≥ 0.80**, on the **point estimate**. The plan proposed 0.90.
- **Why the plan value is inadequate:**
  - Pre-existing v3 evidence (plan §22): over a non-learned baseline at R² 0.794, the learned increment was
    +0.054 with a CI touching 0 at n = 151, and was judged not defensible.
  - With an analytic R² of 0.89, the residual left for any learned model on change means is at most 0.11, further
    reduced by replicate noise. A corpus of the planned size could not establish an increment that small.
  - 0.80 leaves at least 0.20.
- **The other three choices** (change means rather than runs, maximum over five baselines, point estimate rather
  than the lower CI bound) each make the kill easier, never harder.
- A G2 kill is also a scientific NO-GO for the ML contribution (§16).

## 11. G5 — cost — metric and threshold FROZEN (D6)

- **Metric (FROZEN):** median `wall_s` over population runs, using each run's **final** attempt.
  `wall_s` runs from staging start to teardown end, as recorded by the runner.
- **Decision D6:** kill if the median exceeds **180 s** (the plan's proposal, kept).
- **Rationale:**
  - Plan §38 and §43 size the recommended corpus at 120 s per lab: ≈ 187 CPU-hours, ≈ 23 h on 10 dedicated workers.
  - At 180 s the same corpus needs ≈ 280 CPU-hours (≈ 35 h on 10 dedicated workers). That is the upper edge of the
    30–40 h run size the plan (§1, item 5) and the project brief treat as the expensive computation.
  - Beyond 180 s the corpus exceeds that size, and the plan justifies no stricter value.

## 12. Exclusion and retry rules — FROZEN (including D7 and D8)

**Statuses.**
- `OK`: measured, and all checks below attempted.
- Retryable execution failures:
  - `STAGING_FAILED`: artifact hash mismatch after copy;
  - `DEPLOY_FAILED`;
  - `CONTAINERS_MISSING`;
  - `NO_CONVERGENCE`;
  - `LAB_INVALID`: OSPF binding race;
  - `PUSH_FAILED`: a vtysh push returned non-OK;
  - `ERROR`: runner exception.
- Not retried, recorded as invalid:
  - `POST_CONFIG_MISMATCH`: the running config after the push does not match the candidate artifact;
  - `NOT_SETTLED`.

**Retry.** Exactly **one** retry per run for retryable statuses (the ANALYSIS-PLAN.md §14.1 policy).
Every attempt keeps its own directory, `results/pilot/raw/<run_id>/attempt<N>/`. Nothing is deleted.

*(Amended A3)* A failure is retried **only if the change was never applied**:
- The runner writes `change_applied.json` before the first push.
- After that point, `ERROR`, `PUSH_FAILED` and a crashed attempt (`INCOMPLETE_AFTER_CHANGE`) are final, and the
  run is invalid.
- Reason: an attempt that has observed part of the outcome must never be re-rolled.
- Separately, the runner refuses to start an attempt while any containerlab container exists (clean host).

**Run validity.** A run is **valid** only if its final attempt has status `OK` and **all** of these hold:
1. no FIB event between the initial snapshot and t0;
2. no UNDETERMINED flow in the final state;
3. |r_final − r_exact| < 1e-6, where r_exact is the analytic steady state, equal to Batfish on all 34
   changes and rounded to 6 decimals;
4. the replayed end state equals the final FIB snapshot on every router, in forwarding semantics, including
   link states (A3);
5. the post-change running config matches the candidate;
6. the run settled;
7. *(A3)* every initial and final snapshot succeeded on every router;
8. *(A3)* no route or link event after t_end;
9. *(A3)* the golden state carries exactly the analytic number of flows (`n_flows_carried_pred`);
10. *(A3)* the replay equals every unambiguous in-transient poll dump. A dump is ambiguous, and skipped, if one of
    that router's events falls within 10 ms before or 250 ms after it;
11. *(A3)* no nexthop object that routes use is replaced in place or deleted, since either would be a silent route
    change;
12. *(A3)* no monitor error line, such as a netlink receive error;
13. *(A3)* the container clock is UTC.

Invalid runs are excluded from target statistics but counted, by change and reason, in every report.

**Run order.** The fixed shuffled order (seed 20260914, `manifests/run_plan_pilot.json`) is executed as is.
Retries run immediately after the failed attempt.

**The two thresholds formerly open are now decided:**
- **Decision D7 — minimum valid replicates for a change: ≥ 4 of 5.**
  - It keeps at least 3 degrees of freedom for each change's sd, and a median that one outlier cannot move.
  - One isolated infrastructure failure does not by itself remove a change.
  - 5 of 5 would let lab flakiness masquerade as a scientific result; 3 of 5 gives a median of 3 values.
- **Decision D8 — pilot validity guard: at least 90 % of the 100 population runs valid** after the one retry.
  This is the stricter candidate.
  - v3 Phase 3 lost 0 of 186 labs after retry (plan §15), so losing more than 10 % indicates a protocol or
    instrument problem.
  - Failures could also concentrate in the most disruptive changes (for example `NOT_SETTLED`), which would
    bias every gate.

## 13. Missing and undetermined measurements — FROZEN

- **Final-state UNDETERMINED flows** (terminal NO_RIB, UNKNOWN_NH or MAX_HOPS): the run is invalid (§12).
- **Transiently UNDETERMINED flows during the window:** the run stays valid.
  - They are excluded from broken_excess in T1 (the primary definition) and counted separately
    (`undetermined_peak`).
  - T1_upper counts them as broken.
  - Both are reported for every run.
- **Missing or empty probe logs:** probe metrics are NaN and the run stays valid, because probes are secondary.
- **A missing FIB monitor log for a router:** treated as "no events on that router". Consistency check 4
  (§12) then catches any real gap as a replay mismatch and invalidates the run.
- **Failed OSPF polls:** recorded as they are. The settle rule uses the latest completed poll.
- **A change with fewer valid replicates than D7 (§12)** is reported as missing. It is never imputed.
- *(A3)* **Link-state semantics** are applied identically to every run (§1). Population mechanisms never change link
  state, so for them the computation is exactly the pre-A3 one; `tests/test_smoke_regression.py` reproduces every
  preserved smoke target.
- *(A3)* **ECMP with unusable members:** only usable members are walked. A flow counts as broken only when no
  member can forward, which can miss a partial loss but never invents one.

## 14. Feature whitelist, leakage bans and baseline definitions — FROZEN

**Whitelist.** Pre-deployment only, computed from golden + candidate configuration by `v4lib/analytic.py`:
- r_exact, r_broken_exact, r_rerouted_exact;
- n_fib_entries_changed, n_routers_changed;
- pml_flow_frac;
- n_devices_pushed, n_config_commands;
- n_routers, n_endpoints;
- changed_link_betweenness;
- golden_mean_path_len;
- mechanism (one-hot: cost, drain, blackhole). It is a function of the configuration diff, verified for all 34
  changes in `tests/test_core.py`.

**Banned from any model input:**
- transient telemetry of any kind (FIB events, probes, OSPF polls, convergence and settle times);
- any post-deployment measurement;
- measured T1, T2 or T3 in any form;
- labels and run statuses;
- execution results (wall time, retries, load average);
- generation or run order;
- change, run, experiment and replicate identifiers;
- topology identifier or name;
- the role label (cost-hi etc.);
- worker or host identity;
- random seeds.

Environment metadata is recorded for host analyses only, and is never a feature.

**Baselines.** All are evaluated leave-one-topology-out (4 folds). The gate unit is change means (§10, D5).
Both units are reported descriptively.

| id | definition |
|---|---|
| B0 | constant: training-fold mean |
| B1 | mechanism lookup: training-fold mean per mechanism, falling back to the training mean |
| B2 | ordinary least squares on r_exact |
| B3 | OLS on n_fib_entries_changed |
| B4 | OLS on pml_flow_frac |
| B5 | OLS on [r_exact, n_fib_entries_changed, pml_flow_frac, n_devices_pushed] |
| B6 | OLS on [changed_link_betweenness, golden_mean_path_len, n_routers] |
| ML | RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=0) on the full whitelist; **feasibility only**, no hyperparameter search |

**What the ML comparison shows.** ML is only ever compared with the strongest analytic baseline (§10).
A nonzero ML R² by itself is not evidence of usefulness.

## 15. Statistical summaries — FROZEN

- **Per population change, for T1, T2, T3, detour_area, probe_lost_packet_s_window and fib_settle_s:**
  mean, median, sd (ddof 1), CV (sd/mean, only when mean > 0), min, max, and n valid.
- **Variance components:** as §8, for T1 (gate) and T2/T3 (descriptive).
- **Distribution:** run-level share of T1 = 0, mean, median and max, plus change-level histograms.
- **Baselines:** LOTO R² (pooled over held-out predictions), MAE, and a change-level bootstrap 95% CI
  (2,000 resamples, seed 20260914). With only 4 topology clusters, the CI is stated as weak.
- **ML − strongest analytic:** ΔR² with a paired bootstrap CI (same resamples).
- **Host and timing:** Spearman ρ with a permutation p-value (2,000 permutations) for:
  - replicate residuals (T1 − change mean) against run order, pre-run 1-min load average and wall-clock start;
  - no-op T1 against run order;
  - probe lost packet-seconds against T1.

  Convergence-time median, sd and range are also reported.
- **Positive controls:** T1, T2 and T3 per positive-control run, reported against the noise floor (§6).
- **Validity:** counts per status and per failed check, by change.

**No multiple-comparison correction.** None of these analyses is confirmatory; the gates are the only
decisions. This is stated here so it is not decided later.

## 16. Decision logic — FROZEN (structure and inputs D1–D9)

The decision is exactly one of **NO-GO**, **GO-WITH-FIXES** and **GO**, evaluated in this order.

1. **NO-GO** if any of:
   - the pilot validity guard fails (§12, D8);
   - G1 kills (§7);
   - G3 kills (§8);
   - G2 kills (§10), which is also explicitly a scientific NO-GO for the ML contribution;
   - G5 kills (§11);
   - **Decision D9 — instrument sensitivity** fails. All **4 of 4** positive-control runs must be valid and
     above the D1 floor, and an invalid positive control counts as not above. This is the stricter candidate.
     Each positive control is a hard shutdown of the highest-betweenness link, the most disruptive event in the
     design. An instrument that misses it on any topology has a blind spot exactly where the study measures,
     and accepting 3 of 4 would tolerate that blind spot.
     *(Amended A4, after smoke 2)* The control is now the shutdown of the highest-betweenness link whose removal
     keeps every carried flow deliverable (§20). A partitioning shutdown causes only steady-state loss, which T1
     excludes by definition, so it cannot test transient sensitivity. The 4-of-4 rule, the floor and the comparator
     are unchanged.
2. **GO-WITH-FIXES** if step 1 did not fire and any of:
   - G4 was not tested (§9, D4: always the case in this single-host pilot);
   - a fixable protocol defect was found and documented, one that does not invalidate the pilot's measurements.
3. **GO** only if every gate G1–G5 was **tested** and passed, and no protocol defect was found. In this
   single-host pilot GO is therefore unreachable. The best attainable decision is GO-WITH-FIXES.

**Computational rules.** The rules R1–R13 in `v4lib/gates.py` (listed in `docs/D1-D9-DECISION-SCHEMA.md` §4)
are adopted as part of this freeze. In particular, a gate whose inputs are undefined is NOT_EVALUABLE and
yields NO-GO.

**ML cannot move the decision.** ML results can never upgrade a decision. An ML LOTO R² below the
strongest analytic baseline is reported but is not a gate.

**The large corpus never starts automatically.** No outcome of this pilot, including GO, starts the
24/48-topology corpus; that needs a separate decision and a separate pre-registration.

## 17. Smoke test — engineering validation only

- **Plan:** `manifests/run_plan_smoke.json`, with V4C-01 (cost-hi) and V4C-03 (drain-hi) on t05_ring6,
  2 replicates each. There is also one deliberate failure-injection run that exercises the retry path
  without touching lab state.
- **Output location:** `results/smoke*/`.
- **Never used in pilot analysis**, and never used to set or adjust anything in §§1–16.

**It validates only:**
- Batfish PASS gating: population changes must be SPEC-PASS before a run is allowed;
- non-root deployment;
- telemetry collection;
- preservation of raw time series;
- target computation;
- run IDs, replicate IDs and manifest linkage;
- failed-run handling and attempt preservation;
- that no v2/v3 data or code is modified.

**Engineering smoke 2 (A3)** validates the amended instrument on real labs, using exactly what the first smoke
never ran.
- **Plan:** `manifests/run_plan_smoke2.json`, built by `pilot/build_smoke2.py`, one run each:
  - the shutdown positive control of all four topologies;
  - one no-op control;
  - blackhole changes on t05 and t13;
  - cost-hi on t14 and drain-hi on t15.
- **Validation:** `analysis/validate_smoke2.py` checks:
  - status;
  - every §12 validity check;
  - capture of the admin-down and peer carrier-loss events;
  - replay against in-transient polls;
  - the no-op null;
  - code provenance.
- **Use of results:**
  - its target values are engineering-only and are not pilot data;
  - no check depends on their size;
  - they were not used to set or change anything in §§1–16.
- **Timing:** smoke 2 runs only after A3 is committed.

**Engineering smoke 3 (A4, A5)** revalidates the amended positive controls and the amended runner on real labs.
- **Plan:** `manifests/run_plan_smoke3.json`, built by `pilot/build_smoke3.py`, one run each (16 runs): the four pilot
  positive controls (including the A4 replacements), the two retired controls (descriptive), a no-op on t05 and on
  t15, the four smoke-2 population scenarios, and cost-mid on every topology.
- **Validation:** `analysis/validate_smoke3.py`, against the acceptance criteria and hard stop fixed in
  `docs/V4-LAUNCH-AUDIT-2.md` §3–§4 (Git commit `b165c23`) before smoke 3 existed.
- **Use of results:** engineering only; not pilot data; nothing in §§1–16 is set or changed from them.
- **Timing:** smoke 3 runs only after A4 and A5 are committed.

## 18. Amendment log

Any change to this file must be logged here with UTC date, decider and reason, before the pilot.

| UTC | decider | change | reason |
|---|---|---|---|
| 2026-09-14 (after the validated smoke runs) | implementer (Claude) | added §20, population and design | The section was omitted when this file superseded the earlier draft. Its content is transcribed from `pilot/build_pilot.py`, `manifests/pilot_manifest.json` and `manifests/run_plan_pilot.json`. Those were built before any validated smoke run and are unchanged (artifact lock digest `d84a9629…`). No target, threshold, rule or decision was changed, and no smoke number was used. |
| 2026-09-14 (before any pilot run) | implementer (Claude), under explicit delegation from the project owner | decided and froze D1–D9 in §6–§12 and §16. Added the D1 resolution floor as an always-applied lower bound (schema field `minimum_resolution_floor_scope`). Added the explicit start confirmation (§0 item 4). Adopted computational rules R1–R13. Updated §0, §13, §14 and §19 wording. | The project owner instructed that D1–D9 be determined from this document and the V4 plan, not from data. Every value is justified from the plan, this design and pre-existing v3 evidence; no smoke-test or pilot outcome was consulted. Stricter than the plan: D1 (floor lower bound), D3 (0.50 not 0.80), D5 (0.80 not 0.90), D8 (90 %), D9 (4 of 4). Kept from the plan: D2 (30 %), D6 (180 s). D4 records that G4 is untestable here. The primary target, feature whitelist, population and measurement protocol are unchanged. Values: `config/pilot_decisions.json`; hashes: `manifests/PREREG-APPROVAL.json`, `manifests/PREREG-FROZEN-RECORD.json`. |
| 2026-09-15, before any pilot run. The Git commit of this amendment is the timestamp anchor; the pre-amendment state is commit `399b39b` | implementer (Claude), under the project owner's explicit 2026-09-15 authorization to fix and amend V4 | **Amendment A3:** (1) link and nexthop-object monitoring, with kernel link-down semantics in the FIB reconstruction (§1, §3, §13); (2) in-transient FIB polls cross-checked against the replay, and validity checks 7–13 (§12); (3) retry only before the change is applied, plus the clean-host guard (§12); (4) settle rule uses a fresh OSPF poll, and link events count as activity (§5); (5) descriptive T1_merge10ms (§2); (6) engineering smoke 2 (§17); (7) replicate estimand stated (§20); (8) Git-anchored execution freeze and launch-audit register enforced by the runner, and the §15 change-level bootstrap implemented as written (it previously resampled rows). | The launch audit of 2026-09-15 found **B1**: the shutdown positive controls are invisible to a route-event replay, because the kernel flushes routes on link down without events (verified in throwaway containers). As a result D9 would have failed for an instrument reason. The other items close silent-change, outcome-selection and provenance gaps found in the same audit. **Unchanged:** research question, target definitions (flows broken per the kernel FIB), population, controls, features, baselines, and all D1–D9 values and gate rules. Fixing the instrument was preferred over replacing the positive control because it changes the design least and also makes T1 faithful to the kernel. No pilot data exist; smoke 2 had not been run when A3 was written. |
| 2026-09-15, **after engineering smoke 2**, before any pilot run. Issue opened in Git commit `b165c23` (diagnosis, rule and hard stop fixed there before implementation); the Git commit of this amendment is the timestamp anchor | implementer (Claude), under the project owner's explicit 2026-09-15 instruction to resolve launch-audit-2 blockers without changing the question, T1, D1–D9, population or thresholds | **Amendment A4 — positive-control selection (§16, §20). Not part of the original pre-registration.** Launch audit 2 (`docs/V4-LAUNCH-AUDIT-2.md`) found that the frozen rule "shutdown of the highest-betweenness link" picks a **cut edge for carried flows** on t05_ring6 (coreb–edgeb) and t15_campus12 (corea–coreb). Every flow such a shutdown breaks stays broken in the final state, so T1, which subtracts final-state breakage (§1), is 0 **by definition**, and D9 would fail by construction on every pilot run. **New rule:** shut the highest-betweenness link among links whose removal leaves every golden-carried flow deliverable (analytic r_broken = 0), same tie-break. Result: t05 corea–wan1 (new V4P-05), t15 coreb–distb1 (new V4P-06); t13 and t14 unchanged. The retired V4P-01 and V4P-04 stay in the manifest as `control_positive_retired`, with artifacts and smoke-2 evidence untouched, and are never run in the pilot; the replacements take their run-order slots, so every other run keeps its seeded position. **Disclosure:** written after every smoke-2 value was known, including T1 = 0 for V4P-01/04 and T1 ≈ 5e-3 for the non-partitioning V4P-02/03. The rule uses only the frozen topology and analytic model; the replacement links had never been measured when it was written. **Hard stop:** smoke 3 is the single revalidation. If V4P-05 or V4P-06 (or V4P-02/03 under the A5 runner) is invalid or not strictly above max(6.944 × 10⁻⁴, every valid smoke-3 no-op T1), V4 is NO-GO and no further positive-control replacement or rule change is permitted under this pre-registration. In the pilot, D9 applies as frozen. | The original rule's stated purpose (§16: an instrument that misses the most disruptive event has a blind spot) cannot be tested by a partitioning shutdown under the frozen T1; the instrument did record the whole disruption in smoke 2 (peak broken_total = r_final_broken). Choosing a non-partitioning link is the smallest change that restores the control's purpose without touching T1, D1, D9 or the population. **Unchanged:** research question, all targets, D1–D9 values and rules, population, no-op controls, features, baselines, protocol. |
| 2026-09-15, **after engineering smoke 2**, before any pilot run; same anchors as A4 | implementer (Claude), same instruction | **Amendment A5 — runner performance (engineering; §11 cost only).** Launch audit 2 found smoke-2 population wall times of 151–421 s (median 232.0 s) against the frozen D6 180 s, dominated by serial `docker exec` calls outside the observation window. The runner now performs, across routers or host pairs in parallel and phase by phase: the pre-change OSPF-binding check, monitor start, reference snapshot and probe start; and after t_end the monitor and probe reads, final snapshot and state capture (`nrl.clab.capture_state` called per router, unmodified). **Unchanged, pinned by hash in `tests/test_runner_parallel.py`:** `nrl.clab.wait_for_convergence`, the 10 s baseline, the push, the observation loop and its 2 s polls, the OSPF poller, the serial instrument stop, all §3–§5 parameters, extraction, replay, validity checks and targets; `nrl/` stays read-only. **Disclosed side effect:** after t_end the final snapshot of each router is taken sooner after its monitor stops than under the serial runner (a shorter interval in which a late route change would be caught as a replay mismatch, check 4); the settle rule (§5) is unchanged. **Disclosure:** motivated by smoke-2 runtimes. D6 (180 s, median over population final attempts) is not changed; if smoke 3's population median exceeds it, the issue stays open and V4 is NO-GO. | Wall time outside the window measures implementation overhead, not the protocol; removing it lowers the real cost of a corpus, which is what G5 guards. No measured quantity, window, resolution or check is reduced. |

## 20. Population and design — FROZEN (fixed in `pilot/build_pilot.py` before any measurement)

**Topologies.** Frozen v3 designs `t05_ring6`, `t13_bowtie7`, `t14_ladder8`, `t15_campus12`: four shapes, 6–12 routers.
Topology identity is never a feature.

**Population.** 5 changes per topology, 20 in total. Each must be Batfish SPEC-PASS under the frozen suite 1.1.0
(P01, P02, P05, P07, P08). Verified in `manifests/batfish_check.json`: 20/20 PASS. Roles are chosen by analytic
steady-state r, with ties broken by the target's string form:
- `cost-hi`: one link, cost ×20 at both ends, highest r;
- `cost-mid`: same, r closest to the median of the remaining non-zero values;
- `drain-hi`: every link of one router, cost ×20 at both ends, highest r;
- `drain-lo`: same, lowest non-zero r;
- `bh`: router-loopback /32 static blackhole, highest r.

**Replicates and controls.**
- 5 fresh-deployment replicates per population change.
- 10 no-change controls (3, 3, 2, 2 per topology). Each re-pushes an unchanged `ip ospf cost`; 1 run each.
- 4 positive controls: shutdown of the highest-betweenness link, 1 run each. They are Batfish SPEC-FAIL by
  design (P08) and **outside the population**.
  - *(Amended A4, after smoke 2; not part of the original design)* the link is the highest-betweenness link whose
    removal leaves every golden-carried flow deliverable (analytic r_broken = 0), same tie-break: t05 corea–wan1
    (V4P-05), t13 b1–mid (V4P-02, unchanged), t14 l2–l3 (V4P-03, unchanged), t15 coreb–distb1 (V4P-06). The originally
    selected cut edges, V4P-01 (t05 coreb–edgeb) and V4P-04 (t15 corea–coreb), are retired: kept in the manifest as
    `control_positive_retired`, never run in the pilot. Batfish SPEC-FAIL with r_match is required for all of them
    (`manifests/batfish_check.json`, checked by `tests/test_controls_a4.py`).

**Run order.** 114 runs shuffled with seed 20260914 (`manifests/run_plan_pilot.json`).

**Deviation from plan §43, fixed before data.**
- **What:** the plan lists the mechanisms "cost, drain, shutdown, blackhole".
- **Why:** under the frozen SPEC, shutdown fails P08 in 100% of cases (`nrl/repairs_v3.spec_pass`).
- **Effect:** shutdown is therefore a positive control, and the population mechanisms are cost, drain and blackhole.

**Replicate estimand (stated in A3; the design is unchanged).** A replicate is an independent fresh deployment of
the same frozen artifact, run in the seeded shuffled order.
- **What the replicate mean estimates:** the expected T1 of that change under this protocol on this host.
- **What the within-change variance (G3) captures:** run-to-run execution variability, namely:
  - host scheduling;
  - `docker exec` latency between device pushes;
  - FRR SPF and flooding timing;
  - the phase of the change relative to protocol timers.
- **Why no controlled perturbation is added:** the change is applied after convergence detection at a time that is
  not synchronised to OSPF timers. Adding artificial jitter would inject variance the estimand does not call for.
- **What the replicates do not estimate:** variability across hosts (G4), timer configurations or load, so no claim
  about those is made.

## 19. Decisions D1–D9 (frozen before the pilot)

| # | decision | value | vs plan | section |
|---|---|---|---|---|
| D1 | noise floor | max T1 over all valid no-op runs; replicate median; T1 only; lower bound 0.05 s / 72 flows = 6.944 × 10⁻⁴ applied always | stricter (plan undefined) | §6 |
| D2 | G1 | kill if < 30 % of all 20 population changes above the floor | kept | §7 |
| D3 | G3 | kill if within-change share > 0.50; "= 0" kills only if G2 kills; zero total variance kills | stricter (plan 0.80) | §8 |
| D4 | G4 | metric: median abs change-mean difference / pooled within-sd; tolerance 1.0; second host all 20 changes; **untested here**, caps at GO-WITH-FIXES | untestable in this pilot | §9 |
| D5 | G2 | change means, max LOTO R² over B2–B6, point estimate; kill if ≥ 0.80 | stricter (plan 0.90) | §10 |
| D6 | G5 | kill if median wall_s > 180 s | kept | §11 |
| D7 | minimum valid replicates | ≥ 4 of 5 | candidate | §12 |
| D8 | validity guard | ≥ 90 % of 100 population runs valid | stricter candidate | §12 |
| D9 | positive-control sensitivity | 4 of 4 valid and above floor; invalid counts as not above | stricter candidate | §16 |
