# CALIBRATION FIX REPORT

Date: 2026-09-13

## A. Frozen Requirement

`docs/ANALYSIS-PLAN-V3.md` requires:

- secondary nested grouped five-fold CV
- calibration following `docs/ANALYSIS-PLAN.md` section 5
- Platt and beta calibration both fitted on held-out calibration data
- lower calibration-fold log loss selected
- ties go to Platt
- no isotonic calibration
- calibration slope, intercept, and four-bin observed-flow calibration reporting

For v3's continuous `r`, the frozen target is a fraction of affected flows. The implemented operational interpretation is the binomial representation already implied by the plan's exact binomial intervals:

- successes `k = broken_flows + rerouted_flows`
- trials `n = golden_carried_flows`
- raw prediction is a probability in `[0, 1]`
- log loss is binomial negative log likelihood over affected and unaffected flows

The calibrators are canonical probability calibrators applied to the predicted fraction:

- Platt: `sigmoid(a * logit(p) + b)`
- beta: `sigmoid(a * log(p) + b * log(1-p) + c)`

This uses the existing target representation; it does not change `r`, thresholds, labels, or features.

## B. Previous Incorrect Implementation

The previous `run_v3_ml_audit.py` implementation:

1. ran grouped five-fold model prediction by incident;
2. collected out-of-fold predictions;
3. fit one global `numpy.polyfit` slope/intercept over all out-of-fold predictions;
4. split those predictions into four equal-frequency bins.

It did not fit Platt or beta calibrators, did not use a designated calibration fold, did not select by calibration-fold log loss, and did not implement nested train/calibration/test separation.

## C. Exact Code Change

Modified only:

- `analysis/v3_audit/run_v3_ml_audit.py`

Added:

- binomial log-loss calculation;
- canonical Platt calibrator fitting using SciPy optimization;
- canonical beta calibrator fitting using SciPy optimization;
- calibrator application;
- exact Clopper-Pearson bin intervals;
- `nested_grouped_calibration()`;
- nested calibration results in `v3_ml_audit.json`.

No corpus, Phase 2 output, Phase 3 output, frozen plan, manifest, lock, target computation, LOTO split, shortcut model, or GO criteria were changed.

## D. Nested Calibration Procedure

The executed procedure was:

1. Split all 151 candidates into five outer folds using `GroupKFold(n_splits=5)` grouped by topology.
2. Keep each outer test topology set completely out of model and calibrator fitting.
3. Within each outer training partition, use four grouped inner folds by incident ID.
4. Train a gradient-boosted regressor on each inner-training partition.
5. Generate out-of-fold predictions for the designated inner calibration rows.
6. Fit both Platt and beta calibrators only on those inner calibration predictions and their flow counts.
7. Compute binomial calibration log loss for both calibrators on the inner calibration data.
8. Select the lower-log-loss calibrator; ties select Platt.
9. Fit a final gradient-boosted regressor on all outer-training rows.
10. Apply the selected calibrator to predictions for the untouched outer test topology rows.
11. Pool only the five outer test predictions for slope, intercept, and bins.

No test target was used for model fitting, calibrator fitting, or calibrator selection. No test-derived normalization or feature selection was used. Predicted severity was not used as a feature.

## E. Platt Results

Platt was fitted in every outer fold and reported in every fold's inner calibration log-loss comparison. It was not selected in any fold.

Inner calibration log loss by fold:

| outer fold | test topologies | Platt log loss |
|---:|---|---:|
| 1 | t09_twin6, t19_dualcore16 | 0.339857 |
| 2 | t13_bowtie7, t18_grid12 | 0.324694 |
| 3 | t03_dual8, t15_campus12 | 0.321820 |
| 4 | t06_mesh6, t17_metro13, t20_leafspine12 | 0.347892 |
| 5 | t05_ring6, t14_ladder8, t16_pop14 | 0.326957 |

Selected folds: **0/5**.

## F. Beta Results

Beta was fitted in every outer fold.

| outer fold | test topologies | Beta log loss |
|---:|---|---:|
| 1 | t09_twin6, t19_dualcore16 | 0.319320 |
| 2 | t13_bowtie7, t18_grid12 | 0.320593 |
| 3 | t03_dual8, t15_campus12 | 0.311323 |
| 4 | t06_mesh6, t17_metro13, t20_leafspine12 | 0.326989 |
| 5 | t05_ring6, t14_ladder8, t16_pop14 | 0.313044 |

Selected folds: **5/5**.

## G. Selection Result

Beta had lower inner calibration log loss in all five folds. No ties occurred.

- Platt selected: 0/5
- Beta selected: 5/5
- Selection used only inner calibration data
- Outer test log loss was not used for selection

Pooled test log loss:

- Raw model predictions: 0.301369
- Selected calibrated predictions: 0.310801

The higher pooled test loss is reported, not hidden. It does not alter selection because test loss was not available to the selection procedure.

## H. Calibration Gate Result

Pooled outer-test calibration:

- Calibration slope: **0.690776**
- Calibration intercept: **0.021027**
- Number of bins: **4**
- Bins with predicted mean inside the exact observed-flow 95% interval: **0/4**

Frozen thresholds:

- slope must be in `[0.8, 1.2]`: **FAIL**
- intercept must be within `+/-0.05`: **PASS**
- at least 3/4 bins must pass: **FAIL**

The calibration criterion therefore fails. This is a methodology/result finding, not a reason to alter the corpus or tune the calibrator after seeing the result.

## I. LOTO Result

The existing independently verified LOTO result was not changed by the calibration implementation:

- Pooled LOTO R2: **0.8478958**
- Mean fold R2: **0.8566786**
- Clustered bootstrap CI: **[0.780427, 0.916695]**

The independent raw-RIB measured-r check still reports zero mismatches across all 151 candidates.

## J. Shortcut Result

The shortcut result was not changed:

- Full LOTO R2: **0.8478958**
- Shortcut-only R2: **0.3129410**
- Difference: **0.5349549**
- Frozen requirement: difference greater than 0.05
- Result: **PASS**

Within-mechanism improvements were also unchanged:

- Blackhole: **+0.308332 R2**
- Cost: **+0.730611 R2**

## K. Final Frozen GO/WEAK/NO-GO/STOP-FIX Status

**Final status: STOP/FIX**

The reason is the failed frozen calibration gate after executing the required nested procedure. The target, data integrity, LOTO generalization, within-mechanism results, and shortcut separation remain valid and positive. No Containerlab rerun, data change, threshold change, or feature change is authorized by this result.

The next analysis action is to review the failed calibration result against the frozen methodology and decide whether the calibration definition itself requires a preregistered amendment. This report does not make that amendment.

## Validation

Executed successfully:

```powershell
.\.venv\Scripts\python.exe analysis\v3_audit\run_v3_ml_audit.py
.\.venv\Scripts\python.exe analysis\v3_independent\independent_r_check.py
.\.venv\Scripts\python.exe analysis\v3_independent\independent_ml_check.py
.\.venv\Scripts\python.exe analysis\v3_independent\independent_prediction_and_counts.py
.\.venv\Scripts\python.exe pipeline\test_phase4.py
.\.venv\Scripts\python.exe -m py_compile analysis\v3_audit\run_v3_ml_audit.py
```

All existing independent measured-r, LOTO, shortcut, within-mechanism, and Phase-3 count checks remained unchanged and passed.

## Files

Modified:

- `analysis/v3_audit/run_v3_ml_audit.py`
  - Added only the frozen nested calibration implementation and derived-output wiring.

Created:

- `analysis/v3_audit/CALIBRATION-FIX-REPORT.md`
  - This report.

Generated/updated derived analysis output:

- `analysis/v3_audit/v3_ml_audit.json`

Unchanged:

- `data/pilot-v3/**`
- Phase 2 outputs
- Phase 3 outputs
- `docs/ANALYSIS-PLAN-V3.md`
- `manifest.json`
- `pilot.lock.json`
- measured-r implementation
- LOTO model implementation
- shortcut implementation

No commit was created.
