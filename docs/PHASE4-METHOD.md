# Phase 4 — method and results

Reads Phases 1–3, writes only to `data/pilot-v1/phase4/`. No lab re-run, no
frozen definition changed, no Phase 1–3 file modified (`verify_phase4` CHECK 5).

## Population

The 24 candidates that passed the Batfish SPEC gate: **12 HARMFUL, 12 SAFE**.
That is the whole modelling population, and it spans **10 incidents**, six of
which contribute exactly one candidate.

## Protocol

- **Leave-one-incident-out CV.** Mandatory: candidates from one incident share a
  fault, a BEFORE state and most of their config. A random split leaks.
- **Metrics:** AUC-ROC, AUC-PR (preferred under imbalance), balanced accuracy.
- **Bootstrap 95% CI** (2000 resamples) on every metric.
- **Permutation test** (2000 shuffles) — at n=24 the only statement about
  significance worth making.
- **Models in numpy**, not scikit-learn: logistic regression (L2), a depth-1
  stump, and a majority baseline. At this size the whole analysis should be
  auditable in a hundred lines, and it adds no dependency to the venv Phases 1–2
  already run in.

## Three feature tiers, because they answer different questions

| Tier | Contents | Available when |
|---|---|---|
| **A** | config-diff only (`change_stats`, `spec_coverage`) | before any verification |
| **B** | A + Batfish spec-gate outputs (parse health, RIB/adjacency counts, differential-vs-incident) | after running the spec |
| **C** | B + Batfish's verdicts on the **oracle-only** properties | — |

**Tier C is not a learned contribution.** It answers *"what would simply asking
more questions achieve?"* If C beats A and B, the finding is **widen the
specification**, not **train a model**. Separating the tiers is what keeps that
comparison honest.

## Results (leave-one-incident-out)

| Ablation | Tier | Model | n | AUC-ROC [95% CI] | AUC-PR | perm. p |
|---|---|---|---|---|---|---|
| all-24 | A | logistic | 24 | 0.583 [0.33, 0.83] | 0.571 | 0.258 |
| all-24 | A | stump | 24 | 0.691 [0.45, 0.89] | 0.570 | 0.058 |
| all-24 | B | logistic | 24 | 0.656 [0.39, 0.88] | 0.719 | 0.103 |
| all-24 | C | logistic | 24 | **0.747 [0.49, 0.95]** | 0.699 | **0.026** |
| excl. exact_revert | A | logistic | 14 | 0.417 [0.15, 0.69] | 0.876 | 0.671 |
| excl. exact_revert | B | logistic | 14 | 0.375 [0.11, 0.65] | 0.860 | 0.727 |
| excl. exact_revert | C | logistic | 14 | 0.542 [0.24, 0.83] | 0.919 | 0.469 |

**Non-learned baseline — widen the specification.** Predict HARMFUL iff Batfish
reports any oracle-only property failing:

> **7 of 12 harmful caught, 0 false alarms, balanced accuracy 0.792.**

That beats every Tier-A and Tier-B model, and it is a deterministic rule.

## What the numbers mean

**1. Repair-diff features carry no usable signal.** Tier A is 0.583 with
p = 0.258. Nothing about how large or where a config change is predicts harm here.

**2. The only tier approaching significance is the one that isn't learning.**
Tier C reaches p = 0.026, but Tier C *is* Batfish's answers to more questions.

**3. The label is degenerate.** The SAFE class is **83% `R-exact_revert`** —
10 of 12 — and those are byte-identical to golden. Remove them and every model
collapses to ≤ 0.542 with p ≥ 0.469. A model trained on the full 24 is largely
learning *"is this the revert?"*, which is a shortcut and useless in deployment:
you do not know which candidate is the revert, and if you did you would deploy it.

**4. 5 of 12 harmful candidates are irreducible by more questions.** The
spec-widening rule catches 7. The remaining 5 are missed either because Batfish
is optimistic about the oracle-only property too, or because the divergence is on
a SPEC property Batfish was asked and got wrong (C-0013/14/15).

**5. Caveat on the fold structure.** The majority baseline scores AUC-ROC 0.222 —
below chance. That is a small-sample artifact of leave-one-group-out: fold base
rates are anti-correlated with fold composition when six of ten incidents hold a
single candidate. It is a warning that at this size the grouping itself moves
the metric.

## Conclusion for the research question

> **Can a model predict which verified-passing changes cause harm?**
> **Not from this pilot, and the blocker is not only n = 24.** The positive class
> is dominated by a single trivially-identifiable repair operator, so the
> apparent signal is a shortcut. With that shortcut removed there is no signal
> left to find.

The useful finding is the decomposition, not a model: **7/12 of the residual
risk after verification is recoverable by asking more questions; 5/12 is not.**
The first number is an argument for better specifications. Only the second is an
argument for a learned risk layer, and 5 samples cannot support one.

## What would make Phase 4 answerable

1. **A repair distribution where SAFE is not mostly reverts.** LLM-generated repairs, or a mutation library with many plausible-and-correct operators.
2. **More incidents.** 10 gives 10 CV folds and six singleton folds. 50+ incidents is the minimum for a grouped protocol to mean anything.
3. **Enough positives.** At a 50% false-pass rate, ~1,500 candidates yields ~750 harmful — the registered target range.
4. **Then, and only then, conformal risk control.** Calibration on 12 points is not calibration.
