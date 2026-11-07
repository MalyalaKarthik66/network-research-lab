# Final Independent Scientific Audit of V3

Date: 2026-09-13

This audit did not modify `data/pilot-v3`, Phase 2 outputs, Phase 3 outputs, manifests, locks, topology/configuration corpus, or `docs/ANALYSIS-PLAN-V3.md`. It did not commit changes.

## 1. Data Integrity

The frozen verifier was rerun:

- **40/40 checks passed**
- 180 summary rows
- 151 candidates
- 12 golden baselines
- 12 incidents
- 5 golden replicates
- 2,160 measurement rows = 180 x 12
- 1,812 delta rows = 151 x 12
- 151 outcome rows
- All summary statuses `OK`
- Outcomes: 101 SAFE, 48 HARMFUL, 2 UNDETERMINED
- No terminal failures
- No terminal LAB_INVALID runs
- Six LAB_INVALID attempt-1 archives, all resolved on retry
- No NO_CONVERGENCE runs
- No duplicate summary, outcome, or delta IDs
- Golden gate `|G| = 12` for all candidates
- Same-artifact and raw-evidence checks passed

The five golden replicates are permitted by the verifier as extra control runs. They are not silently counted as candidate runs.

## 2. Phase 2

Phase 2 metadata and the tagged commit report:

- 151/151 candidates processed
- 151 PASS
- 0 FAIL
- 0 ERROR
- 0 INVALID
- Artifact and snapshot digests match Phase 3
- Phase 2 commit: `f3c9035`, tag `v3-phase2-complete`

The v3 corpus has 20 topology definitions, 12 primary topologies, 8 held-out topologies, and the primary mechanisms cost plus blackhole. The manifest contains 151 candidates and no candidate-generation fault/incident rows are used as candidate features.

## 3. Phase 3

Phase 3 expected-set completeness is independently confirmed by the frozen verifier:

`12 golden + 12 incident + 151 candidate + 5 permitted golden replicates = 180 present runs`.

The `labs_completed: 6` field in the final `run_metadata.json` is a final-batch count. It is not the cumulative count; the cross-file counts and expected-set verifier establish the cumulative result.

## 4. Independent Measured-r Computation

I wrote a separate raw-RIB implementation in [independent_r_check.py](independent_r_check.py). It does not import `nrl.flowmatrix` or the previous `compute_measured_r.py`.

The independent implementation:

1. Loads the golden route JSON for each topology.
2. Loads the candidate route JSON for each candidate.
3. Builds all ordered router-loopback and LAN-host endpoint pairs.
4. Uses only golden-carried flows as the denominator.
5. Selects installed/selected routes and performs longest-prefix matching.
6. Detects `NO_ROUTE`, `LOOP`, and discard/blackhole as broken.
7. Counts a surviving path as rerouted only when its forwarding path differs from golden.
8. Counts unknown next-hop/max-hop reconstruction cases as undetermined.
9. Never uses predicted severity.

Result: **151/151 candidates matched the prior measured-r table exactly**, including golden denominator, broken count, rerouted count, undetermined count, and `r` after rounding to six decimals.

Sample independent rows:

| candidate | golden flows | broken | rerouted | undetermined | r |
|---|---:|---:|---:|---:|---:|
| C-00001 | 110 | 0 | 40 | 0 | 0.363636 |
| C-00002 | 110 | 0 | 16 | 0 | 0.145455 |
| C-00003 | 110 | 0 | 44 | 0 | 0.400000 |
| C-00004 | 110 | 0 | 20 | 0 | 0.181818 |
| C-00005 | 110 | 0 | 0 | 0 | 0.000000 |

Measured-r result:

- 151/151 decidable
- 91 distinct values
- Zero fraction: 9.27%
- Minimum: 0.0
- Maximum: 0.447619
- Mean: 0.116245
- Median: 0.058333
- Q1: 0.025 by the independent order-statistic calculation
- Q3: 0.158333 by the independent order-statistic calculation

The slight Q1/Q3 display difference from interpolated quantiles in the preliminary report is a quantile-convention difference, not a target mismatch. The frozen degeneracy decision is unaffected.

## 5. Predicted-vs-Measured

Independently recomputed from the frozen manifest predictions and independent measured-r values:

- MAE: **0.0000196821**
- RMSE: **0.0000241631**
- Pearson: **0.999999984**
- Spearman: **1.0**
- Maximum absolute error: **0.000047**
- MAE `<= 0.10`: **PASS**

This is corpus validation, not ML performance. The near identity is expected because v3 candidates were selected using the analytic `severity.Fabric` construction, and the analytic model predicts path changes from topology/configuration structure. It is evidence that the analytic construction reproduces this fixed FRR/RIB environment; it is not evidence of learned generalization.

## 6. ML Implementation Audit

The audited full feature matrix contains 43 numeric columns:

- 6 `chg_*` columns
- 5 `cov_*` columns
- 20-plus `g_*` graph columns
- Tier B Batfish state metrics
- `verdict_P06` and `verdict_P11` Tier C columns

The feature filter removed no selected columns. It did not include candidate ID, incident ID, topology name, fault family, repair class, repair ID, generation order, predicted severity, transient telemetry, or post-deployment measurements.

The target is measured `r` from the independent table. The estimator is:

- `HistGradientBoostingRegressor`
- learning rate `0.05`
- `max_iter=300`
- `max_leaf_nodes=15`
- `l2_regularization=1.0`
- `random_state=0`

For every LOTO fold, the held-out topology is excluded from training. No normalization is fitted. No feature selection is fitted on the test fold. No test target is used to choose a model or hyperparameter. Predictions are genuinely out-of-sample for the held-out topology.

## 7. Independent LOTO Rebuild

The independent evaluator reproduced every fold and the pooled result:

| topology | n | R2 | MAE | RMSE |
|---|---:|---:|---:|---:|
| t03_dual8 | 12 | 0.758077 | 0.042811 | 0.065190 |
| t05_ring6 | 10 | 0.981297 | 0.014293 | 0.017054 |
| t06_mesh6 | 10 | 0.965040 | 0.017861 | 0.023316 |
| t09_twin6 | 11 | 0.820459 | 0.044853 | 0.054043 |
| t13_bowtie7 | 12 | 0.957739 | 0.025447 | 0.029554 |
| t14_ladder8 | 13 | 0.603027 | 0.062052 | 0.083952 |
| t15_campus12 | 15 | 0.729130 | 0.057176 | 0.072757 |
| t16_pop14 | 12 | 0.927903 | 0.027026 | 0.035969 |
| t17_metro13 | 13 | 0.964815 | 0.019519 | 0.024966 |
| t18_grid12 | 15 | 0.730195 | 0.042842 | 0.067038 |
| t19_dualcore16 | 16 | 0.937285 | 0.022889 | 0.028789 |
| t20_leafspine12 | 12 | 0.905175 | 0.027206 | 0.038761 |

Pooled result:

- R2: **0.847896**
- Mean fold R2: **0.856679**
- Median fold R2: **0.916539**
- Mean fold MAE: **0.033664**
- Mean fold RMSE: **0.045116**

## 8. Bootstrap

The independent bootstrap resampled the 12 topology clusters 2,000 times while retaining the already out-of-sample LOTO predictions. It therefore estimates uncertainty around pooled LOTO R2, not a newly refit model's in-sample performance.

- Point estimate: 0.847896
- 2.5th percentile: 0.780427
- Median: 0.851937
- 97.5th percentile: 0.916695

The lower bound is greater than zero.

## 9. Within-Mechanism Results

Independent LOTO results against per-mechanism means computed from training topologies only:

| mechanism | model R2 | baseline R2 | improvement |
|---|---:|---:|---:|
| blackhole | 0.281023 | -0.027309 | +0.308332 |
| cost | 0.726351 | -0.004260 | +0.730611 |

Both exceed the frozen `+0.15` criterion. Individual fold values are preserved in [independent_ml.json](independent_ml.json).

## 10. Calibration: NOT VERIFIED

The preliminary numeric slope/bin values can be independently reproduced:

- Grouped 5-fold continuous R2: 0.825285
- Slope: 0.932758
- Intercept: 0.006450
- Four bins passing the +/-0.05 interval: 4/4

However, this is not the complete frozen calibration protocol requested by the audit. The audited scripts perform `GroupKFold(5)` model predictions and then fit one global regression slope plus four bins. They do **not** implement:

- a separate calibration fold inside each outer evaluation structure
- Platt calibration
- beta calibration
- inner-fold log-loss selection between Platt and beta
- a nested grouped train/calibration/test protocol

No isotonic calibration was used, but omission of isotonic does not compensate for the missing Platt/beta protocol. Therefore the numeric slope/bin threshold passes, but the calibration procedure itself is **UNVERIFIED** and cannot be reported as a fully executed frozen calibration result.

This is a methodology/reporting defect, not a data-corruption finding. It does not justify changing the corpus or rerunning Containerlab.

## 11. Shortcut Analysis

The shortcut-only model uses exactly the six `chg_*` change-shape features:

- `chg_lines_removed`
- `chg_lines_changed_total`
- `chg_devices_touched`
- `chg_touches_ospf`
- `chg_touches_static`
- `chg_touches_cost`

These are permitted predeployment features. It uses the same topology-held-out evaluation principle.

- Full LOTO R2: 0.847896
- Shortcut-only random-forest LOTO R2: 0.312941
- Difference: 0.534955
- Frozen requirement: difference > 0.05
- Result: PASS

Diagnostics:

- Mechanism grouped OOF recoverability: AUC 1.000
- Repair-class grouped OOF worst one-vs-rest AUC: 0.940
- Mechanism-only mean baseline R2: 0.316148
- Repair-class-only mean baseline R2: 0.256160

Mechanism is strongly recoverable and explains a real part of the target distribution. However, the full model materially exceeds both diagnostic baselines, and both within-mechanism LOTO results are positive. The evidence does not support saying that the full 0.848 R2 is primarily only mechanism or repair-class identity. It does support reporting mechanism recoverability prominently.

## 12. Target Viability

- Distinct values: 91, PASS against minimum 20
- Maximum one-value fraction: 9.27%, PASS against maximum 70%
- Target degeneracy: **not present**

## 13. Frozen Gate Table

| Criterion | Measured result | Frozen threshold | Result |
|---|---:|---:|---|
| LOTO R2 and CI | 0.847896; CI [0.780427, 0.916695] | R2 >= 0.40 and CI excludes 0 | PASS |
| Within-mechanism improvement | blackhole +0.308332; cost +0.730611 | >= 0.15 for both | PASS |
| Calibration numeric values | slope 0.932758; intercept 0.006450; 4/4 bins | slope [0.8,1.2], intercept +/-0.05, >=3/4 | NUMERIC PASS, PROTOCOL UNVERIFIED |
| Shortcut separation | 0.534955 | > 0.05 | PASS |
| Target degeneracy | 91 distinct; 9.27% largest value | >=20 distinct; <=70% one value | PASS |
| Predicted/measured MAE | 0.0000196821 | <= 0.10 | PASS |
| Terminal LAB_INVALID | 0 | <=5% | PASS |
| Golden controls | identical | must be identical | PASS |

## 14. Frozen Decision

The preliminary **GO is not accepted as a final scientific decision** because the required calibration protocol was not executed. The numeric calibration thresholds pass, but the method required to substantiate them is missing.

**Frozen decision: STOP/FIX**

The fix is analysis-only: implement and run the already-frozen nested grouped Platt/beta calibration procedure, with inner log-loss selection and no isotonic calibration. Do not modify the v3 corpus, labels, target, feature bans, thresholds, splits, or Containerlab evidence. Until that analysis is completed, the learned v3 claim should not be finalized as GO.

This is not a NO-GO result for the blast-radius target or the LOTO model. It is a stop on final reporting because a required calibration method is absent.

## 15. Scientific Assessment

### Data integrity

Strong. The verifier and independent cross-file counts agree.

### Phase 2 and Phase 3

Strong and reproducible. Digests agree, Phase 2 is 151/151 PASS, and Phase 3 is complete and duplicate-free.

### Measured blast radius

Verified. The independent raw-RIB implementation matches all 151 candidates.

### Predicted versus measured

Verified as corpus validation. The near-perfect agreement is expected from the analytic severity-targeted construction and must not be described as ML performance.

### ML model and LOTO

Verified under the implemented LOTO procedure. R2 is a variance-explained regression measure, not accuracy: 0.848 means the model's out-of-sample predictions explain approximately 84.8% of measured-target variance under this corpus and split. It does not mean 84.8% classification accuracy.

### Calibration

Not fully verified. The simple continuous calibration summary is reproducible, but the required Platt/beta nested protocol is absent.

### Claims permitted after calibration is fixed

The paper may claim that, under the frozen synthetic v3 design, predeployment features predict the measured blast-radius target with the reported topology-held-out regression performance and calibration, provided the missing calibration analysis passes.

### Claims not permitted

Do not claim real-world or production safety, vendor generalization, ECMP generalization, production prevalence, `P(harm | Batfish PASS)`, state-of-the-art performance, or that the model sees information fundamentally unavailable to Batfish.

## 16. Evidence Score

Because the required calibration protocol is missing, this is a **provisional evidence-strength score**, not a final GO score and not accuracy:

- Target quality: **20/20**
- Held-out generalization: **20/25**
- Calibration: **5/15**
- Shortcut resistance: **16/20**
- Statistical robustness: **9/10**
- Reproducibility/data integrity: **10/10**

**TOTAL: 80/100 provisional**

The score is reduced for the missing frozen calibration procedure and for the fact that the eight held-out topology designs are not represented by v3 candidate rows. Confidence in the underlying data and LOTO recomputation is high; confidence in the final reportability decision is medium until calibration is completed.

## 17. Change Log

### Created by this independent audit

- `analysis/v3_independent/independent_r_check.py`
- `analysis/v3_independent/independent_ml_check.py`
- `analysis/v3_independent/independent_prediction_and_counts.py`
- `analysis/v3_independent/independent_r.csv`
- `analysis/v3_independent/independent_ml.json`
- `analysis/v3_independent/independent_metrics.json`
- `analysis/v3_independent/FINAL-INDEPENDENT-V3-AUDIT.md`

### Modified

None.

### Deleted

None.

### Unchanged but read

- `docs/ANALYSIS-PLAN-V3.md`
- `data/pilot-v3/manifest.json`
- `data/pilot-v3/pilot.lock.json`
- `data/pilot-v3/phase2/`
- `data/pilot-v3/phase3/`
- `nrl/topologies_v3.py`
- `nrl/repairs_v3.py`
- `nrl/severity.py`
- `nrl/flowmatrix.py`
- `pipeline/run_phase3.py`
- `pipeline/verify_phase3.py`
- `analysis/v3_audit/run_v3_ml_audit.py`
- `analysis/v3_audit/run_v3_secondary_checks.py`

`git status --short` shows only the pre-existing untracked Phase-3 corpus and derived analysis directories. `git diff -- docs/ANALYSIS-PLAN-V3.md data/pilot-v3` is empty. No commit was made.

## Final Verified V3 Status

- Phase 3 execution: **PASS**
- Phase 3 verification: **PASS**
- Measured-r computation: **VERIFIED**
- Target viability: **PASS**
- ML leakage audit: **PASS**
- LOTO generalization: **PASS**
- Calibration: **FAIL / UNVERIFIED PROTOCOL**
- Shortcut resistance: **PASS**
- Statistical robustness: **PASS**
- Reproducibility: **PASS**

**FROZEN V3 DECISION: STOP-FIX**

**MODEL STRENGTH SCORE: 80 / 100 provisional**

**CONFIDENCE IN THAT SCORE: MEDIUM**
