# Research Viability Audit

## 1. Executive Summary

This audit is a research-decisions audit only. No experiments, no candidate generation, no runtime execution, and no ML training were performed.

The original V4 confirmatory experiment is frozen and unchanged. Its result remains:

- 20 population changes
- 5 replicates each
- 99/100 valid runs
- frozen noise floor = 6.944e-4
- only 1/20 changes had median T1 above the floor
- V4 therefore failed the D2/G1 requirement and was a NO-GO

The forensic and offline mechanistic work established the following evidence:

- V4C-04 contains a genuine transient forwarding-loop mechanism.
- The representative loop is:
  - corea -> wan1 -> corea
  - wan1 -> corea -> wan1
- Model 1 (global directed-SPF) does not reproduce the phenomenon.
- Model 2 (mixed old/new forwarding-state model) reproduces a V4C-04-like cycle but also predicts cycles for EX-V4-01 through EX-V4-05.
- Model 3 (asynchronous convergence model) captures the structural plausibility of the mechanism but still does not provide a strong predeployment distinction between V4C-04 and the exploratory cases.

The key conclusion is that the transient-loop phenomenon is structurally plausible but not yet identifiable with sufficient discriminative power from predeployment information alone. Exact T1 magnitude is not presently predictable from configuration/topology alone, and the current loop-susceptibility label is too weak to justify ML or a new runtime batch.

Final project direction: D. STOP.

## 2. Evidence Base Reviewed

The following evidence was considered:

- original frozen V4 population and outcomes
- V4C-04 raw artifacts and forensic reconstructions
- EX-V4-01 through EX-V4-05 exploratory results
- Model 1: global directed-SPF model
- Model 2: mixed old/new forwarding-state model
- Model 3: offline asynchronous convergence model
- existing reports, manifests, scripts, and JSON/CSV summaries in the repository

No runtime experiment was run during this audit.

## 3. What V4 Actually Established

The original V4 result is not a near miss. It is a failed confirmatory experiment:

- the original target was exact transient disruption prediction under a frozen metric and gate;
- the population-level feasibility requirement was not met;
- one candidate did show a strong transient effect, but the overall population did not support the original research target as a general predictive task.

The scientific problem is therefore not simply that one candidate was positive. It is that the large-scale target was not supported by the available signals.

## 4. Target Definition Analysis

### Target A: Exact transient disruption prediction

Question: Can predeployment configuration/topology information predict the magnitude of transient traffic disruption T1 during convergence?

This target is not currently defensible.

Reason:

- The loop mechanism is structurally plausible in V4C-04, but the actual realized disruption depends materially on runtime ordering and timing.
- The evidence shows that multiple candidates can structurally contain a loop but have very different T1.
- The exact values of T1 are determined by runtime timing and event ordering that are not available before deployment.
- The available predeployment evidence can represent possibility, not duration.

Therefore, Target A is not identifiable from predeployment information in the current formulation.

### Target B: Transient-loop susceptibility

Question: Can predeployment information determine whether a configuration change is structurally capable of producing a transient forwarding loop during staged convergence?

This target is more defensible, but it is still not sufficiently validated.

Reason:

- Model 2 reproduced a V4C-04-like cycle and also predicted cycles for exploratory cases.
- The model therefore demonstrates structural possibility, not discriminative capability.
- The label "loop-susceptible" is definable, but the current evidence does not show that it separates V4C-04 from the exploratory cases with enough reliability to justify a new experimental program.

This is a better-defined target than exact T1 prediction, but it is not yet strong enough for a paper-worthy ML target or a new runtime batch.

## 5. Identifiability Analysis

The key question is which parts of the causal chain are predeployment-determined and which are runtime-dependent.

| Quantity | Predeployment? | Deterministic? | Runtime-dependent? | Learnable from config? |
|---|---|---|---|---|
| final connectivity | Yes | Mostly yes | No | Yes |
| final rerouting | Yes | Mostly yes | No | Yes |
| intermediate forwarding cycle existence | Yes, partially | Usually yes for a given model | Yes, actual installation matters | Partially |
| cycle length | Partially | Not reliably | Yes | Partially |
| affected-flow structural exposure | Yes | Usually yes for a given model | Somewhat | Partially |
| LSA propagation order | No | No | Yes | No |
| SPF recomputation order | No | No | Yes | No |
| FIB installation order | No | No | Yes | No |
| loop duration | No | No | Yes | No |
| T1 | No | No | Yes | No |

The strongest conclusion is that the causal chain separates into:

- predeployment structural possibility;
- runtime realization and duration;
- realized traffic disruption magnitude.

The last two are not sufficiently observable before deployment to support exact T1 prediction.

## 6. Discrimination Test Against the Six Cases

The six cases are:

- V4C-04
- EX-V4-01
- EX-V4-02
- EX-V4-03
- EX-V4-04
- EX-V4-05

The offline mechanistic models did not find a predeployment feature that cleanly discriminates V4C-04 from the exploratory cases.

Specifically:

- Model 1 failed completely.
- Model 2 produced cycles for all six cases.
- Model 3 reproduced the structural mechanism but still did not produce a clear and unique V4C-04-like signal.

No candidate property without using runtime T1 created a clean discriminating rule.

Therefore, the current evidence does not support a novel predeployment discriminator.

## 7. ML Viability Audit

### A. Target identifiability

Not sufficiently identifiable for exact T1. The target is not well-defined as a predeployment task.

### B. Label quality

For Target A, labels are not stable because runtime conditions dominate the magnitude. For Target B, the label is conceptually possible but too weak and too non-discriminative in the current dataset.

### C. Dataset size

The dataset is too small for a meaningful ML study given the lack of label stability and mechanism diversity.

### D. Dataset diversity

There is some topology diversity, but not enough to ensure generalization.

### E. Topology diversity

Limited. The six relevant cases are all drawn from a small selected set of known topologies.

### F. Mechanism diversity

Limited. The evidence reveals one broad mechanism family, but not enough variation to separate structural susceptibility from runtime realization.

### G. Class balance

Not strong. Very few positive cases relative to negative cases; and the positive case is not sufficiently separated by a stable definition.

### H. Independence

Not clearly independent. Candidate generation and topology families are not independent samples in the same sense as a general I.I.D. dataset.

### I. Shortcut risk

High. A model could easily learn topology identity, candidate-generation artifacts, or manual construction patterns rather than the actual mechanism.

### J. Leakage risk

High if runtime outcomes or T1 are allowed to guide feature construction or selection.

### K. Generalization

Not supported by evidence.

### L. Predeployment features

There is no convincing feature set that cleanly captures the actual runtime-dependent loop duration.

### M. Deterministic alternative

Yes: a deterministic graph analysis can detect possible mixed-state cycles and path dependency. This is not necessarily a good ML task because the mechanism is more naturally represented as a symbolic graph analysis problem than as a learned classifier.

Conclusion: ML is not justified at this stage.

## 8. Is the Current Dataset Good Enough to Train ML?

Decision: NO.

Reason:

- the target is not well-defined as a predeployment problem;
- the real magnitude depends on runtime conditions that are not available before deployment;
- the available cases do not provide a stable, discriminative signal;
- the exact T1 target is fundamentally not identifiable from the available predeployment information;
- the loop-susceptibility target is not yet strong enough to justify ML.

Therefore:

NO ML TRAINING SHOULD BE PERFORMED AT THIS STAGE.

## 9. Research Gap and Contribution

### Existing work

The repository evidence and the offline models show that existing work in this project has already established:

- transient loops are structurally possible in a mixed-state convergence model;
- V4C-04 is a real positive case;
- the issue is not captured by a global static topology analysis;
- runtime ordering and timing matter significantly.

### Limitation

The current limitation is that incomplete runtime timing information prevents a reliable predeployment predictor for realized T1, and the loop-susceptibility label is not yet discriminative enough.

### Potential contribution

A valid contribution would be to study a more precise structural label such as:

"configuration can induce a mixed-state directed cycle under deterministic serial update order"

but only if it is framed explicitly as a structural-failure-mode analysis rather than a T1-prediction task.

### Required evidence

A future study would need:

- a formally defined staged update model;
- explicit per-router update ordering rules;
- a deterministic graph model of partial knowledge,
- validation against a richer and more diverse case set;
- evidence that the structural label really separates harmful from harmless changes.

### Falsification criteria

The contribution would be falsified if:

- the structural label does not discriminate across a diverse set of cases;
- runtime timing dominates the outcome so completely that no predeployment label remains informative;
- a deterministic graph algorithm captures the same phenomenon without substantive learning benefit.

## 10. Best Next Direction

The current evidence does not justify a new runtime experiment or ML campaign.

The best next direction, if the project continues at all, is a reformulation around structural mixed-state cycle analysis rather than exact T1 prediction.

However, this is not the same as saying the current project is viable. It means the research question must change substantially.

## 11. Project Direction Decision

Choice: D. STOP.

Reason:

- exact T1 prediction is not identifiable from predeployment configuration;
- the current loop-susceptibility label is not sufficiently discriminative;
- the mechanistic model remains only partially supported;
- the dataset is too small and too structurally narrow to justify another runtime experiment or ML;
- the research question in its current form is not scientifically defensible as a continuing target.

## 12. Final Research Viability Decision

### What we know

- V4C-04 exhibits a real transient forwarding-loop mechanism.
- The mechanism is not captured by a globally consistent directed-SPF model.
- A mixed old/new forwarding-state model can represent the mechanism structurally.
- The current mechanisms do not yet distinguish V4C-04 from several exploratory cases.

### What we do not know

- whether a stronger predeployment formulation exists;
- whether exact T1 is predictably learnable from configuration before deployment;
- whether loop susceptibility can be defined in a stable, discriminative way across a larger sample.

### What V4 falsified

- the original V4 confirmatory target was not supported at population level;
- exact T1 prediction from the available predeployment evidence remains unsupported.

### What the forensic investigation supported

- transient loops are structurally possible during staged convergence;
- runtime ordering and timing matter substantially;
- current predeployment features are not sufficient to predict realized disruption magnitude.

### Whether exact T1 prediction is viable

No. Not in the current formulation.

### Whether loop susceptibility prediction is viable

Only partially, and not yet in a scientifically robust form.

### Whether ML is justified

No.

### Whether more runtime experiments are justified

No.

## 13. Final Decision Summary

The strongest honest conclusion is:

The current V4 project direction should stop. The domain may still support a redefined structural-convergence research problem, but not the exact T1 prediction target and not the current ML formulation.

This is not a failure of the domain. It is a failure of the current target definition and the available predeployment signal.
