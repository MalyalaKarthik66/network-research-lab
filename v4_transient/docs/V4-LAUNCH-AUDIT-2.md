# V4 launch audit 2 — positive-control construction (D9) and runner cost (G5)

- **Date:** 2026-09-15 (UTC), after engineering smoke 2 and before any pilot run.
- **Auditor:** Claude, independent readiness audit requested by the project owner, superseding the previous thread's
  "FINAL GO".
- **Status when written:** FINAL NO-GO. Blocking issues **B2** and **B3** opened in `manifests/AUDIT-BLOCKING-ISSUES.json`.
- **Chronology:** this document and the register entries are committed **before** any fix is implemented and before
  engineering smoke 3 exists. The remedy rules, the hard stop and the smoke-3 acceptance criteria below are therefore
  fixed before any new measurement.
- **What was already known when this was written:** every smoke-2 value, including the T1 values of all four positive
  controls and all runtimes. This is stated so no later reader assumes otherwise.

## 1. B2 — two positive controls are structurally incapable of positive T1

**Rule as frozen (§20, `pilot/build_pilot.py`):** shut the highest-betweenness link of each topology.

**Finding.** On t05_ring6 and t15_campus12 that link is a **cut edge for carried flows**:

| control | link | betweenness | analytic r_broken / r_rerouted after removal | why |
|---|---|---|---|---|
| V4P-01 t05_ring6 | coreb–edgeb | 0.500 | 0.500 / 0.000 | edgeb (hostb, hostc) has a single uplink |
| V4P-02 t13_bowtie7 | b1–mid | 0.444 | 0.000 / 0.444 | alternate path exists |
| V4P-03 t14_ladder8 | l2–l3 | 0.455 | 0.000 / 0.455 | alternate path exists |
| V4P-04 t15_campus12 | corea–coreb | 0.533 | 0.533 / 0.000 | the only core–core link |

T1 counts a flow only while it is broken **and not broken in the final state** (§1). Every flow a cut-edge shutdown
breaks stays broken; no other flow's route changes. Hence T1 ≡ 0 for V4P-01 and V4P-04 **by definition**, on every
possible run. This follows from `r_rerouted_exact = 0`, a pre-deployment value present in
`manifests/pilot_manifest.json` since commit `399b39b`.

**Raw-evidence confirmation (smoke 2, recomputed in memory, no file written):**
- V4P-01: peak `broken_total` 0.500 = `r_final_broken` 0.500; T1 = T2 = 0; valid; 24 in-transient poll checks.
- V4P-04: peak `broken_total` 0.533 = `r_final_broken` 0.533; T1 = T2 = 0; valid; 36 in-transient poll checks.
- Monitor logs: the link events are captured and the deleted routes are never re-added.

**Classification:** not an instrument bug (the instrument recorded the whole disruption). It is an invalid control
construction caused by a topology interaction: under the frozen T1, a partitioning shutdown cannot be a positive control
for *transient* disruption. D9 would fail by construction. Launch audit 1 (B1) described D9 as failing "for an
instrument reason"; that was incomplete, since two of four controls would have failed D9 regardless.

**Also by construction (disclosed, not a defect):** all four `bh` population changes have `r_rerouted_exact = 0`, so
their T1 is structurally 0. G1 can reach at most 16 of 20 changes.

## 2. B3 — runner overhead outside the observation window

Smoke-2 population wall times: 151.02, 227.51, 236.50, 420.56 s, median **232.0 s** against the frozen 180 s (D6).
Engineering only, not a G5 evaluation.

Phase decomposition from `run.json` and snapshot timestamps (s):

| run | convergence | baseline + observation | exec overhead outside the window | wall |
|---|---|---|---|---|
| smoke 1, t05 (pre-A3) | 45–65 | 31–35 | ~27–33 | 104–131 |
| smoke 2 V4C-05, t05 bh | 54 | 36 | ~60 | 151 |
| smoke 2 V4C-10, t13 bh | 63 | 38 | ~136 | 237 |
| smoke 2 V4C-11, t14 cost-hi | 67 | 32 | ~128 | 228 |
| smoke 2 V4C-18, t15 drain-hi | 121 | 40 | ~260 | 421 |

The overhead is serial `docker exec` calls that do not measure anything inside the window: OSPF-binding check
(2/router), monitor start (2/router), snapshots (1/router, twice), probe start (2/pair), instrument stop, monitor and
probe reads, and `nrl.clab.capture_state` (6/router; 72 serial calls on campus12). Host load average was 1–3 on 16 vCPU.
The frozen protocol time (convergence + baseline + observation) is ~90–160 s.

## 3. Remedies fixed before implementation

### A4 — positive-control selection (minimum change)

- **Rule:** the positive control of a topology is the administrative shutdown, on one end, of the link with the highest
  golden link betweenness **among links whose removal leaves every golden-carried flow deliverable**
  (`Fabric.predict(removed=[link])["r_broken"] == 0`). Ties are broken exactly as before (first maximum in sorted link
  order).
- **Inputs:** the frozen topology specification and analytic model only. No lab value, no smoke value, no T1.
- **Resulting selections (derivable now, before any run):** t13 b1–mid and t14 l2–l3 (unchanged); t05 **corea–wan1**
  (0.444, tied with coreb–wan1, first in sorted order); t15 **coreb–distb1** (0.448).
- **Provenance:** the retired controls V4P-01 and V4P-04 remain in the manifest as `control_positive_retired` with
  their artifacts and smoke-2 evidence untouched. The replacements get new IDs (V4P-05, V4P-06) and occupy the retired
  controls' positions in the run list, so the seed-20260914 run order of all other 112 runs is unchanged.
- **Unchanged:** research question, T1 and all targets, D1–D9 values and rules, population, no-op controls, features,
  baselines, observation protocol.
- **Batfish:** the replacement controls must be Batfish SPEC-FAIL (as every positive control) with r_match; the 34
  existing verdicts must reproduce.

### A5 — runner performance (engineering only)

- Parallelize, across routers or host pairs, the `docker exec` phases that lie **outside** [t_baseline_start, t_end]:
  pre-change OSPF-binding check, monitor start, initial snapshot, probe start; post-window instrument stop, monitor and
  probe reads, final snapshot, state capture (`nrl.clab.capture_state` called per router; `nrl/` stays read-only).
- Phase order is preserved (all monitors started before any snapshot; all instruments stopped before any read; reads
  before the final snapshot). Per-router command order is preserved.
- **Not changed:** `nrl.clab.wait_for_convergence` (frozen §5), the 10 s baseline, the push, the observation loop,
  the 2 s polls, the OSPF poller, all frozen parameters, extraction, replay, validity checks and targets.
- Regression tests must pin the A3 observation-window code by hash.

### Hard stop against control shopping

- Smoke 3 is the **single** revalidation of the A4 controls.
- If V4P-05 or V4P-06 is invalid in its final attempt, or its T1 is not strictly above the engineering floor
  (max of the D1 lower bound 6.944e-4 and every valid smoke-3 no-op T1), **B2 stays open and V4 is NO-GO**. No further
  positive-control replacement or rule change is permitted under this pre-registration; the shutdown positive-control
  design would be declared inadequate for this T1.
- The same criterion applies to the unchanged V4P-02 and V4P-03 under the A5 runner (a failure there is treated as a
  runner regression: NO-GO).
- In the pilot itself D9 applies as frozen (4 of 4, strict, invalid counts as not above).

## 4. Engineering smoke 3 — plan and acceptance criteria (fixed now)

**Runs (one each, fixed order):** V4P-05 (t05), V4P-06 (t15), V4P-02, V4P-03, retired V4P-01, retired V4P-04,
V4N-01 (t05 no-op), V4N-09 (t15 no-op), V4C-05 (t05 bh), V4C-10 (t13 bh), V4C-11 (t14 cost-hi), V4C-18 (t15 drain-hi),
and cost-mid on every topology (V4C-02, V4C-07, V4C-12, V4C-17). The first ten non-control runs repeat smoke 2 so the old
and new runners are compared on the same scenarios; cost-mid adds a second population run per topology so the runtime
sample is balanced by topology, like the pilot.

**Acceptance (all required to resolve B2 and B3):**
1. Every run's final attempt is valid under all 13 §12 checks; code hashed at run time equals the committed code.
2. Admin-down and peer carrier-loss events are captured for every shutdown run; replay consistent with in-transient
   polls; both no-op runs show no FIB state change and no link event.
3. Hard-stop criterion above for V4P-02, V4P-03, V4P-05, V4P-06.
4. Retired V4P-01 and V4P-04: descriptive prediction T1 = 0 and peak `broken_total` = `r_broken_exact` (a failure is
   investigated, not used to select anything).
5. **Runtime:** median `wall_s` of the 8 population final attempts ≤ 180 s, the frozen D6 threshold unchanged; per-topology
   values reported. Otherwise B3 stays open and V4 is NO-GO.
6. Smoke 3 values are engineering-only: they are not pilot data, and no gate or threshold is set or changed from them.

**Then:** WSL preflight (approval, freeze, artifact digest, clean host, register, Batfish, containerlab, Python
environment, commit, no pilot state, runner refuses without token) before any GO/NO-GO statement.

## 5. Results (added after smoke 3; everything above was committed in `b165c23` before it)

**Implementation:** Git commit `cfa0d83` (A4, A5, pre-registration §18 rows, re-approval, Batfish check, tests). Offline
suites 10/10 pass (561 checks, including the new `test_controls_a4.py` and `test_runner_parallel.py`).

**Batfish (`logs/batfish_check_A4.log`):** verdict OK over 36 changes; V4P-05 and V4P-06 SPEC-FAIL (P08) with r_match;
the 34 pre-A4 verdicts reproduce exactly (digest test).

**Engineering smoke 3** (`results/smoke3/`, run on `cfa0d83`, 16/16 runs OK on the first attempt, 16/16 valid under all
13 checks; `SMOKE3-VALIDATION.json` 153/153 acceptance checks).

| run | kind | T1 | T1_merge10ms | T2 | wall_s (smoke 2 → smoke 3) |
|---|---|---|---|---|---|
| V4P-05 t05 (A4) | positive | 4.931e-3 | 4.444e-3 | 0.444 | – → 116.09 |
| V4P-06 t15 (A4) | positive | 5.304e-3 | 8.952e-3 | 0.448 | – → 162.14 |
| V4P-02 t13 | positive | 4.982e-3 (smoke 2: 4.965e-3) | 4.444e-3 | 0.444 | 262.47 → 121.69 |
| V4P-03 t14 | positive | 5.237e-3 (smoke 2: 5.734e-3) | 6.818e-3 | 0.455 | 239.54 → 141.33 |
| V4P-01 t05 (retired) | descriptive | 0 | 0 | 0 | 204.35 → 117.78 |
| V4P-04 t15 (retired) | descriptive | 0 | 0 | 0 | 219.36 → 189.65 |
| V4N-01 t05, V4N-09 t15 | no-op | 0, 0 | 0, 0 | 0, 0 | 141.59 → 123.86; – → 156.43 |
| V4C-05 t05 bh / V4C-10 t13 bh | population | 0 / 0 | 0 / 0 | 0 / 0 | 151.02 → 121.70; 236.50 → 131.03 |
| V4C-11 t14 cost-hi | population | 1.849e-4 (smoke 2: 1.21e-4) | 5.45e-4 | 0.218 | 227.51 → 132.96 |
| V4C-18 t15 drain-hi | population | 3.08e-5 (smoke 2: 2.13e-4) | 0 | 0.171 | 420.56 → 186.99 |
| V4C-02 / 07 / 12 / 17 cost-mid | population | 3.19e-5 / 0 / 2.77e-5 / 3.58e-5 | 0 / 0 / 0 / 0 | ≤ 0.095 | 117.44 / 138.06 / 143.21 / 159.92 |

**Hard stop (A4):** engineering floor = max(6.944e-4, no-op T1 0, 0) = 6.944e-4. All four pilot positive controls are
valid and strictly above it (7.1–7.6×). The hard stop did not trigger; no further control change was made or considered.

**Predictions stated before smoke 3:** retired V4P-01/V4P-04 and both `bh` changes gave T1 = 0 with peak broken_total =
r_broken_exact — the structural zeros reproduce.

**Runtime (A5):** population median wall_s **135.51 s** (8 final attempts, 2 per topology) against the frozen 180 s.
Pre-change overhead fell from 25–92 s to 10–15 s and post-window time from 35–167 s to 14–31 s; convergence
(55–111 s) is the frozen `nrl.clab` loop and now dominates. The t15 runs are 157–190 s, so a quarter of pilot runs will
sit near 180 s; the median over a topology-balanced pilot is driven by t13/t14 (~131–143 s here). G5 is decided only by
the pilot.

**Resolution:** B2 and B3 met every acceptance criterion and were moved to `resolved` in the register.

### Disclosures (no decision was changed by them)

1. **Population transient signal is below the floor in every engineering run.** All 12 population measurements in smoke 2
   and smoke 3 (including the highest-r cost and drain changes) have T1 ≤ 1.85e-4 < 6.944e-4, and all but one vanish
   under the 10 ms merge; the four `bh` values are 0 by construction. G1 needs at least 6 of 20 changes with a replicate
   median above the floor. **If this pattern holds, the pilot will end NO-GO on G1**, a pre-registered negative result
   ("transient forwarding loss from SPEC-PASS cost/drain/blackhole changes in this setting is below measurement
   resolution"). It is not an instrument defect (the positive controls show events of ~5e-3 are resolved) and not a
   construction defect, and it is not grounds to change T1, the floor, the population or G1 (§1: a degenerate target is
   a pilot result). Engineering smoke runs are single replicates and are not gate evidence.
2. The runner log line `runner exit True` is an artefact of PowerShell expanding `$?` in the launch command; the runner's
   completion is evidenced by 16/16 run records and the ledger, not by that line.
3. Smoke-3 labs ran with the Batfish container idle on the same host, as in smoke 2.

## 6. Launch preflight in WSL and final state (added after the preflight)

**Frozen state.** Execution freeze written at commit `7f85d70` and committed in `d578c73`: 31 files and 1,206 artifact
files (digest `78a6e858…`). Later commits `fa5ea8d` and `723f230` changed only `tools/pilot_preflight_check.py`, which is
not a frozen file; the commit adding this section adds only this document and the preflight log.

**Offline, Windows.** At `d578c73`: 10/10 suites (561 checks), preserved smoke 1 89/89. At `723f230`: `freeze.verify`
and `check_approval` pass; register empty.

**WSL preflight for the exact pilot command** (`logs/preflight_20260915T142217Z.json`, HEAD `723f230`): 32/32 checks —
`.venv-wsl` interpreter, non-root, `clab_admins`/`docker` groups, containerlab 0.79.0, Docker 29.7.2, FRR 8.4.1 and
alpine 3.19 images (digests recorded), Batfish reachable, D1–D9 approval, empty register, execution freeze and artifact
digest, clean host, manifest/lock digest, Batfish gate for all 114 planned runs, plan composition (100 population, 10
no-op, 4 positive; no retired control, no injection), no pilot state, smoke 3 validated, and `run_pilot.py --plan pilot`
refusing with exit 2 without a valid token (three variants).

**Exact command shell.** The pilot command uses `bash -c` (non-login); the smokes and the preflight used `bash -lc`. Both resolve `/usr/bin/containerlab` and `/usr/bin/docker`, the same groups (`clab_admins`, `docker`), umask 0022, and neither sets any `DOCKER_*` or `CLAB_*` variable.

**Preflight tooling disclosures.** Two earlier preflight attempts crashed inside the tool's own Git section before any
launch check ran: `git status` from WSL over `/mnt/c` exceeded 10 minutes, and Windows interop is unavailable in this
distro (`/etc/wsl.conf` enables systemd and no WSLInterop binfmt entry is registered, so `git.exe` fails with
`Exec format error`). No system setting was changed. The working-tree status is now taken by Windows-native git on the
same checkout immediately before the preflight and bound to it by HEAD equality; the file-hash freeze that the runner
itself enforces remains the integrity guarantee for every launch-relevant file.

**Remaining limits (disclosed; not launch blockers):**
- G4 is untested on one host, so the best attainable pilot decision is GO-WITH-FIXES (§9, §16).
- Every engineering population T1 is below the D1 floor (§5, disclosure 1): a G1 KILL, i.e. a pre-registered negative
  result, is the most likely pilot outcome.
- t15 runs take 157–190 s; the topology-balanced median is what G5 evaluates.
- The frozen `nrl.clab.wait_for_convergence` checks its 180 s timeout only between polls; a pre-change
  `NO_CONVERGENCE` took 1,317 s once in smoke 2. It extends real duration, not the G5 metric (final attempts).
- The Batfish container was idle on the host during smokes 2 and 3; leaving it idle during the pilot keeps the
  environment consistent with the engineering validation (the runner records the environment per run).
