# Mechanistic Model Report

Date: 2026-09-16

## 1. Research Question

Can predeployment analysis identify configuration changes susceptible to transient forwarding cycles during staged convergence after a Batfish-SPEC-PASS change?

This analysis did not run Containerlab, FRR, Batfish, or any new experiment. It did not use T1, runtime telemetry, FIB monitor events, packet loss, convergence duration, or observed runtime ordering as model inputs.

## 2. Inputs

The model used only:

- frozen topology definitions from `nrl/topologies_v3.py`;
- candidate push plans and configuration-change descriptions from the original/exploratory manifests;
- baseline and candidate configuration-derived costs;
- the actual serialized device/interface command order recorded in each push plan.

The six cases were V4C-04 and EX-V4-01 through EX-V4-05.

Runtime artifacts were used only after model computation for forensic comparison. They were not model inputs.

## 3. Offline Algorithms

Two related models were evaluated.

### 3.1 Global directed-cost staged SPF model

Each interface-level cost operation was applied one at a time in serialized push order. After each operation, directed interface costs were used to recompute shortest paths and next hops globally. Directed cycles were then detected by walking each endpoint flow's selected next hops.

This model produced no cycles for any of the six cases, including V4C-04. It is therefore too coarse: a globally consistent SPF state cannot represent the mixed old/new FIB states observed at runtime.

### 3.2 Mixed old/new forwarding dependency model

For each candidate:

1. Compute the golden forwarding path map.
2. Compute the final forwarding path map from the candidate configuration.
3. Preserve the serialized device push order.
4. After each device becomes active, use its final next-hop map while untouched routers retain their golden next-hop map.
5. Walk every ordered golden-carried endpoint flow through this mixed forwarding state.
6. Record cycles, cycle length, affected flows, and the number of intermediate states containing cycles.

This is a predeployment susceptibility model. It does not claim to predict runtime duration or T1.

A cycle exists when next-hop walking revisits a router before reaching the destination.

## 4. Machine-Readable Features

`results.json` and `results.csv` contain:

- number of interface-level operations;
- number of intermediate states;
- global directed-SPF cycle features;
- mixed old/new hybrid cycle-state count;
- maximum hybrid cycle-flow count;
- maximum hybrid cycle-flow fraction;
- cycle flow identities and cycle sequences for every intermediate state.

## 5. Results

| Candidate | Hybrid cycle states | Max cycle flows | Max cycle fraction | Runtime T1 reference |
|---|---:|---:|---:|---:|
| V4C-04 | 2 | 4 | 0.0625 | ~0.019306 |
| EX-V4-01 | 3 | 15 | 0.1471 | ~0.0000385 |
| EX-V4-02 | 4 | 23 | 0.1139 | ~0.0000411 |
| EX-V4-03 | 4 | 39 | 0.4756 | ~0.0000722 |
| EX-V4-04 | 4 | 46 | 0.4510 | ~0.0000957 |
| EX-V4-05 | 4 | 116 | 0.5743 | ~0.0001810 |

The runtime T1 column is validation evidence only. It was not used by the model.

## 6. V4C-04 Reconstruction

The hybrid model produces the following V4C-04 intermediate cycles after `corea` switches to its final map while the other routers retain their golden maps:

```text
corea -> wan1 -> corea
wan1  -> corea -> wan1
```

The model identifies four affected flows at that stage, including:

```text
corea->wan2
edgea->wan2
wan1->wan2
hosta->wan2
```

This is consistent with the raw runtime forensic evidence, where V4C-04 showed:

```text
corea -> wan1 -> corea
coreb -> wan1 -> coreb
```

before settling to final reachable paths such as:

```text
corea -> wan1 -> coreb -> wan2
```

The model therefore reproduces a plausible predeployment intermediate-cycle vulnerability for V4C-04.

## 7. Comparison With Exploratory Cases

The model also predicts cycles for every exploratory case:

- EX-V4-01: 3 hybrid cycle states;
- EX-V4-02: 4 hybrid cycle states;
- EX-V4-03: 4 hybrid cycle states;
- EX-V4-04: 4 hybrid cycle states;
- EX-V4-05: 4 hybrid cycle states.

This is important. The model reproduces the existence of a possible mixed-state cycle, but it does not distinguish V4C-04 from the five candidates that produced much smaller T1.

Indeed, several failed exploratory candidates have larger predicted cycle exposure than V4C-04. Therefore cycle existence or static cycle-flow fraction is not sufficient to predict realized transient disruption.

## 8. What the Model Explains

Supported:

- V4C-04's runtime loop is structurally plausible from predeployment old/final forwarding maps.
- The relevant abstraction is mixed old/new per-router forwarding state, not one globally consistent intermediate SPF state.
- A final configuration can be reachable while a staged mixed state contains forwarding cycles.

Not explained:

- Why V4C-04's cycles persisted long enough to produce T1 ≈ 0.0193.
- Why EX-V4-01 through EX-V4-05, despite predicted cycles, produced much smaller T1.
- Exact cycle duration.
- FRR LSA flooding and SPF scheduling.
- Runtime event ordering.
- Which cycle state will be installed first or persist longest.

## 9. Hypothesis Evaluation

| Hypothesis | Result |
|---|---|
| Static PML alone predicts T1 | Not supported |
| FIB-event count predicts T1 | Not supported |
| Final rerouting predicts T1 | Not supported |
| Multi-router change count predicts T1 | Partially supported, insufficient |
| Mixed old/new forwarding states can contain cycles | Supported |
| The hybrid cycle model distinguishes V4C-04 from all failed cases | Not supported |
| Runtime ordering/timing dominates realized T1 | Supported by the combined evidence |

## 10. Predeployment Versus Runtime Information

### Predeployment

The following are available before deployment:

- topology graph;
- baseline and candidate configuration;
- interface-level operations;
- serial push order;
- old and final forwarding maps;
- mixed old/new dependency cycles;
- cycle length and affected-flow exposure in the hypothetical mixed state.

### Runtime-only

The following remain unavailable before deployment:

- actual OSPF propagation order;
- actual FIB installation order;
- exact duration of each mixed state;
- FRR scheduling delays;
- whether a theoretically possible cycle is installed at all;
- realized transient T1.

The evidence supports a two-stage causal interpretation:

```text
predeployment structure -> possible cycle susceptibility
runtime timing/order   -> realized cycle duration and T1
```

## 11. Scientific Conclusion

**MECHANISM PARTIALLY SUPPORTED — refine the offline model before running experiments.**

The mixed old/new model explains the qualitative mechanism observed in V4C-04, but it is not a useful discriminator across the six cases. It predicts cycles for all five exploratory candidates and sometimes predicts greater exposure for candidates with much smaller observed T1.

The model should not yet be used to select a new runtime batch or to justify ML training.

## 12. Whether Another Runtime Experiment Is Justified

Not yet. A runtime validation experiment would be premature because the current offline feature reproduces possible cycles but not the observed distinction in realized disruption.

The next appropriate step is further offline mechanistic work, specifically modeling:

- per-router LSDB knowledge state;
- LSA propagation dependencies;
- SPF recomputation triggers;
- interface-level cost advertisements;
- route installation barriers;
- possible asynchronous orderings between neighboring routers.

Any such model must be defined independently of observed T1 and validated against all six existing cases. Only a model that distinguishes the V4C-04-like case from the exploratory cases should motivate another small runtime validation.

## 13. Limitations

- The hybrid model treats a router's transition as an old-to-final map switch, not a full FRR OSPF/LSA simulator.
- It does not represent timer scheduling or flooding delay.
- It does not claim a cycle will actually be installed.
- It does not predict T1 magnitude.
- Six cases are forensic validation, not statistical evidence.
- No ML was trained.

## 14. Files and Commands

Created in the repository:

- `v4_transient/analysis/mechanistic/analyze_mechanistic.py`
- `v4_transient/analysis/mechanistic/results.json`
- `v4_transient/analysis/mechanistic/results.csv`
- `v4_transient/analysis/mechanistic/MECHANISTIC_MODEL_REPORT.md`

No frozen V4 experiment file was modified. No candidate was created. No Containerlab or FRR run occurred during this analysis. No runtime artifact was used as a model input.

Command used:

```powershell
.\\.venv\\Scripts\\python.exe v4_transient\\analysis\\mechanistic\\analyze_mechanistic.py
```
