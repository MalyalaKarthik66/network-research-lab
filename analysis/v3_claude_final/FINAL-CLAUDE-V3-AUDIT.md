# Final independent audit of the v3 blast-radius arm

Date: 2026-09-14. Analysis only. No frozen plan, corpus, label, feature or
experiment file was modified. Every number below was recomputed from the
repository by the scripts in this folder, not copied from either Copilot folder.

| script | what it establishes |
|---|---|
| `reproduce_r.py` | measured r three ways: emulator RIB walk, analytic Dijkstra from each candidate's actual scenario, Copilot CSV |
| `audit_ml_calibration.py` | STOP-FIX clauses, leakage, LOTO, within-mechanism, §7.2, §7.3, §7.1 ablations, secondary splits, all calibration readings |
| `learning_curve_tiers.py` | training-topology learning curve, Tier B vs Tier C headline, estimator sensitivity |
| `p06_lookup_baseline.py` | how much of the result one Batfish oracle-only verdict carries |

## Verdict: C. STOP/FIX: calibration plus other issues

Calibration is the only §8 gate that fails. It is not the only thing that has
to be fixed before any write-up. Every fix is analysis or documentation. No lab
has to be rerun.

## 1. Integrity (verified)

- Frozen plan: `git diff 65505a2 HEAD` removes 0 lines; amendments are append-only.
- Corpus: no commit touches `candidates/`, `manifest.json` or `pilot.lock.json` after `ff432ca`.
- `verify_phase3.py`: **40 passed, 0 failed**; 180 runs, 1,812 deltas, 101 SAFE / 48 HARMFUL / 2 UNDETERMINED.
- Measured r: **0 mismatches** on 151 candidates across three independent computations. 91 distinct values, mean 0.116245, median 0.058333, range 0 to 0.447619, 0 undetermined flows.
- §8 STOP-FIX: SPEC disagreement 0.0%, terminal LAB_INVALID 0, goldens identical, predicted vs measured MAE 1.97e-5. Largest single-value share 9.3%.

## 2. Gates as pre-registered

| gate | result | status |
|---|---|---|
| 1 LOTO R² ≥ 0.40, CI excludes 0 | per-fold 0.857 ± 0.125; pooled 0.8479 [0.776, 0.919] | PASS |
| 1, Tier B, as §4 wants Tier C separate | per-fold 0.757 ± 0.173; pooled 0.744 [0.642, 0.835] | PASS |
| 2 within-mechanism gain ≥ 0.15 | blackhole 0.281 vs −0.027 (+0.308); cost 0.726 vs −0.004 (+0.731) | PASS |
| 3 calibration | see §4; fails under the literal pre-registered interval for every learned model | **FAIL as written** |
| 4 shortcut > 0.05 below full | **plan-worded** §7.3 (identity + provenance + diff-shape) **0.499**, gap 0.349 | PASS |
| NO-GO recoverability | mechanism LOTO-AUC 1.000 in every tier while R² moves 0.41 → 0.74 → 0.74 → 0.85: performance does not track it | not triggered |

Leakage: no live feature matches a banned substring. Predicted severity is not in X.
Incident equals topology 1:1, so no fold leaks a held-out topology. Estimator is
not named in the frozen plan; the result is robust to that choice (RF 0.845,
v2-frozen GBT hyperparameters 0.851).

## 3. Corrections to the Copilot reports

1. **§7.3 shortcut used the wrong feature set.** Copilot used 6 `chg_` columns
   (0.313). §7.3 names identity, provenance and diff-shape. With those it is
   **0.499**. The gate still passes, but the reported shortcut understated it by 0.19 R².
2. **Tier C was headlined.** §4 requires Tier C (oracle-only Batfish verdicts) to be
   reported separately as a specification finding. The learned headline is Tier B, **0.744**.
3. **Nested calibration failure is largely an implementation artefact** (see §4).
4. **§6.4 transfer (8 held-out topologies) and §6.5 auxiliary arm were never
   executed.** Neither audit says so. They are not §8 gates, but they are
   pre-registered analyses and must be disclosed as not run.
5. **The LOMO interpolation direction fails.** Amendment 12.1.3 calls cost → blackhole
   "a fair transfer test". R² −5.27 (MAE 0.055 vs train-mean 0.148; test sd 0.025).
   Copilot reported it only as a "mechanism holdout".

## 4. Calibration

### What the plan actually says, and where it is ambiguous

- §5: "Calibration follows `ANALYSIS-PLAN.md` §5 unchanged". **Unexecutable
  as written:** the frozen `nrl.phase4.PlattCalibrator` raises
  `ValueError: Unknown label type: continuous` on r. Any implementation is an adaptation.
- The protocol that hosted calibration (secondary nested 5-fold by incident) was
  **voided by 12.1.3**. After the amendment, the plan does not say which split
  produces the calibrated predictions the gate is scored on.
- §6.2 says "exact binomial intervals on the observed flow counts". §6.2 also
  says the claim is "says 10% → observed 5–15%", which is ±0.05. **At this
  corpus size these two readings disagree by 5–13×.**
- §8.3 says "observed fraction inside the predicted bin's interval", which does
  not say whose interval it is.
- §6.1 and v2 §5 say per-fold is primary and pooled is visualisation only. A
  4-bin test is not estimable on a 10–40 row fold, so pooled is the only
  feasible reading for the bins.

### Is flows-as-binomial-trials justified? No, not as an inferential interval

r is deterministic given the configuration, so there is no sampling process
that makes flows Bernoulli trials. Flows within one candidate share one
configuration and one SPF tree. The flow-count Clopper–Pearson half-width
is ±0.004 to ±0.011 per bin, 2.1× to 3.2× narrower than a candidate bootstrap and narrower
still than a topology bootstrap. **The decisive control:** scored by the same
gate, the analytic Dijkstra (MAE 2e-5) passes 4/4. The raw primary LOTO model,
at slope 0.967 and intercept +0.001, passes only 2/4. The literal interval
tests near-oracle precision, not calibration.

As a *loss*, binomial likelihood on (k, n) is defensible. It is fractional-logit
quasi-likelihood (Papke & Wooldridge 1996), which is consistent for the mean
without an independence assumption. It weights large topologies more.
Platt and beta are probability calibrators, but they are valid monotone maps
on [0, 1], and beta nests Platt, which nests identity. The practical defect:
8 raw predictions are negative and are clipped to 1e-6, so log p = −13.8 feeds the beta map.

### Reproduced results (slope / intercept / bins passing under each interval)

| predictions scored | slope | icpt | flow CP | ±0.05 | cand. boot | topo boot |
|---|---|---|---|---|---|---|
| C0 analytic Dijkstra (control) | 1.000 | 0.000 | 4 | 4 | 4 | 4 |
| C1 raw 12-fold LOTO (primary model) | 0.967 | +0.001 | 2 | 4 | 4 | 4 |
| C2a Copilot outer 5-fold, raw | 0.933 | +0.006 | 0 | 4 | 3 | 4 |
| **C2b Copilot nested, calibrated** | **0.691** | +0.021 | **0** | 3 | 0 | 2 |
| C3b frozen `nested_cv` structure, calibrated | 0.902 | +0.000 | 2 | 4 | 4 | 4 |
| C4b calibrator nested inside LOTO (8 fit / 3 cal) | 0.819 | +0.025 | 1 | 4 | 3 | 3 |

- Copilot's result reproduces exactly (0.690776, 0.021027, 0/4, beta 5/5).
- **Copilot's calibrator makes predictions worse than raw on the same folds:** slope 0.933 → 0.691; test log loss 0.301 → 0.311.
  This is consistent with fitting the map on cross-fitted inner models trained on ~¾ of the
  data and then applying it to a refit on all of it. The frozen `nested_cv` structure scores
  the calibration fold and the test fold with the *same* model, and gives 0.902.
- Per-fold slope under the frozen structure is 1.21 ± 0.47 (range 0.84 to 2.04 on 23 to 40 rows).
  The per-fold reading is noise at this size, and it fails the [0.8, 1.2] band narrowly.
- **Calibration conclusion:** the pooled model is well calibrated at the ±0.05
  resolution the paper wants to claim. The pre-registered gate cannot certify
  that. As written it fails every learned model. The pass/fail outcome depends
  on implementation choices the plan does not fix (slope ranges 0.69 to 1.21).

## 5. The threat to the contribution

- `verdict_P06` ("hosta→hostb uses the primary WAN") is a single oracle-only
  Batfish boolean. Alone it has in-sample R² 0.777.
- **A zero-parameter LOTO lookup of mechanism × P06 reaches R² 0.794.** The
  43-feature model reaches 0.848, so the learned increment is **+0.054**.
- Within cost, the model reaches 0.726 and P06 alone 0.731.
- Blackhole r is 100% broken flows and cost r is 100% rerouted flows, so the
  broken/rerouted "decomposition" in §11 is fixed by mechanism, not found.
- The target is computed exactly pre-deployment by Dijkstra (MAE 2e-5), and
  Batfish can compute the same paths. A reviewer will ask why a learned
  approximation is the contribution.
- Learning curve under LOTO with 4 / 6 / 8 / 11 training topologies gives R²
  0.22 / 0.48 / 0.65 / 0.85. The result exists only at the full 11.

## 6. Scores

| | /100 |
|---|---|
| Model quality | 55 |
| Data quality | 86 |
| Methodology | 62 |
| Calibration | 45 |
| Overall readiness | 50 |

## 7. The one next action

Write dated amendment **§12.4** in `docs/ANALYSIS-PLAN-V3.md`, append-only and
explicitly post-result. It must (a) record §8.3 as **FAILED as literally
pre-registered**, with the full table in §4 including Copilot's 0.691 / 0/4 and the
C0 oracle control; (b) fix one replacement calibration protocol and interval
before it is run; (c) record the four reporting corrections in §3 and the P06
lookup baseline in §5 as mandatory same-table results; (d) record §6.4 and §6.5 as
not executed. Nothing else is run until that amendment is committed.

---

## 8. Final results under amendment 12.4 (run once from `a38d258`)

The ChatGPT review was right that a calibration method must be chosen on
methodology, not on its result. Amendment 12.4 derives every choice from the
frozen texts or frozen code. It was committed in `a38d258` before its result
existed. `final_gates_12_4.py` refuses to run from an uncommitted plan or
script, and it records the commit hash.

| | Tier B (learned, 41 features) | Tier C (full, 43 features) |
|---|---|---|
| C1 LOTO R² (per-fold / pooled [CI]) | 0.757 ± 0.173 / 0.744 [0.643, 0.836] PASS | 0.857 ± 0.125 / 0.848 [0.776, 0.915] PASS |
| C2 within-mechanism gain | blackhole +0.308, cost +0.668 PASS | blackhole +0.308, cost +0.731 PASS |
| C3 slope / intercept | 0.904 [0.778, 1.143] / +0.005 | 0.931 [0.851, 1.057] / +0.005 |
| C3 bins (topology bootstrap) | **3/4 PASS** (bin 3 misses by 0.0008) | **2/4 FAIL** (bin 1 misses by 0.0004, bin 3 by 0.0081) |
| C3 literal pre-registered flow-count interval | 1/4 FAIL | 2/4 FAIL |
| C3 ±0.05 claim check | 4/4 | 4/4 |
| C3 sensitivity: 10 inner seeds / flow-weighted loss | 8/10 pass (slopes 0.45–1.02) / pass | 8/10 pass (slopes 0.74–0.99) / pass |
| C4 §7.3 shortcut 0.499, gap | +0.244 PASS | +0.349 PASS |
| **Verdict by 12.4 rules** | **GO under amendment 12.4; pre-registered §8.3 failed** | **NOT GO: criterion 3; no calibration claim** |

Every C3 figure scores the nested model fit on 8 topologies (R² 0.599 Tier B,
0.703 Tier C), not the 11-topology headline model.

Mandatory same-table rows: mechanism lookup 0.313; **mechanism × P06 lookup 0.794,
above the Tier B learned model (0.744)**; LOMO cost→blackhole (interpolation, fair)
R² −5.27, MAE 0.055 vs 0.148; LOMO blackhole→cost (extrapolation) −0.90;
grouped 4-fold 0.797; random 5-fold 0.835 (−0.013 vs LOTO). §6.4 and §6.5 not executed.

Per 12.4.4 no further calibration variant is run. The calibration pass is at the
minimum bin count and fails for 2 of 10 alternative inner seeds, so it is
reported as borderline.
