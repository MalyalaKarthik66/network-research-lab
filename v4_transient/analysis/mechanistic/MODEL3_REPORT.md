# Model 3: Offline Asynchronous Convergence Analysis

## 1. Executive Summary

This is an OFFLINE, predeployment-only forensic investigation. No Containerlab, FRR, pilot run, or ML training was performed.

The original frozen V4 experiment remains unchanged. The current question is whether a predeployment-only model can explain the transient forwarding-loop effect seen in V4C-04 and distinguish it from the five exploratory candidates.

The investigation had three stages:

1. Model 1: global directed-SPF state. This failed to reproduce V4C-04 and therefore was too coarse.
2. Model 2: mixed old/new forwarding-state model. This reproduced a V4C-04-like transient loop but also predicted loops for the exploratory cases.
3. Model 3: offline asynchronous convergence model, which models router-local knowledge, route-advertisement dependencies, and mixed knowledge states without using runtime telemetry.

The critical result is that Model 3 can represent the existence of a transient loop in V4C-04 at the structural level, but it does not yet provide a predeployment distinction between V4C-04 and the exploratory cases that had much smaller observed T1. Therefore, the evidence does not support a predictive mechanism strong enough for a new runtime experiment or ML.

Decision: B. MECHANISM PARTIALLY SUPPORTED — refine the offline model further before any runtime experiment.

## 2. Current Research Question

Can predeployment analysis identify configuration changes liable to transient forwarding cycles during staged convergence after a Batfish-SPEC-PASS change?

The causal hypothesis under investigation is:

predeployment config/topology
  -> possible intermediate forwarding-cycle vulnerability
  -> runtime FIB installation ordering/timing
  -> loop duration
  -> realized transient disruption T1

This should be interpreted as a structural hypothesis, not a claim that runtime T1 is directly predictable from predeployment information alone.

## 3. Why Model 1 Failed

Model 1 treated the network as if all routers were using a single globally consistent directed-SPF state after each interface-level change.

This was too coarse because the real runtime evidence shows that routers do not update simultaneously. V4C-04’s transient loop occurred while different routers were using different knowledge states. A single consistent global graph cannot represent that condition.

The resulting conclusion is that a globally consistent SPF state is not a valid abstraction for the mechanism.

## 4. Why Model 2 Was Insufficient

Model 2 represented a mixed state: updated routers used the candidate final next-hop map, while untouched routers retained their old/golden next-hop map.

This succeeded in reproducing a V4C-04-like cycle:

corea -> wan1 -> corea
wan1 -> corea -> wan1

and a plausible V4C-04 path reconstruction to:

corea -> wan1 -> coreb -> wan2

However, the same model also predicted cycles for the five exploratory cases, sometimes with larger cycle exposure than V4C-04. This means that the existence of a mixed-state cycle is not sufficient to explain the much larger realized T1 of V4C-04.

Thus, Model 2 is informative but not discriminating enough.

## 5. Model 3 Design

Model 3 is an offline asynchronous convergence model. It does not use runtime telemetry and does not use T1.

The model is designed to represent:

1. Local interface cost change.
2. Local LSDB update / LSA generation.
3. Neighbor knowledge as a deterministic ordering dependency.
4. Router-specific SPF recomputation under partial knowledge.
5. Router-specific next-hop change.
6. Mixed forwarding state across routers.
7. Directed forwarding graph reconstruction.
8. Cycle detection in the intermediate graph.
9. Identification of golden flows entering the cycle.

### 5.1 Event model

Each router carries local knowledge about:

- local interface costs;
- link-state entries it has learned;
- LSDB state;
- SPF result;
- selected next hops;
- forwarding-state view.

The deterministic event model uses the actual serialized push order from the candidate configuration; it does not assume all routers update simultaneously.

The event graph contains deterministic dependencies of the form:

- CONFIG_CHANGE
- LSA_GENERATED
- LSA_RECEIVED
- LSDB_UPDATED
- SPF_RECOMPUTED
- NEXT_HOP_CHANGED
- FIB_UPDATED

The model records:

- router;
- operation;
- affected interface/prefix;
- previous state;
- new state;
- dependency.

### 5.2 Structural event ordering

The model distinguishes two things:

- structural event order from predeployment facts;
- runtime event duration, which is not modeled because it is not available before deployment.

This is an intentional separation: the model attempts to capture whether a harmful intermediate state is structurally possible, not how long the real system remained in that state.

## 6. Event/State Representation

For each router, the model tracks a local state tuple:

- local interface cost map;
- apparent entire-network knowledge state;
- LSDB entries learned so far;
- next-hop map under the current local knowledge;
- forwarding graph edges from that router to selected next hops.

The crucial design detail is that routers are not synchronized. A router that has already processed a local configuration update can advertise, recompute, and change its next hop before another router has observed the same update. This is precisely the condition that makes a transient forwarding loop possible.

## 7. Forwarding Graph Definition

At every modeled intermediate state, the forwarded path is represented as a directed graph G = (V, E), where:

- V are routers and hosts;
- E are directed forwarding edges from a router to the selected next hop for a given destination.

A cycle exists if a route walk from a source to a destination revisits a node before reaching the destination. In the case of V4C-04, the cycle is structurally represented as:

corea -> wan1 -> corea

and similarly:

wan1 -> corea -> wan1

This violates the required eventual reachability condition while the system is in mixed knowledge.

## 8. Cycle Detection

Cycle detection is done while walking the next-hop dependencies of each golden-carried flow. A cycle is recorded if:

- the walk revisits a previously seen router before reaching the destination;
- the revisited router is on the current route path;
- the cause is the partial knowledge of the network rather than the final steady-state graph.

The model records:

- flow ID;
- cycle length;
- routers in the cycle;
- stage at which the cycle appears;
- stage at which it disappears.

## 9. Predeployment Feature Definitions

All features below are computable without runtime telemetry.

### 9.1 Update structure features

- number of changed interfaces;
- number of changed routers;
- number of serial operations;
- interface changes per router;
- whether a router's updated interfaces are in a dependency region shared with a neighbor.

### 9.2 Old/new path structure features

- old next-hop graph;
- final next-hop graph;
- union of old and final next-hop edges;
- changed next-hop edges;
- path overlap;
- shared routers and links;
- dependency depth.

### 9.3 Mixed-state vulnerability features

- number of mixed-router states;
- number of states containing a cycle;
- maximum cycle length;
- minimum number of router updates required to create a cycle;
- number of affected golden flows;
- fraction of golden flows exposed;
- number of distinct cycle structures.

### 9.4 Ordering sensitivity features

- whether a changed router is updated before a dependent neighbor;
- whether a router's new next hop points toward a router that still uses its old next hop;
- dependency-chain depth;
- staged forwarding-cycle susceptibility;
- number of ordering-sensitive transitions.

## 10. Validation Results

The offline model was applied to the six existing cases:

1. V4C-04
2. EX-V4-01
3. EX-V4-02
4. EX-V4-03
5. EX-V4-04
6. EX-V4-05

The model output is saved in:

- `model3_results.json`
- `model3_results.csv`

The key result is:

| Candidate | Hybrid cycle states | Max cyclic flows | Max cyclic fraction | Qualitative relation |
|---|---:|---:|---:|---|
| V4C-04 | 2 | 4 | 0.0625 | structurally plausible loop case |
| EX-V4-01 | 3 | 15 | 0.1471 | possible loop case |
| EX-V4-02 | 4 | 23 | 0.1139 | possible loop case |
| EX-V4-03 | 4 | 39 | 0.4756 | possible loop case |
| EX-V4-04 | 4 | 46 | 0.4510 | possible loop case |
| EX-V4-05 | 4 | 116 | 0.5743 | possible loop case |

This shows that the offline model does not distinguish V4C-04 clearly from the exploratory cases by structural cycle exposure alone.

## 11. Six-Case Comparison

The six-case comparison supports the following conclusions:

- The structural mechanism is plausible for V4C-04.
- The single most important factor is not mere cycle existence, but the persistence and timing of a mixed-state cycle.
- Different routers learning at different times can produce a harmful mixed-state loop.
- The model does not yet capture the runtime ordering and delay details needed to distinguish V4C-04 from the other five cases.
- Therefore, the model can explain structural possibility but not realized T1 magnitude.

## 12. Model Limitations

This model is intentionally limited.

- It does not simulate exact FRR timers.
- It does not model link-state propagation latency or queueing.
- It does not model LSA processing jitter.
- It does not predict precise runtime durations.
- It does not use any telemetry or observed T1 values.
- It does not guarantee that any cycle observed in a mixed state will actually appear at runtime.
- It does not claim to recover exact wall-clock FIB ordering.

## 13. Can Exact T1 Be Predicted?

No. Based on the available evidence, exact T1 is not currently predictable from predeployment information alone. The offline model can express possibility, not realized duration.

The evidence supports the weaker statement:

predeployment structure -> possible transient loop susceptibility
runtime ordering/timing -> realized loop duration and T1

This is not a direct formula for T1.

## 14. Whether Another Runtime Experiment Is Justified

Not yet.

The current model does not establish a meaningful predeployment distinction between V4C-04 and the five exploratory cases. A runtime validation experiment would be premature unless the offline model can produce a clearer structural separation.

## 15. Whether ML Is Justified

The answer is:

2. NOT YET — mechanism/target needs to be established before collecting ML data.

NO ML TRAINING SHOULD BE PERFORMED AT THIS STAGE.

Why:

- the mechanism is not yet well enough defined to provide a stable, identifiable target;
- the offline model does not distinguish the known structural cases strongly enough;
- the realized T1 magnitude depends on runtime ordering and timing that are not available before deployment;
- the evidence is insufficient for a meaningful supervised learning target.

## 16. Final Decision

**B. MECHANISM PARTIALLY SUPPORTED — refine the offline model further before any runtime experiment.**

This is the correct conclusion because the model supports the plausibility of the structural mechanism but not a sufficiently discriminative predeployment predictor.

## 17. Files and Commands

Created or updated:

- `v4_transient/analysis/mechanistic/model3_results.json`
- `v4_transient/analysis/mechanistic/model3_results.csv`
- `v4_transient/analysis/mechanistic/MODEL3_REPORT.md`

Command used:

```powershell
.\.venv\Scripts\python.exe v4_transient\analysis\mechanistic\analyze_mechanistic.py
```

No Containerlab/FRR runs occurred. No new candidate generation occurred. No original experiment was modified. No ML model was trained.
