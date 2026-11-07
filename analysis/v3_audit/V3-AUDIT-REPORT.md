# V3 Frozen Experiment Audit

Date: 2026-09-13

This is a read-only audit of the completed v3 corpus. No file under `data/pilot-v3` or `docs/ANALYSIS-PLAN-V3.md` was modified. Derived outputs are under `analysis/v3_audit/`.

## Executive Decision

**Overall v3: GO**, under the frozen v3 blast-radius claim only.

This does not revive v2's `P(harm | Batfish PASS)` claim. V3 evaluates continuous measured blast radius `r`.

## Repository and Provenance

- HEAD: `f3c9035`, tag `v3-phase2-complete`
- Frozen plan tag: `frozen-v3-plan-20260912`
- Corpus build tag: `built-v3-corpus-n151`
- V3 gate tag: `v3-gate-GO-20260912`
- Artifact digest: `6d1b7348e9ca4c58f5da314f5a9e4a121f3217534bf55662337cb0498e2086e3`
- Snapshot digest: `86648b27bf499d2513c33ea78b5fb530b18a354216cbdd0a3e166a62952ab707`
- Phase 2: 151 requested, 151 processed, 151 PASS, 0 FAIL, 0 ERROR, 0 INVALID
- Phase 3 output: `data/pilot-v3/phase3/`
- Phase 3 verifier: **40/40 passed**

The working tree has the pre-existing untracked Phase-3 corpus and the new untracked `analysis/v3_audit/` results. There is no diff to the frozen plan.

## Phase 3 Verification

The repository verifier independently recomputed the expected set as:

- 12 golden baselines
- 12 incident runs
- 151 candidate runs
- 5 golden replicate runs
- 180 present runs total

Results:

- Candidate coverage: complete
- Duplicate run IDs: 0
- Golden controls: identical
- Execution failures: 0
- LAB_INVALID terminal failures: 0
- LAB_INVALID retries: 6 attempt-1 archives; all retries resolved
- NO_CONVERGENCE: 0
- UNDETERMINED candidate outcomes: 2, excluded from labels and counted
- Property measurements: 12 per run
- Candidate deltas: 1,812 = 151 x 12
- Candidate outcomes: 151
- Golden property width: `|G| = 12` for every candidate
- Same-artifact checks: pass
- Raw evidence and RIB state: present
- Running Containerlab instances: none

The `run_metadata.json` field `labs_completed: 6` is the final batch count, not the cumulative count. The verifier's independent cumulative expected-set check is the authoritative completion check and passed.

## Measured Blast Radius

Target computation used all ordered router-loopback and LAN-host endpoint pairs, with forwarding paths reconstructed from the captured Phase-3 route JSONs using the existing `nrl.flowmatrix` path logic. Predicted severity was not used as ground truth or as a feature.

- Total candidates: 151
- Decidable candidates: 151
- Excluded candidates: 0
- Terminal failures: 0
- NO_CONVERGENCE: 0
- Candidates with undetermined flows: 0
- Distinct measured `r` values: 91
- Fraction `r = 0`: 9.27%
- Mean: 0.116245
- Median: 0.058333
- Q1: 0.024405
- Q3: 0.163962
- Minimum: 0.0
- Maximum: 0.447619

By mechanism:

| mechanism | n | mean | min | max | zero fraction | distinct |
|---|---:|---:|---:|---:|---:|---:|
| blackhole | 72 | 0.038977 | 0.007353 | 0.097222 | 0% | 43 |
| cost | 79 | 0.186667 | 0.0 | 0.447619 | 17.72% | 50 |

The target viability gate passes: 91 distinct values is above 20, and no single value exceeds 70% of observations.

## Predicted-vs-Measured Validation

This is corpus validation, not ML performance.

- MAE: 0.0000197
- RMSE: 0.0000242
- R2: 0.99999997
- Pearson correlation: 0.99999998
- Spearman correlation: 1.0
- STOP/FIX threshold `MAE > 0.10`: **not triggered**

The largest absolute prediction error was 0.000047. There was no target exclusion or route-evidence error.

## ML and Calibration

Features came from the existing Phase-4 loader and frozen feature filter: change statistics, coverage, graph features, Tier B metrics, and Tier C oracle-only verdicts. The predicted severity column was explicitly absent from X; the filter removed no candidate target or provenance field into X.

Primary 12-fold topology LOTO using gradient-boosted regression:

- R2: 0.847896
- MAE: 0.034515
- RMSE: 0.051166
- Mean fold R2: 0.856679
- Clustered topology bootstrap 95% CI for R2: [0.780427, 0.916695]

Grouped 5-fold calibration view:

- R2: 0.825285
- MAE: 0.037083
- RMSE: 0.054837
- Calibration slope: 0.932758
- Calibration intercept: 0.006450

Primary LOTO calibration was slope 0.966601 and intercept 0.001239. All four equal-frequency bins were within the prescribed predicted interval.

Within-mechanism LOTO versus per-mechanism mean baseline:

| mechanism | model R2 | mean baseline R2 | improvement |
|---|---:|---:|---:|
| blackhole | 0.281023 | -0.027309 | 0.308332 |
| cost | 0.726351 | -0.004260 | 0.730611 |

Both exceed the frozen 0.15 improvement criterion.

## Shortcut and Recoverability

The frozen shortcut-only random forest using change-shape features achieved:

- LOTO R2: 0.312941
- Full-model LOTO R2: 0.847896
- Full minus shortcut R2: 0.534955

The shortcut separation criterion therefore passes by a wide margin.

Mechanism and repair-class recoverability were also measured:

- Mechanism grouped topology-OOF AUC: 1.000
- Repair-class grouped topology-OOF worst one-vs-rest AUC: 0.940
- Mechanism-only mean baseline R2: 0.316148
- Repair-class-only mean baseline R2: 0.256160

Mechanism is a legitimate v3 construct, not a hidden forbidden identifier. Its perfect recoverability is disclosed. The full model materially exceeds the mechanism-only and repair-class-only baselines, and both within-mechanism analyses remain positive. Therefore the frozen NO-GO condition requiring recoverability **and** learned performance tracking that recoverability across ablations is not triggered by these results.

## Frozen Gate Table

| Criterion | Result | Threshold | Status |
|---|---:|---:|---|
| LOTO measured-r R2 and clustered CI | R2 0.847896; CI [0.780427, 0.916695] | R2 >= 0.40; CI excludes 0 | PASS |
| Within-mechanism improvement | +0.308 blackhole; +0.731 cost | >= 0.15 on both | PASS |
| Calibration | slope 0.9328; intercept 0.00645; 4/4 bins | slope [0.8,1.2], intercept +/-0.05, >=3/4 bins | PASS |
| Shortcut separation | full - shortcut = 0.534955 | > 0.05 | PASS |
| Target degeneracy | 91 distinct; max single-value fraction 9.27% | >=20; <=70% | PASS |
| Predicted/measured STOP/FIX | MAE 0.0000197 | MAE <=0.10 | PASS |
| Phase-3 data quality | verifier 40/40 | complete, consistent evidence | PASS |

## Audit Scope and Limitations

- V2 remains NO-GO for the binary residual-risk claim and was not pooled with v3.
- The eight held-out topologies are not present in the v3 candidate corpus; no held-out-topology transfer score was fabricated.
- Platt/beta calibration is a binary-probability procedure from the v2 plan. V3's frozen target is continuous, so the executed v3 calibration is the prescribed continuous slope/intercept plus flow-bin calibration; no binary Platt/beta result was invented.
- The existing repository did not contain a dedicated frozen v3 ML driver, so the derived audit scripts document their model and split implementation in `analysis/v3_audit/`. The frozen corpus remains unchanged.

## Files Created

Analysis code and generated results only:

- `analysis/v3_audit/compute_measured_r.py`
- `analysis/v3_audit/compare_predicted_measured.py`
- `analysis/v3_audit/run_v3_ml_audit.py`
- `analysis/v3_audit/run_v3_secondary_checks.py`
- `analysis/v3_audit/measured_blast_radius.csv`
- `analysis/v3_audit/measured_blast_radius_summary.json`
- `analysis/v3_audit/predicted_vs_measured.json`
- `analysis/v3_audit/v3_ml_audit.json`
- `analysis/v3_audit/v3_secondary_checks.json`
- `analysis/v3_audit/V3-AUDIT-REPORT.md`

No experimental code, corpus file, frozen plan text, commit, or tag was modified or created.

## Reproducibility Commands

```powershell
.\.venv\Scripts\python.exe pipeline\verify_phase3.py --pilot data\pilot-v3
.\.venv\Scripts\python.exe analysis\v3_audit\compute_measured_r.py
.\.venv\Scripts\python.exe analysis\v3_audit\compare_predicted_measured.py
.\.venv\Scripts\python.exe analysis\v3_audit\run_v3_ml_audit.py
.\.venv\Scripts\python.exe analysis\v3_audit\run_v3_secondary_checks.py
```

## Final Status

- Phase 3: **PASS**
- Data quality: **PASS**
- Target viability: **PASS**
- ML viability: **PASS under the frozen v3 blast-radius claim**
- Calibration: **PASS**
- Shortcut criterion: **PASS**
- Overall v3: **GO**

## What I Changed

I did not change the frozen experiment. I created only the analysis scripts and derived report/results listed above under `analysis/v3_audit/`. No file under `data/pilot-v3` or `docs/ANALYSIS-PLAN-V3.md` was modified, deleted, regenerated, or overwritten.
