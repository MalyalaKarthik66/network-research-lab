# FINAL PLAN — consolidated after external review (v2)

**Date:** 2026-09-02
**Supersedes:** `docs/RESEARCH-PLAN-v2.md`, and v1 of this file.
**Reviews incorporated:** Perplexity Pro, Gemini Pro, ChatGPT deep research — all three, complete.

This document is the single plan of record. Nothing in it has been executed.

**What changed from v1 of this file:** ChatGPT's review arrived after v1 was written. It
confirmed most of v1's decisions, corrected two citations, and raised one class of objection
the other two only touched in passing — **generator confounds** — which is now the largest
substantive change (§3.10–3.12). It is also the most pessimistic of the three on novelty and
publishability, and that pessimism is now reflected in §3.13 rather than argued away.

---

# 1. Current situation

## 1.1 What exists and is verified on disk

| item | state |
|---|---|
| `data/pilot-v1` | Phases 1–4 complete. 50 candidates, 24 Batfish-PASS, 12 SAFE / 12 HARMFUL → P(harm\|PASS)=50%. Do not modify. |
| `data/pilot-v2` | Phase 1 only. 1,793 candidates, 100 incidents, 10 topologies, 10 goldens, suite 1.1.0. `snapshot_digest f1a49e3c…`, `artifact_digest 16635513…`. **No `phase2/`, no `phase3/`.** |
| repair mix | correct 450 / regressive 453 / incomplete 890 across 37 operators, largest 100/1,793. No `exact_revert`. 1,307 duplicate AFTER-configs dropped at build. |
| fault families | 10 families × 10 incidents, balanced |
| gates passing | `test_topology_aware.py`, `test_batching.py`, both pure-Python |
| gates never run on v2 | `verify_pilot`, `spike_frr_batfish`, `verify_golden_properties`, all of Phase 2 and 3 |
| version control | **none.** `.gitignore` present, no `.git` |

## 1.2 Where we actually are

Phase 1 of v2 is built and structurally sound. **Zero labels exist for v2.** Every
methodological decision in this document is therefore still legitimate to make — that window
closes the moment the first Phase 3 batch runs, and this is the last point at which the
analysis plan can be frozen honestly.

Four blockers (B1–B4) stand between here and any expensive run, plus two code defects found
in audit and eight changes driven by the three reviews.

---

# 2. What must change before any expensive experiment

## 2.1 Blockers — nothing runs until these are done

**B1. `verify_phase3.py` is hardcoded to pilot-v1.** CHECK 2 expects `golden` + `I-01…I-10`
+ exactly 50 candidates; CHECK 8 expects delta rows for all manifest candidates while
`--only-passing` runs only the PASS subset. Under v2 it fails on every check — loudly, but
*after* the compute. **Fix:** rewrite manifest-derived; expected run set = goldens for every
topology in the lock + all incidents + exactly the candidates eligible under this run's own
filter.

**B2. No Containerlab-side golden gate; the harm definition can narrow silently.**
`HARM-DEFINITION.md` defines `G` as the oracle properties holding on the golden *measured in
Containerlab*. `run_phase3.py:418` computes `in_G` per candidate and looks for regressions
only inside it. If one property fails on a topology's golden lab it leaves the harm
definition for that whole topology, silently, and the false-pass rate drops. **Fix:** hard
gate — per topology, |G| must equal 12 or Phase 3 refuses that topology's candidates, naming
the failing property.

**B3. The FAIL arm.** `--only-passing` is right for the risk model and wrong for the
verification study. **Decision: 150 FAIL controls**, stratified by topology and family, with
a stated target: *rule out a Batfish-pessimistic rate above 2%*. Report the **Clopper–Pearson
exact interval** as primary (ChatGPT), with the rule of three (3/150 = 2.0%) as the intuition.

**B4. Label mapping.** `phase4.build_dataset` maps NO_CONVERGENCE, UNDETERMINED and
EXECUTION_FAILED to y = 0 (safe). All three reviewers call this blocking. **Fix per §4.6.**

## 2.2 Fix — defects found in code

- `spec_coverage_features` semantics: `spec.primary_path` holds transit nodes only, so
  `edgea`/`edgeb` — the ingress and egress of every SPEC property — are classified as
  off-primary in every topology, making `change_touches_backup_path_device` fire on the
  primary path. **Fix:** spec path = `primary_path ∪ {ingress, egress}`; rename the flag.
- `spec = spec or T2V1` fallbacks in `bf_eval`, `p3_eval`, `run_phase3.py:217` — make `spec`
  required.
- `phase4.BANNED_SUBSTRINGS` drops columns silently. Keep the filter, print the exclusions.

## 2.3 Add

- Git repository, initial commit, tag on the frozen definitions. **First action.**
- `docs/ANALYSIS-PLAN.md` — splits, metrics, bin counts, the one confirmatory test, stop
  rules, pre-specified MDEs. Dated and committed **before Stage 1**.
- Tier A+ graph features at build time (§4.5).
- Transient/convergence telemetry recording (§3.5).
- **LLM-generated repair arm** (§3.10) and **reference-derived topologies** (§3.11).
- `pipeline/spec_sweep.py`, `pipeline/attribute_harm.py` — pure analysis.
- `--fail-controls N`, `--replicate N`, `--llm-arm` in `run_phase3.py`.
- Within-incident ranking metrics in Phase 4.

## 2.4 Remove

- `--override-spike` from `run_phase2.py`.
- Dead pilot-v1 constants `bf_eval.HOST_ATTACH`, `bf_eval.EXPECTED_OSPF_PAIRS`,
  `p3_eval.SRC_NODE`.

## 2.5 Methodological issues resolved

1. Specification sweep was an uncorrected multiple-comparisons exercise → **nested
   pre-registered sequence, one confirmatory test** (§3.1).
2. Conformal on clustered data had no named method, no exact α floor → **hierarchical
   conformal, max-per-incident score, exact quantile, α floor stated** (§3.2–3.3).
3. Pooled out-of-fold predictions from five calibrators → **no inferential claim rests on the
   pooled curve** (§3.9).
4. `effective n` never entered the power calculations → **recompute all power numbers on
   effective n after Stage 0**.
5. **Generator confounds** — synthetic repairs, one topology generator, single run per
   candidate → §3.10–3.12.

## 2.6 Research-design changes

- Dataset reshaped from 10 × 10 × ~18 to **20 × 10 × ~9** (§3.4).
- Harm attributed to (a)/(b)/(c) per case (§3.6).
- Contribution reframed as **methodology + instrument** (§4.2).
- Venue: NOMS/CNSM primary, TNSM dropped (§3.13).

---

# 3. Reviewer findings — adopted, rejected, disagreements resolved

Where reviewers conflict, one decision is made and the reason given. Only items that change
the plan are listed.

## 3.1 ADOPTED — the sweep needs different statistics (3/3, blocking)

All three flagged it. Perplexity: nested overlapping subsets over the same candidates give
correlated points; naive Wilson CIs understate joint uncertainty; garden of forking paths.
Gemini: demanded FWER/FDR. ChatGPT: "violates exchangeability and inflates type-I error…
Bonferroni or permutation tests."

**Decision — remove the multiplicity by construction rather than correcting it after:**

- **One pre-registered nested sequence.** Add the seven oracle-only properties to SPEC one at
  a time in ascending id order (P03, P04, P06, P09, P10, P11, P12), declared in
  `ANALYSIS-PLAN.md` before any label exists. **8 nested points**, |SPEC| = 5…12. No subset
  sampling, no combinatorial explosion.
- **One confirmatory test:** P(harm | PASS) under SPEC-5 vs SPEC-12, paired at candidate
  level, **clustered permutation test resampling incidents**. Everything else on the curve is
  descriptive and labelled as such.
- **Clustered bootstrap band** over incidents, reported as simultaneous over the curve.
- Random subsets per size k appear in an appendix as sensitivity to the ordering rule.

Gemini's FDR/FWER and ChatGPT's Bonferroni are both rejected as the wrong instrument: with
one confirmatory comparison there is nothing to correct, and correcting a hundred exploratory
points would produce bands wide enough to say nothing. Note both were reviewing the *original*
sweep design; this redesign is the answer to their objection, not a rejection of it.

## 3.2 ADOPTED — conformal method named exactly (3/3, blocking)

All three named the same primary reference. Verified: **Dunn, Wasserman & Ramdas,
"Distribution-Free Prediction Sets for Two-Layer Hierarchical Models", arXiv:1809.07441,
JASA 118(544).** The correct ID is `1809.07441`; one pasted summary had `1809.07341`, a
different paper.

ChatGPT added a second, verified: **Principato et al., "Conformal Prediction for Hierarchical
Data", arXiv:2411.13479 (2024)** — group-aware calibration that reduces interval size while
keeping coverage. Cite both; use Dunn et al. as the method, Principato et al. as the
efficiency refinement.

**Decisions:**
- Two-layer hierarchical framework, subsampling variant.
- **Nonconformity score per incident = max** over that incident's candidates, not mean.
  Conservative, and this is a harm-control application.
- State the exact quantile: q̂ = ⌈(K+1)(1−α)⌉-th order statistic of the K incident-level
  scores; if ⌈(K+1)(1−α)⌉ > K then q̂ = ∞ and the bound is vacuous.
- **Two clustering levels.** Perplexity's unrequested critique, which neither other reviewer
  caught: incidents nest inside topologies and share nearly the whole base config, so
  incident-level calibration alone leaves topology-level dependence. Report **both** —
  incident-level as primary (new change, known network), topology-level as the conservative
  case (new network).

ChatGPT's framing that "incident-level calibration is not the correct fix… ignores
within-incident variation" is agreeing with the destination while criticising v1's shorthand;
the max-score hierarchical construction is what it asks for.

## 3.3 ADOPTED with a design change — the α floor (Gemini + ChatGPT, blocking arithmetic)

Both derived it independently and agree: with K calibration clusters, α < 1/(K+1) yields
q̂ = ∞. At K = 20 incidents the floor is ≈ 0.048, so v1's intended α = 0.05 was not
supportable.

**Decision: change the split, not the claim.** A dedicated grouped split of the 200 incidents
— **120 train / 40 calibration / 40 test** — gives K = 40 and a floor of 1/41 ≈ 0.024, so
α = 0.05 and α = 0.10 are both reportable. At topology level K = 20 → floor ≈ 0.048, so only
α ≥ 0.05 is claimable there, stated as a limitation.

## 3.4 RESOLVED DISAGREEMENT — dataset shape

Gemini **disagreed** with 20 × 5 (thins within-topology sampling, degenerate
per-family-per-topology cells). Perplexity **agreed** but caught the arithmetic: with 5
incidents and 10 families, each topology hosts at most half the families, so **family and
topology become confounded**. ChatGPT **agreed** with the reallocation and noted only the
variance cost, suggesting topology be treated as a random effect.

Both objections are right and v1's 20 × 5 was wrong.

**Decision: 20 topologies × 10 incidents × ~9 candidates ≈ 1,800 candidates.**

| property | 10×10×18 (current) | 20×5×18 (rejected) | **20×10×9 (final)** |
|---|---|---|---|
| candidates / Phase 3 cost | 1,793 | ~1,800 | **~1,800 — unchanged** |
| topologies, LOTO folds | 10 | 20 | **20** |
| incidents (conformal groups) | 100 | 100 | **200** |
| family × topology crossing | full | **confounded** | **full** |
| incidents per family | 10 | 10 | **20** |
| PASS candidates per incident (at 48%) | ~8.6 | ~8.6 | **~4.3** |

Resolves both objections and doubles the conformal group count. Cost: ~4 PASS per incident
instead of ~9 — still enough for within-incident ranking (needs ≥2), less within-incident
strategy diversity. Accepted trade.

ChatGPT's random-effects suggestion is adopted in weaker form: report per-topology rates with
Wilson intervals and a between-topology variance estimate, rather than fitting a mixed model
on 20 groups.

**Gemini's orchestration-overhead argument is rejected on the facts:** every candidate is its
own lab deploy and teardown, so Phase 3 cost is per-candidate. Twenty topologies adds twenty
golden builds — minutes — and nothing else.

## 3.5 ADOPTED — transient/convergence measurement (Gemini, "what is missing")

The harness measures at a quiescent point ≥45 s after deploy, so a repair that restores
connectivity while flapping adjacencies four times scores SAFE. The study therefore measures
gaps (a) and (c) and almost none of (b) — which matters, because if the rate is driven
entirely by specification incompleteness, the honest conclusion is "write more properties"
and the contribution shrinks.

**Decision, scoped:**
- Record during the convergence window already being polled: time to converge, RIB change
  count per router, adjacency state transitions after the first Full, and reachability
  sampled every 5 s from deploy.
- **Primary label stays harm definition v1.1.0, binary, unchanged** — pilot-v1 comparability
  survives.
- **Pre-register secondary definition v1.2.0**, dated now, before any v2 label exists:
  harmful if v1.1.0 harmful **or** the candidate flaps/blackholes during convergence. Report
  both. Declaring it now is what makes it legitimate.

## 3.6 ADOPTED — per-case a/b/c attribution (Perplexity, "what is missing")

Turns "we measured 30% false-pass" into "18 points specification incompleteness, 9 model
scope, 3 model-vs-device." Data already collected; zero extra compute. Pre-registered rule:

- **(a)** Batfish reported the violated oracle-only property as FAIL — the verifier knew,
  nobody asked.
- **(b)** Batfish reported PASS and the violation is visible only in transient telemetry, or
  resolves at steady state.
- **(c)** Batfish reported PASS and the violation persists at converged steady state.

## 3.7 ADOPTED — calibration details (3/3)

- Fit **both Platt and beta calibration**; select by log loss on an inner split, rule
  pre-registered; report both. Beta calibration: **Kull, Silva Filho & Flach, AISTATS 2017,
  PMLR v54** — ChatGPT's attribution, verified. Gemini cited it as NeurIPS 2017, which is
  wrong; use ChatGPT's.
- Isotonic not used; reason stated (O(n) effective parameters at n_cal ≈ 170).
- Report inter-fold calibrator variance (Platt slope/intercept across outer folds).

## 3.8 ADOPTED — label treatment (3/3)

NO_CONVERGENCE → y = 1. UNDETERMINED and EXECUTION_FAILED **excluded and reported**, never
silently y = 0. Plus, from Gemini and reinforced by ChatGPT's mechanism argument (undetermined
outcomes plausibly correlate with riskier changes, so dropping them biases the rate
*downward*): report **Manski partial-identification bounds**, P_min = HARMFUL/N and
P_max = (HARMFUL + UNDETERMINED + EXEC_FAILED)/N. Report exclusion rate **by topology and by
fault family** (Perplexity), not just overall.

## 3.9 SHARPENED — pooled out-of-fold predictions (3/3)

All three flagged it. Gemini: don't pool. Perplexity: legitimate, report inter-fold variance.
ChatGPT: "akin to cross-conformal prediction, which requires careful theory."

Three of three is enough to change the language rather than just add a diagnostic.
**Decision: per-fold metrics (mean ± sd) are primary; the pooled out-of-fold curve is a
visualisation only, and no inferential claim rests on it.** The conformal guarantee already
comes from the dedicated 120/40/40 split, not from pooling, so nothing load-bearing depends
on it.

## 3.10 ADOPTED — LLM-generated repair arm (3/3 flagged the confound; promoted from deferred)

All three independently raised the synthetic-generator confound. ChatGPT stated it most
directly: *"all 'repairs' come from synthetic operators, not real fixes — this could bias the
harm rate."* v1 of this plan deferred an LLM arm for scope discipline. Three independent
reviewers naming the same confound overrides that.

**Decision: add 150 LLM-generated candidates across 30 incidents** spanning all 10 fault
families and at least 10 topologies, run through the identical pipeline.

Why this is worth the scope increase, and not scope creep:
- It is the **only** change that answers the confound all three named.
- It makes the paper's motivating framing — *LLM-proposed* repairs — literally true rather
  than a stand-in, which is currently a soft spot in the introduction.
- It creates a **distribution-shift test**: does the false-pass rate, and does the risk model,
  hold on repairs from a different generator? Informative either way.
- Cost: API calls plus ~72 additional labs (~2 h), because only the Batfish-PASS subset
  reaches Phase 3.

It runs at Stage 4, after the main arm, so it cannot destabilise the primary measurement.

## 3.11 ADOPTED — reference-derived topologies (ChatGPT)

*"All topologies are generated by one algorithm, limiting generality."* Correct, and cheap to
partially fix.

**Decision: of the 20 topologies, derive 4 by hand from published reference architectures**
(a three-tier campus design, a small ISP PoP, a hub-and-spoke WAN, a collapsed-core branch)
rather than from `make_topology()`. Report results split by generated versus reference-derived
so the generator's contribution to the rate is visible rather than assumed away.

## 3.12 ADOPTED — measurement stochasticity (ChatGPT)

*"The emulator is run only once per candidate, so any stochastic convergence issues are
ignored."* v1 had 30 random replicates. ChatGPT is right that random replicates mostly sample
easy cases.

**Decision: 40 replicates, stratified** — 20 random, 20 drawn from candidates whose Phase 3
measurement sat near a decision boundary (partial packet loss, convergence time in the top
decile, or any property that flipped between polls). Report label agreement overall and for
the boundary stratum separately. The boundary agreement rate is the real noise floor.

## 3.13 RESOLVED DISAGREEMENT — novelty and publishability

The three diverge, and this is the most important disagreement in the set.

| reviewer | verdict |
|---|---|
| Perplexity | Publishable if the measurement, sweep and bound are bundled. Not TNSM — a journal bar a single-generator ≤16-router study will not clear. |
| Gemini | Publishable only if repositioned entirely as a systems measurement study with the negative ML result demoted. |
| ChatGPT | Hardest line: contributions "too incremental"; a negative ML result is "at best a workshop or short paper"; likely rejection for lack of substance. |

**Assessment.** ChatGPT is evaluating the worst-case outcome as though it were the plan, and
it under-weights the measurement contribution — which stands independently of any model, and
which the vendor itself declines to publish. But three independent reviewers landing on
"novelty is thin" is not noise, and the right response is to strengthen the contribution, not
to argue with them.

**Decisions:**
1. **Venue: NOMS or CNSM full paper, primary. IM alternate. TNSM removed** unless the
   measurement result is strong *and* the transient arm produces a real (b) component.
   Plan for a short/poster track as an acceptable landing spot.
2. **The strengthening is §3.5, §3.6, §3.10 and §3.11 taken together** — a real (b)
   component, a causal decomposition, a second repair generator, and non-generated
   topologies. Those four convert "we measured a rate on our own artifact" into "we measured
   a rate, decomposed its causes, and showed it survives a change of repair generator and
   topology source." That is the answer to "too incremental", and it is affordable.
3. **The intro states the framing explicitly:** this is a methodology and an instrument plus
   a measurement on a public artifact, not a universal rate for network verification. That
   sentence is the rebuttal to the strongest rejection reason and it appears early, not in
   limitations.
4. If the ML arm shows no signal, **"machine learning" comes out of the title** (§9).

## 3.14 REJECTED, with reasons

| suggestion | source | why rejected |
|---|---|---|
| Integrate Config2Spec as a mined-spec baseline | Gemini ("must"), ChatGPT | Infeasible in budget — research code requiring Minesweeper; integrating it is a project in itself. Answered instead by the nested sweep plus an explicit statement that mined specs are the strongest baseline, are future work, and still inherit the same model scope (a mined spec cannot see reconvergence either). Perplexity required only that the objection be answered, not that the tool be integrated. |
| Full multi-protocol BGP redesign | Gemini ("must") | Rejected wholesale; **adopted in limited form** — second OSPF area or route redistribution on 4 of the 20 topologies, so "does the rate hold outside single-area OSPF" gets a partial answer without rebuilding the artifact. |
| Discard binning entirely | Gemini | Too absolute. Continuous curve + Brier–Murphy + Spiegelhalter is primary; a 4-bin equal-frequency table stays as an illustrative supplement because it is what a practitioner reads. Perplexity and ChatGPT both endorsed that ordering. |
| Bonferroni / FDR across the sweep | Gemini, ChatGPT | Wrong instrument once the sweep is a single pre-registered nested sequence with one confirmatory test (§3.1). |
| Gemini's citations: "Beyond Pinning: Conformal Prediction for Clustered Data, arXiv 2202.10630"; Config2Spec credited to Nelson; beta calibration as NeurIPS 2017 | Gemini | **Unverifiable or wrong.** Config2Spec's first author is Birkner; beta calibration is AISTATS 2017 (PMLR v54). Do not cite anything from that review without checking. ChatGPT's and Perplexity's reference lists both verified clean. |

---

# 4. Final research structure

## 4.1 Research question

**Primary.** Among network configuration repairs that pass a formal verification gate, what
is P(harm | PASS) when executed in an emulated network, how does it decompose into
specification incompleteness / model scope / model-vs-device, and how does it vary with
specification strength?

**Secondary (selection).** Given several verification-passing repairs for one incident, can a
risk model rank them so acting on the lowest-risk one reduces realised harm relative to
choosing arbitrarily?

**Tertiary (control).** Can the risk estimate support a distribution-free bound: auto-apply
the lowest-risk fraction, hold expected harm among them at ≤ α?

**Robustness.** Do the rate and the model survive a change of repair generator (LLM vs
parametric) and topology source (generated vs reference-derived)?

## 4.2 Contribution — final wording

1. **An instrument and a measurement.** An open harness that measures P(harm | verification
   PASS) on any FRR-emulable network, and the first published rate on an open artifact — with
   the specification/oracle gap declared and frozen before any label existed.
2. **A causal decomposition** of that rate into (a) specification incompleteness, (b) model
   scope, (c) model-vs-device, per case.
3. **A specification-completeness curve** separating residual risk more properties can remove
   from residual risk they cannot.
4. **A calibrated residual-risk layer** over the PASS population, with an autonomy–risk curve
   and a hierarchical conformal bound valid under incident clustering.
5. **A generator-robustness check** — the rate and the model evaluated on LLM-generated
   repairs and on reference-derived topologies.
6. Open dataset, harness and analysis code.

**Cannot claim:** first verifier-vs-emulator comparison (arXiv 2608.11340); first calibrated
or conformal change-risk prediction (JIT defect-prediction literature); first LLM
configuration-repair benchmark (Cornetto); anything about production networks, or about
vendors, protocols or scales not tested.

## 4.3 Dataset structure

`Topology → Incident (fault) → Candidates (repairs) → Batfish verdict → Containerlab outcome`

X = Dataset 1 (config/topology features) + Dataset 2 (Batfish outputs); y from Dataset 3
(Containerlab outcome), restricted to the Batfish-PASS population.

## 4.4 Topology / incident / candidate design — final

| quantity | value |
|---|---|
| topologies | **20** — 16 generated, **4 derived by hand from published reference architectures** |
| protocol surface | 16 single-area OSPF/static, **4 with a second area or route redistribution** |
| topology sizes | 4–8 routers (14), **12–16 routers (6)** |
| incidents per topology | **10 — one per fault family, fully crossed** |
| total incidents | **200** |
| incidents per family | **20** |
| candidates per incident | **~9** (3 correct / 3 regressive / 3 incomplete, post-dedup) |
| main-arm candidates | **~1,800** |
| **LLM arm** | **150 candidates across 30 incidents**, all families, ≥10 topologies |
| expected Batfish-PASS | ~865 main + ~72 LLM |
| expected HARMFUL | ~430 (at pilot's 50%) |

## 4.5 Feature tiers — final

- **Tier A** — config diff only (`change_stats`, `spec_coverage` with corrected path
  semantics). Available before any verification.
- **Tier A+** — A plus hand-computed graph features: degree / betweenness / eigenvector
  centrality of changed devices; distance from changed device to the spec path; bridge
  (cut-edge) status; edge and node connectivity before and after; shortest-path count
  ingress→egress before and after; fraction of all-pairs shortest paths through the changed
  device; change in cost-weighted diameter. All permutation-invariant, all computable at
  inference time.
- **Tier B** — A+ plus Batfish spec-gate outputs (parse health, RIB/adjacency counts,
  differential reachability vs the incident snapshot).
- **Tier C** — B plus Batfish's verdicts on the oracle-only properties. **Not a learned
  contribution** — it answers "what would asking more questions achieve?" and feeds §4.11.

Banned from X, unchanged: `fault_family`, `repair_id`, `repair_class`, `incident_id`,
`candidate_id`, anything derived from `golden_to_candidate.diff`. The leakage filter now
prints what it removed.

## 4.6 Ground-truth label — final

| outcome | primary (v1.1.0) | sensitivity |
|---|---|---|
| HARMFUL | y = 1 | y = 1 |
| SAFE | y = 0 | y = 0 |
| NO_CONVERGENCE | **y = 1** | excluded |
| UNDETERMINED | **excluded**, counted | Manski bounds |
| EXECUTION_FAILED | **excluded**, counted | Manski bounds |

Report P_min and P_max. **If P_max − P_min > 10 points the harness is too fragile to support
the claim** — that is a stop condition. Exclusion rates reported by topology and family.

Secondary definition **v1.2.0**, pre-registered now: harmful if v1.1.0 harmful **or** the
candidate flaps/blackholes during the convergence window. Telemetry recorded: time to
converge, RIB change count per router, adjacency transitions after first Full, reachability
sampled every 5 s from deploy.

**Label noise floor:** 40 stratified replicate labs (20 random, 20 boundary), agreement
reported overall and for the boundary stratum, treated as the ceiling on every calibration
claim.

## 4.7 Model and architecture — final

**Primary: gradient-boosted trees** (scikit-learn `HistGradientBoosting` or LightGBM) on Tier
A+ / B / C. Move Phase 4 off the hand-rolled numpy models.

- **CNN: no.** No canonical node ordering, so an adjacency-matrix image is
  permutation-sensitive; ~700 training rows against 10⁴–10⁶ parameters; the signal is
  graph-theoretic scalars. **All three reviewers agreed without reservation.**
- **GNN: declared ablation only**, ≤50k parameters, heavily regularised, reported honestly
  either way. Both Gemini and ChatGPT note pretraining/transfer would be the only route to
  viability at this n; that is stated as future work.
- Also run: regularised logistic regression (interpretable reference), random forest
  (robustness), decision stump (shortcut detector), base rate (floor).

## 4.8 Calibration — final

- Nested grouped CV: 5 outer folds; within each, 3 sub-folds fit the model, 1 fits the
  calibrator, 1 held out. Grouping by incident at **every** level.
- **Platt and beta calibration both fitted**; selection by log loss on an inner split, rule
  pre-registered; both reported. (Kull et al., AISTATS 2017.)
- **Per-fold metrics (mean ± sd) primary. The pooled out-of-fold curve is a visualisation
  only; no inferential claim rests on it.**
- Inter-fold calibrator variance reported as a diagnostic.
- Isotonic not used; reason stated.

## 4.9 Evaluation metrics — final

**Calibration.** Continuous reliability curve (smoother, clustered bootstrap band) primary;
Brier with Murphy decomposition; Spiegelhalter z; ECE with equal-frequency bins and bootstrap
CI. Four equal-frequency bins as an illustrative supplementary table only.

**Discrimination.** AUC-PR primary, AUC-ROC secondary.

**Selection.** Per-incident top-1 accuracy (is the lowest-risk candidate SAFE?), mean
per-incident AUC, and **regret** versus choosing uniformly at random among that incident's
PASS candidates.

**Decision usefulness.** Autonomy–risk curve: coverage vs realised harm rate, hierarchical
conformal bound overlaid.

**Verification study.** The 2×2 with Wilson intervals; P(harm|PASS) overall, per topology,
per family, **and split generated vs reference-derived, parametric vs LLM**; the a/b/c
decomposition; optimistic vs pessimistic property disagreements with the Clopper–Pearson
bound from the FAIL arm; the specification-completeness curve.

Not headline: accuracy, F1.

## 4.10 Statistical methodology — final

- Wilson intervals for proportions; **Clopper–Pearson exact** for the zero-count FAIL-arm
  bound, rule of three as the intuition.
- **All bootstraps resample incidents**, 2,000 resamples.
- Clustered permutation test for the one confirmatory sweep comparison.
- DeLong or paired clustered bootstrap for AUC comparisons; McNemar for classifier errors.
- Spiegelhalter z for calibration.
- **Pre-specified MDE for LOTO and LOFO**, so an underpowered null is distinguishable from a
  negative finding.
- One confirmatory test; everything else declared exploratory. No FDR correction, by design.
- All power numbers recomputed on **effective n** after Stage 0.
- Between-topology variance reported; no mixed model fitted on 20 groups.

## 4.11 Specification-completeness experiment — final

Nested pre-registered sequence, |SPEC| = 5 → 12, adding oracle-only properties in ascending id
order. At each point recompute which candidates would have passed and the resulting
P(harm | PASS). Clustered bootstrap band over incidents. **One confirmatory test: SPEC-5 vs
SPEC-12, clustered permutation.** Random-subset variants in an appendix as sensitivity. Zero
additional compute.

## 4.12 Risk / autonomy evaluation — final

Hierarchical conformal risk control — Dunn et al. (arXiv:1809.07441) as the method, Principato
et al. (arXiv:2411.13479) as the efficiency refinement — subsampling variant, **max
nonconformity score per incident**, exact quantile q̂ = ⌈(K+1)(1−α)⌉-th order statistic with
q̂ = ∞ when that index exceeds K. Dedicated grouped split 120/40/40 incidents → K = 40, floor
α ≈ 0.024, so α = 0.05 and 0.10 are reportable. Topology-level variant reported as the
conservative case (K = 20, floor ≈ 0.048).

---

# 5. Execution path, in order

| # | step | gate before moving on |
|---|---|---|
| 1 | `git init`, commit, tag `frozen-defs-v1.1.0` | history exists |
| 2 | B1 — `verify_phase3.py` manifest-derived | rewritten, reviewed |
| 3 | B2 — \|G\|=12 gate in `run_phase3` | gate refuses on a deliberately broken golden |
| 4 | B4 — label mapping + Manski bounds + exclusion reporting | unit-tested |
| 5 | `spec_coverage` path semantics; remove `spec or T2V1`, `--override-spike`, dead constants; leakage filter prints | `test_topology_aware` green |
| 6 | Tier A+ graph features at build time | present in `meta.json` |
| 7 | 10 new topologies — 4 reference-derived, 4 multi-area/redistribution, 6 at 12–16 routers; reshape to 20 × 10 × ~9 | `test_topology_aware` green on 20 specs |
| 8 | Transient telemetry in `clab.py` / `run_phase3.py` | recorded on a hand-run lab |
| 9 | `docs/ANALYSIS-PLAN.md` + harm definition v1.2.0, **dated and committed** | committed before any label |
| 10 | Rebuild pilot-v2; Stage 0 gates | §6 |
| 11 | **Stage 1** validation | §6 |
| 12 | **Stage 2** | §7 |
| 13 | **Stage 3** | §7 |
| 14 | **Stage 4** — main remainder + FAIL controls + replicates + LLM arm | §8 |
| 15 | Phase 4 analysis: sweep, attribution, calibration, conformal, ranking, learning curve, generator-robustness split | — |

Steps 1–9 are code and documents, no compute. **Do not reorder step 9 after step 11.**

---

# 6. Short validation test (Stage 1)

**Scope.** 2 topologies × 3 incidents — one small generated single-area topology, one
reference-derived or larger multi-area one, so the new artifact surface is exercised. All
candidates for those 6 incidents (~54), Phase 2 on all, Phase 3 on the PASS subset (~26), plus
**10 replicate labs** and the 2 goldens.

**Both Phase 2 and Phase 3 run.** Phase 2 alone proves nothing about labels.

```powershell
# Stage 0 -- ~15 min, no Docker
python pipeline\test_topology_aware.py
python pipeline\test_batching.py
Remove-Item -Recurse -Force data\pilot-v2
python pipeline\build_pilot_v2.py --profile c --topologies all
python pipeline\verify_pilot.py             --pilot data\pilot-v2
python pipeline\spike_frr_batfish.py        --pilot data\pilot-v2
python pipeline\verify_golden_properties.py --pilot data\pilot-v2 --negative-control
python pipeline\audit_dataset.py            --pilot data\pilot-v2

# Stage 1 -- ~1.5 h
python pipeline\run_phase2.py --pilot data\pilot-v2 --only <all candidates of the 6 incidents>
python pipeline\run_phase3.py --pilot data\pilot-v2 --only-passing --batch-size 30 --replicate 10
python pipeline\verify_phase2.py --pilot data\pilot-v2
python pipeline\verify_phase3.py --pilot data\pilot-v2
```

**Runtime.** ~15 min + ~1–1.5 h.

**Expected outputs.** ~54 Phase 2 rows with a PASS/FAIL mix; ~26 Phase 3 labs with labels; 10
replicate pairs; convergence telemetry; measured seconds-per-lab.

**GO criteria — all must hold.**

1. Stage 0: 16/16 structural checks; golden gate PASS on all topologies **with the negative
   control firing**; `audit_dataset` shows `repair_class` not recoverable from X above AUC
   0.85, zero empty golden diffs, effective n not catastrophically below row count.
2. |G| = 12 on every topology in Containerlab.
3. Phase 2 produces a **PASS/FAIL mix**.
4. **Replicate label agreement ≥ 95%.**
5. NO_CONVERGENCE < 5%; UNDETERMINED + EXECUTION_FAILED < 5%.
6. `verify_phase2` and the rewritten `verify_phase3` both pass.
7. Seconds-per-lab within 2× of the 100 s assumption.

**STOP and fix if:** any golden fails |G| = 12; replicate agreement < 95%; all PASS or all
FAIL; NO_CONVERGENCE ≥ 5%; either verifier fails; seconds-per-lab > 200 (the budget no longer
closes and the design must be resized).

---

# 7. Medium / staged testing

| stage | scope | added labs | runtime | check between stages |
|---|---|---|---|---|
| **2** | **Full Phase 2** on all ~1,800 (Batfish only), then Phase 3 on **150 PASS** stratified across all 20 topologies and 10 families | 150 | ~2–5 h + ~4 h | first false-pass rate with clustered CI; per-topology spread; class balance; exclusion rates by topology/family; Manski width; Batfish memory at ~1,800 snapshots |
| **3** | Phase 3 to **450 PASS** cumulative | +300 | ~+8.5 h | learning-curve points 2 vs 3; first calibration read; shortcut ablation; a/b/c attribution stable |
| **4** | Phase 3 to **865 PASS** + 150 FAIL controls + 40 replicates + LLM arm (~72 labs) | +667 | ~+18.5 h | final |

**Between every stage:** re-run `verify_phase2` / `verify_phase3`; ledger duplicates = 0;
golden replicate control still yields an identical property vector; recompute P_min/P_max.

**Continue** if checks hold and the rate is in 10–60%. **Pause** on any verifier failure or a
rate outside that band. **Stop collecting for the model** if the learning curve is flat from
Stage 2 to Stage 3 — redirect the remainder to the FAIL arm, replicates, LLM arm and sweep.

---

# 8. Final long experiment

| quantity | expected |
|---|---|
| main-arm candidates | ~1,800 |
| LLM-arm candidates | 150 |
| Batfish-PASS | ~865 main + ~72 LLM |
| HARMFUL / SAFE among PASS | ~430 / ~430 (at 50%) |
| Phase 3 candidate labs | ~937 |
| FAIL control labs | 150 |
| replicate labs | 40 |
| golden labs | 20 + per-batch replicates |
| **total labs** | **~1,150** |
| Phase 2 runtime | ~2–5 h |
| Phase 3 runtime | **~32 h** at 100 s/lab, staged and resumable |
| Phase 4 analysis | ~1–2 h |
| **total** | **~35–39 h**, spread over days |

**Final dataset:** ~1,950 candidates with Batfish verdicts on all 12 properties and full raw
question output; ~937 with Containerlab outcomes under harm definitions v1.1.0 and v1.2.0
plus convergence telemetry; 150 FAIL controls; 40 stratified replicate pairs; a/b/c
attribution per harmful-after-PASS case; generated-vs-reference and parametric-vs-LLM splits;
and the frozen analysis plan the results are read against.

---

# 9. Stopping and decision rules

| condition | decision |
|---|---|
| False-pass rate **< 2%** at Stage 2 | Specification too strong or faults too easy. Fix once, retry. Still <2% → publish the near-zero completeness finding honestly; trigger the fallback direction. |
| False-pass rate **> 60%** | Suspect the oracle, not the verifier. Premature convergence measurement produced exactly this bias once already. Debug before believing. |
| Rate in **10–60%** | Proceed. |
| **Replicate agreement < 95%** (overall or boundary stratum) | Stop. Fix the measurement layer. Everything downstream is bounded by this number. |
| **P_max − P_min > 10 points** | Harness too fragile. Fix the UNDETERMINED / EXECUTION_FAILED causes before claiming a rate. |
| **NO_CONVERGENCE ≥ 5%** | Investigate before scaling; check correlation with topology size — if it correlates, the large topologies are the problem and the design shrinks. |
| **Learning curve flat Stage 2 → Stage 3** | Stop collecting for the model. Redirect to FAIL arm, replicates, LLM arm, sweep. Write the negative result. |
| **No signal above base rate in Tier A+/B** | **Drop "machine learning" from the title.** Reframe as a measurement study on the operational boundaries of formal verification; non-learnability becomes a finding and the conformal bound the practical contribution. |
| **Spec-widening rule beats every learned model** (most likely) | Report as headline. The a/b/c decomposition and the sweep carry the paper. |
| **LLM arm rate differs materially from parametric arm** | That is a result, not a problem — report both and treat the parametric rate as generator-specific. |
| **LOTO fails but the pre-specified MDE says underpowered** | Report as underpowered, not as a negative finding. Pre-registered. |
| **Conformal q̂ = ∞ at the chosen α** | Report the α floor and the K that produced it. Do not lower α to make a bound appear. |
| **Any gate fires** | Fix the cause. Never bypass. No `--override-spike`. |

---

# 10. FINAL PLAN BEFORE EXECUTION — checklist

**Current state**
- [ ] pilot-v2 Phase 1 built (1,793 candidates, 10 topologies); no Phase 2/3 data; no labels
- [ ] pure-Python gates green; nothing Batfish/Docker has run on v2
- [ ] no version control

**Changes to repository**
- [ ] `git init` + commit + tag frozen definitions ← **first action**
- [ ] B1 `verify_phase3.py` manifest-derived
- [ ] B2 |G| = 12 gate
- [ ] B4 label mapping + Manski bounds + exclusion reporting by topology/family
- [ ] `spec_coverage` path = `primary_path ∪ {ingress, egress}`
- [ ] remove `--override-spike`, dead constants, `spec or T2V1`
- [ ] leakage filter prints exclusions
- [ ] Tier A+ graph features
- [ ] transient/convergence telemetry
- [ ] `--fail-controls`, `--replicate`, `--llm-arm`
- [ ] Phase 4 → scikit-learn; GBT primary; ranking metrics; nested grouped CV; hierarchical conformal
- [ ] `pipeline/spec_sweep.py`, `pipeline/attribute_harm.py`

**Changes to dataset / design**
- [ ] 20 × 10 × ~9 ≈ 1,800, full family×topology crossing
- [ ] 4 reference-derived topologies; 4 multi-area/redistribution; 6 at 12–16 routers
- [ ] 150-candidate LLM repair arm
- [ ] 40 stratified replicates (20 random, 20 boundary)
- [ ] rebuild; confirm digests move as predicted

**Changes to research methodology**
- [ ] `docs/ANALYSIS-PLAN.md` dated and committed **before Stage 1**
- [ ] harm definition v1.2.0 pre-registered; v1.1.0 stays primary
- [ ] nested spec sweep, one confirmatory test, clustered bootstrap band
- [ ] hierarchical conformal (1809.07441 + 2411.13479), max-per-incident, exact quantile, 120/40/40
- [ ] Platt + beta both fitted (Kull, AISTATS 2017); pooled curve is visualisation only
- [ ] all bootstraps resample incidents; Clopper–Pearson for the FAIL bound
- [ ] MDE pre-specified for LOTO and LOFO
- [ ] power numbers recomputed on effective n
- [ ] venue: NOMS / CNSM primary, IM alternate, TNSM removed

**Short test (Stage 1)** — 2 topologies × 3 incidents, Phase 2 + Phase 3, ~26 labs + 10 replicates, ~1.5 h
- [ ] GO: |G|=12 everywhere · PASS/FAIL mix · replicate agreement ≥95% · NO_CONVERGENCE <5% · both verifiers pass · s/lab ≤ 200

**Medium test** — Stage 2 (full Phase 2 + 150 PASS, ~9 h) → Stage 3 (450 PASS, +8.5 h)
- [ ] GO: rate 10–60% · exclusions <5% · Manski width ≤10 points · learning curve informative

**Long test** — Stage 4: to 865 PASS + 150 FAIL + 40 replicates + LLM arm, +18.5 h

**Final expected outputs**
- [ ] P(harm|PASS) with clustered CI — overall, per topology, per family, generated vs reference, parametric vs LLM
- [ ] a/b/c decomposition per harmful-after-PASS case
- [ ] specification-completeness curve with one confirmatory test
- [ ] calibrated risk model, reliability curve, Brier–Murphy, autonomy–risk curve
- [ ] hierarchical conformal bound at α = 0.05 and 0.10
- [ ] within-incident selection accuracy and regret
- [ ] learning curve; label-noise floor incl. boundary stratum; open dataset and harness

**Proceed when** every stage gate is green and no gate was bypassed.

**Stop when** replicate agreement < 95%, Manski width > 10 points, the rate is < 2% after one
fix, or the learning curve is flat — and in each case write up what was found rather than
tuning until something looks better.
