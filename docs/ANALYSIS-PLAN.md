# Analysis plan — FROZEN 2026-09-02

**Frozen before any pilot-v2 label exists.** At the time of writing
`data/pilot-v2/phase2/` and `phase3/` do not exist on disk, no candidate in the
20-topology design has an outcome, and the dataset has not been built. Git
history is what makes that claim checkable: this file is committed before the
build, and the build commit follows it.

Everything below is the confirmatory protocol. Anything not written here is
**exploratory** and must be reported as exploratory. The point of the
distinction is that "we found a calibrated model" and "we searched until
something looked calibrated" produce the same numbers and are not the same
claim.

Changing this file after labels exist requires a new dated section stating what
changed and why, exactly as `HARM-DEFINITION.md` does.

---

## 1. Population

The modelling population is candidates that **passed the Batfish SPEC gate**
and received a **decidable** Containerlab outcome.

    r(x) = P(Y = 1 | X = x, V(x) = PASS)

The conditioning on `V(x) = PASS` is not decoration: it defines the population,
and it is why the model is trained only on passing candidates.

## 2. Labels

| outcome | primary (harm definition v1.1.0) | sensitivity |
|---|---|---|
| HARMFUL | y = 1 | y = 1 |
| SAFE | y = 0 | y = 0 |
| NO_CONVERGENCE | **y = 1** | excluded |
| UNDETERMINED | **excluded, counted** | excluded |
| EXECUTION_FAILED | **excluded, counted** | excluded |
| LAB_INVALID (→ EXECUTION_FAILED) | **excluded, counted** (see §14.1) | excluded |

Excluded rows are never y = 0. Exclusion is reported overall **and broken down
by topology and fault family**, because a rate concentrated in the
subpopulation where the interesting risk lives is not the same as a uniform
one.

**Manski partial-identification bounds are reported alongside every rate:**
`p_min` treats every undecidable outcome as safe, `p_max` as harmful. Excluding
a row is an assumption, not a neutral act, and these are the sharp bounds under
no assumption at all.

Secondary label **v1.2.0** (transient) is pre-registered in
`HARM-DEFINITION.md` and reported as a secondary analysis. v1.1.0 remains
primary so the pilot-v1 comparison stays valid.

## 3. Feature tiers

| tier | contents | available |
|---|---|---|
| A | `change_stats`, `spec_coverage` | before any verification |
| A+ | A + `graph_features` (`nrl/graphfeat.py`) | before any verification |
| B | A+ + Batfish spec-gate outputs | after running the spec |
| C | B + Batfish's verdicts on the oracle-only properties | — |

**Tier C is not a learned contribution.** It answers *"what would asking more
questions achieve?"* If C beats A+ and B, the finding is **widen the
specification**, not **train a model**.

Banned from X: `fault_family`, `repair_id`, `repair_class`, `incident_id`,
`candidate_id`, anything derived from `golden_to_candidate.diff`, and every
`transient_` field (those are the v1.2.0 label, not an input). The filter
**prints what it removed**.

**Effective n** — the count of distinct feature vectors — is reported alongside
the row count, and every power calculation uses it, not the row count.

## 4. Splits

All grouping is by `incident_id` at **every** level, including the calibration
split. Candidates from one incident share a fault, a BEFORE state and most of
their config.

- **Primary protocol.** Nested grouped 5-fold CV. Within each outer fold, three
  sub-folds fit the model, one fits the calibrator, one is held out.
- **Generalisation.** Leave-one-topology-out, 20 folds.
- **Stress.** Leave-one-fault-family-out, 10 folds.
- **Conformal.** A dedicated grouped split of the incidents, **120 / 40 / 40**
  (train / calibration / test).

No fixed final holdout: at this sample size, grouped cross-validation with a
protocol frozen in advance uses the data better, and frozen-in-advance is what
makes it legitimate.

**Minimum detectable effect, pre-specified.** For LOTO and LOFO, an
observed AUC-PR whose clustered bootstrap CI contains the base rate is reported
as **underpowered**, not as a negative finding. The two are different claims
and the distinction is fixed here, before the result is seen.

## 5. Calibration

Platt and beta calibration (Kull, Silva Filho & Flach, AISTATS 2017, PMLR v54)
are **both** fitted on the calibration fold. **Selection rule, fixed now:**
lower log loss on that fold wins; ties go to Platt as the simpler model. Both
are reported.

Isotonic regression is **not used**: its effective degrees of freedom scale
with n and it overfits below roughly a thousand calibration points.

**Per-fold metrics (mean ± sd) are the primary report.** The pooled
out-of-fold curve is a **visualisation only** — it mixes five calibrators and
no inferential claim rests on it. The spread of fitted calibrator parameters
across folds is reported as a diagnostic.

## 6. Metrics

**Calibration.** Continuous reliability curve with a clustered bootstrap band
(primary); Brier score with the Murphy decomposition; Spiegelhalter z; ECE with
**equal-frequency** bins. **Four bins**, as a supplementary illustration only —
at ~150 evaluation rows per fold, ten bins cannot be estimated to better than
about ±13 points and the extreme bins would be noise.

**Discrimination.** AUC-PR primary, AUC-ROC secondary. Not accuracy, not F1.

**Selection.** Per-incident top-1 accuracy, mean within-incident AUC, and
**regret** against the oracle, with choosing uniformly at random among that
incident's passing candidates as the baseline.

**Decision usefulness.** Autonomy–risk curve: coverage versus realised harm,
with the conformal bound overlaid.

**Verification study** (independent of any model). The 2×2 with Wilson
intervals; P(harm | PASS) overall, per topology, per fault family, and split
**generated vs reference-derived**; the a/b/c decomposition; optimistic versus
pessimistic property disagreements with a **Clopper–Pearson exact** bound from
the FAIL control arm; the specification-completeness curve.

## 7. Statistics

- Wilson intervals for proportions; **Clopper–Pearson exact** for zero-count
  bounds (the rule of three is quoted as intuition, not as the number).
- **Every bootstrap resamples incidents**, 2,000 resamples.
- Clustered permutation test for the one confirmatory comparison (§8).
- DeLong or paired clustered bootstrap for AUC comparisons; McNemar for
  classifier errors.
- No FDR or Bonferroni correction, because there is exactly one confirmatory
  test by design. Every other comparison is exploratory and labelled so.

## 8. The specification-completeness sweep

**Pre-registered nested sequence.** Oracle-only properties are added to SPEC one
at a time in **ascending property id**:

    P03, P04, P06, P09, P10, P11, P12

giving eight points, |SPEC| = 5 … 12. Ascending id is chosen because it is the
one ordering that cannot have been selected to make the curve look a particular
way.

**The single confirmatory test of the whole study:** P(harm | PASS) under
SPEC-5 versus SPEC-12, by clustered permutation over incidents.

Every other point on the curve is descriptive, with a clustered bootstrap band.
The random-subset variant is a sensitivity analysis and appears in an appendix.

## 9. Harm attribution

Each candidate that passed the SPEC gate and measured harmful is attributed to
exactly one category, by this rule:

- **(a) specification incompleteness** — Batfish reported the violated property
  as FAIL, and it is oracle-only, so the SPEC gate never consulted it.
- **(b) model scope** — Batfish reported PASS and the violation is visible only
  in the transient telemetry, or the run did not converge.
- **(c) model vs device** — Batfish reported PASS and the violation persists at
  converged steady state with no transient signal.
- **unattributed** — anything matching none of the above, reported rather than
  forced into a bucket. A decomposition that always sums to 100% by
  construction is not a measurement.

## 10. Conformal risk control

Two-layer hierarchical split conformal — Dunn, Wasserman & Ramdas,
*Distribution-Free Prediction Sets for Two-Layer Hierarchical Models*,
arXiv:1809.07441, JASA 118(544); efficiency refinement from Principato et al.,
arXiv:2411.13479.

- **One nonconformity score per cluster, the MAX** over that cluster's
  candidates. Conservative, which is the right direction for harm control.
- Exact quantile: `q̂` is the `⌈(K+1)(1−α)⌉`-th order statistic of the K
  cluster scores. If that index exceeds K the bound is **vacuous** and is
  reported as vacuous. The α floor is `1/(K+1)`.
- **Primary: incident-level clustering** (K = 40 calibration incidents, floor
  ≈ 0.024, so α = 0.05 and α = 0.10 are both supportable).
- **Also reported: topology-level clustering** (K = 20, floor ≈ 0.048), the
  conservative case, because incidents nest inside topologies and share nearly
  the whole base configuration.
- α is never lowered to make a bound appear.

## 11. Learning curve

Train on n ∈ {50, 100, 200, 400, 600, …} sampled **by incident**, five
repetitions per point, AUC-PR and ECE with bands. Read as: still rising at the
largest size → more data helps, and the recommendation has a number attached.
Flat by the middle → the ceiling is the representation or the label noise, not
n, which is the argument for a distribution-free bound rather than a sharper
classifier.

## 12. Stop rules

Fixed now, so that stopping is a decision and not a rationalisation.

| condition | action |
|---|---|
| false-pass rate < 2% | fix once, retry; still < 2% → publish the near-zero completeness finding and trigger the fallback direction |
| false-pass rate > 60% | debug the oracle before believing it |
| replicate label agreement < 95% (overall or boundary stratum) | stop; the measurement layer bounds everything downstream |
| Manski width > 10 points | stop; the harness is too fragile to support a rate |
| NO_CONVERGENCE ≥ 5% | investigate; check correlation with topology size |
| learning curve flat between stages | stop collecting for the model; spend the remainder on the FAIL arm, replicates and the sweep |
| no signal above base rate in A+/B | drop "machine learning" from the title; report as a measurement study |
| conformal q̂ = ∞ at the chosen α | report the floor and K; do not lower α |
| any gate fires | fix the cause; never bypass |

## 13. Claims

**Permitted:** P(harm | Batfish SPEC PASS) with clustered CI on this artifact;
the a/b/c decomposition; the specification-completeness curve; a calibrated
risk estimate over the PASS population with reliability quantified; a
distribution-free bound at a stated coverage; whether the risk is learnable at
this scale; whether the rate survives a change of repair generator and topology
source.

**Not permitted:** anything about production networks (the ground truth is an
emulator with no hardware forwarding plane); that Batfish is buggy or unsound;
a general false-pass rate for *network verification* rather than for this
specification, these fault families, this repair distribution and these
topologies; transfer to unseen vendors, protocols or scales; any causal claim
about *why* a repair is risky — the features are correlational.

---

# 14. Amendments

Each amendment is dated, states what changed and why, and says what evidence
existed at the time. Nothing here alters §1–§13; where an amendment interacts
with them it says so explicitly.

## 14.1 `LAB_INVALID` retry policy — pre-registered 2026-09-04

**Status when written: no Stage 2 label exists.** `data/pilot-v2/phase3/`
contains only the 39 Stage 1 runs (2 topologies, 6 incidents, 20 labelled
candidates). No candidate outside that slice has an outcome, and no Stage 2
harm label has been computed, inspected or plotted. This is written *before*
the Stage 2 run and committed before it starts, which is what makes it a
pre-registration rather than a rationalisation.

**Why it is needed.** S-020 found that a containerlab interface-rename race can
leave ospfd unbound to an interface the artifact puts in OSPF. The
configuration is correct, the addresses are correct, and one adjacency simply
cannot form — so the lab measures a network that was never deployed as
specified. `clab.verify_ospf_binding` detects this and marks the run
`LAB_INVALID`. Observed rate: 1 in 77 Stage 1 runs (~1.3%), which is roughly 23
labs across the full ~1,800-lab budget.

**The policy.**

1. **Trigger — exhaustive and mechanical.** A retry is attempted if and only if
   the run status is `LAB_INVALID`, i.e. `verify_ospf_binding` returned
   `MISMATCH`. No other status is retried: not `DEPLOY_FAILED`, not
   `STAGING_FAILED`, not `CONTAINERS_MISSING`, not `NO_CONVERGENCE`, and never
   a run that produced a decidable outcome. The trigger is a property of the
   apparatus, evaluated **before any property is measured** — it cannot see the
   label, so it cannot select on it.
2. **At most one retry per run id.** The retry is a fresh deploy of the *same*
   artifact, byte-verified against `pilot.lock.json` exactly as the first
   attempt was. No configuration, timing parameter or property is changed
   between attempts. A run that has already been retried is never retried
   again, under any circumstance.
3. **Second failure is terminal.** If the retry is also `LAB_INVALID`, the run
   is recorded `LAB_INVALID` permanently, mapped to `EXECUTION_FAILED`,
   **excluded from y and counted** under §2, and included in the Manski
   `p_min`/`p_max` bounds like every other undecidable outcome. It is never
   relabelled, never retried a third time, and never quietly dropped from the
   denominator.
4. **Separate accounting, reported either way.** Every attempt is preserved on
   disk: attempt 1 is archived to `runs/<run_id>.attempt1/` and attempt 2
   written to `runs/<run_id>/`. `run_metadata.json` records
   `lab_invalid_attempts` and `lab_invalid_terminal`. The paper reports the
   invalid-lab rate **before retry** (the apparatus's true flake rate) and
   **after retry** (the rate that actually costs sample), as two numbers, never
   one.
5. **Decided before any label is inspected.** This section is committed before
   the Stage 2 invocation. If the invalid-lab rate after retry exceeds **5%**,
   that is a §12 stop condition — the apparatus is too flaky to support a rate,
   and the cause is investigated before more labs are run, rather than retried
   harder.

**What this policy deliberately does not do.** It does not retry to obtain a
different label, because it cannot: the trigger is evaluated before measurement
and is blind to the outcome. It does not retry a lab that converged, however
surprising its result. And it does not treat a recovered lab as free — retried
labs are flagged in the dataset so any reviewer can recompute every headline
number with them excluded.

## 14.2 S-014 — `repair_class` recoverability is a declared threat to the ML arm

**Recorded 2026-09-04. No methodology changes.** §3 already bans
`repair_class` from X. This section states what the measured leakage means for
the claims in §13, so that it is on the record before Stage 2 rather than
discovered in review.

**The measurement.** `pipeline/diagnose_shortcut.py` on the Stage 1 corpus:
`repair_class` is recoverable from Tier A/A+ features at worst-case
**AUC 0.999** (`chg_` 0.995, `g_` 0.943, `cov_` 0.766). No leave-one-group-out
ablation falls below 0.951, so it is not one leaking column — each repair
operator uses a systematically different set of configuration constructs, and
the class is distributed across the whole diff. The mitigation already applied
(five same-device regressive operators, `RR-*_same`) moved
`chg_devices_touched` from 0.890 to 0.777 and left the **joint AUC at 0.998**.

**Why it threatens the ML arm and not the measurement study.** The false-pass
rate, the a/b/c decomposition, the specification-completeness sweep and the
conformal bound are computed from outcomes and verdicts; none of them consumes
a learned score. They are unaffected. But a model trained on Tier A/A+ can
reach the label through the generator's fingerprint: `repair_class` correlates
with harm by construction, so "the model predicts risk" and "the model
recognises which operator produced this diff" are indistinguishable on this
corpus. A reviewer is entitled to read a positive learned result as evidence
that the dataset is synthetic, not that risk is predictable.

**Decision point — Stage 2, before any Stage 3 modelling.** Tier B/C
(Batfish's own outputs) returned **0.517** on Stage 1, near chance, but at
n = 46 across 6 incidents that is underpowered rather than clean. Re-run
`diagnose_shortcut.py` at Stage 2's n (~150 PASS across 20 topologies and 10
families) and decide:

| Tier B/C `repair_class` AUC at Stage 2 | decision |
|---|---|
| < 0.85 | the leak is confined to config-diff features. Report Tier A/A+ results **only** as a leakage-contaminated upper bound, and treat Tier B/C as the ML arm. |
| ≥ 0.85 | the leak reaches the verifier's own outputs. The learned arm is **not reportable as a risk model** on this corpus; report it as a documented failure, keep the measurement study and the conformal bound, and drop predictive claims from §13. |

Either way the paper reports the leakage measurement itself — it is a finding
about synthetic repair corpora, and it is the reason the conformal bound
(which needs no learned score to be valid) carries the autonomy argument.

**Not permitted under either branch:** claiming a learned model predicts
operational risk without reporting the `repair_class` recoverability alongside
it, in the same table.
