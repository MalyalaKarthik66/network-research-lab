# Interim verdict — Stage 3 partial (n = 299)

**Status: EXPLORATORY.** `docs/ANALYSIS-PLAN.md` preamble — anything not written in
that file is exploratory and reported as such. No plan, label, manifest or Phase-3
artifact was modified. Outputs: `interim_results.json`, `interim_report.txt`, this file.

## VERDICT: BAD — SHORTCUT-ONLY

`ANALYSIS-PLAN.md` §14.2, the `≥ 0.85` branch, fires on every frozen tier.
The learned arm is **not reportable as a risk model on this corpus.**

---

## 1. The gate, re-measured on the correct population

Worst-case one-vs-rest `repair_class` AUC, incident-grouped nested CV, on the
299 PASS-conditioned modelling rows (not the mixed 1,479-candidate corpus that
`diagnose_shortcut.py` uses).

| feature set | worst AUC | verdict |
|---|---|---|
| A | 0.961 | FAIL |
| A+ | 0.966 | FAIL |
| B | 0.977 | FAIL |
| C | 0.975 | FAIL |
| B_only | 0.765 | ok |
| C_only | 0.587 | ok |
| B+C_only | 0.779 | ok |
| no_chg_no_g | 0.822 | ok |

The previously recorded 0.921 came from the wrong population. On the right one the
number is **worse (0.975)**, not better. The hypothesis that the population mismatch
had inflated it is refuted.

`fault_family` is recoverable from tier C at **0.9975** — a second, independent route
to the label that is not risk.

## 2. Why the label is recoverable: the generator determines it

| repair_class | harmful / n | rate |
|---|---|---|
| correct | 0 / 153 | 0.000 |
| incomplete | 41 / 73 | 0.562 |
| regressive | 39 / 73 | 0.534 |

A 3-level generator variable, one level containing **zero** harmful cases.
Oracle score from `repair_class` alone: **AUC-ROC 0.8535, AUC-PR 0.5550.**
Chain: features → `repair_class` (0.97) → harm (0.85).

## 3. Dose-response: performance is a function of contamination

Across 8 feature ablations, GBT AUC-PR against that set's `repair_class` recoverability:

| feature set | recoverability | AUC-PR |
|---|---|---|
| C_only | 0.587 | 0.603 |
| B_only | 0.765 | **0.291** |
| B+C_only | 0.779 | 0.617 |
| no_chg_no_g | 0.822 | 0.627 |
| no_chg | 0.926 | 0.821 |
| A+ | 0.966 | 0.835 |
| C | 0.975 | 0.895 |
| no_g | 0.982 | 0.831 |

**Spearman ρ = 0.905 (p = 0.002)**; Pearson r = 0.699 (p = 0.054).

**B_only — Batfish's own after-network metrics, the cleanest feature space —
AUC-PR 0.291 against a base rate of 0.268, CI [0.226, 0.382] contains the base
rate, p = 0.319. No signal.**

## 4. The non-learned rule beats every shortcut-controlled model

`spec_widening_rule` (HARMFUL iff Batfish reports any oracle-only property failing):

- AUC-PR **0.8137** [0.7308, 0.8889], AUC-ROC 0.8790
- TP 61, **FP 1**, FN 19, TN 218
- precision **0.984**, recall 0.762, balanced accuracy 0.879

One false positive in 219 safe candidates, with no model and no training.
Best learned model on a clean feature set: 0.603 (C_only). FINAL-PLAN §9:
*"Spec-widening rule beats every learned model → report as headline; the
conclusion is widen the specification, not train a model."*

## 5. The residual population kills the last hope

Restricting to the 237 candidates the spec-widening rule calls safe — the actual
residual-risk question:

- 19 / 237 harmful (8.02%), Wilson [0.052, 0.122]
- **all 19 are `repair_class == incomplete`**; `correct` 0/153, `regressive` 0/33
- oracle `repair_class` score inside the residual: AUC-ROC 0.9266
- `repair_class` recoverability inside the residual, tier B/C: **0.968**

The apparent residual signal (tier B/C AUC-PR 0.633) is the model recovering one
generator class that happens to contain 100% of the residual harm.

## 6. What survives, and it is not nothing

- **P(harm | Batfish SPEC PASS) = 80/299 = 0.2676**, Wilson [0.221, 0.321],
  clustered bootstrap [0.216, 0.323]. Stable across three sample sizes
  (0.2635 at n=148, 0.2587 at n=259, 0.2676 at n=299).
- Manski width **0.66 points** — the exclusion assumption costs almost nothing.
- **76.2% of post-PASS harm (61/80) is recoverable by widening the specification.**
  23.8% (19/80) is not. That is ANALYSIS-PLAN §9 category (a) vs (b)/(c), measured.
- Per-topology harm 0.000–0.625, per-family 0.107–0.594, all with Wilson intervals.

## 7. Next

1. **Do not run Stage 4 as designed.** The 18.5 h main arm adds labels to a corpus
   whose label is 85% determined by a 3-level generator variable. The learning
   curve is still rising (0.247 → 0.409 → 0.634) because it is learning the
   shortcut faster, not because risk is becoming predictable.
2. **Reframe per FINAL-PLAN §9** — drop "machine learning" from the title.
   Measurement study + specification-completeness sweep + conformal bound.
   Report the leakage measurement as a finding about synthetic repair corpora.
3. **Promote the LLM repair arm.** It is the only arm whose repairs are not drawn
   from 3 parametric operator classes and is the one realistic chance of breaking
   the fingerprint. Run it before, not after, the main expansion.
4. **Run the 40 replicates first.** Zero have ever produced an outcome row; the
   label-noise floor that bounds every number above is still unmeasured.
5. **Fix the generator if the learned arm is to be rescued at all:** decouple
   `repair_class` from harm (correct-but-harmful and regressive-but-safe cases),
   and make operators produce structurally indistinguishable diffs.
6. **Finish Stage 3** — it stopped at 301 of 450; 149 candidates remain.

## Defects found (not fixed; frozen code untouched)

- `build_dataset` merges `meta` and `batfish_summary`, both of which carry
  `prov_fault_family_BANNED`, producing `_x`/`_y`. Every `if by in df.columns`
  guard downstream misses it, so the per-fault-family exclusion and harm tables
  required by ANALYSIS-PLAN §2 **never print** in `run_phase4.py`. Worked around
  locally here. No leakage: no suffixed column reaches X at any tier.
- `run_phase4.py` raises `ValueError` in `conformal_incident_split` at any
  incident count ≠ 200, after printing sections 1–4 and **before** writing
  `phase4_results.json`. It cannot complete on a partial dataset.
