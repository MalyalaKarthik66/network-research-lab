# Analysis plan, v3 blast-radius arm — FROZEN 2026-09-12

**Frozen before any v3 candidate exists.** At the time of writing
`data/pilot-v3/` does not exist on disk, no v3 artifact has been rendered, no
Batfish snapshot has been created and no lab has run. Every number in this
document is *predicted* by `nrl/severity.py`, an analytic model validated 36/36
against real FRR measurements (§9). Git history is what makes that claim
checkable: this file is committed before the build, and the build commit
follows it.

This freeze exists because the v3 generator was revised four times under review.
Each revision had a diagnosed cause and is recorded in §10, but "revised until
the metrics passed" is a fair reading of that history unless the design is
locked before the data exists. It is locked here.

Changing this file after any v3 label exists requires a new dated section
stating what changed and why, exactly as `ANALYSIS-PLAN.md` and
`HARM-DEFINITION.md` do.

---

## 0. What this arm is, and what it is not

**This arm asks:** among configuration changes that **pass** the Batfish SPEC
gate, can the *blast radius* — the fraction of network flows the change breaks
or reroutes — be predicted from pre-deployment evidence?

**This arm does not resurrect the residual-risk arm.** `ANALYSIS-PLAN.md` §14.2
and the Gate 0 result stand unchanged:

- Gate 0: 40 candidates, randomised link churn, **0/40 steady-state outcome
  flips**. The binary harm label is deterministic under environmental
  perturbation.
- `repair_class` recoverable from the PASS-conditioned Tier B/C features at
  **AUC 0.975**; learned AUC-PR tracked that recoverability at Spearman
  ρ = 0.905.

Those findings are not superseded. `P(harm | PASS)` as a binary, aleatoric
quantity remains **NO-GO** on this apparatus and is reported as a negative
result. The v3 target is a different quantity — continuous, deterministic given
the configuration — and is stated as such in §3. The two must never be pooled,
and no v3 result may be described as evidence about `P(harm | PASS)`.

**Prevalence claims do not come from this arm.** The v3 corpus is constructed to
span severity, not to reproduce the natural frequency of repairs. Any base-rate
statement belongs to the v2 measurement study (`P(harm | Batfish SPEC PASS) =
0.2676`, Wilson [0.221, 0.321], n = 299).

---

## 1. Frozen generator configuration

Source of truth: `nrl/topologies_v3.py`, `nrl/repairs_v3.py`,
`nrl/severity.py` at commit `2d5f46f`. The constants below must match the code;
a mismatch is a defect in one of them and blocks the build.

### 1.1 Topologies

Derived from the v2 designs by `nrl/topologies_v3.py`. **`nrl/topologies.py` is
not modified** — `data/pilot-v2` was built from those definitions and
`pilot.lock.json` hashes every file, so editing them in place would leave the
frozen corpus describing artifacts that can no longer be regenerated.

**ECMP elimination.** 18 cost increments of +1 across 9 designs, applied
deterministically (largest `(node, next-hop)` in any equal-cost set, repeat
until none remain). Result: **0 equal-cost sets in all 20 topologies**, from up
to 37/210 ambiguous hops in `t20_leafspine12`. Under ECMP a flow's path is a
tie-break convention rather than a physical fact, so severity would not be
uniquely defined on those flows. Every nudge is retrievable from
`topologies_v3.report()` and must be published.

**Primary set — 12 topologies:**

    t03_dual8   t05_ring6   t06_mesh6    t09_twin6
    t13_bowtie7 t14_ladder8 t15_campus12 t16_pop14
    t17_metro13 t18_grid12  t19_dualcore16 t20_leafspine12

**Held out for the generalisation arm — 8 topologies:**

    t01_chain4 t02_wan6 t04_star5 t07_tier7
    t08_chain8 t10_deep9 t11_branch6 t12_campus8

The eight are excluded because they have **no peripheral links**: in a 4-router
chain every link carries about half the flows, so their achievable severity
starts at 0.33–0.48 and they can emit only high-severity repairs. Including
them made network size a severity proxy by construction — topology R² on
severity was **0.5521**, against **0.0091** on the primary set. They remain
valid networks and are the transfer test in §6.4, not discarded data.

### 1.2 Mechanisms

| | |
|---|---|
| **Primary** | `cost`, `blackhole` |
| **Auxiliary** | `shutdown`, `exact` |

`COST_MULTIPLIER = 20` — a cost-mechanism repair sets the OSPF cost on **both
ends** of one link to 20× its configured value. One construct, one diff shape.

`blackhole` adds exactly one `ip route <prefix> blackhole` static at one router,
for an endpoint prefix that router does not originate (a blackhole on the
originating router is a no-op: the connected route's administrative distance 0
beats the static's 1).

**Why these two, and not the previous `cost + shutdown`:** the gate that defines
the population was never tested against. Measured predictions:

| mechanism | SPEC-PASS | severity range |
|---|---|---|
| `cost` | **100%** | 0.000 – 0.455 |
| `blackhole` | **91%** | 0.003 – 0.097 |
| `shutdown` | **0%** | — every one fails P08 |

Shutting a link drops an OSPF adjacency, so P08 fails unconditionally. The
earlier `cost + shutdown` corpus was 42% unable to enter the population.
`blackhole` had been excluded to flatten a mechanism R², and it is the
**canonical false-pass case**: it breaks hosta→hostc, which is P03/P04 —
oracle-only — so the SPEC gate never asks and the repair passes. Choosing
mechanisms to improve a shortcut metric, without checking the gate, had
optimised the study's own subject out of the corpus.

### 1.3 Selection rule

For each topology, `catalogue()` enumerates every `(mechanism, target)` pair,
predicts `r` for each with `severity.Fabric`, and predicts its SPEC verdict.
**Only SPEC-PASS entries are selectable.**

`_pick()` then takes the candidates nearest evenly spaced points of the
achievable **severity range** — `QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)` —
not quantiles of the candidate *list*, which is dominated by blackhole entries
and produced a bimodal corpus. Mechanisms are rotated across the quantiles.
Picks are then **relabelled by target**, so a repair id's index is arbitrary
with respect to severity: emitting in pick order made `_q0` mean "lowest" and
scored repair_id at R² 0.84.

Classes draw from the same quantile range, which is what makes their severity
bands overlap rather than partition.

### 1.4 Predicted corpus

215 repairs, 12 topologies, 15–20 per topology, **all SPEC-PASS by
construction**.

| | |
|---|---|
| severity range | 0.000 – 0.448 |
| median / mean | 0.097 / 0.153 |
| distinct values | 81 |
| zero-severity repairs | 14 |
| class bands overlapping | 3 of 3 |

Zero-severity repairs are `RC-noop`: raising the cost of a link with no
alternative path is a real configuration change that moves no traffic. They are
**not** empty diffs — `exact` is auxiliary precisely because an empty diff
always scores 0 and was worth R² 0.27 on its own.

---

## 2. Population

The modelling population is v3 candidates that **passed the Batfish SPEC gate**
and received a **decidable** Containerlab measurement.

    r(x) = E[ blast radius | X = x, V(x) = PASS ]

The SPEC gate is P01, P02, P05 (hosta↔hostb reachability), P07 (no forwarding
loops), P08 (all OSPF adjacencies established). P03, P04, P06 and P09–P12 are
oracle-only: Batfish is never asked, so a change can break them and still pass.

**The predicted SPEC verdict is a design tool, not a substitute for the gate.**
Every candidate is verified by Batfish in Phase 2, and the measured verdict is
authoritative. Disagreement between predicted and measured SPEC verdict is
itself reported (§7.4): it is model-vs-implementation divergence and belongs in
the paper.

---

## 3. Target

    r(x) = (flows broken + flows rerouted) / (flows the golden network carries)

measured by `nrl/flowmatrix.py` over all ordered endpoint pairs (router
loopbacks and LAN hosts), with forwarding paths reconstructed from each run's
captured RIBs.

- **broken** — the flow stops working, or its route vanishes, loops, or is
  discarded (`NO_ROUTE`, `LOOP`, `BLACKHOLE`).
- **rerouted** — the flow still works but takes a different forwarding path.
- **undeterminable** — either side errored or the path could not be
  reconstructed. Reported, never treated as healthy, and bounded by
  `risk_r_min` / `risk_r_max` the way Manski bounds a rate.

`r`, `r_broken` and `r_rerouted` are reported **separately in every table**.
They are different contributions: `r_broken` is model-vs-device divergence,
`r_rerouted` is a policy change a wider specification could have caught.
Reporting one pooled number would let the two be conflated.

**`r` is deterministic given the configuration.** Phase 2 measured identical
values across replicate pairs for 12 of 12 candidates. This arm therefore
performs **regression calibration** — "the model says 10% of flows affected,
about 10% are" — and not probabilistic risk estimation. The honest name for the
claim is *blast-radius prediction*.

### 3.1 Exclusions

| outcome | treatment |
|---|---|
| decidable measurement | included |
| `LAB_INVALID` | one retry of the same byte-verified artifact (`ANALYSIS-PLAN.md` §14.1); second failure is terminal |
| terminal `LAB_INVALID` → `EXECUTION_FAILED` | **excluded, counted**, reported by topology and mechanism |
| flow undeterminable | excluded from that candidate's denominator, counted, bounded |
| candidate fails the measured SPEC gate | excluded from the population, counted, and compared against its predicted verdict |

Excluded rows are never scored as `r = 0`. Exclusion rates are reported overall
and broken down by topology and mechanism, because a rate concentrated where the
interesting severity lives is not the same as a uniform one.

---

## 4. Features

**Allowed in X** — everything computable before deployment:

- `chg_*` — 16 change-statistics: four counts, eleven `touches_<construct>`
  booleans. Verified to contain **no raw cost values**.
- `cov_*` — spec coverage.
- `g_*` — 28 graph features of the change and the after-network.
- Tier B — Batfish network-state outputs.
- Tier C — Batfish verdicts on oracle-only properties, reported separately
  because Tier C answers *"what would asking more questions achieve?"*, which is
  a specification finding and not a learned one.

**Banned from X**, enforced by `nrl.phase4.BANNED_SUBSTRINGS` and re-verified
before every fit: `repair_class`, `repair_id`, `fault_family`, `incident_id`,
`candidate_id`, `topology` as an identifier, the severity quantile index, the
generation order index, anything derived from `golden_to_candidate.diff`, all
`transient_*` fields, all execution telemetry, and the predicted severity from
`nrl/severity.py`.

**The predicted severity must never enter X.** It is the design tool that chose
the candidate; using it as a feature would be circular.

The filter prints what it removed. A silent filter is how features go missing.

---

## 5. Splits

**Primary protocol: leave-one-topology-out (LOTO), 12 folds.** Grouped by
topology, not by incident, because the v3 target is a function of network
structure and the question is transfer to a network never seen.

**Secondary: nested grouped 5-fold CV** grouped by incident, reported alongside.

**Random CV is reported but is not the headline**, and the gap to LOTO is
reported as a number. On the predicted corpus that gap is +0.09 to +0.14 R²;
whatever it is on measured data, it is the size of the memorisation.

Calibration follows `ANALYSIS-PLAN.md` §5 unchanged: Platt and beta both fitted
on a held-out fold, lower log loss wins, ties to Platt, isotonic excluded.

---

## 6. Pre-registered analyses

### 6.1 Primary
Predict measured `r` from X. Report per-fold mean ± sd under LOTO; pooled
figures are visualisation only.

### 6.2 Calibration
Predicted vs observed `r`, binned by predicted value, with exact binomial
intervals on the observed flow counts. Calibration slope and intercept. This is
the claim the arm exists to support: **when the model says 10%, the observed
fraction of affected flows is 5–15%**.

### 6.3 Mechanism-within analysis — the real test
`mechanism` is legitimately predictive: it is which construct an operator
changed, it is visible in the config, and that blackholes have small blast
radius while cost changes span a wide one is a true property of what passes a
five-property spec, not a generator artifact. Predicted mechanism R² on
severity is **0.3741** and is reported, not engineered away.

The pre-registered test is therefore **within-mechanism**: fit and evaluate
separately on the `cost` candidates and on the `blackhole` candidates, and
report whether the model beats the per-mechanism mean. A model that only
separates the two constructs has learned nothing about networks.

### 6.4 Transfer
Train on the 12 primary topologies, evaluate on the 8 held-out ones. Those have
a different severity distribution by construction, so this measures transfer
under distribution shift and is reported as such rather than as a headline
accuracy.

### 6.5 Auxiliary arm
`shutdown` and `exact` are generated and measured separately and never pooled
with the primary corpus. `shutdown` is expected to fail the SPEC gate and is
the control that the gate does what we predict.

---

## 7. Mandatory shortcut and leakage reporting

Reported **in the same table as every learned number**. Not optional, not an
appendix.

### 7.1 Recoverability
Worst-case one-vs-rest AUC for `repair_class` and for `mechanism`, from the
exact feature set that produced the learned result, on the exact
PASS-conditioned rows, grouped by incident. This is `ANALYSIS-PLAN.md` §14.2's
rule applied to this arm.

### 7.2 Association table
R² of measured severity against: `repair_class`, `mechanism`, `topology`,
repair id, quantile index, generation order, and every `chg_*` feature
individually. Predicted-corpus values for reference:

| | predicted |
|---|---|
| topology | 0.0091 |
| repair_class | 0.0681 |
| mechanism | 0.3741 |
| quantile index | 0.1119 |
| generation order | 0.0185 |

### 7.3 Shortcut-only model
Random forest on identity, provenance and diff-shape features only, evaluated
LOTO, reported against the full-feature model. If the shortcut-only model is
within 0.05 R² of the full model, the full model has demonstrated nothing.

### 7.4 Predicted vs measured
Correlation and mean absolute error between `severity.Fabric` predictions and
measured `r`, plus the confusion between predicted and measured SPEC verdict.
Divergence is a finding about model-vs-device, not a defect to hide.

---

## 8. GO / NO-GO

Fixed now, so that stopping is a decision and not a rationalisation.

**GO — the arm is reportable as a blast-radius model.** All four:

1. LOTO R² on **measured** `r` ≥ 0.40, with a clustered-bootstrap CI excluding 0.
2. The within-mechanism model beats the per-mechanism mean by ≥ 0.15 R² on
   **both** `cost` and `blackhole`.
3. Calibration slope in [0.8, 1.2], intercept within ±0.05, and observed
   fraction inside the predicted bin's interval in ≥ 3 of 4 bins.
4. The shortcut-only model of §7.3 is **more than 0.05 R² below** the
   full-feature model.

**WEAK — report as underpowered, not as a negative.** LOTO R² ≥ 0.40 but a CI
touching 0, or criterion 2 met on one mechanism only. Per `ANALYSIS-PLAN.md` §4,
underpowered and negative are different claims.

**NO-GO — the arm is not reportable as a learned contribution.** Any of:

- shortcut-only model within 0.05 R² of the full model;
- within-mechanism model fails to beat the per-mechanism mean on both
  mechanisms;
- measured `r` degenerate — fewer than 20 distinct values, or over 70% at a
  single value;
- `repair_class` or `mechanism` recoverable at AUC ≥ 0.85 **and** learned
  performance tracking that recoverability across ablations.

**STOP AND FIX — methodology, not result.** Any of: predicted vs measured SPEC
verdict disagreeing on more than 10% of candidates; terminal `LAB_INVALID` over
5% after retry; golden controls not identical; measured `r` disagreeing with
predicted `r` by mean absolute error > 0.10 (the analytic model was validated at
36/36, so a large divergence means one of the two is wrong and both must be
re-examined before any model is fitted).

---

## 9. Evidence this design rests on

| claim | evidence |
|---|---|
| the analytic severity model reproduces FRR | 6/6 blackhole candidates exactly; 30/30 cost and shutdown interventions across 3 topologies after the ECMP fix — **36/36 total** |
| path measurement matches the frozen labeller | `outcome_of()` replayed 301/301 frozen Phase 3 labels, 0 mismatches |
| flow measurement is sound | golden baselines 24/24 reachable on 6 topologies, 0 probe errors |
| `r` is deterministic | 12/12 candidates identical across replicate pairs |
| the binary target is not | Gate 0, 0/40 outcome flips under randomised churn |

**Every predicted number in this document is exactly that — predicted.** The
random-forest R² figures quoted during design (LOTO 0.76, later 0.87) were
computed on *predicted* severity, i.e. a forest approximating a Dijkstra. They
are function approximation, not evidence, and they do not appear in §8. The
thresholds in §8 apply to **measured** severity only.

---

## 10. Revision history before the freeze

Recorded so the design's history is auditable rather than implied.

| # | change | cause |
|---|---|---|
| 1 | severity-targeted operators replace fixed operators | v2 `correct` was 12/12 at r=0, P(r=0)=1.00; class bands disjoint |
| 2 | value-range quantiles replace list-position quantiles | corpus was bimodal, 183/378 under r=0.06 |
| 3 | `incomplete` draws from the whole catalogue | restricting it to flow-breaking interventions capped it at 0.119 and made mechanism a perfect class tag |
| 4 | primary set restricted to 12 topologies | topology R² 0.5521; eight designs can emit only high severity |
| 5 | repair ids relabelled by target | ids emitted in severity order, repair_id R² 0.8404 |
| 6 | `RC-noop` added | corpus had no zeros and median 0.389 |
| 7 | **`cost + blackhole` replaces `cost + shutdown`; SPEC gate enforced in selection** | `shutdown` fails P08 at 100%; 42% of the corpus could not enter the population, and `blackhole` — the canonical false-pass case — had been excluded to flatten a metric |

Revisions 1–6 were driven by leakage and distribution diagnostics. Revision 7
was driven by a correctness failure the design was not tuned against, and is the
reason this freeze exists: a design revised under review needs a lock before the
data arrives, not after.

---

## 11. Claims

**Permitted, if §8 GO is met:** that the blast radius of a SPEC-passing change is
predictable from pre-deployment evidence on this artifact, with a stated
calibration quality, LOTO transfer, and the shortcut table alongside; that
blast radius decomposes into broken and rerouted flows; the predicted-vs-measured
divergence of the analytic model.

**Not permitted, under any result:** anything about `P(harm | PASS)` as a
probability (that is the v2 arm, and its verdict is NO-GO); any prevalence or
base-rate statement from this corpus; transfer to real networks, other vendors,
other protocols, or ECMP-bearing networks — ECMP was deliberately removed, and
that is a stated limitation, not an oversight; any claim that the model sees
something Batfish fundamentally cannot, since the blast radius of a change is in
principle derivable from the RIB that Batfish already models.

---

# 12. Amendments

Each amendment is dated, states what changed and why, and says what evidence
existed at the time. Nothing here alters §8's thresholds; where an amendment
interacts with a threshold it says so explicitly.

## 12.1 Corpus as built — recorded 2026-09-12

**Status when written:** the corpus exists (`data/pilot-v3`, commit `ff432ca`,
tag `built-v3-corpus-n151`, artifact digest
`6d1b7348e9ca4c58f5da314f5a9e4a121f3217534bf55662337cb0498e2086e3`). **No
Batfish snapshot has been analysed, no lab has run, and no model has been
fitted.** Every number below comes from the build and from the analytic
predictions that selected the candidates. Nothing is regenerated, deleted,
overwritten or altered by this amendment; it is a document change only.

Three facts emerged from the build that §1–§11 did not anticipate. All three
were found by the build's own integrity checks, not during analysis.

### 12.1.1 The corpus is 151 candidates, not 215

§1.4 predicted 215. That count was taken **before configuration
de-duplication**. The build emitted 215 class-labelled repairs, of which **64
rendered byte-identical configurations** and were dropped, leaving **151**.

| | §1.4 predicted | as built |
|---|---|---|
| candidates | 215 | **151** |
| severity range | 0.000 – 0.448 | 0.000 – 0.448 |
| median | 0.097 | **0.058** |
| distinct values | 81 | **91** |
| zero-severity | 14 | 14 |
| per topology | 15 – 20 | **10 – 16** |
| by mechanism | — | cost 79, blackhole 72 |
| predicted SPEC verdict | all PASS | **151/151 PASS** |

**151 supersedes 215 everywhere.** §8's thresholds are unchanged: none of them
is a function of corpus size.

### 12.1.2 `repair_class` is void in this corpus

Of the 64 dropped configurations, **59 are cross-class collisions**:

    correct    <- regressive   28
    correct    <- incomplete   25
    incomplete <- regressive    6

The classes draw from overlapping selection pools, so the *same* `(mechanism,
target)` intervention is emitted under different class labels. Which label
survives is decided by **emission order alone** — `correct` is emitted first and
therefore wins 53 of the 59 collisions, which is why it holds 65 of 151 rows.

The leakage audit measured `repair_class` R² = 0.068 on severity and read that
as "nearly uninformative". **That reading was wrong.** The variable does not
carry a weak signal; it carries no content. A given configuration would have
been labelled `correct` or `regressive` depending only on the order the
generator happened to emit it in.

**Consequences, binding:**

1. `repair_class` is **not provenance and not a finding**. It must not appear in
   any table, figure, claim or interpretation of the v3 arm. It must not be
   described as a repair taxonomy, because in this corpus it is not one.
2. It is **retained in `manifest.json` and `meta.json` unchanged**, because the
   corpus is frozen and regenerating it to drop a field would destroy the
   artifact digest for a cosmetic gain. It stays as an audit trail of what the
   generator did, labelled void.
3. It remains **banned from X** by §4, as before. No model is affected.
4. §7.1 required recoverability of `repair_class` **and** `mechanism`. The
   `repair_class` half is **void** — measuring whether features can recover a
   label assigned by emission order answers nothing. The `mechanism` half is
   unchanged and remains mandatory.
5. §8's NO-GO clause "`repair_class` or `mechanism` recoverable at AUC ≥ 0.85
   **and** learned performance tracking that recoverability" now reads as the
   `mechanism` clause alone. **The threshold value 0.85 does not change**; one
   of its two inputs has been found not to exist.

The v2 arm is untouched by this. There `repair_class` is a genuine generator
variable, recoverable at AUC 0.975, and its status as a declared threat
(`ANALYSIS-PLAN.md` §14.2) stands unchanged.

### 12.1.3 The secondary split was degenerate; replaced

v3 has **no faults**. Every candidate is the golden scenario plus one
intervention, so `incidents/` holds 12 baselines containing the golden network
unmodified, each with an empty `golden_to_faulted.diff`. **Incident identity is
therefore topology identity**, and §5's secondary protocol — "nested grouped
5-fold CV grouped by incident" — is the primary leave-one-topology-out split
with a different fold count. It tests nothing the primary does not.

**§5's secondary protocol is replaced by two genuinely non-degenerate
analyses.** The primary protocol is unchanged: **12-fold
leave-one-topology-out**.

**Secondary A — leave-one-mechanism-out, 2 folds, both directions reported
separately.** These are not symmetric and must never be averaged:

- **train `cost` (0.000–0.448) → test `blackhole` (0.007–0.097).**
  Interpolation: the test range lies inside the training range. This is a fair
  transfer test.
- **train `blackhole` (0.007–0.097) → test `cost` (0.000–0.448).**
  **Extrapolation beyond the training range by a factor of ~4.6.** A model
  cannot be expected to predict severities it has never seen, so this is a
  stress test whose failure is uninformative about the model and informative
  about the corpus. Reported as such, never as a model failure.

**Secondary B — grouped 4-fold by topology, 3 topologies per fold.** Same
grouping variable as the primary but more training data per fold, so the gap
between it and 12-fold LOTO measures sensitivity to training-set size rather
than to the grouping.

Random CV remains reported with its gap to LOTO, and remains not the headline.

### 12.1.4 What this amendment does not change

No threshold in §8 moves. No mechanism, topology, selection rule, quantile,
target definition or feature ban is altered. The corpus is not regenerated: its
artifact digest after this amendment is the same as before it, which is
verified in the commit that carries this text.

## 12.2 The Batfish gate for a corpus with no faults — recorded 2026-09-12

**Status when written:** the corpus exists and is unchanged (`ff432ca`, digest
`6d1b7348…`). Batfish has been *queried* by the spike and by
`analysis/v3_batfish_precheck.py`, both read-only. **Phase 2 has not run and no
Batfish dataset has been produced.**

**The problem.** `spike_frr_batfish.py` is the gate `run_phase2.py` obeys. Two
of its six checks are written against fault snapshots:

- **CHECK 5** — is the `static_route_loop` fault family observable to Batfish?
- **CHECK 6** — do static routes reach the RIB, read off a `static_blackhole`
  fault?

§12.1.3 recorded that v3 has no faults. Neither construct appears in any
incident snapshot, both checks skip, and the spike scores a skipped check as
**FAILED** — correctly, because a check that did not run has not passed. The
verdict is therefore STOP and Phase 2 is blocked.

Two defects were found while establishing this and are fixed in
`spike_frr_batfish.py`: both skip paths printed `SKIPPED`, set the check False,
and then fell through into the body, calling `bf.set_snapshot(None)` and raising
`ValueError`. The guards are the only semantic change to that file — verified by
`git diff -w` showing nothing else — so v2's behaviour is unaltered.

**The resolution.** `pipeline/spike_v3.py` is the v3 gate. It **invokes the real
spike as a subprocess** and reads its verdict file; checks 1–4 are therefore the
frozen logic byte for byte, not a reimplementation. A gate that reimplements
what it verifies is a gate that can lie, and this arm already produced one
instance of exactly that — a consistency check that rebuilt the build-scope
filter instead of importing it and reported a file-count mismatch that did not
exist.

It then resolves the two fault-dependent checks, and only those two:

| check | disposition | reasoning |
|---|---|---|
| **CHECK 6 `statics`** | **SUBSTITUTED** | The question is whether Batfish installs a static route into the RIB. v3 *does* contain statics — 72 of 151 candidates are blackholes — they are in candidate snapshots rather than fault snapshots. Verified directly on candidates: route present, next hop `discard`, and `static` the only protocol listed for the prefix, so it beat OSPF on administrative distance and is installed. Same question, stronger evidence: read off the snapshots the corpus will actually use. |
| **CHECK 5 `f10_observable`** | **NOT APPLICABLE** | The question is whether Batfish can observe a fault family. v3 has none. No substitute evidence exists because there is nothing to substitute for. Recorded N/A and excluded from the verdict — marking an inapplicable check as passed would be as wrong as marking it failed. |

**Every other check must pass unchanged.** If any check outside those two fails,
the verdict is STOP. The underlying spike's own verdict is preserved verbatim in
the output under `underlying_spike.verdict_as_written`, so the substitution is
visible rather than buried.

**What this does not do.** It does not weaken checks 1–4, does not alter any §8
threshold, does not modify the corpus, and does not touch the v2 gate's
behaviour. It is a gate for a corpus the original gate was not written for, and
the substitution is recorded here so a reader can disagree with it.

## 12.3 Correction to §1.2's blackhole rationale — recorded 2026-09-12

**Status when written:** Phase 2 is complete (151/151 SPEC-PASS, verifier 29/29).
Phase 3 has not run.

§1.2 justified including `blackhole` by writing that it "breaks hosta→hostc,
which is P03/P04 — oracle-only — so the SPEC gate never asks and the repair
passes." **The mechanism named there is wrong.** Measured on the built corpus:

- All **72** blackhole candidates target a **router loopback /32**, not a host
  LAN. `repairs_v3.endpoint_prefix()` returns a loopback for a router endpoint
  and a LAN prefix for a host endpoint, and the severity-quantile selector
  happened to choose router endpoints throughout.
- **P03/P04 PASS on all 151 candidates.** The oracle-only property blackholes
  actually surface in is **P11** (edgea→edgeb loopback), and only for **9 of
  72**; the other 63 break no property in the suite at all.

**The conclusion §1.2 drew survives; the route to it does not.** Blackhole does
pass the SPEC gate while damaging forwarding, which is what it was included
for. It simply does so through P11 rather than P03/P04, and for far fewer
candidates than the rationale implied. No mechanism, threshold, selection rule
or target definition changes.

**What Phase 2 additionally establishes, and it is the arm's subject:**

| | n | predicted severity |
|---|---|---|
| at least one oracle-only property FAILs | 39 | 0.009 – 0.448, median 0.324 |
| every one of the 12 properties PASSes | 112 | 0.000 – 0.364, median 0.041 |
| **all 12 PASS and predicted blast radius > 0** | **98** | 0.007 – 0.364, median 0.047 |

98 of 151 candidates are ones Batfish's full twelve-property suite — SPEC and
oracle-only together — reports as entirely clean, while the analytic model
predicts their forwarding changed for up to 36% of flows. Whether that gap is
real is exactly what Phase 3 measures; the severity figures above are
predicted, not measured, and must not be quoted as results.

## 12.4 Calibration is not executable as written; the replacement is derived, not searched — recorded 2026-09-14

**Status when written: POST-RESULT.** Phase 3 is complete, measured `r` exists,
and calibration results from several implementations have been seen (listed
below). Nothing in this section is pre-registered in the sense of §0. It is a
disclosed deviation. The protocol it specifies was written and committed
**before its own result was computed**, and it is run once.

### 12.4.1 Why §5 / §6.2 / §8.3 cannot be executed as written

1. **§5 "follows `ANALYSIS-PLAN.md` §5 unchanged" is impossible.** The frozen
   `nrl.phase4.PlattCalibrator` and `BetaCalibrator` are logistic regressions on
   class labels. On continuous `r` they raise
   `ValueError: Unknown label type: continuous`. Any calibrator is an adaptation.
2. **The split calibration lived in no longer exists.** §5 attached calibration to
   the secondary nested 5-fold protocol, and §12.1.3 voided it. The plan does not
   say which predictions §8.3 scores.
3. **"Exact binomial intervals on the observed flow counts" (§6.2) has no sampling
   model behind it.** `r` is deterministic given the configuration (§3). Flows are
   not Bernoulli trials. Flows of one candidate share one configuration and one
   SPF tree, and candidates of one topology share the network. The frozen code
   already states the rule this violates (`nrl.phase4.clustered_bootstrap`):
   *"Resampling candidates ignores the clustering and produces intervals that are
   too narrow."* Flow-level resampling is one level further down.
4. **§6.2 contradicts itself.** Its claim sentence is ±5 points ("says 10% →
   5–15%"). Its interval is ±0.004 to ±0.011 per bin at this corpus size.
5. **§6.1 / v2 §5 say per-fold metrics are primary.** A LOTO test fold holds 10–16
   candidates, on which neither a slope nor four bins is estimable.

### 12.4.2 What was seen before this protocol was written

| predictions scored | slope | intercept | bins, flow-count CP | bins, ±0.05 | bins, topology bootstrap |
|---|---|---|---|---|---|
| analytic Dijkstra, MAE 2e-5 (control) | 1.000 | 0.000 | 4 | 4 | 4 |
| raw 12-fold LOTO, no calibrator | 0.967 | +0.001 | 2 | 4 | 4 |
| Copilot nested 5-fold, raw | 0.933 | +0.006 | 0 | 4 | 4 |
| Copilot nested 5-fold, beta calibrated | 0.691 | +0.021 | 0 | 3 | 2 |
| frozen `nested_cv` structure, 5-fold, calibrated | 0.902 | +0.000 | 2 | 4 | 4 |
| LOTO outer, 3 random calibration topologies, flow-weighted loss | 0.819 | +0.025 | 1 | 4 | 3 |

**§8.3 as literally pre-registered (flow-count exact binomial interval) is
recorded as FAILED.** It fails for every learned model tried and passes only for
the analytic control. The last row is the closest relative of the protocol below.
It differs in how calibration topologies are chosen and in loss weighting. The
protocol below had not been computed when this was committed.

### 12.4.3 The replacement protocol — each choice and its source

| choice | specification | source |
|---|---|---|
| predictions scored | calibrated predictions from calibration **nested inside the primary 12-fold LOTO** | §5 "fitted on a held-out fold"; §12.1.3 leaves LOTO as the only protocol |
| inner split | for held-out topology *i* (sorted order, index `gi`): `inner = nrl.phase4.grouped_folds(train topologies, 4, seed=gi+1)`; `inner[0]` fits the calibrator, the rest fit the model | frozen `nested_cv`: `max(2, k_outer-1)` = 4 inner folds, seed `gi+1`, `inner[0]` |
| model reuse | the **same** fitted model scores the calibration fold and the test topology; no refit | frozen `nested_cv`. A refit applies a map learned on one model to another |
| calibrators | Platt on `logit(s)`; beta on `[log s, −log(1−s)]`; `s` clipped to [1e-6, 1−1e-6]; unpenalised | frozen `PlattCalibrator`, `BetaCalibrator`, `_logit` |
| calibrator loss | mean over candidates of `−[r log p + (1−r) log(1−p)]` | frozen `log_loss`, a per-row mean. It reduces to it exactly for r ∈ {0,1}. One row is one candidate; flows are not the unit |
| selection | lower calibration-fold loss wins; ties go to Platt | ANALYSIS-PLAN.md §5 |
| estimator | `HistGradientBoostingRegressor(learning_rate=0.05, max_iter=300, max_leaf_nodes=15, l2_regularization=1.0, random_state=0)` | the plan names none; this is the estimator all reported gate-1 figures used |
| slope, intercept | OLS of measured `r` on calibrated prediction, pooled over the 12 test folds. Thresholds unchanged. Per-fold slope mean ± sd and a topology-clustered bootstrap CI reported as diagnostics | pooling is forced by 12.4.1(5); §8.3 thresholds are point thresholds |
| bins | 4 equal-frequency bins by calibrated prediction (`np.argsort(kind="stable")`, `np.array_split`) | frozen `N_CALIBRATION_BINS = 4`, equal-frequency |
| observed fraction | mean measured `r` of the bin's candidates | one candidate is one unit, as in the loss |
| interval | 95% percentile interval from **2,000 topology-clustered bootstrap resamples, seed 0**. Topologies are resampled with replacement, bin membership stays fixed per candidate, and a resample with no member in a bin is skipped for that bin | v2 §6: "reliability curve with a clustered bootstrap band (primary)"; frozen `clustered_bootstrap` (2,000, seed 0) |
| bin passes | the bin's mean calibrated prediction lies inside that interval | §8.3 |
| criterion 3 | slope in [0.8, 1.2], \|intercept\| ≤ 0.05, ≥ 3 of 4 bins pass | §8.3, **unchanged** |

**Feature tier.** §4 classes Tier C as a specification finding, not a learned
one. All four §8 criteria are therefore computed on **Tier B** (the learned
claim) and on **Tier C** (the full-feature model §7.3 compares against), and both
are reported. A learned blast-radius claim requires Tier B to pass. A pass on
Tier C alone supports only the specification finding.

### 12.4.4 Binding rules

- The protocol runs **once**, from the commit that carries this text. The script
  records the commit hash.
- **Sensitivity is reported and cannot change the verdict:** 10 further inner
  seeds, flow-weighted loss, the literal flow-count interval, and the ±0.05 claim check.
- **If amended criterion 3 fails, no further calibration variant is tried.**
  The arm is then reported without any calibration claim.
- A pass is never reported as plain GO. It is reported as **GO under amendment 12.4,
  with pre-registered §8.3 failed**.

### 12.4.5 Reporting corrections, same table as every learned number

1. §7.3's shortcut uses identity, provenance **and** diff-shape features
   (mechanism, repair_class, repair_id, quantile index, generation order, `chg_*`).
   An earlier audit used `chg_*` only.
2. Tier C is reported separately from Tier B (§4).
3. §12.1.3 Secondary A is reported in its own framing: cost → blackhole is the
   interpolation test, and its result stands whatever it is.
4. **Mandatory baseline:** a zero-parameter LOTO lookup of `mechanism × verdict_P06`
   (one oracle-only Batfish verdict), reported beside the learned model.
5. **§6.4 (transfer to the 8 held-out topologies) and §6.5 (auxiliary
   `shutdown`/`exact` arm) were not executed.** They are recorded as not run, not
   as passed or failed.

No threshold in §8 moves. No corpus, label, target, feature ban or measurement changes.
