# V4 Post-Mortem

Date: 2026-09-16

This is a separate analysis report. No V4 experiment code, raw artifacts, manifests, preregistration, thresholds, or results were modified. No ML was trained.

## A. Final Result

The frozen V4 pilot is a valid negative feasibility result.

- Planned entries: 114
- Raw run directories: 114
- Attempt directories: 118
- Ledger entries: 117
- Final accepted runs: 113 `OK`
- Incomplete attempt: `V4C-12.rep4` attempt 1 has no `run.json`
- Population runs planned: 100
- Valid population runs: 99/100
- D7: 20/20 changes have at least four valid replicates
- D8: 99/100 = 99%
- D3 within-change share: 0.0278317
- No-op controls: 10/10 with T1 = 0
- D1 floor: `0.0006944444444444445`
- Population changes above floor: 1/20 = 5%
- Frozen G1/D2 requirement: at least 30%
- Positive controls: 4/4 valid and above floor

**FINAL SCIENTIFIC NO-GO.** G1/D2 fails exactly as preregistered. The pipeline correctly stopped before D5/ML.

## B. Population Diagnosis

T1 is transient broken-flow area after subtracting final steady-state breakage. The frozen predeployment descriptors below are not T1 features; they are included for diagnosis only.

`FIB` is the analytic number of changed FIB entries, `PML` is analytic microloop potential, `r_exact` is analytic steady-state affected fraction, and `final-rerouted` is the final steady-state rerouted fraction.

| Change | Topology | Role | Mechanism | Valid n | T1 median | T1 mean | Min..max | Replicate T1 values | r_exact | FIB | PML | Devices | Events avg | Above D1 |
|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| V4C-01 | t05_ring6 | cost-hi | cost | 5 | 0.0001253 | 0.0002289 | 0.0000262..0.0007804 | 0.0001607; 0.0007804; 0.0001253; 0.0000517; 0.0000262 | 0.4444 | 9 | 0.2639 | 2 | 22.0 | No |
| V4C-02 | t05_ring6 | cost-mid | cost | 5 | 0.0000055 | 0.0000105 | 0.0000036..0.0000234 | 0.0000043; 0.0000159; 0.0000055; 0.0000036; 0.0000234 | 0.1111 | 5 | 0.0556 | 2 | 11.8 | No |
| V4C-03 | t05_ring6 | drain-hi | drain | 5 | 0.0000184 | 0.0000160 | 0..0.0000325 | 0.0000093; 0.0000199; 0.0000325; 0.0000184; 0 | 0.3333 | 4 | 0 | 3 | 32.8 | No |
| V4C-04 | t05_ring6 | drain-lo | drain | 5 | 0.0229234 | 0.0218540 | 0.0172482..0.0266592 | 0.0229234; 0.0193060; 0.0266592; 0.0231333; 0.0172482 | 0.1111 | 5 | 0.0556 | 4 | 31.2 | **Yes** |
| V4C-05 | t05_ring6 | bh | blackhole | 5 | 0 | 0 | 0..0 | 0; 0; 0; 0; 0 | 0.0972 | 1 | 0 | 1 | 1.0 | No |
| V4C-06 | t13_bowtie7 | cost-hi | cost | 5 | 0.0000276 | 0.0000304 | 0.0000045..0.0000567 | 0.0000045; 0.0000276; 0.0000567; 0.0000160; 0.0000472 | 0.4444 | 10 | 0.2222 | 2 | 27.8 | No |
| V4C-07 | t13_bowtie7 | cost-mid | cost | 5 | 0 | 0 | 0..0 | 0; 0; 0; 0; 0 | 0.1333 | 5 | 0 | 2 | 14.0 | No |
| V4C-08 | t13_bowtie7 | drain-hi | drain | 5 | 0.0000515 | 0.0000575 | 0.0000310..0.0000845 | 0.0000737; 0.0000468; 0.0000845; 0.0000310; 0.0000515 | 0.3333 | 5 | 0 | 3 | 42.0 | No |
| V4C-09 | t13_bowtie7 | drain-lo | drain | 5 | 0.0000261 | 0.0000287 | 0.0000111..0.0000474 | 0.0000474; 0.0000261; 0.0000148; 0.0000111; 0.0000440 | 0.0556 | 5 | 0 | 3 | 29.0 | No |
| V4C-10 | t13_bowtie7 | bh | blackhole | 5 | 0 | 0 | 0..0 | 0; 0; 0; 0; 0 | 0.0778 | 1 | 0 | 1 | 1.0 | No |
| V4C-11 | t14_ladder8 | cost-hi | cost | 5 | 0.0000426 | 0.0000446 | 0.0000222..0.0000754 | 0.0000536; 0.0000754; 0.0000222; 0.0000292; 0.0000426 | 0.4545 | 21 | 0.3545 | 2 | 56.0 | No |
| V4C-12 | t14_ladder8 | cost-mid | cost | 4 | 0.0000121 | 0.0000150 | 0..0.0000357 | 0; 0.0000357; 0.0000216; 0.0000026 | 0.1818 | 9 | 0.0727 | 2 | 24.0 | No |
| V4C-13 | t14_ladder8 | drain-hi | drain | 5 | 0.0001275 | 0.0001125 | 0.0000335..0.0001777 | 0.0001777; 0.0001275; 0.0001425; 0.0000815; 0.0000335 | 0.4000 | 22 | 0.3727 | 4 | 114.2 | No |
| V4C-14 | t14_ladder8 | drain-lo | drain | 5 | 0.0000267 | 0.0000193 | 0.0000018..0.0000359 | 0.0000050; 0.0000267; 0.0000359; 0.0000272; 0.0000018 | 0.0364 | 2 | 0 | 4 | 65.0 | No |
| V4C-15 | t14_ladder8 | bh | blackhole | 5 | 0 | 0 | 0..0 | 0; 0; 0; 0; 0 | 0.0727 | 1 | 0 | 1 | 1.0 | No |
| V4C-16 | t15_campus12 | cost-hi | cost | 5 | 0.0000877 | 0.0001038 | 0.0000529..0.0001910 | 0.0000554; 0.0000877; 0.0001910; 0.0000529; 0.0001322 | 0.4476 | 34 | 0.4476 | 2 | 77.8 | No |
| V4C-17 | t15_campus12 | cost-mid | cost | 5 | 0.0000088 | 0.0000098 | 0..0.0000204 | 0.0000088; 0; 0.0000200; 0; 0.0000204 | 0.1905 | 12 | 0.0952 | 2 | 31.0 | No |
| V4C-18 | t15_campus12 | drain-hi | drain | 5 | 0.0000633 | 0.0000682 | 0.0000226..0.0001154 | 0.0000370; 0.0000226; 0.0000633; 0.0001154; 0.0001027 | 0.3524 | 22 | 0.3476 | 3 | 104.4 | No |
| V4C-19 | t15_campus12 | drain-lo | drain | 5 | 0.0000545 | 0.0000558 | 0.0000326..0.0000898 | 0.0000545; 0.0000326; 0.0000662; 0.0000357; 0.0000898 | 0.0190 | 2 | 0 | 3 | 22.0 | No |
| V4C-20 | t15_campus12 | bh | blackhole | 5 | 0 | 0 | 0..0 | 0; 0; 0; 0; 0 | 0.0619 | 1 | 0 | 1 | 1.0 | No |

## C. Population Versus Positive Controls

The current positive controls had T1 values:

- V4P-02: 0.004738
- V4P-03: 0.005067
- V4P-05: 0.004927
- V4P-06: 0.005898

Their final-state broken fraction equals their analytic broken fraction, but their shutdown causes a temporary loss before the final state is restored through an alternative path. This is exactly the transient phenomenon T1 measures.

The population is different:

- blackholes create permanent final-state breakage, so `broken_excess` is zero by design;
- cost changes mostly create final reroutes without transient broken flow;
- drain changes alter costs on multiple interfaces and usually converge without a transient broken state;
- the population was selected by analytic steady-state severity, not transient sensitivity;
- positive controls use link shutdown, while population changes use cost, drain, and blackhole mechanisms.

The exceptional population change, V4C-04, is a `drain-lo` on `t05_ring6`:

- median T1: 0.0229234;
- analytic `r_exact`: 0.1111;
- microloop potential: 0.0556;
- 4 devices pushed, 12 commands;
- approximately 31 FIB state changes per run;
- FIB settling approximately 5.5–9.1 seconds;
- all replay/intermediate validity checks passed.

It is the only population change whose transient behavior clearly resembles the intended phenomenon. Its result is reproducible across all five replicates, not a single lucky run.

## D. Measurement/Target Diagnosis

The target is responsive. Evidence:

1. All four positive controls produce nonzero T1 above the floor.
2. V4C-04 produces large, reproducible T1 with valid replay and no monitor errors.
3. No-op controls all produce zero T1.
4. The target uses runtime FIB/link/nexthop replay and final-state subtraction; it is not a static analytic score.
5. Positive-control T1 differs across runs despite similar final steady-state structure, demonstrating dependence on convergence behavior.

There is no evidence that the low population result is caused by missed FIB events or a broken target. The strongest explanation is population design, with a secondary mechanism effect.

## E. Most Likely Explanation

Ranked by evidence:

1. **Population-design limitation: strong.** The population was selected by steady-state analytic severity. That selection does not target transient route withdrawal, microloops, or event ordering. Four blackhole changes are guaranteed to have zero T1 when their final blackhole remains active. Most cost/drain changes produce a final reroute without a transient broken interval.
2. **Mechanism/topology interaction: strong.** Shutdown controls explicitly remove forwarding adjacency and create a temporary outage before alternate forwarding settles. Cost/drain changes generally preserve connectivity while SPF reconverges. V4C-04 shows that a cost-drain construction can produce transient disruption, but it is not common in the selected 20.
3. **Measurement failure: weak.** No-op null behavior, valid replay, positive-control response, and V4C-04 all argue against a general instrumentation failure.
4. **Target-definition suppression: expected by design, not a bug.** Permanent final breakage is intentionally excluded. That makes blackhole changes unsuitable as transient-disruption cases when their final damage remains active, but changing this now would invalidate V4.

The evidence supports a combination of hypotheses A and B, with B dominant:

- V4 shows that transient disruption is measurable under these conditions.
- The selected population does not exercise it often enough to pass G1.
- V4 does not establish that the ML hypothesis is false in all configuration-change populations.

## F. What V4 Established

- A valid runtime FIB/link/nexthop instrument can measure transient disruption.
- The positive-control mechanism produces repeatable transient T1.
- The no-op controls establish a zero empirical noise floor with the preregistered resolution lower bound.
- One carefully selected population change (`V4C-04`) produces repeatable, substantial transient disruption.
- Under the frozen population, only 5% of changes are above the measurement floor.

## G. What V4 Did Not Establish

- It did not establish a useful ML prediction problem; G1 stopped the pipeline.
- It did not establish that predeployment evidence cannot predict transient disruption in general.
- It did not justify changing the floor, threshold, target, population, or controls after observing results.
- It did not support prevalence claims or production-network claims.
- It did not validate cross-host behavior.

## H. Whether a V5 Is Justified

A V5 is scientifically defensible only as a new preregistered experiment, not as a repair of V4. The evidence supports a narrower transient-reconfiguration question, but the current V4 result should remain permanently negative for its frozen design.

### Direction 1: Transient disruption from connectivity-preserving link events

- Question: Can predeployment evidence predict transient disruption caused by a link shutdown that preserves final reachability?
- Why V4 could not answer it: only four such positive controls were included; the population did not contain this mechanism.
- Target: unchanged T1-style transient broken-flow area, with final-state breakage removed.
- Population: connectivity-preserving shutdowns selected across topology positions and alternatives, not by steady-state r alone.
- Controls: no-op, current positive controls, and golden repeats.
- Features: frozen predeployment graph, link betweenness, alternative-path count, microloop potential, and configuration change descriptors.
- Evaluation: topology-held-out regression, mechanism-stratified analysis, preregistered uncertainty.
- Kill gates: measurable-change prevalence, repeatability, analytic reducibility, host limitation, and runtime cost fixed before data.
- Risk: shutdown may remain a mechanism-specific result and may be too easy to distinguish from other mechanisms.
- Falsifier: most connectivity-preserving shutdowns remain below the resolution floor or the analytic baseline reaches the kill threshold.

### Direction 2: Cost/drain transient dynamics with timer-phase variation

- Question: Can predeployment topology and change structure predict transient disruption from OSPF cost reconfiguration without link shutdown?
- Why V4 could not answer it: only one of 16 cost/drain changes crossed the floor.
- Target: a preregistered transient area measure, with the existing V4 definition retained unless formally amended before data.
- Population: cost/drain changes selected directly for predicted transient-risk proxies such as microloop potential and alternative next-hop transitions, rather than steady-state severity alone.
- Controls: matched low-risk cost/drain changes, no-op, and shutdown sensitivity controls.
- Features: predeployment microloop potential, next-hop graph transitions, changed-link structure, and push topology.
- Evaluation: held-out topology and within-mechanism tests.
- Risk: selecting on analytic transient proxies may make the baseline too strong or create another V3-like analytic-reducibility result.
- Falsifier: the selected cost/drain set remains below the floor or the analytic proxy computes T1-like behavior nearly exactly.

### Direction 3: Convergence-dynamics measurement study without ML

- Question: Which configuration-change structures produce transient FIB disruption under FRR convergence?
- Why V4 could not answer it: G1 stopped before the 20-change set provided enough measurable cases for ML.
- Target: T1, T2, T3, event counts, settle times, and replay-validity diagnostics as descriptive outcomes.
- Population: a deliberately balanced mechanistic design, not a predictive corpus selected by steady-state severity.
- Controls: no-op and shutdown sensitivity controls on every topology.
- Features: descriptive only; no claim of prediction is required.
- Evaluation: mechanism/topology factorial summaries, replicate variance, event-sequence analysis.
- Risk: this becomes a measurement paper rather than an ML contribution.
- Falsifier: transient T1 remains nearly zero outside shutdown controls or is dominated by host-specific timing.

## I. Tempting Changes That Must Not Be Made

The following would rescue the gate rather than diagnose the experiment and are not recommended:

- lowering the D1 floor;
- lowering the 30% G1 threshold;
- replacing low-T1 population changes after observing outcomes;
- adding positive controls to the population denominator;
- redefining T1 to include permanent final-state breakage;
- extending observation selectively for low-T1 changes;
- excluding inconvenient runs;
- training ML on the one successful change or on positive controls;
- treating the smoke controls as population observations.

## J. Recommended Next Research Step

Preserve V4 exactly as a negative feasibility result and publish the diagnosis internally as:

> The V4 instrument detected transient disruption, but the frozen population selected by steady-state analytic severity produced measurable transient disruption in only 1 of 20 changes, so the preregistered G1 feasibility gate failed and no ML claim was attempted.

Before any V5 implementation, choose one new scientific direction, write and freeze its population construction and controls, and explicitly separate transient-sensitivity selection from steady-state severity selection. Do not modify V4.
