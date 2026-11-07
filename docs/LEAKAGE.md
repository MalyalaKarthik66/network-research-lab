# Feature leakage rules

## The problem, stated concretely

In a synthetic pilot the generator knows the answer. `repair_id ==
"R-exact_revert"` is a near-perfect predictor of `SAFE`, and `fault_family`
narrows the outcome almost as sharply. A model given those fields will report a
very high AUC, and the number will mean nothing — it will have learned the
generator, not the network.

This field already has a credibility problem exactly here: a large fraction of
published ML-for-networking reports 99% accuracy while the model reads a
shortcut. High accuracy is treated with suspicion. An honestly measured, lower
number with a leakage audit is treated as trustworthy. Optimise for the second.

## BANNED from X — provenance only

Everything under `meta.json → provenance`:

- `fault_id`, `fault_family`, `fault_description`
- `repair_id`, `repair_description`
- `incident_id`, `candidate_id`

Also banned: anything read from `incidents/*/fault.json`, and the
`golden_to_candidate.diff` — comparing against the healthy network is
information nobody has at inference time, because if you had the healthy config
you would just deploy it.

`verify_pilot.py` CHECK 7 enforces that none of these appear inside
`change_stats` or `spec_coverage`.

## ELIGIBLE for X

- `meta.json → change_stats` — derived from `faulted_to_candidate.diff` alone.
  This is exactly what is available for a repair proposed in production: the
  current config and the proposed change.
- `meta.json → spec_coverage` — the specification-coverage group. Computed at
  generation time because it cannot be harvested from Batfish output afterwards.
  Per the project guardrails this is the most important feature group, so it is
  built in from the start rather than bolted on.
- `meta.json → phase2_batfish` — everything Batfish reports about the candidate.
  Legitimate: it is available before deployment.

## Splitting

**Group by `incident_id`, never split candidates from the same incident across
train / calibration / test.** Five candidates share one fault, one BEFORE state
and most of their config; splitting them randomly leaks and inflates test scores.
With conformal prediction it does worse than inflate — it silently voids the
coverage guarantee, because exchangeability fails.

With 10 incidents the pilot is far too small to split at all. Its purpose is to
prove the pipeline and estimate the false-pass rate, not to train anything.
Grouped splitting becomes mandatory at the 800–2,000 candidate scale.

## Calibration

The conformal calibration set must be disjoint from the training set. Calibrating
on training data voids the guarantee and produces no error message.
