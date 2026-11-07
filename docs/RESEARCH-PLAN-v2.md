# Research and design plan — v2

**Project:** risk-calibrated autonomy for network configuration repair
**Status:** design review before the expensive Phase 2/3 runs. Nothing here has been executed.
**Written:** 2026-09-02
**Repository inspected:** `C:\Users\karth\network-research-lab`, `data/pilot-v2` on disk

This document is written to be handed to other reviewers. Where I am confident, I say so.
Where the evidence is thin, I say that too. Section 4 contains a novelty finding that
narrows what you are allowed to claim, and section 22 contains an arithmetic result that
forces the headline evaluation to change. Read those two first if you read nothing else.

---

## 1. Your original idea, and whether the reasoning is correct

Your reasoning is correct, and it is sharper than the version currently implemented.

You described it as a **selection** problem: Batfish says PASS to three repairs, and the
operator still does not know which to deploy. A risk layer ranks them, the lowest-risk one
is chosen. That framing is right, and it is the more compelling application.

The repository currently implements a **calibration** problem: estimate
P(harm | verification PASS) for each candidate independently. That is a strictly harder
requirement than ranking. Ranking within an incident only needs the scores to be ordered
correctly among candidates that share a fault; calibration needs the absolute number to
mean something across the whole population.

Both are worth having, and they fail differently. A model can be a useful ranker while
being badly calibrated, and it can be well calibrated while being useless for selection
(if every candidate in an incident gets the same score). **Recommendation: evaluate both,
and make within-incident ranking a first-class result rather than a corollary.** It maps
onto your motivating example, and it gives the paper a second result if global calibration
turns out weak. This is currently missing from the repository entirely.

One correction to the framing. Your phrasing "how confident should we be that Batfish is
right" invites a reviewer to reply *"Batfish is formally sound; you have misunderstood
verification."* Batfish is not wrong. It answers the question it was asked, about the model
it was given. The residual risk comes from three places, all of them outside soundness:

- **(a) specification incompleteness** — it proves the properties you wrote down. An outage
  caused by the property nobody wrote is not a verifier error.
- **(b) model scope** — converged steady state only. Reconvergence transients, timer
  interactions and flap are out of scope by design.
- **(c) model versus device** — ECMP hashing, TCAM limits, platform quirks, partial grammar
  coverage.

The defensible sentence is: *"the verification stack is sound with respect to its
specification and model scope; we measure how often a change that passes nonetheless causes
harm, and build a layer that predicts and bounds that residual risk."* Keep that wording.

---

## 2. The precise research question

**Primary.** Among network configuration repairs that pass a formal verification gate,
what is P(harm | PASS) when the repair is executed in an emulated network, and can that
residual risk be predicted from information available before deployment?

**Secondary (selection).** Given several verification-passing repairs for the same
incident, can a risk model rank them so that acting on the lowest-risk one reduces realised
harm relative to picking arbitrarily?

**Tertiary (control).** Can the risk estimate support a distribution-free bound of the form
*"auto-apply the lowest-risk k% of changes and the expected harm rate among them is at most
α"*?

The three are ordered by how much data they need. The first is a rate and needs the least.
The third needs a calibration set. The second needs candidates clustered by incident, which
you have by construction.

---

## 3. The proposed scientific contribution

1. An empirical characterisation of the **verification false-pass rate** across multiple
   topologies and fault families, with the specification/oracle gap declared in advance and
   frozen before any label exists.
2. A **specification-completeness sweep**: false-pass rate as a function of how much of the
   oracle is in the spec, separating risk that is recoverable by writing more properties
   from risk that is not. (New — see §26. This is the single most important addition.)
3. A **calibrated residual-risk model** conditioned on the PASS population, with an
   autonomy–risk curve as the evaluation metric in place of raw success rate.
4. **Conformal risk control** applied to network change management, giving an operator a
   tunable autonomy budget with a bound on harmful auto-applied changes.
5. Open dataset and harness.

Note what is *not* on this list: a novel architecture. See §19–20.

---

## 4. Novelty assessment and related work

I searched Batfish + ML, network verification, configuration repair and synthesis, LLM
network repair, conformal prediction in operations, change-risk prediction, and
verification-versus-emulation comparisons. One paper materially changes what you can claim.

### The paper that constrains you

**"Self-evolving network verifiers" (arXiv 2608.11340, August 2026)** uses almost exactly
your apparatus. LLM agents extend a symbolic verifier, and correctness is judged by
**differential testing against oracles that are Batfish and Containerlab-emulated FRRouting**.
Same tools, same comparison.

The difference is what they do with a disagreement. **They treat verifier-versus-oracle
disagreement as a bug in the verifier, to be repaired.** You treat it as a residual risk to
be quantified and controlled. They report convergence on models matching the oracle (e.g.
544/544 on OSPF areas); they do not report a rate, do not calibrate, and do not predict.
Critically, their gap is (c) model-versus-device. Yours is primarily (a) specification
incompleteness, which no amount of verifier repair fixes — a perfect verifier still cannot
prove a property nobody wrote.

**Consequence: you can no longer claim "first to compare a model-based verifier against an
emulator."** Delete that sentence if it appears in any draft. Cite this paper prominently in
the intro, and use it as independent evidence that the gap is real.

### The rest of the closest work

| Work | What it does | How yours differs | Threat |
|---|---|---|---|
| **Self-evolving network verifiers** (arXiv 2608.11340, 2026) | LLM agents repair a symbolic verifier; oracle = Batfish + Containerlab FRR | Disagreement is a bug to fix, not a risk to quantify; no rate, no calibration, no prediction; targets model-vs-device, not spec incompleteness | **High** — must be cited and distinguished in the intro |
| **Cornetto — Benchmarking LLM-Driven Network Configuration Repair** (arXiv 2604.22513, 2026) | Benchmarks LLM repairs; correctness judged by **Batfish data-plane verification against Config2Spec-mined specs**; reports Fix Score, Regression Rate, Success Rate (max 25.5%) | **Their ground truth is the verifier.** Yours tests exactly that assumption by executing the repair. No risk model, no calibrated probabilities — their metrics are binary spec satisfaction | **Medium** — complementary, and a usable data source. Also the source of the strongest objection: see below |
| **Evaluating Agentic Configuration Repair for Computer Networks** (arXiv 2606.06212, 2026) | Agentic repair evaluation | Could not retrieve full text (PDF not machine-readable, HTML fetch blocked). **Retrieve and read this before submitting.** Open risk | **Unknown — resolve it** |
| **Config2Spec** (NSDI '20, ETH) | Mines a near-complete specification from configurations | Directly relevant: it is the answer to "why not just write a complete spec?" | **High as an objection**, see below |
| **Validating the Validator** (Batfish, 2020) | Batfish's own model-validation process: feature/device/network benchmarks, nightly CI against real network data | **Explicitly does not quantify a disagreement rate.** The vendor says its models "are not guaranteed to be perfect" and publishes no number | **Supports you** — the rate is genuinely unpublished |
| **On the Calibration of Just-in-Time Defect Prediction** (MSR 2025); **Just-in-Time Conformal Defect Prediction** (2024) | Calibrated and conformal change-risk prediction for software commits | Same machinery, different domain, and **no verification-conditioned population** — there is no formal verifier in JIT defect prediction whose PASS defines the population | **Medium** — you cannot claim calibration or conformal for change risk is new; only the conditioning and the domain |
| **Confucius** (Meta, SIGCOMM 2025) | Multi-agent LLM netops in production; reports validation prevents regressions | You quantify how often it does not | Low |
| **STRATUS / TNR** | Hard invariant: detect regression, roll back | TNR assumes reliable regression detection and clean rollback; both false in networks (reverting config does not un-flap a session). You give a probabilistic guarantee where those assumptions fail | Low |
| **Interpretable Network Verification via Subspecifications** (APNet 2025) | Decomposes specifications for interpretability | Adjacent to spec incompleteness; cite | Low |
| **GNN networking literature** (RouteNet family, NetGenius, GNN routing optimisation) | Delay/throughput prediction, routing recommendation | None of it predicts config-change risk or conditions on a verifier verdict | Low — the space is open, which does not make a GNN appropriate (§20) |
| **AIOps outage prediction** (largely industry) | Predicts outages from telemetry | Telemetry-based and post-hoc; yours is pre-deployment from a config diff | Low |

### The objection most likely to kill the paper

> *"Your specification is five properties. Config2Spec mines near-complete specifications
> automatically. Your false-pass rate measures the weakness of your hand-written spec, not a
> property of verification."*

This is correct as stated and it is fatal if unanswered. Two responses, and you need both:

1. **Make specification strength a variable, not a constant.** Compute the false-pass rate
   for every subset of the oracle used as the spec — 5 properties, 6, 7, … 11 — and plot the
   curve. If residual risk decays toward zero, the honest finding is "write more properties";
   if it plateaus above zero, you have isolated risk that specification cannot remove, and
   *that* is the paper. Your pilot already hints at the answer: 7 of 12 harmful PASS
   candidates were recoverable by widening the spec, 5 were not. Turn that anecdote into a
   curve. **This converts the objection into your main result.**
2. **State plainly** that a mined specification is the strongest available baseline and that
   evaluating against one is future work, with the reason (Config2Spec's own cost, and the
   fact that mined specs inherit the same model scope — a mined spec still cannot see
   reconvergence).

### What you may and may not claim

**May not claim:** first to compare a model-based verifier to an emulator; first calibrated
or conformal change-risk prediction; first benchmark of LLM configuration repair.

**May claim:** first quantification of P(harm | verification PASS) as an operational rate
across topologies and fault families, with a frozen, declared specification gap; the
specification-completeness sweep separating recoverable from irreducible residual risk;
first application of conformal risk control to network change management; an autonomy–risk
curve as a risk-aware alternative to success rate; an open dataset and harness.

That is enough for a solid venue (NOMS, CNSM, TNSM, IM). It is not a SIGCOMM claim, and you
should not write it as one.

---

## 5. Current repository status — verified on disk

`data/pilot-v2`: 1,793 candidates, 100 incidents, 10 goldens, `suite_version 1.1.0`,
`snapshot_digest f1a49e3c…`, `artifact_digest 16635513…`, **no `phase2/`**. All 1,793
manifest entries carry a valid topology. `properties.yml` contains the `topology_resolved:`
block for all ten topologies.

Repair mix: correct 450, regressive 453, incomplete 890, across **37 distinct operators**,
largest 100/1,793. Fault families: ten, exactly 10 incidents each. Per-topology candidates
172–183.

Pure-Python gates pass: `test_topology_aware.py`, `test_batching.py`. Nothing requiring
Batfish or Docker has been run against pilot-v2.

---

## 6. What the previous implementation did

Four phases: Phase 1 builds goldens, incidents and candidates; Phase 2 runs Batfish on every
candidate; Phase 3 executes Batfish-PASS candidates in Containerlab; Phase 4 assembles the
dataset and trains models. Supporting machinery: a same-artifact guarantee (the exact bytes
Containerlab mounts are embedded in the Batfish snapshot, proven by an inverse function and
asserted per device per candidate), a deliberate split of `snapshot_digest` from
`artifact_digest` so an irrelevant edit does not invalidate good data, disk-as-state batching
with resume, and a long defect log.

Pilot-v1 result: 50 candidates, 24 Batfish-PASS, 12 SAFE / 12 HARMFUL → **P(harm | PASS) =
50%**, with 21 Batfish-optimistic and 0 Batfish-pessimistic property comparisons. Phase 4
found no learnable model once the trivial class was removed.

---

## 7. What to keep

Keep all of this. It is the strongest part of the project and most of it is unusual for
undergraduate work.

- **The same-artifact guarantee.** Without it Phase 2 and Phase 3 could measure different
  networks and the false-pass rate would be meaningless. Keep the per-device assertion.
- **The dual digest.** Correct design, and it earns its keep every time the property suite
  changes.
- **Disk-as-state batching and resume.** `an item is DONE iff its completion record exists`
  is the right contract. Keep the duplicate-execution counter.
- **The frozen SPEC/oracle split and the frozen harm definition**, including the dated change
  log and the requirement that a membership change bumps `SUITE_VERSION`.
- **The leakage rules**: provenance banned from X, grouped splits, features computable from
  the config diff at inference time.
- **The convergence policy** (≥45 s floor, no transitional neighbour, RIB stable over three
  5 s polls, 180 s timeout) and the reason it exists.
- **The defect log and `surprises.md`.** These are the motivation section of the paper.
- **`repairs_v2`'s two design rules**: no operator may emit golden, and every operator's
  content must derive from the fault. These directly kill the pilot-v1 shortcut.
- **The per-batch golden replicate control.**
- The measurement layer's runtime assertions: `verify_running_config`, `verify_addresses`,
  `stage_artifact` with expected hashes, transitional-neighbour detection.

---

## 8. What to remove

- **`--override-spike`** from `run_phase2.py`. A gate with a documented bypass is a gate that
  will eventually be bypassed at 2 a.m.
- **Dead module-level pilot-v1 constants**: `bf_eval.HOST_ATTACH`, `bf_eval.EXPECTED_OSPF_PAIRS`,
  `p3_eval.SRC_NODE`. They are currently policed as "defined, never read", which is a
  reasonable interim, but they are loaded guns — every one of them encodes a pilot-v1
  address or router set.
- **`phase4.BANNED_SUBSTRINGS` silent filtering.** It drops any column containing `golden`,
  `harm`, `label`, etc. without reporting what it dropped. Keep the filter, print the
  exclusions.
- **The `spec = spec or T2V1` fallbacks** in `bf_eval`, `p3_eval` and `run_phase3.py:217`.
  Make `spec` required; pilot-v1 reproduction can pass `T2V1` explicitly.

---

## 9. What to redesign

Four blockers, then four design changes.

**B1 — `verify_phase3.py` is hardcoded to pilot-v1.** CHECK 2 expects `golden` + `I-01…I-10`
+ exactly 50 candidates and asserts `kind counts are 1 golden / 10 incident / 50 candidate`.
CHECK 8 expects `len(manifest['candidates']) * len(PIDS)` delta rows — 1,793 × 12 — but with
`--only-passing` only the PASS subset runs. Under v2 every one of these fails. It fails
loudly, which is better than silently, but it fails **after** the 24 hours. Rewrite it
manifest-derived, the way `verify_phase2.py` already is.

**B2 — no Containerlab-side golden gate; the harm definition can narrow silently.**
`docs/HARM-DEFINITION.md` §Sets defines `G` as the ORACLE properties that hold on the golden
**measured in Containerlab**, and says "expected to be all 12; if it is not, the pilot is
broken." `run_phase3.py:418` computes `in_G` per candidate and looks for regressions only
within it. If one property fails or errors on a topology's golden lab, it drops out of the
harm definition for every candidate of that topology — no error, no warning, and the
false-pass rate goes down. `golden_properties_in_G` is recorded per row; nothing asserts it
equals 12. Add a hard gate: per topology, |G| must equal 12 or Phase 3 refuses to run
candidates for that topology.

**B3 — `--only-passing` deletes the FAIL arm.** Correct for the risk model, wrong for the
paper. Your headline 2×2 and the "0 Batfish-pessimistic" claim would rest on n=26 from one
topology while everything else scales to ten. See §15 for the sample-size answer.

**B4 — Phase 4 mislabels non-convergence as safe.** `phase4.build_dataset`:
`df["y_harmful"] = (df["outcome_harm_v1"] == "HARMFUL").astype(int)`. `run_phase3` emits
five outcomes; that line maps NO_CONVERGENCE, UNDETERMINED and EXECUTION_FAILED to **y = 0,
safe**. The frozen definition says NO_CONVERGENCE counts as harmful in the primary analysis.
Direction of error is optimistic in both cases. It did not fire in pilot-v1 because there
were no such rows; on 8-router topologies across hundreds of labs it will.

**D1 — reallocate the compute budget from candidates to topologies.** See §11.
**D2 — add the specification-completeness sweep.** See §26.
**D3 — add within-incident ranking evaluation.** See §27.
**D4 — add a measurement-reliability replicate arm.** See §16.

---

## 10. Dataset design

The design is scientifically suitable, with two caveats.

**What is right.** The pilot-v1 killer — SAFE was 83% `exact_revert`, so the model learned
"is this the revert?" — is designed out on purpose. `repairs_v2` forbids emitting golden and
requires fault-derived content; 37 operators, none dominant; duplicate AFTER-configs dropped
at build time (1,307 of them). At the pilot's 48% pass rate you would get roughly 860
PASS candidates and, at a 50% harm rate, ~430 positives. That is a real dataset.

**Caveat 1 — effective n is smaller than 1,793.** The correct class is mostly *parameter*
diversity: `RC-cost_norm_1..9` plus `loopback_cost_1..3` plus `both_cost_norm_1..4` is 340 of
450 correct repairs. Candidates differing only in an integer cost may share an identical
Tier-A feature vector, in which case they are one point to any Tier-A model however many
rows the CSV has. `pipeline/audit_dataset.py` (already on your disk) computes the distinct
feature-vector count. **Report effective n, not row count.** It is what sets how tight a
conformal interval can be.

**Caveat 2 — a semantic bug in an ML feature.** `spec.primary_path` holds transit nodes
only: t01 is `['corea','coreb']`, t07 is `['agga','corea','coreb','aggb']`. `edgea` and
`edgeb` appear in **no** topology's primary path. So `spec_coverage_features` places them in
`off_primary_nodes`, and a change touching only `edgea` gets
`change_touches_backup_path_device: True` and `spec_covers_changed_devices: False`. Those two
routers are the ingress and egress of every SPEC property. The earlier fix corrected the
denominator and left the semantics. Fix: define the spec path as
`primary_path ∪ {ingress, egress}`, and rename the flag to what it measures.

---

## 11. Topology design

**Ten topologies is enough for incident generalisation and thin for topology generalisation.**
Leave-one-topology-out gives ten folds, so any statement about between-topology variance
rests on ten points.

The important observation is that **topologies are nearly free and candidates are not**. The
Phase 3 cost driver is labs, i.e. candidates. Adding topologies while holding the candidate
budget fixed costs minutes in Phase 1 and nothing in Phase 3.

**Recommendation: 20 topologies × 5 incidents × ~18 candidates ≈ 1,800 candidates.** Same
compute, double the topology diversity, twenty LOTO folds instead of ten. This is a strictly
better allocation of an unchanged budget, and it is the single cheapest improvement available.

Also add **size diversity**. Current range is 4–8 routers, which is small and uniform. Add
two or three topologies in the 12–16 router range so "does residual risk grow with network
size?" is answerable. Containerlab memory is the constraint — FRR is roughly 100–200 MB per
container, so 16 routers plus 3 hosts is comfortable on 16 GB, but run one by hand and
measure before committing.

Keep the structural variety you have (chain, star, ring, mesh, tiers, dual-WAN, deep
hierarchy) — that part is good and it is what makes LOTO meaningful.

---

## 12. Incident and failure design

Ten families, ten incidents each, is a reasonable spread and covers the configuration-fault
space Batfish can actually see (it never consumes telemetry, so "high CPU" is not a fault
you can inject).

Two additions worth the effort:

- **A family that targets model scope (b), not just spec incompleteness (a).** Every current
  family is a static misconfiguration. A fault whose harm is transient — a cost change that
  causes a long reconvergence, or a change that induces a temporary micro-loop — probes the
  gap Batfish is *designed* not to see. If the false-pass rate is driven entirely by (a),
  the paper's answer is "write more properties" and the contribution shrinks. You need (b)
  represented to show the irreducible part.
- **Stratify difficulty deliberately.** Record, per incident, whether the golden→incident
  diff touches the primary path. Incidents off the primary path produce repairs whose harm is
  invisible to a reachability-only spec, which is exactly the interesting cell.

Under the 20-topology reallocation, 5 incidents per topology × 20 = 100 incidents, so each
family still gets 10. Keep that balance; it makes leave-one-family-out clean.

---

## 13. Candidate and repair design

Three classes (correct / regressive / incomplete) is right, and `repair_class` is correctly
treated as *design intent*, not ground truth — Phase 3 decides, and the field is banned from
X. Keep that.

The weakness is honestly stated in the code's own docstring: diversity is mostly parameter
diversity, not strategy diversity, "because a small single-area OSPF network admits few
genuinely distinct correct configurations." That is true and it caps what the dataset can
show. Two mitigations:

- **Widen the protocol surface.** Adding a second area, or route redistribution, or a
  route-map on a boundary, multiplies the number of genuinely distinct correct repairs and
  the number of ways a repair can be subtly wrong. This is the highest-value change to the
  artifact, and it is Phase-1 work, so it is cheap.
- **Consider LLM-generated repairs for a subset.** This is what makes the paper's motivation
  land — the framing is about *LLM-proposed* repairs — and it removes the "your repairs come
  from a generator with a signature" objection for that subset. Even 150 LLM-generated
  candidates across 20 incidents, as a held-out distribution-shift arm, would be
  disproportionately valuable. Cost is API calls, not compute.

**Test before trusting Tier A:** `repair_class` is banned from X, but if `change_stats`
predicts it accurately then a model can rediscover the generator's signature and any Tier-A
"signal" is that shortcut in new clothes. Section 3 of `audit_dataset.py` tests this with no
labels required. AUC above ~0.85 there means Tier A is contaminated and must be reported as
such.

---

## 14. Batfish stage

Sound as built. Every candidate gets all twelve properties evaluated and the full raw
question sweep serialised; the SPEC-only gate is applied by the runner, not baked into the
evaluator, so Batfish's opinion on the oracle-only properties is preserved for analysis.
That distinction — "the verifier could not have known" versus "nobody asked it" — is what
makes the specification-completeness sweep possible, and it is already in the data.

`RULE 1` (a harness error is never a FAIL; status OK/ERROR is separate from verdict
PASS/FAIL) is correct and non-negotiable. Keep it.

Two things to verify before the full run, both cheap:

- Parse health on every candidate, not just goldens. `parseWarning` being empty is not
  evidence that a construct was modelled — FRR `access-list` and `ip ospf network broadcast`
  both parsed silently to nothing in this project's history. The spike's construct-coverage
  check (where `checked=0` on a present construct is a failure) is the right instrument;
  make sure it runs on the v2 artifact.
- The golden property gate must pass on every topology with a negative control, so that a
  green result is known to be discriminating rather than merely green.

---

## 15. Containerlab stage

The measurement layer is the most carefully built part of the repository, and it is where
the project's credibility lives. Runtime state is asserted rather than inferred
(`verify_running_config` exists because FRR once echoed `shutdown` while leaving the
interface up), interface scope is restricted to artifact interfaces, convergence is polled
rather than slept on, and each batch carries a golden replicate control.

Three changes:

**Add the |G| = 12 gate (B2).** Non-negotiable; the harm definition depends on it.

**Add a FAIL control arm (B3).** You do not need the whole FAIL population. You need enough
to bound the Batfish-pessimistic rate. If the true pessimistic rate is 0, then observing 0 in
n samples gives a 95% upper bound of 3/n (the rule of three). n = 100 gives "at most 3%";
n = 150 gives "at most 2%". **150 FAIL candidates, stratified across topologies and fault
families, is the right number** — roughly 4 hours of labs, and it converts a hand-wave into a
publishable bound. Anything beyond ~200 buys almost nothing.

**Be explicit about what "harm" measures.** `probe_ping` treats any received packet as
reachable, so 60% packet loss is recorded as HOLDS. That is a defensible binary definition
but it is a definition, and a reviewer will ask. State it in limitations, and consider
recording loss percentage and RTT as secondary severity signals (they are already captured in
`extra`) without changing the frozen binary label.

---

## 16. Ground-truth label definition

Keep the frozen definition. Fix the mapping and add a reliability measurement.

**The label.** For candidate *c* with golden property set *G* (the oracle properties that
hold on that topology's golden lab):

- `HARMFUL` if ∃ p ∈ G that fails in *c*
- `SAFE` if every p ∈ G holds in *c*
- `NO_CONVERGENCE`, `UNDETERMINED`, `EXECUTION_FAILED` otherwise

**The mapping into y**, which is what B4 gets wrong:

| outcome | primary analysis | sensitivity analysis |
|---|---|---|
| HARMFUL | y = 1 | y = 1 |
| SAFE | y = 0 | y = 0 |
| NO_CONVERGENCE | **y = 1** | excluded |
| UNDETERMINED | **excluded**, counted and reported | excluded |
| EXECUTION_FAILED | **excluded**, counted and reported | excluded |

Never silently y = 0. Report the excluded count in every table; if exclusions exceed ~5% of
the population, that is itself a finding about harness reliability.

**Measurement reliability — currently missing and important.** Calibration is only
meaningful up to label noise. If the same candidate can come out SAFE on one run and HARMFUL
on the next, the ceiling on achievable calibration is set by that flip rate, not by the model.
The golden replicate control tests reproducibility on the *healthy* case, which is the easy
case. **Add: re-run ~30 randomly chosen non-golden candidates a second time and report the
label agreement rate.** Cost is under an hour. If agreement is below ~95%, say so and treat
it as the noise floor in every calibration claim. This is a small experiment that a reviewer
will respect and whose absence they will notice.

---

## 17. Feature engineering

Three tiers, as currently designed, are the right structure because they answer different
questions. Keep the tiering; fix the contents.

- **Tier A — config diff only** (`change_stats`, `spec_coverage`): available before any
  verification. Currently ~14 live features after `matrix()` drops zero-variance columns —
  three of the eight `spec_coverage` fields (`spec_n_properties`, `oracle_n_properties`,
  `spec_fraction_of_oracle`) are suite-level constants identical on every row. Thin.
- **Tier B — A + Batfish spec-gate outputs**: parse health, RIB/adjacency counts, differential
  reachability versus the incident snapshot.
- **Tier C — B + Batfish's verdicts on the oracle-only properties.** **Tier C is not a
  learned contribution.** It answers "what would asking more questions achieve?" If C beats A
  and B, the finding is *widen the specification*, not *train a model*. Keeping that
  comparison honest is the entire point of the tiering, and it is what feeds the sweep in §26.

**Add Tier A+ — hand-computed graph features.** This is how you get topological signal
without paying the sample cost of learning graph structure (§20):

- degree, betweenness centrality and eigenvector centrality of each changed device
- shortest-path distance from the changed device to the primary path
- whether the changed edge is a cut edge (bridge) of the topology graph
- edge connectivity and node connectivity of the graph, before and after the change
- number of distinct shortest paths between the ingress and egress, before and after
- fraction of all-pairs shortest paths traversing the changed device
- change in the OSPF-cost-weighted diameter

All are cheap, deterministic, computable from the config diff plus the topology at inference
time, and permutation-invariant by construction. This block is where I would expect signal to
live if signal exists.

**Leakage discipline** (already in `docs/LEAKAGE.md`, keep it): `fault_family`, `repair_id`,
`repair_class`, `incident_id`, `candidate_id` and anything derived from `golden_to_candidate.diff`
are banned from X. The golden diff ban is right for a subtle reason — if you had the healthy
config you would deploy it, so it is not available at inference time.

---

## 18. Model choices

At n ≈ 700 training rows, ~50% positives, and ~25 features after adding Tier A+:

1. **Regularised logistic regression** — the interpretable reference. Coefficients are the
   feature-importance story the paper needs.
2. **Gradient-boosted trees** (LightGBM/XGBoost, or sklearn's `HistGradientBoosting`) — the
   realistic best performer on tabular data at this size. This should be your primary model.
3. **Random forest** — a robustness check, cheap.
4. **Decision stump** — kept deliberately: if one threshold on one feature separates the
   classes, that is a shortcut, not a model. Keep this diagnostic.
5. **Majority / base-rate baseline** — the floor.

The current numpy-only implementation was justified at n=24 for auditability. At n≈860 with
calibration, conformal, bootstrap CIs and a learning curve, hand-rolled models become a
liability rather than an asset. **Move to scikit-learn.** The venv already carries pandas and
numpy; adding scikit-learn is not a meaningful dependency risk, and reviewers trust a standard
implementation more than 100 lines of hand-written gradient descent.

---

## 19. Is a CNN appropriate?

**No. Do not use a convolutional network here.** Three independent reasons, any one of which
is sufficient:

1. **No grid structure.** A CNN's inductive bias is translation invariance over a regular
   grid — neighbouring pixels are meaningfully adjacent, and a pattern means the same thing
   wherever it appears. A network topology is a graph with **no canonical node ordering**. If
   you encode it as an adjacency matrix "image", relabelling the routers permutes rows and
   columns and produces a completely different image of the *same* network. A CNN would have
   to learn permutation invariance from data. That costs orders of magnitude more samples
   than you will ever have, and it is a known-solved problem — the solution is a GNN, not a
   CNN.
2. **Sample size.** A small CNN has 10⁴–10⁶ parameters. You have ~700 training rows. This is
   textbook overfitting, and with grouped splits it will look like noise across folds.
3. **The signal is not spatial.** What plausibly predicts residual risk is "did the change
   touch a cut edge", "is the changed device on the specified path", "did the number of
   equal-cost paths drop from 2 to 1". These are graph-theoretic scalars. Convolution over a
   matrix is a strictly worse way to extract them than computing them directly.

A note on wording: you wrote "AI and CNN", and elsewhere your project documents read "CN" as
Computer Networks. If you meant **Computer Networks + AI**, the project already is that, and
nothing needs to change. If you meant convolutional networks specifically, the answer above
stands.

The uncomfortable part, said plainly: **a CNN would make the paper worse, not better.** A
NOMS/CNSM/TNSM reviewer will not reward architecture novelty in a measurement-and-calibration
paper; they will ask why a 10⁵-parameter model was fitted to 700 points, and the paper will
be weaker for having to answer. Your resume is better served by a defensible result than by
the string "CNN" appearing in the abstract. The AI contribution here is the calibrated risk
layer and the conformal guarantee, not the layer type.

---

## 20. Is a GNN or another architecture better?

**A GNN has the right inductive bias and the wrong sample requirement.**

Right: permutation invariant, handles variable node counts, naturally encodes the topology
you actually have. If this project had 50,000 labelled candidates across hundreds of
topologies, a GNN over the router graph with per-node config-change features would be the
obvious architecture.

Wrong: at ~700 training examples with 20 topologies, a GNN will not beat gradient-boosted
trees on hand-computed graph features, and it will be much harder to defend.

**Recommendation.** Primary model: gradient-boosted trees on Tier A+B+graph features. Then
run a small GNN (2–3 message-passing layers, ≤50k parameters, heavy regularisation) as a
**declared ablation** and report the result honestly, whichever way it comes out. If it does
not beat the tabular model, that is a legitimate and interesting finding — "graph structure
helps, but as engineered features rather than learned representations, at the sample sizes
achievable in this setting" — and it is the intellectually honest way to include the deep
component you want.

**On the hybrid** (graph encoder + tabular encoder + fusion + calibrated head): scientifically
coherent, and the right architecture at 100× the data. At your scale it adds parameters and
degrees of freedom without adding information. Describe it in future work with the sample-size
argument; do not build it. Complexity you cannot support with data is a liability at review.

---

## 21. Calibration methodology

**Three-way grouped split, calibration fitted on data the model never saw.**

1. Fit the risk model on the training folds → raw score s(x).
2. Fit a calibrator on a **disjoint, grouped** calibration fold.
3. Evaluate on a **disjoint, grouped** test fold.

**Which calibrator.** At n_cal ≈ 170 use **Platt scaling** (a one-dimensional logistic
regression on the logit of s) or **beta calibration**. Do **not** use isotonic regression:
it is non-parametric with O(n) effective parameters and overfits badly below roughly 1,000
calibration points. State this choice and its reason in the paper — reviewers notice when
isotonic is used at small n.

Platt: p̂(x) = σ(a·logit(s(x)) + b), with (a, b) fitted by maximum likelihood on the
calibration fold only.

**Critical detail on cross-validated calibration.** A single 20% test fold gives ~170
evaluation points, which is not enough for a useful reliability curve (§22). Instead use
**nested grouped cross-validation**: in each of 5 outer folds, fit the model on 3 sub-folds,
the calibrator on a 4th, and predict the held-out 5th. Concatenating out-of-fold predictions
gives calibrated probabilities for **all ~860 candidates**, each produced by a model that
never saw that candidate's incident. That is the correct way to buy statistical power without
leaking, and it is standard practice.

---

## 22. What the risk percentage means mathematically, and how many buckets

**Definition.** The model estimates

> r(x) = P(Y = 1 | X = x, V(x) = PASS)

where Y = 1 is HARMFUL under the frozen harm definition v1.1.0 as measured in Containerlab,
X is the feature vector available before deployment, and V is the Batfish SPEC gate. **The
conditioning on V(x) = PASS is not decoration** — it defines the population, and it is why the
model must be trained only on PASS candidates. Your pipeline already does this.

**The claim you want to make** — "among candidates assigned ≈5% risk, about 5% are actually
harmful" — is a statement about calibration, and here is the arithmetic that determines
whether you can make it.

For a bin with true harm rate p and n candidates, the standard error is √(p(1−p)/n). For the
observed rate to be within ±5 percentage points at 95% confidence near p = 0.1 you need
n ≈ 138 **per bin**. Ten bins therefore need ~1,380 *evaluation* candidates. With a 20% test
fold that implies ~6,900 PASS candidates, ~14,000 total, and at ~100 s per lab that is
roughly **190 hours of Containerlab**. That is out of budget by an order of magnitude.

**Therefore:**

- **Do not use ten buckets.** With ~860 out-of-fold predictions, use **four equal-frequency
  bins** (~215 each, ±3.4 points at p = 0.1) or at most five. Use equal-*frequency*, not
  equal-width: equal-width bins are empty at the tails at this n and produce a reliability
  diagram whose extreme points are noise.
- **Report the reliability curve continuously** — a LOESS or isotonic smoother over the
  out-of-fold predictions with a bootstrap band — alongside the binned table. The curve does
  not depend on an arbitrary bin count.
- **Report Brier score with the Murphy decomposition**: BS = reliability − resolution +
  uncertainty. Reliability is the calibration term, resolution is the discrimination term.
  This decomposition is more informative than either AUC or ECE alone and is standard in
  forecast verification.
- **Report ECE with a bootstrap CI**, computed with equal-frequency bins, and state the bin
  count.
- **Test calibration formally** with the **Spiegelhalter z-test** (a proper test of the null
  that the forecasts are calibrated, with no binning) rather than Hosmer–Lemeshow, which is
  binning-sensitive and unstable at this n.

**The honest headline.** Given the arithmetic above, a full ten-row reliability table is not
achievable within your compute budget, and you should stop planning for one. The result that
*is* achievable and is more useful operationally is the **autonomy–risk curve**: for each
threshold t, the fraction of changes auto-applied (coverage) versus the realised harm rate
among them, with a distribution-free upper bound. It is one-dimensional, so it needs far less
data than ten independent bin estimates, and it answers the operator's actual question.

**Conformal risk control.** Choose λ so that auto-applying every candidate with r(x) ≤ λ
keeps expected harm among auto-applied changes at or below α. On a calibration set of size n,
the standard finite-sample construction picks λ̂ as the appropriate empirical quantile such
that the guarantee E[L] ≤ α holds under exchangeability. Two things you must state:

- **Exchangeability fails at the candidate level** because candidates are clustered by
  incident. The defensible fix is to form **one nonconformity score per incident** (e.g. the
  incident's mean or max loss) and calibrate at the incident level, or to use a cluster-robust
  conformal variant. Calibrating candidate-wise on clustered data yields a bound that does not
  hold, and a conformal-literate reviewer will go straight here. This is the single most
  likely methodological objection to the ML half of the paper.
- With ~20 calibration incidents, the achievable α is coarse — the finite-sample correction
  at n incidents is roughly 1/(n+1), so 20 incidents cannot support α much below ~0.05. Say
  so explicitly rather than reporting a bound the data cannot support.

---

## 23. Train / calibration / test methodology

Freeze all of this before looking at any Phase 3 output. Write it into `docs/` with a date.

**Primary protocol — grouped by incident, nested, 5-fold.** Model on 3 sub-folds, calibrator
on 1, evaluate on 1; rotate. Yields out-of-fold calibrated predictions for every candidate.
This is the protocol for the calibration and autonomy–risk results.

**Generalisation protocol — leave-one-topology-out.** 20 folds under the reallocation.
Answers "does the risk model transfer to a network it has never seen?" This is the claim
reviewers care about most, and it is the one most likely to fail. Report it whether or not it
does.

**Stress protocol — leave-one-fault-family-out.** 10 folds. Answers "does it generalise to an
unseen failure mode?" Hardest and most operationally relevant.

**Held-out sets, explicitly:**

- Unseen-topology test set: **yes**, via LOTO. Do not carve out a fixed topology holdout as
  well — with 20 topologies you cannot afford to spend some permanently.
- Unseen-fault-family test set: **yes**, via LOFO.
- A fixed final holdout: **no**. At this sample size, cross-validation with correct grouping
  is a better use of the data than a single holdout, provided the protocol is frozen in
  advance. Frozen-in-advance is what makes it legitimate; state the date.

**Sample-size targets** (under the 20-topology reallocation):

| quantity | target | reasoning |
|---|---|---|
| topologies | 20 | 20 LOTO folds; costs nothing in Phase 3 |
| incidents | 100 (5 per topology, 10 per family) | keeps LOFO balanced |
| candidates | ~1,800 | Phase 2 is cheap; this is the Phase 3 input |
| Batfish-PASS | ~850 (at 48%) | the modelling population |
| HARMFUL | ~425 (at 50%) | positives |
| SAFE | ~425 | negatives |
| training (per fold) | ~510 | 60% of PASS |
| calibration (per fold) | ~170 | Platt is fine here; isotonic is not |
| test (per fold) | ~170 | but use out-of-fold pooling for calibration curves |
| FAIL controls | 150 | rule of three: bounds the pessimistic rate at ≤2% |
| replicates | 30 | label-noise floor |

If the measured pass rate or harm rate differs markedly from the pilot, recompute these
before scaling. The stage gates in §32 exist for exactly that.

---

## 24. Leakage prevention

Keep `docs/LEAKAGE.md` as written and add three items:

- **Grouping must be by incident, everywhere** — including inside the calibration split.
  Candidates from one incident share a fault, a BEFORE state and most of their config.
- **Golden-derived anything is banned from X**, including `golden_to_candidate.diff` and
  anything computed from it. Already stated; enforce it in code, not only in the document.
- **The generator-signature test** (§13). Provenance being absent from X does not prove it is
  unrecoverable from X. Test it directly and report the number.
- **Print what the leakage filter removed.** A filter that silently drops columns is the same
  shape as every defect in your log.

---

## 25. Baselines

Every one of these must appear in the results table. Several are non-learned and one of them
beat every model in the pilot — that is a feature of the study, not an embarrassment.

1. **Base rate** — predict the training-set harm rate for everyone. The floor.
2. **Batfish PASS alone** — predict "safe" for everything that passed. This is the current
   state of practice and it is what your paper is arguing against; its harm rate *is* the
   false-pass rate.
3. **Spec-widening rule** — predict HARMFUL iff Batfish reports any oracle-only property
   failing. Deterministic, no learning. In pilot-v1 this caught 7 of 12 harmful with zero
   false alarms and beat every learned model. **If this wins again, that is the paper's
   result**, and the honest conclusion is "widen the specification".
4. **Count of failing oracle properties** — a graded version of (3), gives a ranking.
5. **Logistic regression** on Tier A, A+B, A+B+graph.
6. **Gradient-boosted trees** on the same tiers.
7. **Random forest.**
8. **Decision stump** — the shortcut detector.
9. **GNN** — declared ablation (§20).

---

## 26. Ablation studies

**The tier ablation** (A / A+B / A+B+C / A+B+graph) as designed, with the Tier C caveat kept
prominent: Tier C is Batfish answering more questions, not a learned contribution.

**The specification-completeness sweep — the most important experiment in the plan, and it
is currently missing.** Because Phase 2 records Batfish's verdict on all twelve properties
and Phase 3 measures all twelve, you can retroactively define SPEC as any subset and
recompute the false-pass rate without running anything again. So:

For k = 5, 6, 7, …, 11, and over sampled subsets of size k drawn from the oracle:
- recompute which candidates would have PASSed a spec of that size
- recompute P(harm | PASS) for that spec

Plot false-pass rate against specification size, with a confidence band.

This single figure does four things: it answers the "your spec is deliberately weak"
objection that is otherwise fatal; it separates recoverable from irreducible residual risk;
it produces a quantitative version of your pilot's 7-of-12 / 5-of-12 decomposition; and it
costs **zero additional compute** because the data is already collected. Build the analysis
before the run so you know the required columns are being written.

**The shortcut ablation.** Re-run the headline model with the most-suspect feature group
removed, and report both. In pilot-v1 the equivalent ablation (dropping `exact_revert`)
collapsed every model from 0.75 to ≤0.54 and was the finding.

**The learning curve** falls out of the staged collection for free (§32): train on the data
available after each stage and plot AUC-PR and ECE against n. If performance is flat from
stage 2 to stage 4, more data is not the answer and you can stop early and say so.

---

## 27. Evaluation metrics

Report all of these, and be explicit about which answers which question.

**Discrimination** — can it rank?
- **AUC-PR (primary)** and average precision. Prefer over ROC under imbalance; if the harm
  rate really is ~50% the imbalance is mild, but report PR anyway for comparability.
- AUC-ROC, secondary.
- **Within-incident ranking (currently missing, and it is the metric that matches your
  motivating example):** for each incident with ≥2 PASS candidates, does the lowest-risk
  candidate turn out SAFE? Report top-1 selection accuracy, mean per-incident AUC, and
  **regret** — the harm rate of the model-selected candidate minus the harm rate of the best
  available candidate — against the baseline of choosing uniformly at random among PASS
  candidates. This is the number an operator would act on.

**Calibration** — does the number mean what it says?
- Brier score with the Murphy decomposition (reliability / resolution / uncertainty).
- ECE with equal-frequency bins, bin count stated, bootstrap CI.
- Reliability curve with bootstrap band, plus the 4-bin observed-versus-predicted table.
- Spiegelhalter z-test.

**Decision usefulness** — is it worth deploying?
- **The autonomy–risk curve**: coverage (fraction auto-applied) versus realised harm rate,
  with the conformal bound overlaid.
- Harm prevented per unit of autonomy surrendered, relative to "auto-apply everything Batfish
  passes".

**The verification study** — the paper's first contribution, independent of any model.
- The 2×2: {Batfish PASS, FAIL} × {SAFE, HARMFUL}, with Wilson confidence intervals.
- P(harm | PASS) overall, per topology, and per fault family.
- Optimistic versus pessimistic disagreement counts at the property level, with the
  pessimistic rate bounded from the FAIL control arm.
- False-pass rate versus specification size (§26).

Do **not** lead with accuracy or F1. Accuracy is uninformative under any imbalance and F1
hides the direction of error, which here is the whole point — a model that is optimistic about
a harmful change is far worse than one that is pessimistic about a safe one.

---

## 28. Statistical tests

- **Wilson score intervals** for every proportion (false-pass rate, per-bin harm rate). Not
  the normal approximation — it misbehaves at the extremes, which is exactly where your
  interesting bins are.
- **Rule of three** for zero-count observations: observing 0 pessimistic disagreements in n
  gives a 95% upper bound of 3/n. This is how you turn "we saw none" into a publishable claim.
- **Permutation test** against the null that labels are noise, for every model metric.
- **DeLong's test** or a paired bootstrap for comparing two AUCs on the same data.
- **McNemar's test** for comparing two classifiers' errors on the same candidates.
- **Spiegelhalter z** for calibration.
- **Clustered/grouped bootstrap** — resample **incidents**, not candidates. Resampling
  candidates ignores the clustering and produces intervals that are too narrow. This applies
  to every CI in the paper.
- Correct for multiple comparisons (Holm) across the tier × model grid, or state that the
  comparisons are exploratory.

---

## 29. Confidence intervals

Every headline number gets one, computed with incident-level clustering:

- False-pass rate: Wilson, plus a clustered bootstrap for the design effect.
- Per-topology and per-family rates: Wilson, and expect them to be wide — 5 incidents per
  topology is not many.
- AUC-PR / AUC-ROC: clustered bootstrap, 2,000 resamples.
- ECE: clustered bootstrap.
- Conformal bound: it is already a high-probability bound; report the confidence level and
  the calibration-set size that produced it.

---

## 30. Learning curves

Train on n ∈ {50, 100, 200, 400, 600, 850} PASS candidates, sampled **by incident** so the
grouping is preserved, five repetitions per point, and plot AUC-PR and ECE with bands.

Read it as follows: if the curve is still rising at 850, more data helps and that is a
concrete recommendation for future work with a number attached. If it plateaus by 400, the
ceiling is the feature representation or the label noise, not n — and the honest conclusion
is that a sharper classifier is not obtainable from config-diff-plus-verifier features, which
is precisely the argument for a distribution-free bound instead. Either outcome is a result.

The staged collection plan produces these points as a by-product. Do not run a separate
experiment for it.

---

## 31. The small validation experiment

Your instinct here is right and it is the most important operational decision in this
document. Do not launch a 30-hour job to discover a measurement bug in hour 26.

**Stage 0 — ~15 minutes, no Docker, no Batfish.**

```
python pipeline/test_topology_aware.py
python pipeline/test_batching.py
python pipeline/verify_pilot.py --pilot data/pilot-v2
python pipeline/audit_dataset.py --pilot data/pilot-v2
```

Gate: 16/16 structural checks; `audit_dataset` §3 shows `repair_class` is **not** recoverable
from X at AUC > 0.85; §4 shows zero empty golden diffs; §2's effective-n is not catastrophically
below the row count.

**Stage 1 — ~1 to 1.5 hours, end to end.** Two topologies × 3 incidents, every candidate for
those incidents through Phase 2, then Phase 3 on the PASS subset — roughly 40 labs. Include
10 replicate labs for the noise floor.

What it must demonstrate, all of which are currently unproven on v2:
- Batfish parses the v2 artifact and the spike returns GO
- every property passes on every golden, in Batfish **and** in Containerlab (|G| = 12)
- the same-artifact assertion holds at runtime
- Phase 2 produces a PASS/FAIL **mix** — all-PASS means the gate is not discriminating
- Phase 3 labs converge within the policy, with no NO_CONVERGENCE storm
- labels are produced, and `UNDETERMINED`/`EXECUTION_FAILED` are near zero
- the replicate labels agree
- `verify_phase2` and the rewritten `verify_phase3` both pass
- a measured seconds-per-lab, to extrapolate honestly

Only if all of that is clean do you scale.

---

## 32. Staged scaling plan

Your staging is statistically reasonable and I would tighten it as follows. Note that the
stages double as the learning curve, so nothing here is wasted.

| stage | scope | approx. cost | GO criteria to proceed |
|---|---|---|---|
| **0** | gates + dataset audit | 15 min | as above |
| **1** | 2 topologies × 3 incidents, Phase 2+3, +10 replicates | 1–1.5 h | pipeline clean; label agreement ≥95%; PASS/FAIL mix; |G|=12 everywhere |
| **2** | **full Phase 2** on all candidates (no Docker) + Phase 3 on ~150 PASS, stratified across all topologies and families | ~5 h | false-pass rate in 10–60%; class balance not degenerate; NO_CONVERGENCE <5%; per-topology rates not wildly divergent |
| **3** | Phase 3 to ~450 PASS cumulative | ~+10 h | learning curve point 2 vs 3; first calibration read; shortcut ablation stable |
| **4** | Phase 3 to ~850 PASS + 150 FAIL controls + 30 replicates | ~+15 h | final |

**Stop-early rules, decided now:**

- **False-pass rate < 2%** at stage 2 → the specification is too strong or the faults too
  easy. Fix once, retry. Still < 2% → pivot to the fallback direction and publish the
  near-zero result honestly; it is a legitimate finding that verification is more complete
  than assumed.
- **False-pass rate > 60%** → suspect the oracle before believing it. In this project's
  history, premature convergence measurement produced exactly this bias.
- **Learning curve flat from stage 2 to stage 3** → stop collecting for the model. Spend the
  remaining budget on the FAIL arm, the replicates, and the specification sweep instead, and
  write the negative result.
- **Label agreement < 95%** → stop and fix the measurement layer. Everything downstream is
  bounded by this number.

Keep the existing batching (Phase 2 in 500s, Phase 3 in 100s, disk-as-state resume,
zero-duplicate assertion). It is well built and the resume contract is correct.

---

## 33. Compute and runtime strategy

16 GB Windows laptop, Docker Desktop, WSL2, Containerlab, Batfish, all on one machine.

- Phase 2 is Batfish only, no Docker labs — cheap, parallel-friendly, and safe to run in full
  early. Do it before Phase 3 in every stage; it is what tells you the Phase 3 population.
- Phase 3 is the budget. Roughly 100 s per lab at 6–8 routers; larger topologies will be
  slower and you should measure rather than assume.
- ~1,900 snapshots in one Batfish network is untested at this scale in this project. Watch
  memory during stage 2 and be prepared to shard by topology into separate Batfish networks.
- Host suspend has already caused a 932 s wall-clock against a 25 s subprocess timeout in this
  project's history. Disable sleep for the duration of a batch, and keep the timeout
  generous.
- Tune `.wslconfig` — WSL2 claims about half of system RAM by default, which is not what you
  want while Docker is also running.
- Always `clab destroy --cleanup`; orphaned containers and veth interfaces are a documented
  failure mode here.

---

## 34. Reproducibility requirements

Most of this exists. Keep it and add the last two.

- Pinned images (`frrouting/frr:v8.4.1`, `batfish/allinone`), pinned Python deps, `.venv` only.
- The dual digest, with timestamps confined to `pilot.lock.json` so rebuilds are byte-identical.
- Every run writes a structured JSON record; raw Batfish frames and full traces preserved.
- Frozen `HARM-DEFINITION.md` and `properties.yml` with dated change entries.
- **Add: put the repository under Git.** There is no `.git` in the folder I inspected, only a
  `.gitignore`. The project's central methodological claim is "the harm definition was frozen
  before results were seen", and **without version history that claim is unverifiable** —
  by a reviewer or by you. This is the cheapest and highest-value fix in this document. Do it
  today, and tag the commit that freezes the definition.
- **Add: freeze the analysis plan** (splits, metrics, bins, stop rules) in a dated file before
  stage 2, exactly as the harm definition was frozen. Pre-registration is what separates
  "we found a calibrated model" from "we searched until something looked calibrated".

---

## 35. Expected failure modes

Ranked by probability × damage:

1. **Tier A carries no signal and the spec-widening rule beats every model again.** Most
   likely single outcome, based on pilot-v1. Mitigation: this is a publishable result if
   framed as the decomposition plus the bound. Plan the paper so this outcome is the
   *expected* one, not a disaster.
2. **The false-pass rate collapses on other topologies.** 50% came from one topology and 24
   candidates. Wide interval. Stage 2 answers it.
3. **NO_CONVERGENCE storms on 8+ router topologies**, eating the budget and, via B4,
   silently mislabelling. Fix B4 first; watch the rate at stage 1.
4. **Label noise above the calibration ceiling.** Unmeasured today. §16 fixes it.
5. **Generator-signature leakage** — the model rediscovers `repair_class` from `change_stats`.
   Detectable now, before any run.
6. **Conformal bound invalid** because calibration was done candidate-wise on clustered data.
   Methodological, silent, and exactly what a reviewer checks.
7. **Batfish memory or state issues at ~1,900 snapshots in one network.** Untested.
8. **A remaining hardcoded pilot-v1 assumption.** The defect log has a dozen of these; assume
   there is at least one more and keep the golden and negative controls in place.

---

## 36. Remaining blockers

**Must fix before Phase 3:**
- B1 `verify_phase3.py` hardcoded to pilot-v1
- B2 no Containerlab-side |G| = 12 gate
- B3 decide the FAIL control arm (recommendation: 150 candidates)

**Must fix before any Phase 4 number is believed:**
- B4 NO_CONVERGENCE / UNDETERMINED / EXECUTION_FAILED mislabelled as safe

**Should fix before Phase 1 is rebuilt** (they change the artifact, so do them together):
- the `primary_path` / edge-router semantics in `spec_coverage_features` (§10)
- the topology reallocation to 20 topologies (§11), if you accept it
- the added graph feature block (§17), since it is computed at build time

**Housekeeping, cheap, do now:**
- Git repository and an initial commit
- remove `--override-spike`
- make the leakage filter print its exclusions
- P07 scope asymmetry recorded in `surprises.md`: Batfish's P07 is `detectLoops()` over all
  flows network-wide, Phase 3's is two traceroutes from `hosta`. Same identifier, different
  function — the fourth instance of a pattern your own notes have already named three times.

---

## 37. Exact implementation changes needed

In dependency order. Nothing here has been implemented; this is the work list.

1. `git init`, commit, tag the frozen definitions.
2. `pipeline/verify_phase3.py` — rewrite manifest-derived; expected run set = goldens for
   every topology in the lock, all incidents, and exactly the candidates that were eligible
   under the run's own `--only-passing` filter; delta rows = runs × 12.
3. `pipeline/run_phase3.py` — hard gate: per topology, |G| must equal 12 before any candidate
   of that topology runs; refuse otherwise with the failing property named.
4. `nrl/phase4.py` — fix the label mapping per §16; report excluded counts; make the leakage
   filter print exclusions.
5. `nrl/properties.py` — `spec_coverage_features`: spec path = `primary_path ∪ {ingress,
   egress}`; rename `change_touches_backup_path_device` to what it measures.
6. `nrl/topologies.py` — add the new topologies for the 20-topology design; add 2–3 in the
   12–16 router range.
7. `nrl/emit.py` / build — add the graph feature block (§17) to `meta.json` at build time.
8. `pipeline/run_phase3.py` — `--fail-controls N` to sample N Batfish-FAIL candidates
   stratified by topology and family; `--replicate N` for the noise-floor arm.
9. `nrl/phase4.py` — move to scikit-learn; add gradient boosting, calibration (Platt), nested
   grouped CV, conformal risk control at the incident level, within-incident ranking metrics,
   the learning curve, and the statistical tests in §28.
10. `pipeline/spec_sweep.py` — new: the specification-completeness sweep (§26), pure analysis
    over collected Phase 2 + Phase 3 data.
11. `docs/ANALYSIS-PLAN.md` — new, dated, frozen before stage 2.
12. Rebuild pilot-v2 after 5–7, re-run every gate, confirm the digests move as predicted.

---

## 38. Exact commands, eventually

After the changes above. Do not run these yet.

```powershell
# Stage 0
python pipeline\test_topology_aware.py
python pipeline\test_batching.py
Remove-Item -Recurse -Force data\pilot-v2
python pipeline\build_pilot_v2.py --profile c --topologies all
python pipeline\verify_pilot.py             --pilot data\pilot-v2
python pipeline\spike_frr_batfish.py        --pilot data\pilot-v2
python pipeline\verify_golden_properties.py --pilot data\pilot-v2 --negative-control
python pipeline\audit_dataset.py            --pilot data\pilot-v2

# Stage 1  (~1-1.5 h)
python pipeline\run_phase2.py --pilot data\pilot-v2 --only <stratified 12 ids>
python pipeline\run_phase3.py --pilot data\pilot-v2 --only-passing --batch-size 40 --replicate 10
python pipeline\verify_phase2.py --pilot data\pilot-v2
python pipeline\verify_phase3.py --pilot data\pilot-v2

# Stage 2  (~5 h)  -- only after stage 1 is clean
python pipeline\run_phase2.py --pilot data\pilot-v2 --batch-size 500
python pipeline\run_phase3.py --pilot data\pilot-v2 --only-passing --batch-size 100

# Stages 3-4 continue run_phase3 in 100-lab batches, then:
python pipeline\run_phase3.py --pilot data\pilot-v2 --fail-controls 150
python pipeline\spec_sweep.py --pilot data\pilot-v2
python pipeline\run_phase4.py --pilot data\pilot-v2
```

---

## 39. GO / NO-GO criteria per stage

| stage | GO if | NO-GO action |
|---|---|---|
| 0 | all gates pass; no generator-signature leakage; no empty golden diffs | fix before spending any lab time |
| 1 | pipeline clean end to end; label agreement ≥95%; PASS/FAIL mix; \|G\|=12 on every topology; NO_CONVERGENCE <5% | debug the measurement layer; do not scale |
| 2 | false-pass rate 10–60%; per-topology rates overlapping; classes not degenerate | <2% → fix once, then pivot; >60% → debug the oracle |
| 3 | learning curve informative; shortcut ablation stable | flat curve → stop collecting, write the negative result |
| 4 | final dataset complete; FAIL arm and replicates in | — |

---

## 40. What success looks like

- A false-pass rate with a confidence interval, measured across 20 topologies and 10 fault
  families — a number nobody has published, and one the tool vendor explicitly declines to
  publish.
- A specification-completeness curve showing how much residual risk more properties can
  remove and how much they cannot.
- A calibrated risk model whose four-bin reliability table is within its confidence bands, an
  autonomy–risk curve, and a conformal bound of the form *"auto-apply the lowest-risk 40% and
  expected harm among them is at most 5%"*.
- Within-incident selection that beats picking arbitrarily among PASS candidates, with a
  regret number.
- An open dataset and harness.

Even three of these five is a solid paper for NOMS / CNSM / TNSM / IM.

---

## 41. What a negative result looks like, and whether it is publishable

Yes, and in two of the three cases it is a *better* paper.

**Case A — the rate is real but risk is not predictable.** Most likely. The paper becomes:
"residual risk after verification is substantial (X%), is concentrated in these fault
families, is partially recoverable by specification widening (the curve), and is **not
predictable** from config-diff and verifier features at achievable sample sizes — therefore
bound it rather than predict it." That is a coherent, honest, useful contribution, and the
negative modelling result strengthens rather than weakens the argument for conformal risk
control.

**Case B — the rate is near zero (<2%).** The paper becomes "verification with a modest
specification is more complete than the automation literature assumes; here is the evidence
across 20 topologies and 10 fault families." Publishable, less exciting, and it triggers the
fallback direction.

**Case C — the model works.** Least likely on current evidence. Write it up with the shortcut
ablations in the same table as the headline, or a reviewer will assume you did not look.

The one outcome that is *not* publishable is a good-looking number obtained by tuning until
something passed. Freezing the analysis plan (§34) is what prevents that, and it protects you
as much as it protects the reader.

---

## 42. Proposed paper structure

1. **Introduction** — the automation safety story; "verification prevents regressions" as the
   standing claim; the unmeasured residual; contributions.
2. **Background and related work** — write this section **first**. Batfish's soundness and
   its three declared blind spots; Cornetto (whose ground truth is the verifier); self-evolving
   verifiers (who repair the model rather than quantify the risk); JIT defect prediction and
   its calibration/conformal literature; Config2Spec as the completeness baseline.
3. **Threat model and definitions** — SPEC versus ORACLE, the frozen harm definition, what
   "harm" does and does not include.
4. **Methodology** — the four-phase harness, the same-artifact guarantee, the two digests, the
   convergence policy, the gates.
5. **The measurement study** — the 2×2, false-pass rate overall and stratified, optimistic
   versus pessimistic with the rule-of-three bound, and the specification-completeness curve.
   *This is the paper's core, and it stands without any model.*
6. **Risk modelling** — features, tiers, models, the grouped protocols.
7. **Calibration and control** — reliability, Brier decomposition, the autonomy–risk curve,
   conformal risk control with the exchangeability discussion.
8. **Selection** — within-incident ranking and regret.
9. **Ablations and negative results** — tiers, shortcuts, the GNN, the learning curve.
10. **Threats to validity** — emulator not production; small topologies; synthetic repair
    distribution; specification chosen by the authors; label noise with the measured
    agreement rate; the same-name-different-function property hazard your notes have
    documented four times.
11. **Conclusion and future work** — mined specifications, LLM-generated repairs, hardware.

Two standing items outside the paper: get the professor named as co-author (unknown solo
undergraduate authors get scrutinised harder), and put a preprint up the moment the
measurement study has a number, to establish priority on the rate.

---

## 43. What you can and cannot claim

**Can claim, with the data this design produces:**
- P(harm | Batfish SPEC PASS) = X% [CI] on this artifact, across 20 topologies and 10 fault
  families, under harm definition v1.1.0.
- Batfish's disagreements with the emulator are optimistic in N cases and pessimistic in at
  most M (rule of three from the control arm).
- Residual risk decreases with specification size as [the curve] and does not reach zero.
- A calibrated risk estimate over the PASS population, with reliability quantified.
- A distribution-free bound on harm among auto-applied changes at a stated coverage.
- Whether the risk is or is not learnable from pre-deployment features at this scale.

**Cannot claim:**
- Anything about **production** networks. The ground truth is an emulator with no hardware
  forwarding plane, no TCAM, no line-rate traffic and idealised link timing. Say this in the
  abstract, not only in limitations.
- That Batfish is buggy, unsound, or wrong. It is sound with respect to its question and model.
- A general false-pass rate for network verification. Yours is a rate for *this* specification,
  *these* fault families, *this* repair distribution, *these* topologies. The specification
  sweep is what generalises it slightly; nothing generalises it fully.
- That the risk model transfers to unseen vendors, protocols beyond OSPF/static, or networks
  larger than those tested.
- Novelty on verifier-versus-emulator comparison (2608.11340), on calibrated/conformal change
  risk (JIT defect prediction), or on LLM repair benchmarking (Cornetto).
- Any causal claim about *why* a repair is risky. The features are correlational.

---

## Summary of what I would change, in one list

1. Fix B1–B4. Nothing else matters until B1 and B2 are done.
2. Put the repository under Git today.
3. Reallocate to 20 topologies at the same candidate budget; add 2–3 larger ones.
4. Add the specification-completeness sweep. It costs nothing and it answers the objection
   that would otherwise sink the paper.
5. Add within-incident ranking as a first-class result.
6. Add graph features; drop the CNN idea; run a GNN only as a declared ablation.
7. Add 150 FAIL controls and 30 replicates.
8. Move Phase 4 to scikit-learn; Platt not isotonic; nested grouped CV; conformal at the
   incident level.
9. Four calibration bins, not ten, and say why in the paper.
10. Freeze the analysis plan, dated, before stage 2.
