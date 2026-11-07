# V4 transient pilot — what a paper can and cannot claim

- **Date:** 2026-09-15.
- **Author:** implementer (Claude).
- **Scope:** this assessment is about the design. It was written before any pilot data existed and does not
  anticipate any outcome.

## 1. What the pilot is

A pre-registered feasibility study with a kill-gate structure (pre-registration §16):
- **Changes:** 20 Batfish-SPEC-PASS OSPF configuration changes: cost, drain and a /32 blackhole, chosen at analytic
  impact extremes on 4 topologies of 6–12 routers.
- **Replicates:** 5 fresh-deployment replicates of each change.
- **Controls:** 10 no-op and 4 shutdown positive controls. Two of the originally selected shutdown links were cut
  edges (T1 = 0 by construction); amendment A4, written after engineering smoke 2, replaced them
  (`docs/V4-LAUNCH-AUDIT-2.md`).
- **Host:** one WSL2 host.
- **Instrument:** exact per-router kernel FIB replay (route, link and nexthop-object events), checked against
  in-transient and final FIB dumps.

## 2. Claims the pilot CAN support, whatever the outcome

1. **Whether transient disruption is measurable** above a pre-registered noise floor on these changes (G1, D1, D2).
   The instrument's sensitivity is checked by positive controls (D9).
2. **Whether change-level transient disruption is repeatable** across fresh deployments on one host (G3, D3).
   It is reported with ICC(1) and reliability.
3. **Whether it is already explained** by the strongest pre-registered analytic baseline under leave-one-topology-out
   (G2, D5).
4. **Whether the protocol is affordable** at the planned corpus scale (G5, D6).
5. **A methods result:** an exact FIB-replay measurement of transient forwarding loss, and the specific kernel
   behaviours that silently defeat route-event replay:
   - admin-down flush;
   - carrier-loss nexthop-object flush;
   - linkdown routes that stay selected;

   together with the consistency checks that detect them. These are reproducible from `audit/` and the tests.

**A NO-GO is a publishable negative result.** Examples: "transient disruption in this setting is below
measurement resolution", "it is analytically reducible", or "it is not repeatable". The pre-registration,
amendment log and Git history make such a result auditable.

## 3. Claims the pilot CANNOT support

- **Prevalence** of transient disruption among real changes. The population is designed (analytic extremes), not
  sampled.
- **Generalization** beyond these conditions:
  - FRR 8.4.1 OSPF with default timers;
  - veth links in containers;
  - software forwarding;
  - no BFD;
  - these 4 topologies;
  - one host.
- **Host invariance.** G4 is untested, so the best attainable decision is GO-WITH-FIXES.
- **ML usefulness.** The RandomForest is feasibility-only:
  - ~20 change means;
  - 4 LOTO folds;
  - no hyperparameter search;
  - never part of the decision.

  No "learned model beats analytic baseline" claim is possible from the pilot.
- **Real packet loss.** T1 is forwarding-state loss computed from the FIB. Probe loss is secondary and not gated.
  Queueing, ARP/neighbour resolution and hardware programming delay are outside the instrument.
- **Novelty.** Transient loops and loss during convergence are well studied: RFC 5715 microloops, ordered FIB
  updates, convergence measurement on emulators. The defensible contribution is:
  - the pre-registered, kill-gated question of whether *pre-deployment* evidence predicts it for Batfish-safe
    changes;
  - the validated instrument.

  It is not the phenomenon itself.

## 4. What a hostile reviewer will attack, and the answer

| attack | answer in this design | residual limit |
|---|---|---|
| Thresholds chosen after seeing data | D1–D9 fixed 2026-09-14 and A3 on 2026-09-15, both before pilot data; Git anchors `399b39b` and `4056099`; execution freeze verified by the runner. A4/A5 (after smoke 2) changed no threshold, target or gate | before `399b39b`, chronology rests on file hashes and timestamps; state this plainly |
| Positive controls replaced after seeing smoke data (A4) | disclosed as a post-smoke-2 amendment; the rule is configuration-only and was committed (`b165c23`) with a hard stop before implementation; the retired controls and their evidence are kept; one revalidation (smoke 3); D9 unchanged | A4 was written knowing that non-partitioning shutdowns gave T1 ≈ 5e-3 on t13/t14 in smoke 2; state this plainly |
| Runner optimized to pass G5 (A5) | only docker-exec parallelism outside the observation window changed, pinned by hash tests against A3; D6 (180 s) unchanged; smoke-2 runtimes that motivated it are disclosed | the final FIB snapshot follows the monitor stop more closely than under the serial runner |
| Structural zeros in T1 | T1 ≡ 0 whenever a change breaks flows only permanently (all four `bh` changes; any cut-edge shutdown); disclosed before the pilot, so G1 can reach at most 16 of 20 changes | the `bh` role contributes no transient signal by construction |
| Plan proposals were changed (G2 0.90 → 0.80, G3 0.80 → 0.50) | both are stricter, and the rationale is logged; they are reported as amendments, not as the original registration | none |
| Instrument misses silent FIB changes | kernel link semantics are modelled; nexthop-object changes are detected; replay is checked against in-transient and final dumps; runs failing any check are invalid, and the D8 guard (≥ 90 % valid) applies | changes shorter than and between 2 s polls are covered by modelling, not by direct observation |
| Cross-router timestamp ordering artefacts | T1_merge10ms sensitivity is reported alongside T1 | descriptive only |
| Failures selectively removed | no retry after the change is applied; invalid runs count against D7/D8/D9; every attempt is kept | none |
| Selection optimism in G2 (max of 5 baselines) | biases toward KILL, the conservative direction for a stopping rule | none |
| n = 20 and 4 topologies | declared as a feasibility pilot; CIs are change-level and stated as weak | inherent |
| Replicates are only execution jitter | the estimand is stated (§20); no host, timer or load claims are made | inherent |
| Leakage into features | the whitelist is config-derived; mechanism is proven to be a function of the config diff; no IDs, roles, order or telemetry (`tests/test_core.py`) | none known |

## 5. What must happen after the pilot, whatever the decision

- **Report every gate outcome,** including NOT_EVALUABLE, and every invalid run by reason.
- **If GO-WITH-FIXES:**
  - run the two-host G4 test (D4) before any corpus;
  - write a separate pre-registration for the corpus.
- **If NO-GO:** do not rescue by changing the target, floor, population or gates. Publish the negative result
  together with the instrument.
