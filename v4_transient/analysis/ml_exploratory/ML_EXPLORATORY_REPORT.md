# Exploratory ML Analysis (post-hoc, existing-data only)

## Purpose

This is a post-hoc exploratory analysis on the existing V4 smoke/smoke2/smoke3 run metrics only. It is not a new experiment and does not validate the original V4 target.

## Dataset construction

- Source files: C:\Users\karth\network-research-lab\v4_transient\results\smoke2\run_metrics.csv, C:\Users\karth\network-research-lab\v4_transient\results\smoke3\run_metrics.csv, C:\Users\karth\network-research-lab\v4_transient\results\smoke\run_metrics.csv
- Constraint: valid population rows only
- Labels used: T1_disruption_area
- Grouping used for validation: leave-one-change-out (change_id)
- Runtime telemetry is excluded from the feature set

## Sample counts

|   n_rows |   n_valid_population_rows |   n_unique_changes |   n_unique_topologies |   n_unique_mechanisms |   n_positive_above_floor |   noise_floor | all_labels_zero   |
|---------:|--------------------------:|-------------------:|----------------------:|----------------------:|-------------------------:|--------------:|:------------------|
|       16 |                        16 |                 10 |                     4 |                     3 |                        0 |   0.000694444 | True              |

## Label definition

Target for regression: T1_disruption_area.
Binary target above the frozen floor (= 0.0006944444444444445) is degenerate because all valid rows are below the floor.

## Leakage audit

- No runtime FIB event data used
- No observed packet loss used
- No runtime T1 used as a feature
- No row-level event-ordering variables used as features
- The feature set is restricted to predeployment features and analytic graph properties

## Shortcut audit

The suspicious shortcut features such as change_id, topology, and mechanism are intentionally excluded from the main ML feature set. The model fails to gain useful signal because the valid population dataset contains no events above the noise floor.

## Grouped validation

Leave-one-change-out was used to prevent leakage across repeated rows from the same incident. Because the valid population dataset contains only 10 changes and zero positive labels above the floor, the generalization signal is weak.

## Results

| feature_group     | model             |         mae |        rmse |         r2 |   spearman |   n_test |
|:------------------|:------------------|------------:|------------:|-----------:|-----------:|---------:|
| topology_only     | linear_regression | 6.57559e-05 | 8.68871e-05 | -0.793199  | -0.0577077 |       16 |
| topology_only     | random_forest     | 5.06951e-05 | 7.44464e-05 | -0.316451  | -0.0174062 |       16 |
| topology_only     | gradient_boosting | 4.89691e-05 | 7.77506e-05 | -0.435905  | -0.0256781 |       16 |
| config_only       | linear_regression | 6.40148e-05 | 7.27981e-05 | -0.258802  |  0.476771  |       16 |
| config_only       | random_forest     | 2.65162e-05 | 4.28775e-05 |  0.563306  |  0.82159   |       16 |
| config_only       | gradient_boosting | 2.23643e-05 | 3.73846e-05 |  0.668026  |  0.829337  |       16 |
| batfish_only      | linear_regression | 0.000169699 | 0.000204469 | -8.93056   |  0.455773  |       16 |
| batfish_only      | random_forest     | 4.44595e-05 | 6.36022e-05 |  0.0391372 |  0.372896  |       16 |
| batfish_only      | gradient_boosting | 4.03149e-05 | 6.13042e-05 |  0.107315  |  0.490077  |       16 |
| all_predeployment | linear_regression | 9.34736e-05 | 0.000105003 | -1.61893   |  0.375927  |       16 |
| all_predeployment | random_forest     | 3.65247e-05 | 5.0492e-05  |  0.394432  |  0.63817   |       16 |
| all_predeployment | gradient_boosting | 3.04766e-05 | 4.56347e-05 |  0.505339  |  0.717276  |       16 |

## Ablation summary

| feature_group     | model             |         mae |        rmse |        r2 |
|:------------------|:------------------|------------:|------------:|----------:|
| topology_only     | linear_regression | 6.57559e-05 | 8.68871e-05 | -0.793199 |
| config_only       | linear_regression | 6.40148e-05 | 7.27981e-05 | -0.258802 |
| batfish_only      | linear_regression | 0.000169699 | 0.000204469 | -8.93056  |
| all_predeployment | linear_regression | 9.34736e-05 | 0.000105003 | -1.61893  |

## Conclusion

The dataset is insufficient for a scientifically meaningful ML experiment. The original V4 target is not validated by this exploratory analysis, and the use of ML here is purely descriptive and post-hoc.
