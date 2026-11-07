# V4 transient pilot — final launch audit

- **Date:** 2026-09-15.
- **Auditor:** Claude, acting as final implementation and scientific auditor.
- **Verdict: FINAL NO-GO.** One blocking instrument defect (B1) makes the pre-registered positive-control rule D9
  fail with certainty. That in turn makes the pilot NO-GO whatever the population shows.
- **Update (2026-09-15, later the same day):** B1 was resolved by amendment A3 and re-validated on real labs. See
  §6. This record is otherwise kept as it was written.
- **Enforcement:**
  - B1 is recorded as open in `manifests/AUDIT-BLOCKING-ISSUES.json`.
  - `run_pilot.py --plan pilot` and `tools/write_pilot_freeze.py` both refuse while it is open.
- **What was not done:**
  - no pilot run, and no pilot data;
  - no change to the scientific question, target, population, feature policy or D1–D9;
  - no V2/V3 file touched;
  - no smoke evidence modified.

## 1. Blocking issue

### B1 — shutdown positive controls are invisible to the FIB-event instrument

**Instrument.** T1 reconstructs each router's FIB from two sources (§1 step 2, §3):
- a `ip -4 route show` snapshot;
- `ip -ts monitor route` events.

**Positive controls.** All four are `shutdown` of one interface (§20).

**Evidence.** Unit checks in throwaway containers used the same WSL kernel, the pilot FRR image and the pilot daemons
file. No lab was deployed and no pilot change was measured. Files are in `audit/2026-09-15-instrument-unit-checks/`.

| check | observed |
|---|---|
| kernel, `ip link set v0 down` | IPv4 routes via v0 and the connected 10.9.0.0/30 are removed, and the monitor prints **no** IPv4 event |
| kernel, peer carrier loss | routes stay installed, flagged `linkdown`, with no event |
| FRR 8.4.1, vtysh `shutdown` | 10.7.0.0/24 via the shut interface disappears with no event; the production replay does not equal the final snapshot |
| FRR 8.4.1, static `blackhole` (control) | the event is emitted and parsed as blackhole; replay equals the final snapshot |

**Consequence.**
1. Every positive-control run fails validity check 4 (`replay_matches_final_snapshot`, §12).
2. Its transient loss is not visible to the replay either.
3. D9 needs 4 of 4 controls valid and above the floor, and an invalid control counts as not above. So D9 FAILS and
   §16 yields NO-GO.
4. The pilot therefore could not test what D9 is meant to test.

**Not affected.**
- The population mechanisms (cost, drain, blackhole) never change link state.
- Cost and drain were validated in the smoke labs.
- The blackhole path is validated by the unit check above.

**Why the audit does not fix it.** Every repair changes frozen scientific protocol:
- one route changes the FIB reconstruction and validity check (§1, §3, §12);
- the other changes the positive-control mechanism (§20, D9).

Either one needs an engineering smoke on a real lab. The user instructed the audit to stop and report instead.

**What must be resolved before launch:**
1. **Decide one of these, by logged amendment:**
   - (a) monitor link events and model kernel link-down semantics in the reconstruction for all runs: admin-down
     flushes routes, and linkdown next-hops do not forward; or
   - (b) replace the positive-control mechanism with one the instrument observes.
2. **Run an engineering smoke** that covers:
   - a positive control;
   - a blackhole change;
   - a no-op control.

   None of these three has ever run in a lab.
3. **Re-approve** (`tools/write_prereg_approval.py`).
4. **Close B1** in the register with a reference to the amendment.
5. **Commit V4 to Git.**
6. **Run `tools/write_pilot_freeze.py`**, then commit `manifests/PILOT-FREEZE.json`.

## 2. Fixed during the audit (no design change)

| # | lead / finding | fix | tests |
|---|---|---|---|
| F1 | Leads 1 and 3: approval authenticated only the pre-registration and decisions; V4 is untracked by Git | New `v4lib/freeze.py`. The runner verifies the frozen tree at start and before every attempt: all executing and analysis code, the imported nrl modules, config, pre-registration, approval, manifests, run plan, Batfish verdicts, every artifact file, and an empty audit register. New `tools/write_pilot_freeze.py` refuses unless the register is empty, approval passes, and every frozen file is Git-tracked and identical to HEAD. It records the commit. | `tests/test_freeze.py` |
| F2 | Lead 5: analysis bootstrap resampled rows, but §15 specifies a change-level bootstrap | `analyze_pilot.change_bootstrap` resamples whole changes. It gives identical draws on change means. It is descriptive only: under D5 (point estimate) no gate uses a CI. | `tests/test_analysis.py` |
| F3 | A lab left running after a crash (smoke run 1 precedent) would perturb later measurements | `run_pilot.host_clean`: refuse before any attempt if a containerlab-labelled container exists, running or stopped | `tests/test_runner.py` |

## 3. Verified correct (no change)

**Question and target.**
- T1 integrates broken_excess, i.e. flows broken now and not broken in the final state. Steady-state damage, which
  is v3's Batfish-computable r, is excluded by construction.
- r is used only as an instrument-validity check (§12.3).
- t0 is the start of the first push.
- A pre-t0 FIB event invalidates the run.
- Integration is piecewise-constant.
- After settling, broken_excess = 0, so the observation tail adds nothing.
- NOT_SETTLED runs are invalid, never truncated.

**Lead 7 (pre-change replay).** No pre-change replay defect was found:
- events before a router's snapshot are already in the snapshot;
- events between snapshot and t0 invalidate the run;
- re-applied events are idempotent;
- the replay is checked against the final snapshot.

The only replay defect found is B1.

**D1–D9 arithmetic and code.**
- **D1:** floor = max(pooled no-op maximum, 0.05/72); comparisons are strict.
- **D2:** 6/20 = 0.30 is not below 0.30, so it passes. The denominator is all 20 changes; D7-ineligible changes
  count as not above.
- **D3:**
  - The ANOVA is method-of-moments with n0 for unequal k.
  - Kill if the within-change share is > 0.50.
  - A share of 0 kills only with G2.
  - Zero total variance kills.
  - Reliability 0.83 and 0.75 at ICC 0.5 for 5 and 3 replicates checked.
- **D4:** untested, capped at GO-WITH-FIXES, so GO is unreachable (asserted in `test_gates`). The 0.43σ figure
  checked.
- **D5:** the maximum LOTO R² over B2–B6 must be ≥ 0.80 to kill.
- **D6:** median wall_s of population final attempts, killed if > 180.
- **D7:** at least 4 valid replicates.
- **D8:** at least 90/100, with planned runs as the denominator.
- **D9:** 4 of 4.

**Lead 4 (selection optimism in D5).** Taking the maximum of five LOTO R² values biases the baseline upward, which
makes a G2 kill easier. That is the conservative direction for a stopping rule. It cannot rescue the project or
inflate an ML claim.

**Baselines.**

| baseline | status |
|---|---|
| B2 | exact steady-state r, used as a linear proxy for transient T1 |
| B3 | exact analytic next-hop-change count (proxy) |
| B4 | RFC 5715 microloop upper bound |
| B5 | OLS combination (proxy) |
| B6 | graph proxies |

- All are computed from configurations before deployment.
- Folds are by topology, and OLS is fitted on training folds only.
- B1 means are per fold.

**Features.**
- `FEATURE_COLUMNS` plus the mechanism one-hot are all computed from configurations.
- None is an ID, role, order, telemetry, timing or label.
- The ML model is LOTO and never enters the decision.

**Design.**
- 4 topologies × the same 5 roles, so mechanism is crossed with topology.
- Seeded shuffled order.
- 10 no-op and 4 positive controls, excluded from population statistics by `kind`.

**Lead 6 (replicates).**
- Replicates are fresh deployments with no injected perturbation.
- They estimate run-to-run execution variability of this frozen protocol on this host. Claims must stay within that
  scope.
- Adding perturbations would be a design change, so none were added.

**Retries.**
- One retry, for failures before measurement or from infrastructure only.
- NOT_SETTLED and POST_CONFIG_MISMATCH are never retried.
- Every attempt is kept.
- A failed attempt's measurements are never used.

**Execution locks.** Before any attempt, the runner requires all of:
- the start token;
- approval hashes;
- the artifact-lock digest equal to the manifest;
- per-file artifact hashes at staging;
- the Batfish gate;
- (new) the freeze and the audit register;
- (new) a clean host.

**Isolation.** Verified by the test suite:
- `git diff HEAD` is empty for V2/V3;
- no file under data/, nrl/ or pipeline/ is modified;
- smoke evidence is byte-identical to the pre-D1–D9 snapshot.

## 4. Chronology — stated honestly (lead 2)

V4 has never been committed to Git. Everything below rests on file timestamps and hashes written by the implementer,
so it is **not independently verifiable**. The first independent anchor will be the freeze commit.

| UTC 2026-09-14 | event |
|---|---|
| 13:19:51 | crashed smoke run 1 (only its deploy status was read) |
| 13:24:58 | pre-registration draft, sha `2090aa2f…`. D1–D9 UNFROZEN; plan proposals G2 0.90, G3 0.80, G1 30 %, G5 180 s |
| 13:27:04 | manifest, run plan, artifact lock (`d84a9629…`) |
| 13:31:57–13:39:24 | validated smoke: 4 runs of 2 changes on 1 topology, plus failure injection; wall_s 103.95–131.17 s |
| 13:41:44 | §20 amendment, sha `a07c770a…` |
| 17:05:48 | D1–D9 decided by the implementer under the owner's delegation; pre-registration sha `bfbcbdec…`; approval written |

**What this means for claims:**
- **Amendments, not original registrations.** D1–D9, including D3 (0.80 → 0.50) and D5 (0.90 → 0.80), were
  decided after the smoke existed. They must be reported as amendments made before any pilot data, not as part of
  the original draft.
- **What the smoke could inform.** It had no no-op run, only 2 changes and 1 topology, so it cannot compute the D1
  floor, G1 share, G3 variance share or any LOTO R².
- **D6.** The smoke wall times could have informed D6, but D6 kept the plan's pre-smoke value of 180 s.

## 5. Limits a hostile reviewer will raise (not launch-blocking; they bound the claims)

1. **Single host.** G4 is untested, and at best the result is GO-WITH-FIXES.
2. **Four topology clusters.** LOTO R² and any CI are unstable, and the CIs are weak.
3. **Population selected at analytic extremes** (hi / mid / lo r). The G1 share is a measurability check, not an
   estimate of how common transient disruption is.
4. **Replicate variance is execution jitter only.** It does not cover timers, load or hardware.
5. **Observer load.** Polling every 2 s via `docker exec` runs during the transient.
6. **Probe loss is secondary** and does not enter the gates.

## 6. Resolution — amendment A3 and re-audit (2026-09-15)

**Git anchors:**
- `399b39b`: the pre-amendment state, including this audit;
- `4056099`: amendment A3, committed before engineering smoke 2 was run.

**Resolution of B1: the instrument was fixed, and the positive-control design was kept.** This was the smallest design
change, and it also makes T1 faithful to the kernel.
- **Instrument change:**
  - monitoring is now `ip -ts monitor link route nexthop`;
  - snapshots and polls now dump routes, link states and nexthop objects;
  - the replay applies kernel link semantics.
- **Kernel semantics, verified on real FRR 8.4.1 in a throwaway container** (`audit/.../a3_frr_*`):
  - administrative down flushes everything through the device;
  - carrier loss flushes nexthop objects, and with them every route installed through one (FRR's protocol routes);
  - routes without a nexthop object stay selected but discard traffic.
- **A correction the real check forced.** My first model of carrier loss (routes stay, flagged linkdown) was true only
  for nexthop-less routes. The real FRR check exposed this, and it was corrected before A3 was committed.

**Further defects found and fixed in A3:**
1. **Silent-change guards.**
   - Detection of nexthop objects replaced in place or deleted while in use.
   - Replay cross-check against every unambiguous in-transient FIB dump.
   - Monitor error lines invalidate a run.
2. **Window edges.**
   - A route or link event after t_end invalidates the run.
   - A missing snapshot invalidates the run.
   - The golden state must carry exactly the analytic flow count.
   - The container clock must be UTC.
3. **Outcome selection.** A failed attempt is no longer retried once the change has been applied (before A3,
   `ERROR`/`PUSH_FAILED` after the push were retried).
4. **Settle rule.** The OSPF verdict must come from an error-free poll that started after the last activity. Link
   events now count as activity.
5. **Descriptive robustness.** T1_merge10ms protects against cross-router timestamp-ordering artefacts.
6. **Estimand.** The replicate estimand is stated (§20); no perturbation is added.
7. **Leakage.** Mechanism is proven to be a function of the configuration diff for all 34 changes.
8. **Tests.** Freeze and runner tests made state-aware; smoke regression added (the A3 extraction reproduces every
   preserved first-smoke target exactly).

**Engineering smoke 2** (`results/smoke2/`, run on commit `4056099`; engineering only). Coverage:
- the shutdown positive control on all four topologies;
- a no-op control;
- blackhole changes on t05 and t13;
- cost-hi on t14 and drain-hi on t15.

Outcome:
- all 9 runs valid under all 13 checks;
- every admin-down and peer carrier-loss event captured;
- replay consistent with the in-transient polls;
- no-op null;
- 82/82 checks passed.

**Its target values were not inspected for, or used in, any decision.**

**Operational findings (not validity defects; nothing was changed because of them):**
- **Convergence overrun.** One pre-change `NO_CONVERGENCE` (t14, OSPF neighbours stuck in Loading) took 1,317 s. The
  frozen `nrl.clab.wait_for_convergence` checks its 180 s timeout only between polls, and hung `vtysh` calls stretch
  a poll. The failure happened before the change, so it was correctly retried, and the retry was valid. It extends
  wall-clock duration only; G5 uses final attempts (§11).
- **Longer lab wall time than in smoke 1** (outside the observation window). The frozen G5 threshold (D6, 180 s) is
  not revisited. G5 is a pilot gate, and a G5 KILL would be a legitimate result.
- **Batfish idle during the labs.** Batfish (Docker Desktop) was running but idle; about 6.5 GB of VM memory was
  available.

**Register.** `manifests/AUDIT-BLOCKING-ISSUES.json` now has `open: []`, and B1 is resolved with references to the
amendment and the evidence.
