# Batfish + Machine Learning: Risk Ranking of Verified Network Repair Candidates

**Version:** 1.0  
**Date:** 6 November 2026  
**Status:** Proposed research design. This is not a completed experiment, validated result, or novelty claim.

---

## 1. Executive summary

The intended project is a decision-support system for choosing between multiple alternative network configuration repairs that all pass the same required Batfish specifications.

The core question is:

> Given several alternative repair candidates for the same network incident, all of which pass Batfish verification, can pre-deployment topology and configuration information predict their independently measured operational risk well enough to rank the candidates from safest to riskiest?

Example (illustrative values only):

| Candidate | Batfish | Predicted risk score | Rank |
|---|---|---:|---:|
| Repair A | PASS | 0.12 | 1 |
| Repair B | PASS | 0.68 | 3 |
| Repair C | PASS | 0.31 | 2 |

The model does not replace Batfish. Batfish is the verification gate; ML is a second-stage ranking aid for eligible candidates.

**Critical honesty rule:** no number of topologies, candidates, runtime repetitions, or model layers can guarantee a successful result or paper acceptance. The design must test the hypothesis, not force a positive outcome.

## 2. Important terminology

These terms must not be conflated:

- **Verification:** Does the candidate satisfy the specific properties checked by Batfish?
- **Blast radius:** How much of the network/traffic is affected under a defined impact calculation.
- **Operational risk:** Probability and/or severity of an undesirable operational outcome.
- **Risk score:** A model output used to order candidates. It is not automatically a probability.
- **Confidence:** Uncertainty in the model's prediction.
- **Expected loss:** Estimated probability of an event multiplied by its expected severity, if both are defined and estimated correctly.

A blast-radius value of 0.20 under a particular formula means 20% of the relevant baseline-carried flows were affected according to that formula. It does **not** mean a 20% chance of failure. A score of 90 does not mean 90% safe or 90% confidence unless calibrated and explicitly defined that way.

---

# Part I — What we did previously and why it failed

## 3. Original motivation

The initial idea was to use Batfish to verify multiple possible network configuration changes or repairs. Some candidates may all pass the required specifications, but they may not have identical operational consequences. The desired ML system would estimate which candidate is safer to try first.

The original pipeline was:

```text
Network incident
      |
      v
Generate alternative repair candidates
      |
      v
Batfish verification
      |
      +---- FAIL / UNKNOWN ---> exclude from primary PASS-ranking task
      |
      v
Eligible Batfish-PASS candidates
      |
      v
Pre-deployment feature extraction
      |
      v
ML risk prediction and ranking
      |
      v
Independent Containerlab + FRR execution
      |
      v
Runtime outcomes become labels
```

## 4. V2 — SAFE/HARMFUL residual-risk prediction

### Objective
Predict whether a candidate that passed Batfish would nevertheless be harmful in the emulated runtime network.

### What happened
The expanded V2 work involved approximately 1,479 candidates, 200 incidents, and 20 topologies. The project record reports 804 Batfish PASS and 675 FAIL at one processing stage.

Shortcut analysis found very strong predictive association with change/repair class. Reported AUC values included approximately 0.995 for one change-related feature and approximately 0.999 for combined features. A deterministic specification-related rule also identified many harmful cases.

### Why it failed scientifically
The model could exploit how candidate classes had been generated or labeled. It did not establish that it learned a general operational-risk mechanism.

### Lessons
- Do not let candidate generation encode the target.
- Do not include IDs, generation order, or repair-family proxies as ordinary model inputs.
- Compare against simple deterministic rules.
- Hold out entire incidents and topologies.
- High AUC is not persuasive if a shortcut explains it.

## 5. V3 — steady-state blast-radius prediction

### Objective
Predict a continuous steady-state impact value:

\[
r=\frac{N_{\mathrm{broken}}+N_{\mathrm{rerouted}}}
        {N_{\mathrm{golden-carried}}}
\]

The exact definitions must be taken from the original V3 implementation and report.

### What happened
The project record reports 151 Batfish-SPEC-PASS candidates across 20 topologies, 12 primary and 8 held-out, with 12 golden/reference incidents. The measured target was reconstructed from raw routing information and matched the analytic target for 151/151 candidates.

### Why it failed scientifically
The target was already analytically available from the routing/configuration state. ML was learning to reproduce a quantity that the verifier or deterministic network analysis could calculate directly.

The central conclusion was:

> ML reproduced, less accurately, a quantity the verifier could compute exactly.

More rows would not fix that target redundancy.

## 6. V4 — transient disruption during convergence

### Objective
Measure temporary traffic disruption during convergence, rather than only final steady-state impact.

Conceptually, the target was an integral over time:

\[
T_1=\int_0^{T_{\mathrm{obs}}} b_{\mathrm{excess}}(t)\,dt
\]

where \(b_{\mathrm{excess}}(t)\) represents temporarily broken golden-carried traffic that is not broken in the final state. The precise normalization, denominator, polling interval, and implementation must be read from the V4 source code before reuse.

### Final pilot result
The final V4 population included:
- 20 changes.
- 5 planned replicates per change.
- 100 planned population runs.
- 99 valid population runs.
- 10 no-op controls.
- 4 positive controls.
- 1 of 20 changes with replicate median above the frozen noise floor.
- Noise floor approximately \(6.9444444\times10^{-4}\).
- Frozen requirement: at least 30% of changes above the floor.
- Observed: 5%, so the primary gate failed.

### Why it failed
Batfish, Containerlab, FRR, runtime measurement, and data processing worked. The candidate population was designed mainly around steady-state severity, not around the specific transient convergence phenomenon. Most candidates did not produce significant transient disruption. ML was not legitimately evaluated on the final V4 dataset.

### Forensic finding
The strongest case, V4C-04, exhibited a transient forwarding loop during staged multi-device updates. An illustrative path sequence was:

```text
Golden:     corea -> wan2
Transient:  corea -> wan1 -> corea   (loop)
Final:      corea -> wan1 -> coreb -> wan2
```

Other exploratory candidates could exhibit temporary loop states, but their integrated disruption was much smaller.

### Lessons
- Steady-state severity is not the same as transient disruption.
- PML or FIB-event count alone did not explain the magnitude.
- Update order and intermediate forwarding state may matter.
- Do not lower frozen thresholds or cherry-pick the one successful case.
- Keep exploratory data separate from confirmatory data.

## 7. Current status

| Version | Target | Main problem | ML conclusion |
|---|---|---|---|
| V2 | SAFE/HARMFUL residual risk | Shortcut/leakage-like class signal | Not established |
| V3 | Steady-state blast radius | Target analytically redundant | Not meaningful |
| V4 | Transient convergence disruption | Too few positive candidate changes | ML not fairly tested |
| Proposed new study | Rank multiple Batfish-PASS repairs | Must validate target, data, and novelty | Unknown; test experimentally |

---

# Part II — Proposed research formulation

## 8. Primary research question

> Among alternative network configuration repair candidates that satisfy the same predeclared Batfish specifications, can pre-deployment topology and configuration information predict independently measured operational risk well enough to rank candidates for safer deployment?

Secondary questions:

1. Does ML add value beyond Batfish's existing outputs and deterministic impact heuristics?
2. Does it generalize to unseen topologies and incidents?
3. Does CNN offer value compared with GNN and gradient-boosted trees?
4. Does following the ranking reduce measured decision regret?
5. Can probabilities be calibrated if the system claims to estimate event probability?

## 9. Define the experimental unit

Do not confuse these entities:

- **Topology:** Network graph and device/link inventory.
- **Incident:** Original network problem requiring repair.
- **Candidate repair:** One alternative configuration for the same incident.
- **Runtime execution:** One execution of one candidate.
- **Replicate:** Repeated execution under the same protocol.
- **Repair family:** Mechanism used to construct a candidate.
- **Topology family:** Ring, mesh, tree, spine-leaf, WAN, campus, etc.

The primary feature table should have one row per candidate. Runtime data should have one row per execution and be aggregated without discarding uncertainty.

## 10. Define “risk” before coding

The project should not use a vague label called “risk.” Select a primary operational outcome.

Possible outcomes:
- Transient packet loss.
- Temporary service unreachability.
- Forwarding loop.
- Excessive convergence duration.
- Fraction of affected flows.
- Persistent final-state failure (usually an eligibility/final-state gate rather than the same transient target).

### Recommended target family
Use a runtime-measured operational loss or within-incident candidate ranking. Keep component metrics visible.

One possible normalized loss is:

\[
L_r=w_pP_r+w_dD_r+w_fF_r
\]

where:
- \(P_r\): normalized packet-loss fraction.
- \(D_r\): normalized outage duration.
- \(F_r\): fraction of baseline-carried flows affected.
- \(w_p,w_d,w_f\): predeclared weights.

This is only a candidate formula. Avoid double counting correlated metrics. Justify weights before observing confirmatory results, and publish component-wise results. If weights cannot be justified, use a lexicographic or multi-objective ranking instead.

For candidate \(c\) with \(R_c\) valid runtime repetitions:

\[
\widehat{\mu}_L(c)=\frac{1}{R_c}\sum_{r=1}^{R_c}L_{c,r}
\]

For a defined event \(E\):

\[
\hat p(E\mid c)=\frac{1}{R_c}\sum_{r=1}^{R_c}\mathbb{1}[E_{c,r}]
\]

A possible expected-loss score is:

\[
\widehat{Risk}(c)=\hat p(E\mid c)\,
\widehat{\mathbb{E}}[S\mid E,c]
\]

This is not automatically reliable with few repeats. Report uncertainty intervals.

### Pairwise ranking
For two candidates \(a,b\) for the same incident:

\[
a\prec b \quad\text{if}\quad \widehat{Risk}(a)<\widehat{Risk}(b)
\]

A practical-difference margin \(\delta\) can define ties:

\[
z_{a,b}=
\begin{cases}
1 & L(a)<L(b)-\delta\\
0 & L(b)<L(a)-\delta\\
\text{tie} & \text{otherwise}
\end{cases}
\]

Do not force statistically indistinguishable candidates into an arbitrary order.

## 11. What the output score means

Three outputs are possible:

1. **Ranking score:** A continuous number used only to sort candidates. It need not be a probability.
2. **Event probability:** \(P(E=1\mid X)\), requiring calibration.
3. **Expected loss:** Probability multiplied by expected severity, if both are estimated and validated.

Recommended starting point: predict continuous operational loss and evaluate within-incident ranking. Add calibrated event probabilities only if the data supports them.

---

# Part III — Existing datasets: what they contain and what they do not

## 12. Cornetto

- Repository: https://github.com/nsg-ethz/cornetto
- Paper: https://arxiv.org/abs/2604.22513

Cornetto is the closest identified Batfish-oriented configuration-repair/verification benchmark. The prior review described 231 misconfiguration scenarios. **231 scenarios must not be called 231 distinct topologies.** The exact number of topology files, unique graphs, router configurations, and scenario-to-topology mappings must be computed from the pinned dataset release.

The prior review indicated that most correct repairs and ground-truth repair annotations are not supplied as a ready-to-use repair corpus. Verify this against the current paper and files.

### Cornetto audit checklist
- Pin release/commit.
- Download all data and read README/paper.
- Count topology files.
- Canonicalize and count unique topology graphs.
- Count router configuration files.
- Map every scenario to its topology.
- Identify routing protocols and configuration constructs.
- Identify specifications and expected behavior.
- Check whether valid reference configurations exist.
- Check whether multiple repairs are included.
- Determine what repair candidates must be generated.
- Check licensing.
- Test conversion to Batfish snapshots.
- Test conversion to Containerlab/FRR.

## 13. LCORE-D

- Dataset: https://data.mendeley.com/datasets/77sztrg5ks/2

Previously identified as a runtime-monitoring dataset with approximately 407 hours of emulated ISP-network monitoring and fault-related observations. The prior review described router CSV files R1–R7. Exact topology count and schema must be verified from the actual download.

Potential use:
- Understand runtime metrics.
- Inspect fault/convergence observations.
- Develop telemetry and label-extraction ideas.

It is not known to contain Batfish-PASS repair alternatives paired with pre-deployment features.

## 14. Graph Neural Networking Challenge 2021

- Dataset: https://bnn.upc.edu/challenge/gnnet2021/dataset/

Previously identified as providing network topologies, routing configurations, traffic matrices, and simulated delay/jitter/loss metrics. The prior review described 12 training topologies and 52 validation topologies; verify exact counts in the downloaded release and its documentation.

Potential use:
- Prototype CNN/GNN graph representations.
- Test graph batching and topology-size handling.
- Explore network-performance prediction.

It is not a Batfish repair-risk dataset and does not directly supply the required candidate-level runtime labels.

## 15. Batfish test networks

- Repository: https://github.com/batfish/test-networks

Potential use:
- Example configurations and snapshots.
- Parser and feature-extraction tests.
- Batfish smoke tests.

It is not a labeled operational-risk corpus.

## 16. Dataset comparison

| Resource | Topologies/configs | Batfish context | Multiple repair alternatives | Runtime measurements | Candidate risk labels | Direct final training? |
|---|---|---|---|---|---|---|
| Cornetto | Yes; exact unique count to audit | Yes | Not assumed complete | Not established | No complete paired labels | No, augment |
| LCORE-D | Emulated network/monitoring | Not paired with Batfish candidates | No matching repair corpus | Yes | No matching candidate labels | No, complementary only |
| GNNet Challenge | Yes; simulated networks | No repair-verification pairing | No | Simulated performance | No Batfish repair labels | No, architecture/pretraining study |
| Batfish test networks | Example configurations | Yes | Not a full repair corpus | No | No | No |
| New project corpus | Yes | Run ourselves | Generate/collect | Containerlab/FRR | Generate ourselves | Yes, after validation |

**Conclusion:** No identified public dataset has been shown to contain the complete matched tuple required by this project: topology + incident + multiple repairs + Batfish PASS + pre-deployment features + independent runtime outcome + repeated measurements.

Do not merge unrelated datasets into one supervised table. A runtime trace from one network cannot be used as the label for a different Cornetto topology simply because the columns look similar.

---

# Part IV — Recommended hybrid data pipeline

## 17. The exact recommended workflow

```text
Cornetto / Batfish test networks / other compatible sources
                         |
                         v
                Audit and select topologies
                         |
                         v
                Select incident scenarios
                         |
                         v
            Generate multiple repair candidates
                         |
                         v
              Deduplicate and validate candidates
                         |
                         v
                  Batfish verification
                         |
             +-----------+-----------+
             |                       |
           FAIL                   PASS
             |                       |
       separate analysis             v
                            Pre-deployment features
                                     |
                                     v
                         Freeze candidate and protocol
                                     |
                                     v
                           Containerlab + FRR runs
                                     |
                                     v
                        Independent runtime measurements
                                     |
                                     v
                        Candidate-level risk labels
                                     |
                                     v
                         Leakage-safe grouped splits
                                     |
                                     v
                      CNN / GNN / GBT / simple baselines
                                     |
                                     v
                      Unseen-topology ranking evaluation
```

### Reuse
- Suitable topologies.
- Router configurations.
- Existing incident scenarios.
- Specifications.
- Some simulator/runtime measurement ideas.

### Generate ourselves
- Multiple alternative repairs per incident where absent.
- Batfish verification records for each candidate.
- Candidate-specific pre-deployment features.
- Containerlab/FRR runtime measurements.
- Repeated-run aggregates and risk labels.
- Final candidate ranking dataset.

### Do not do
- Directly train on Cornetto as if it already contains runtime-risk labels.
- Pair LCORE-D labels with unrelated Cornetto candidates.
- Treat Batfish FAIL as the positive class in a task conditioned on Batfish PASS.
- Label a candidate positive because it belongs to a particular repair family.
- Select only runtime-positive cases after execution.

---

# Part V — Candidate generation

## 18. Multiple repairs per incident are essential

Example:

```text
Incident I-001
  |
  +-- Repair A: local metric adjustment
  +-- Repair B: alternative path preference
  +-- Repair C: staged multi-router repair
  +-- Repair D: another semantically valid alternative
```

All alternatives should aim to satisfy the same intended behavior and required specifications. Otherwise, comparing their risk scores may be meaningless.

## 19. Candidate mechanism matrix

Potential mechanisms, subject to actual protocol/configuration support:

| Mechanism | Example |
|---|---|
| Single-link OSPF cost | Change one interface metric |
| Paired-link cost | Change two related links |
| Multi-router cost | Change several routers |
| Next-hop preference | Change route preference/metric |
| ECMP | Alter equal-cost path conditions |
| OSPF adjacency | Change supported interface/network parameters |
| Redistribution | Change route redistribution policy |
| Route policy | Change filtering or preference |
| Administrative/link state | Controlled link state change |
| Benign control | No-op or semantically equivalent change |

The purpose is diversity, not manufacturing positives. Some candidates will fail Batfish or be invalid; record them and apply the predeclared eligibility rules.

## 20. Avoid candidate-selection bias

Never:
- Use runtime labels to decide which candidates enter the confirmatory set.
- Keep only candidates that cause disruption.
- Generate a large set, inspect labels, then select only the “interesting” ones and call it unbiased.
- Count hundreds of tiny variants of one repair as hundreds of independent examples.
- Make all positives one repair class and all negatives another.
- Put IDs, file names, generation order, or class labels into model features.

A mechanism-balanced design can deliberately cover different types of changes, but the runtime labels must be whatever the frozen execution protocol produces.

---

# Part VI — Batfish verification

## 21. Batfish's role

For every candidate:
1. Build baseline and candidate snapshots.
2. Run Batfish parsing.
3. Run the same required specifications.
4. Run differential reachability/forwarding analysis where relevant.
5. Store PASS/FAIL/UNKNOWN separately.
6. Store all query parameters and outputs.
7. Record Batfish version and snapshot/configuration hashes.
8. Retain eligible PASS candidates for the primary ranking task.

PASS means the candidate satisfied the named properties under the modeled snapshot and query. It does not prove universal runtime safety.

### Batfish data to retain
- Snapshot hashes.
- Batfish version.
- Parsing status.
- Specification IDs and per-property results.
- Differential reachability.
- Flow traces.
- RIB/forwarding summaries.
- Affected-flow or blast-radius outputs with exact formulas.
- Query parameters.
- Logs and timestamps.

If every eligible candidate has a global PASS Boolean, that feature is constant and cannot help distinguish candidates. Detailed per-specification outcomes may still vary.

---

# Part VII — Pre-deployment feature engineering

## 22. Feature groups

Every feature must have a precise definition, unit, source, availability time, missing-value policy, and extraction version.

### A. Topology features
- Router count.
- Link count.
- Endpoint count.
- Average/max degree.
- Network density.
- Diameter.
- Average shortest-path length.
- Articulation points and bridges.
- Edge/node betweenness.
- Alternate-path counts.

### B. Configuration-change features
- Changed routers.
- Changed interfaces.
- Changed links.
- Configuration commands.
- Routing metric changes.
- Route-policy changes.
- Protocol parameter changes.
- Adjacent changed-router count.
- Shared transit/core component changes.

### C. Baseline and predicted-final routing features
- Baseline path length.
- Predicted final path length.
- Path-length delta.
- Affected prefixes and endpoint pairs.
- Next-hop differences.
- Alternate-path count.
- Changed-link centrality.
- Traffic share on changed links.
- ECMP multiplicity.

### D. Structural transition features
Motivated by V4 forensic findings, but still requiring formal definition and independent validation:
- Old and predicted-final next-hop graphs.
- Union of old/new forwarding edges.
- Directed-cycle indicators in a pre-deployment abstraction.
- Changed-router dependency counts.
- Destinations sharing changed dependencies.
- Changed routers on baseline paths.
- Multiple interface changes on a central router.
- Old/new dependency edges crossing the changed-router set.
- Predeclared update-order descriptors, if the deployment sequence is fixed before execution.

A feature that exactly reconstructs the label makes ML unnecessary. Compare every structural feature against deterministic rules and mechanistic baselines.

### E. Batfish-derived features
- Per-specification results.
- Differential reachability summaries.
- Predicted final paths.
- RIB/forwarding summaries.
- Affected-flow counts.

These are allowed if available before runtime and not direct copies of the target.

## 23. Forbidden model inputs

Never use:
- T1 or runtime target values.
- Packet loss measured during execution.
- Runtime convergence time.
- Observed FIB events.
- Post-change runtime RIB/FIB.
- Runtime loop detector results.
- Execution timestamps.
- Retry count/status.
- Runtime duration.
- Run validity if it reveals the outcome.
- Candidate/run/incident/topology IDs as ordinary predictors.
- Generation order.
- Any post-deployment information.

IDs can be used for grouping and leakage audits, not prediction.

---

# Part VIII — Runtime execution and labels

## 24. Freeze the runtime environment

Record:
- Containerlab version.
- FRR version and image digest.
- Linux kernel.
- Host CPU and memory.
- Container resource limits.
- Traffic generator and parameters.
- Topology/configuration hashes.
- Deployment order.
- Polling interval.
- Observation window.
- Convergence and settling definitions.
- Timeout policy.
- Cleanup procedure.

A single-host study must disclose that limitation. Repeated runs on one host do not establish host-level generalization.

## 25. Runtime protocol

For each eligible candidate:
1. Create a clean lab.
2. Apply baseline configuration.
3. Wait for baseline convergence.
4. Verify baseline connectivity and traffic.
5. Start controlled traffic.
6. Capture baseline metrics.
7. Apply candidate using the frozen deployment procedure.
8. Record update events and timestamps.
9. Poll forwarding/traffic behavior.
10. Measure packet loss and service reachability.
11. Determine final convergence.
12. Verify final state.
13. Observe a predefined settling period.
14. Export telemetry, logs, RIB/FIB snapshots, and metadata.
15. Destroy lab and verify cleanup.
16. Repeat according to the preregistered plan.

## 26. Runtime measurements

Potential measurements:
- Packets sent/received.
- Packet-loss fraction.
- Per-flow reachability over time.
- Maximum transient broken-flow fraction.
- Integrated transient disruption.
- Forwarding-loop occurrence and duration.
- Convergence duration.
- Time to first successful forwarding.
- Time to stable forwarding.
- Final-state reachability.
- Final routing state.
- Run validity.

Choose one primary target before confirmatory execution. Others are secondary.

## 27. Network outcome versus infrastructure failure

| Event | Treatment |
|---|---|
| Candidate creates forwarding loop | Valid network outcome |
| Candidate creates packet loss | Valid network outcome |
| Candidate creates wrong final routing state | Valid outcome or eligibility failure according to preregistered rule |
| Containerlab daemon unavailable | Infrastructure failure |
| Image pull failure | Infrastructure failure |
| Host OOM | Infrastructure failure |
| Collector crashes | Measurement failure |
| Candidate causes FRR process failure | Potential operational outcome; classify carefully |

Never silently label a harness failure as safe or harmful.

## 28. Candidate labels

For candidate \(c\), with \(R_c\) valid replicates:

\[
\hat p(E\mid c)=\frac{1}{R_c}\sum_r \mathbb{1}[E_{c,r}]
\]

\[
\bar L(c)=\frac{1}{R_c}\sum_r L_{c,r}
\]

Store:
- Planned and valid replicate counts.
- Invalid-run reasons.
- Event count/rate.
- Mean and median loss.
- Standard deviation.
- Quantiles.
- Confidence interval.
- Final-state failure rate.
- Maximum transient disruption.

Five replicates is only a starting point. Pilot variance and event rarity determine whether more are needed. A candidate with zero events in five runs is not proven to have zero event probability.

---

# Part IX — Dataset scale and sampling

## 29. Planning targets, not guarantees

An ambitious mature-study target might be:

| Dimension | Planning target |
|---|---:|
| Distinct topologies | 30–36 |
| Topology families | 5–8 |
| Independent incidents | 200–300+ if feasible |
| Repair alternatives per incident | 3–5 where valid |
| Eligible candidates | Approximately 1,000–1,400 |
| Runtime replicates | Pilot-derived; 5 is a starting point |
| Held-out topologies | 6 or more if available |

These are planning targets, not scientifically established minimums. A large number of near-duplicate candidates is not a substitute for independent topologies and incidents.

For example:

\[
36\text{ topologies}\times40\text{ candidates}=1,440
\]

does not mean 1,440 independent incidents. Track topology, incident, candidate, and replicate levels separately.

## 30. Positive/negative distribution

Do not force a 40% positive rate. The pilot should determine whether the candidate-generation mechanism naturally produces enough variation.

If positives are rare:
- Report prevalence.
- Use PR-AUC relative to prevalence.
- Evaluate precision/recall at useful operating points.
- Use ranking metrics.
- Consider whether the target is too rare or poorly defined.
- Do not manufacture positives or lower thresholds after observing results.

## 31. Pilot first

Suggested pilot:
- 8–12 topologies.
- Multiple topology families.
- Several incidents per topology.
- 3–5 alternative repairs per incident where feasible.
- Small number of runtime repetitions.
- Frozen measurement procedure.
- Exploratory status, separate from final test.

Pilot questions:
1. Can topologies be converted to Batfish and Containerlab?
2. Can multiple meaningful repairs be generated?
3. Do required specifications produce useful PASS candidates?
4. Does runtime measurement work?
5. Are labels repeatable?
6. What is the event prevalence?
7. What is within-candidate variance?
8. What is the invalid-run rate?
9. Is the target analytically redundant?
10. Is there sufficient diversity for a confirmatory study?

Use pilot results for power/sample-size analysis and protocol design. If candidate-generation rules change based on pilot outcomes, do not present pilot rows as an untouched confirmatory test set.

---

# Part X — CNN, GNN, and baselines

## 32. CNN

A network is naturally a graph, not an image. A CNN can be tested using:
- Adjacency matrices.
- Weighted adjacency matrices.
- Multi-channel matrices for link attributes, routing information, and change masks.
- All-pairs path/next-hop matrices.

Main risk: node ordering is arbitrary. The same graph with routers permuted can produce a different matrix. Therefore:
- Define canonical ordering or permutation-aware augmentation.
- Test random node permutations.
- Test graph relabeling invariance.
- Handle variable topology sizes with masks/padding.
- Ensure node indices do not encode topology identity.

CNN is a research candidate, not a guaranteed best model.

## 33. GNN

Represent:
- Routers as nodes.
- Links as edges.
- Router attributes as node features.
- Link metrics and change indicators as edge features.
- Graph pooling for candidate-level representation.
- Prediction/ranking head for operational loss.

GNN is structurally natural, but can still overfit topology size and feature patterns.

## 34. Tabular models

Use:
- Logistic/linear regression.
- Random forest.
- Gradient-boosted trees (XGBoost/LightGBM/CatBoost-style).

Gradient boosting is an important baseline. If it outperforms CNN and GNN, report that honestly.

## 35. Required baseline comparison

| Model | Role |
|---|---|
| Random ranking within incident | Minimum ranking baseline |
| Rank by changed-device count | Simple heuristic |
| Rank by Batfish steady-state impact | Critical verifier baseline |
| Rank by affected-flow count | Deterministic impact baseline |
| Linear/logistic model | Interpretable baseline |
| Random forest | Nonlinear tabular baseline |
| Gradient boosting | Strong tabular baseline |
| CNN | Main architecture candidate |
| GNN | Graph-native comparator |

The ML model must demonstrate incremental value beyond deterministic Batfish/impact metrics.

---

# Part XI — Evaluation

## 36. Splits

Do not use random row-level splitting as the only evaluation.

Required:
- Incident-grouped split.
- Entire-topology holdout.
- Repair-family holdout where feasible.
- Later-generation/temporal holdout if useful.

An illustrative split, if the audited dataset supports it:
- 24 training/development topologies.
- 6 validation topologies.
- 6 final held-out test topologies.

Freeze the test set before tuning.

## 37. Ranking metrics

The main task is candidate ranking, so use:
- NDCG@k.
- Top-1 safest-candidate rate.
- Pairwise accuracy.
- Kendall's tau.
- Spearman correlation.
- Mean reciprocal rank where applicable.
- Top-k hit rate.
- Regret@1.

For incident \(i\):

\[
Regret_i=L_{i,\mathrm{selected}}-\min_{c\in C_i}L_{i,c}
\]

Lower regret is better. Compare model selection against random choice, deterministic Batfish ranking, simplest repair, and an oracle hindsight upper bound.

## 38. Regression/classification/calibration metrics

If predicting continuous loss:
- MAE.
- RMSE.
- Grouped-test \(R^2\).
- Rank correlation.

If predicting a binary event:
- PR-AUC.
- ROC-AUC.
- Precision, recall, F1.
- Balanced accuracy.
- Precision/recall at top-k.

If predicting probabilities:
- Brier score.
- Log loss.
- Calibration curve.
- Calibration slope/intercept.
- Group-aware confidence intervals.

Accuracy alone is not sufficient.

## 39. Statistical evaluation

Candidates are clustered by incident and topology. Do not bootstrap individual rows if this breaks the dependence structure. Use group-aware resampling or hierarchical analysis.

A rough event-rate standard error under independent Bernoulli assumptions is:

\[
SE(\hat p)\approx\sqrt{\frac{\hat p(1-\hat p)}{n}}
\]

But candidates within the same topology/incident are correlated, so effective sample size can be much smaller.

---

# Part XII — Leakage, ablations, and validity

## 40. Leakage audit

Check:
- Candidate IDs.
- Incident IDs.
- Topology IDs.
- Repair-family labels.
- File paths and names.
- Configuration hashes.
- Generation order.
- Runtime timestamps.
- Retry status.
- Runtime duration.
- Post-deployment fields.
- Duplicate/near-duplicate candidates across splits.

Run a metadata-only model. If it predicts well, investigate whether the dataset construction leaks labels.

## 41. Ablations

Evaluate:
- Topology-only features.
- Config-diff-only features.
- Batfish-only features.
- Structural-transition features.
- All pre-deployment features.
- Without mechanism labels.
- Without topology-size summaries.
- CNN channel ablations.
- GNN edge-feature ablations.
- GBT feature-group ablations.

Ablations must explain what the model learned.

## 42. Threats to validity

- **Construct validity:** Does the target really represent operational risk?
- **Internal validity:** Could host load, scheduling, traffic generation, or telemetry artifacts cause outcomes?
- **External validity:** Does Containerlab/FRR generalize to physical networks and other vendors?
- **Conclusion validity:** Are there enough independent topologies/incidents and narrow enough confidence intervals?
- **Leakage:** Are inputs truly pre-deployment?
- **Selection bias:** Results apply only to candidates passing the selected Batfish specifications.
- **Benchmark bias:** Public datasets may overrepresent certain protocols/topologies.
- **Architecture bias:** CNN may depend on arbitrary router ordering.

---

# Part XIII — Repository and implementation plan

## 43. Suggested repository structure

```text
batfish-ml-risk-ranking/
|
|-- README.md
|-- RESEARCH_PLAN.md
|-- LITERATURE_REVIEW.md
|-- DATASET_AUDIT.md
|-- DATASET_CARD.md
|-- DATA_DICTIONARY.md
|-- PREREGISTRATION.md
|
|-- datasets/
|   |-- external/cornetto/
|   |-- external/lcore_d/
|   |-- external/gnnet/
|   |-- external/batfish_test_networks/
|   |-- manifests/
|   |-- processed/
|   `-- splits/
|
|-- candidate_generation/
|   |-- transformations/
|   |-- repair_templates/
|   `-- generate_candidates.py
|
|-- batfish/
|   |-- snapshots/
|   |-- questions/
|   |-- run_verification.py
|   `-- parse_results.py
|
|-- features/
|   |-- topology_features.py
|   |-- config_diff_features.py
|   |-- routing_features.py
|   |-- structural_features.py
|   `-- build_feature_table.py
|
|-- containerlab/
|   |-- topologies/
|   |-- deployment/
|   |-- traffic/
|   |-- telemetry/
|   `-- run_candidate.py
|
|-- labels/
|   |-- compute_metrics.py
|   |-- compute_operational_loss.py
|   `-- aggregate_replicates.py
|
|-- models/
|   |-- baselines/
|   |-- xgboost/
|   |-- cnn/
|   |-- gnn/
|   `-- ranking/
|
|-- evaluation/
|   |-- grouped_splits.py
|   |-- leakage_audit.py
|   |-- ranking_metrics.py
|   |-- calibration.py
|   `-- decision_utility.py
|
|-- experiments/
|   |-- pilot/
|   |-- confirmatory/
|   `-- ablations/
|
`-- results/
    |-- raw/
    |-- processed/
    |-- figures/
    `-- reports/
```

## 44. Required data tables

1. `topologies`
2. `incidents`
3. `candidate_repairs`
4. `batfish_verification`
5. `predeployment_features`
6. `runtime_runs`
7. `runtime_metrics`
8. `candidate_label_aggregates`
9. `dataset_splits`
10. `environment_manifest`

Join by stable IDs, never by row order.

---

# Part XIV — Detailed phases and exit criteria

## 45. Phase 0: Literature and novelty audit

Tasks:
1. Search IEEE Xplore, ACM DL, USENIX, Google Scholar, SpringerLink, ScienceDirect, arXiv, Semantic Scholar.
2. Search Batfish + repair, risk, ranking, machine learning, runtime, transient, configuration update.
3. Search without Batfish for network-change risk, safe repair ranking, deployment safety, microloops, convergence, runtime verification.
4. Read closest papers and inspect references/citations.
5. Build a novelty matrix.
6. Identify whether prior work already performs candidate ranking, Batfish-PASS conditioning, runtime labeling, or transient prediction.
7. State a narrow contribution without claiming “first” prematurely.

Deliverables: `LITERATURE_REVIEW.md`, `RELATED_WORK_MATRIX.csv`, `NOVELTY_CLAIM.md`.

Exit: a defensible gap is identified.

## 46. Phase 1: Dataset audit

Tasks:
1. Pin Cornetto release/commit.
2. Download and inspect actual files.
3. Count topology files and unique graph structures.
4. Count router configuration files.
5. Map scenarios to topologies.
6. Identify protocols and configuration constructs.
7. Check correct configurations and repair alternatives.
8. Inspect LCORE-D and GNNet for complementary use.
9. Check license.
10. Test sample conversion to Batfish and Containerlab.

Deliverables: `DATASET_AUDIT.md`, topology/incident manifests, conversion report.

Exit: exact usable counts and missing data are known.

## 47. Phase 2: Target definition

Tasks:
1. Choose primary runtime outcome.
2. Define traffic and observation window.
3. Define final-state validity.
4. Define noise floor and operational threshold.
5. Choose continuous loss, binary event, or multi-task target.
6. Define ranking semantics.
7. Justify weights or use lexicographic ranking.
8. Prove target is not directly reconstructable from Batfish steady-state outputs.

Deliverables: `TARGET_DEFINITION.md`, `LABEL_FORMULAS.md`, `MEASUREMENT_PROTOCOL.md`.

Exit: independent reviewers can reproduce labels from raw runtime data.

## 48. Phase 3: Candidate generation

Tasks:
1. Select supported topology/incident scenarios.
2. Define transformation families.
3. Generate multiple alternatives for each incident.
4. Ensure alternatives aim at the same intended behavior.
5. Deduplicate.
6. Record generator provenance.
7. Freeze pilot candidates.

Deliverables: generator, templates, candidate manifest.

Exit: multiple meaningful alternatives per incident without label-informed selection.

## 49. Phase 4: Batfish verification

Tasks:
1. Build snapshots.
2. Run parsing and required specifications.
3. Record PASS/FAIL/UNKNOWN separately.
4. Run differential queries where appropriate.
5. Store raw outputs, versions, hashes.
6. Retain eligible PASS candidates for primary task.
7. Audit specification consistency.

Deliverables: verification runner/results/eligibility report.

Exit: reproducible PASS evidence for every eligible candidate.

## 50. Phase 5: Feature extraction

Tasks:
1. Extract topology features.
2. Extract config-diff features.
3. Extract routing features.
4. Extract structural transition features.
5. Extract allowed Batfish features.
6. Build tabular, CNN, and GNN representations.
7. Audit feature availability and leakage.
8. Freeze feature code.

Deliverables: feature dictionary/table and leakage audit.

Exit: every input is available before runtime.

## 51. Phase 6: Runtime pipeline

Tasks:
1. Convert topology to Containerlab.
2. Validate baseline connectivity.
3. Freeze deployment order.
4. Implement traffic and telemetry.
5. Implement convergence detection.
6. Implement run validity and cleanup.
7. Capture raw traces and environment hashes.
8. Validate measurement accuracy.

Deliverables: runtime runner and validation report.

Exit: reliable, reproducible measurements.

## 52. Phase 7: Pilot

Tasks:
1. Run small frozen candidate population.
2. Repeat executions.
3. Estimate event prevalence and loss distribution.
4. Estimate within-candidate and between-topology variance.
5. Check diversity and label repeatability.
6. Estimate invalid-run rate and runtime cost.
7. Check target redundancy.
8. Conduct independent label audit.
9. Perform power/sample-size analysis.

Deliverables: `PILOT_REPORT.md`, variance analysis, updated study plan.

Exit: confirmatory study is feasible. Otherwise redesign before main runs.

## 53. Phase 8: Confirmatory collection

Tasks:
1. Freeze population, code, images, protocol, and splits.
2. Run all candidates and replicates.
3. Preserve raw artifacts.
4. Apply predeclared invalid-run rules.
5. Record deviations.
6. Do not change thresholds after seeing labels.
7. Produce immutable dataset version.

Deliverables: runtime table, candidate aggregates, dataset card, deviation log.

Exit: completeness and validity gates met.

## 54. Phase 9: Training

Tasks:
1. Freeze grouped splits.
2. Train simple baselines.
3. Train linear/logistic models.
4. Train random forest and gradient boosting.
5. Train CNN.
6. Train GNN.
7. Tune on training/validation only.
8. Calibrate only on allowed validation data.
9. Save model, preprocessing, and metadata.

Deliverables: checkpoints and reproducible scripts.

Exit: model choices frozen before final test.

## 55. Phase 10: Evaluation

Tasks:
1. Evaluate unseen topologies.
2. Evaluate unseen incidents.
3. Evaluate unseen repair families where possible.
4. Report ranking, regression, classification, and calibration metrics as appropriate.
5. Compare with deterministic Batfish baselines.
6. Calculate regret and top-1 utility.
7. Run ablations and robustness tests.
8. Calculate group-aware confidence intervals.
9. Perform error analysis.

Deliverables: final results and statistical report.

Exit: incremental value and limitations established.

## 56. Phase 11: Paper and release

Paper sections:
1. Abstract.
2. Introduction.
3. Background.
4. Related work.
5. Problem formulation.
6. Target and labels.
7. Dataset construction.
8. Candidate generation.
9. Batfish verification.
10. Runtime methodology.
11. Features and model representations.
12. Models.
13. Evaluation.
14. Results.
15. Ablations.
16. Threats to validity.
17. Limitations.
18. Conclusion.

Release code, data dictionary, manifests, environment versions, hashes, reproduction instructions, and permitted raw traces.

---

# Part XV — What makes the paper strong?

## 57. Required scientific evidence

A strong paper should demonstrate:
1. A clear operational decision problem.
2. Multiple alternative repairs for the same incident.
3. Batfish verification as an eligibility gate.
4. A target not trivially computed from steady-state verification.
5. Independent and repeatable runtime measurement.
6. Pre-deployment-only features.
7. Strong deterministic and ML baselines.
8. Unseen-topology and unseen-incident evaluation.
9. Ranking utility and regret.
10. Calibration if probabilities are claimed.
11. Ablations explaining what the model learned.
12. Honest negative findings and limitations.

## 58. Possible contribution statement

If supported by evidence:

> We present and evaluate a learning-based decision-support framework for ranking alternative network configuration repair candidates that satisfy formal Batfish specifications. The framework uses pre-deployment topology and configuration information to estimate operational outcomes measured independently in an emulated runtime environment. We evaluate whether learned rankings provide incremental decision value over deterministic verification and impact-analysis baselines, including tests on unseen topologies and incidents.

Do not claim “first” without a systematic literature review.

## 59. If ML does not win

The project may still provide a useful negative result:
- A paired candidate/runtime benchmark.
- A reproducible methodology.
- Evidence that static pre-deployment features are insufficient for a particular outcome.
- A clear analysis of which operational outcomes are predictable and which depend on runtime timing.

Do not alter labels or thresholds to manufacture success.

---

# Part XVI — Threats and open decisions

## 60. Threats to validity

- **Construct validity:** Does the target represent operational risk?
- **Internal validity:** Could host load, scheduling, traffic generation, or telemetry artifacts explain results?
- **External validity:** Does Containerlab/FRR generalize to physical networks or other vendors?
- **Conclusion validity:** Are independent topologies/incidents numerous enough?
- **Leakage:** Are all inputs truly pre-deployment?
- **Selection bias:** Results apply only to candidates passing the chosen specifications.
- **Benchmark bias:** Public datasets may overrepresent particular protocols and topologies.
- **Architecture bias:** CNN can depend on arbitrary router ordering.

## 61. Open decisions

| Decision | Proposed default | Must be resolved |
|---|---|---|
| Primary target | Runtime operational loss / within-incident ranking | Target phase |
| Steady-state blast radius | Baseline or feature, not target if analytically redundant | Target phase |
| Topology source | Cornetto plus compatible sources | Dataset audit |
| Alternative repairs | Generate where absent | Candidate phase |
| Verification | Batfish | Verification phase |
| Runtime | Containerlab + FRR | Runtime phase |
| Repetitions | Pilot-derived; 5 is a starting point | Pilot |
| CNN | Candidate architecture, not assumed winner | Model phase |
| GNN | Graph-native comparator | Model phase |
| Tabular baseline | Gradient boosting | Model phase |
| Evaluation | Grouped unseen-topology ranking | Preregistration |
| Score semantics | Expected loss or ranking score, not vague confidence | Target phase |

## 62. Final recommendation

Use a hybrid approach:
1. Audit and reuse Cornetto topologies/configurations/scenarios.
2. Add other compatible topologies only if required.
3. Generate multiple alternative repairs per incident.
4. Run Batfish and retain eligible PASS candidates.
5. Extract pre-deployment features.
6. Run candidates independently in Containerlab/FRR.
7. Create runtime-derived labels and candidate-level aggregates.
8. Train CNN, GNN, and tabular baselines.
9. Evaluate ranking on unseen topologies and incidents.
10. Publish only what the evidence supports.

Do not immediately run thousands of experiments. Start with dataset audit and a small pilot.

---

# Appendix A — Mathematical problem formulation

Let:
- \(G_i=(V_i,E_i)\): topology for incident \(i\).
- \(C_i^0\): original configuration.
- \(c_{i,j}\): candidate repair \(j\).
- \(B(c_{i,j})\): Batfish verification result.
- \(X_{i,j}\): pre-deployment features.
- \(L_{i,j,r}\): runtime loss for replicate \(r\).

Eligible set:

\[
\mathcal{C}_i^{PASS}=
\{c_{i,j}:B(c_{i,j})=\mathrm{PASS}\}
\]

Empirical loss:

\[
\bar L_{i,j}=
\frac{1}{R_{i,j}}\sum_{r=1}^{R_{i,j}}L_{i,j,r}
\]

Prediction:

\[
\hat L_{i,j}=f_\theta(X_{i,j})
\]

Ranking:

\[
\pi_i=\operatorname{argsort}_{j\in\mathcal{C}_i^{PASS}}\hat L_{i,j}
\]

Pairwise ranking loss (one possible form):

\[
\mathcal{L}_{rank}=
\sum_i\sum_{(a,b)\in P_i}
\log\left(1+\exp[-(s_\theta(X_{i,b})-s_\theta(X_{i,a}))]\right)
\]

where \(P_i\) contains reliably ordered candidate pairs. Confirm sign conventions in code.

Regression loss:

\[
\mathcal{L}_{reg}=
\frac{1}{N}\sum_{i,j}(\hat L_{i,j}-\bar L_{i,j})^2
\]

If predicting event probability and severity:

\[
\hat R_{i,j}=\hat p_{i,j}\hat\mu_{S|E,i,j}
\]

Validate both components and their product.

# Appendix B — Minimum data dictionary

| Table | One row represents | Key fields |
|---|---|---|
| `topologies` | One topology | topology_id, source, family, router_count, link_count, hash |
| `incidents` | One repair problem | incident_id, topology_id, baseline_hash, specifications |
| `candidate_repairs` | One alternative | candidate_id, incident_id, family, config_hash |
| `batfish_verification` | Candidate/spec result | candidate_id, spec_id, status, version |
| `predeployment_features` | One candidate | candidate_id, feature columns, extraction_version |
| `runtime_runs` | One execution | run_id, candidate_id, replicate, environment_hash, validity |
| `runtime_metrics` | One execution's metrics | run_id, loss, outage, loops, convergence |
| `candidate_label_aggregates` | One candidate aggregate | candidate_id, event_rate, mean_loss, CI |
| `dataset_splits` | One grouped entity | entity_id, split |
| `environment_manifest` | One environment version | versions, image digests, host details |

# Appendix C — Mandatory audit questions

### Dataset
- How many unique topology graphs actually exist?
- How many independent incidents?
- How many repairs per incident?
- Are correct configurations available?
- Are there enough topology families?
- Can the data legally be reused?
- Can topologies be represented in both Batfish and Containerlab/FRR?

### Batfish
- Which specifications are checked?
- Are they identical across alternatives for an incident?
- Does PASS mean the same thing across incidents?
- Are there unsupported constructs?
- Is the proposed target already analytically computable?

### Runtime
- Does the lab reproduce relevant protocol behavior?
- Is polling fast enough to detect transient events?
- Is update order fixed and logged?
- Can harness failures be separated from network outcomes?
- How many repetitions are required based on variance?

### Features
- Is every feature available before deployment?
- Is any feature a direct transformation of the label?
- Can topology/candidate identity leak through features?
- Does CNN survive node permutation?
- Does GNN generalize to unseen graph structures?

### Evaluation
- Are splits grouped by topology and incident?
- Is the test set untouched?
- Are baseline comparisons fair?
- Are confidence intervals group-aware?
- Is ranking utility measured directly?
- Is calibration evaluated if probabilities are reported?

---

# Appendix D — Final principle

The goal is not to make the experiment pass. The goal is to discover whether the approach genuinely works.

```text
Literature review
       |
       v
Dataset audit
       |
       v
Target definition
       |
       v
Candidate generation
       |
       v
Batfish verification
       |
       v
Pre-deployment features
       |
       v
Independent runtime execution
       |
       v
Validated labels
       |
       v
Frozen grouped splits
       |
       v
CNN / GNN / tabular training
       |
       v
Unseen-topology evaluation
       |
       v
Scientific conclusion
```

If the model succeeds, report where and how much it improves candidate selection. If it fails, determine whether the limitation is the target, features, dataset, runtime measurement, or generalization. Do not change the protocol after observing the result merely to obtain a positive paper.

---

# Part XVII — Research Vision, Critical Review, and Mandatory Go/No-Go Decision

## 63. Researcher's vision

My long-term ambition is to produce a rigorous, reproducible, technically meaningful research paper at the intersection of network verification, network configuration repair, runtime systems, and machine learning.

The central vision is to help network engineers make a safer choice when multiple alternative configuration repairs satisfy the same formal Batfish specifications. I want to investigate whether information available before deployment can help rank those eligible candidates by independently measured operational outcomes.

This is an ambitious research goal, not a predetermined result. Scientific correctness, reproducibility, honest negative findings, and a defensible contribution matter more than obtaining a positive ML result.

## 64. Mandatory review of previous work

Before implementing this proposal, inspect the complete existing project repository and read `PROJECT_HISTORY_AND_RESEARCH_EVOLUTION.md` alongside this document.

Reconstruct what was actually implemented and measured in V1, V2, V3, and V4. Inspect source code, manifests, raw data, reports, frozen protocols, evaluation scripts, test results, and Git history wherever available.

Treat raw records and reproducible calculations as stronger evidence than narrative summaries. Clearly distinguish VERIFIED, RECORDED, INFERENCE, PROPOSED, and UNKNOWN findings.

Do not repeat previous experiments without explaining exactly what scientific question has changed and why the previous failure modes have been addressed.

## 65. Mandatory research feasibility gate

The previous V4 study ended NO-GO because only 1 of 20 change-level medians exceeded its frozen noise floor, and the mechanistic audit did not establish a sufficiently discriminative pre-deployment signal.

Therefore, the proposed candidate-risk-ranking study must not automatically inherit the assumption that ML is feasible.

Before launching a large experiment, establish:
1. A precise operational target that is not analytically reconstructable from Batfish or deterministic network analysis.
2. A defensible explanation of why pre-deployment features could predict or rank that target.
3. A candidate-generation process that does not encode labels or leak repair-family shortcuts.
4. Multiple genuinely different, semantically valid repair alternatives for the same incident.
5. A dataset with sufficient independent topology, incident, and repair-family diversity.
6. A runtime measurement protocol with repeatability, controls, provenance, and uncertainty estimates.
7. A meaningful expected advantage over deterministic and simple statistical baselines.

If these conditions cannot be established, recommend STOP, redesign, or a narrower research question. Do not proceed merely because the proposed project is ambitious.

## 66. Required changes to the proposed modeling strategy

Treat gradient-boosted trees and interpretable tabular models as essential early baselines. Compare them against deterministic Batfish-derived heuristics before investing in complex architectures.

Treat GNNs as the more natural graph-learning candidate, subject to adequate independent topology diversity. Treat CNNs as exploratory only, with explicit node-permutation and graph-relabeling tests.

Do not assume that CNN, GNN, deep learning, or any particular architecture will outperform simpler methods. The research contribution must be the validated decision-making improvement, not the use of a fashionable model.

## 67. Required literature and dataset investigation

Perform a systematic related-work and novelty review before making any novelty or "first research" claim.

Audit the actual downloadable releases, schemas, topology counts, scenario mappings, configuration availability, repair availability, licensing, and conversion feasibility of every proposed dataset.

In particular, investigate Cornetto, LCORE-D, GNNet 2021, and Batfish test networks. Do not describe complementary datasets as if they contain matched Batfish-PASS repair candidates and independent runtime-risk labels.

Use these starting resources:
- Cornetto repository: https://github.com/nsg-ethz/cornetto
- Cornetto paper: https://arxiv.org/abs/2604.22513
- LCORE-D: https://data.mendeley.com/datasets/77sztrg5ks/2
- GNNet 2021: https://bnn.upc.edu/challenge/gnnet2021/dataset/
- Batfish test networks: https://github.com/batfish/test-networks
- Batfish documentation: https://batfish.readthedocs.io/
- Containerlab documentation: https://containerlab.dev/
- FRRouting documentation: https://docs.frrouting.org/

Search and review relevant work through IEEE Xplore, ACM Digital Library, USENIX, Google Scholar, SpringerLink, ScienceDirect, arXiv, and Semantic Scholar.

## 68. Required decision report before implementation

Produce a critical assessment that answers:
- What is genuinely new compared with existing research?
- What exactly did our previous work establish, and what did it fail to establish?
- Is the proposed target measurable, meaningful, and not analytically redundant?
- Can suitable candidate alternatives and independent runtime labels realistically be obtained?
- What is the strongest deterministic baseline?
- What are the main threats to validity and likely failure modes?
- Which parts of the current research plan must be changed, removed, postponed, or retained?
- What is the smallest experiment that could decisively falsify the new hypothesis?

Estimate feasibility only with an explicit evidence-based rationale, assumptions, and uncertainty. Do not invent a success percentage or promise publication.

## 69. Final instruction

Do not optimize for completing the proposed plan. Optimize for discovering whether the research question is scientifically valid and worth pursuing.

First investigate, challenge, and improve the proposal. Then present a revised research plan with prioritized actions, deliverables, risks, and objective Go/No-Go criteria. Do not modify historical results, frozen thresholds, or original experiment records. Any genuinely new study must have its own clearly versioned protocol and preregistration.
