# Harm definition — v1.1.0 — FROZEN 2026-08-25

**Frozen before any Phase 3 measurement exists.** Nothing in this repository has
been executed against Containerlab or Batfish at the time of writing. Any change
to this file must bump the version, keep the old text, and state the reason —
a harm definition edited after seeing results is not a definition, it is a
result.

## Baseline

Harm is measured against `reference/golden`, the healthy pre-incident network —
not against the faulted state. A repair is supposed to restore health, so the
question is "is the network as good as it was", not "is it better than broken".

## Sets

- `ORACLE` — all 12 properties in `data/pilot-v1/properties.yml`
- `SPEC` — the 5 properties with `in_spec: true` (P01, P02, P05, P07, P08)
- `G` — the subset of `ORACLE` that holds in the golden network, measured in
  Containerlab. Expected to be all 12; if it is not, the pilot is broken and
  must be fixed before any candidate is run.

## Outcome for a candidate C

Measured in Containerlab after deployment and convergence.

| Outcome | Condition |
|---|---|
| `NO_CONVERGENCE` | the lab does not reach the convergence criterion within 180 s |
| `HARMFUL` | ∃ p ∈ `G` such that p fails in C |
| `SAFE` | every p ∈ `G` also holds in C |

`NO_CONVERGENCE` is counted as harmful in the primary analysis and recorded
distinctly so it can be excluded in a sensitivity analysis. A repair that never
converges is harmful; a repair that fails to converge because the harness timed
out too early is a measurement bug. Keeping them separable is what lets those
two be told apart later.

`HARMFUL` is binary in v1. The **identity of every failing property is
recorded**, so severity tiers can be derived later without editing this file.

## The quantity of interest

    FALSE_PASS(C)  ==  C passes every property in SPEC under Batfish (Phase 2)
                       AND  outcome(C) == HARMFUL (Phase 3)

    false-pass rate  =  |{C : FALSE_PASS(C)}| / |{C : C passes SPEC in Batfish}|

The gap between `SPEC` and `ORACLE` is declared in advance in `properties.yml`
and is the mechanism by which a false pass is possible at all. It models
specification incompleteness — the real cause of most verification-passed
outages — and not any unsoundness in Batfish. Batfish answers what it is asked,
soundly. This measures what happens when the asking is incomplete.

## Convergence criterion — v1.1.0

Poll, never sleep. A lab is converged when **all three** hold:

1. at least **45 s** has elapsed since deploy (`MIN_SETTLE_S`)
2. **no** OSPF neighbour is in a transitional state — Init, 2-Way, ExStart,
   Exchange or Loading. Every link here is point-to-point, so `Full` is the
   only settled state. A neighbour that never appears is **not** transitional.
3. every router's RIB is byte-identical across three consecutive polls 5 s apart

Timeout 180 s → `NO_CONVERGENCE`.

### Why this changed from v1.0.0 — recorded 2026-08-25

**v1.0.0 said** convergence required "every *expected* OSPF adjacency is Full"
plus RIB stability, timeout 120 s.

Two problems, one known at implementation time and one found by running it.

**(a) "Every expected adjacency" was never implementable and was never
implemented.** In a faulted lab an adjacency that cannot form is precisely the
thing being measured; requiring all of them would have timed out every incident
run by construction. The implementation used RIB stability alone. That
divergence between the frozen document and the code should have been recorded
when it was made, and was not.

**(b) RIB stability alone fires on a pre-convergence plateau.** The golden lab
declared convergence at **11.4 s after 3 polls** — the algorithmic minimum. At
t=0 the RIB holds connected routes only and OSPF has not yet begun changing it,
so it is trivially "stable". Everything was then measured mid-convergence:
`hosta`→`hostb` ICMP showed 100 % loss while the *same* probe to the *same*
address seconds later showed 0 %; 5 of 6 adjacency pairs were Full; 5 of 6
routers had no route to either site-B LAN. The network was healthy. The
measurement was early.

Condition 1 exists because conditions 2 and 3 are both trivially true before
OSPF starts: an empty neighbour table contains nothing transitional, and a
connected-only RIB is perfectly stable. 45 s exceeds the OSPF dead interval
(40 s), so an adjacency that is going to form has had the opportunity.

**Why this is not results-driven.** At the time of the change exactly one lab
had been executed — `golden`, which produces no outcome rows. Zero harm labels
existed for any candidate. The change was forced by an obviously wrong
measurement of a network already known to be healthy from its own evidence
(traceroute path correct, no loops, loopback reachable, running-config matching
the artifact), not by any candidate's outcome being inconvenient.

**Consequence:** the golden run recorded under v1.0.0 is void and must be
re-executed. No other run existed.

Measuring before convergence produces noise labels biased *toward* harm, which
would inflate the false-pass rate. If Phase 3 ever reports a rate above 60%,
suspect this before believing the result.

## Ground truth is an emulator

Containerlab runs real routing daemons — the OSPF state machine and SPF are
genuine code — but there is no hardware forwarding plane, no TCAM, no line-rate
traffic, and idealised link timing. The measurement is **static verifier vs
running emulator**, not verifier vs production. This belongs in the paper's
limitations section, written by us before a reviewer writes it.


## Property suite — v1.1.0 — recorded 2026-08-26

**Written before any pilot-v2 harm label exists.** `data/pilot-v2/phase2/` and
`phase3/` are both absent on disk at the time of writing, so no candidate in
pilot-v2 has an outcome. This entry exists because a suite edit made after
outcomes exist is not a specification, it is a result.

**Membership is unchanged.** Twelve properties, P01–P12, same SPEC set
(P01, P02, P05, P07, P08) and the same oracle-only set. The false-pass rate is
defined over that split, so the quantity measured in pilot-v1 and the quantity
to be measured in pilot-v2 are the same quantity.

**What changed: three parameters that depend on the topology are now resolved
from the topology spec instead of carrying a pilot-v1 constant.**

| id | parameter | was | now |
|---|---|---|---|
| P06 | `must_traverse` | `['wan1','wan2']` | `spec.primary_path` (Dijkstra over OSPF cost) |
| P08 | `expected` | `6` | `spec.n_adjacencies` |
| P11 | `src`, `dst` | `10.255.0.1`, `10.255.0.6` | `spec.routers['edgea']`, `spec.routers['edgeb']` |

P06 and P08 were already resolved per topology by `properties_for(spec)`; only
their published literals were stale. **P11 was not**, and that is the defect
that forced this entry: `10.255.0.6` is edgeb's loopback in pilot-v1 only.
Across the ten design-C topologies edgeb's loopback is `.4 .6 .8 .5 .5 .6 .6
.8 .6 .8`, so the hardcoded P11 was

- correct in `t02 t06 t07 t09`,
- a **false FAIL** in `t01 t04 t05` — `.6` does not exist, so `NO_ROUTE`,
- a **false PASS** in `t03 t08 t10` — `.6` exists but belongs to `wan3`,
  `wan4` and `coreb`. The property reported success about a router it was
  never meant to test.

The false-PASS group is the reason this is recorded here rather than in the
notebook: a property that silently measures a different router is a change to
what "harm" means, even though the property's text never changed.

**No pilot-v2 outcome is affected**, because none exists. The twelve pilot-v2
Phase 2 records collected before the fix were computed against the broken P11
and were discarded with the rebuild. Pilot-v1's results stand: pilot-v1 has one
topology, and `properties_for(None)` reproduces its suite byte-for-byte,
including P11 → `10.255.0.6`, which is correct there.

**Also corrected in this entry:** the outcome table above said `120 s` for
`NO_CONVERGENCE`. The v1.1.0 convergence criterion and `nrl/clab.py`
(`CONVERGE_TIMEOUT`) have both said `180 s` since 2026-08-25; the table was a
leftover from v1.0.0. No code changed — the document was wrong, not the
implementation.

**Gates added so that this class of defect cannot recur silently:**

- `pipeline/verify_golden_properties.py` — every property must PASS on every
  golden, because a golden is healthy by construction. It also asserts that
  every topology in the lock was visited and every property evaluated (a
  vacuous run used to print PASS), and checks each address-valued property's
  target against Batfish's own `ipOwners` answer, which is the only check that
  can catch the false-PASS case — pinging the wrong router succeeds.
- `nrl.properties.PER_TOPOLOGY_PARAMS` — the set of parameters that must be
  resolved from the spec. `as_yaml()` refuses to publish a constant for any of
  them, so `properties.yml` can no longer state a value that is true for one
  topology as though it were the suite.
- `nrl.topologies.resolve()` raises on an unknown topology name instead of
  falling back to pilot-v1's network, which would have resolved all three
  parameters to the wrong network at once.


## Secondary definition v1.2.0 (transient) — PRE-REGISTERED 2026-09-02

**Written before any pilot-v2 label exists**, and before the 20-topology
dataset was built. `data/pilot-v2/` does not exist on disk at the time of
writing; Git history is what makes that checkable.

**v1.1.0 remains the PRIMARY label and is unchanged.** Nothing below alters
`outcome_harm_v1`, the SPEC/ORACLE split, or the false-pass rate as measured
for comparison with pilot-v1. v1.2.0 is a SECOND label computed from the same
runs, reported alongside.

### Why a second definition is needed

v1.1.0 measures at a quiescent point at least 45 s after deploy. That is the
right way to measure steady state, and it means a repair that restores
connectivity while flapping OSPF adjacencies four times in the first minute
scores exactly the same as one that never flapped.

Most operational harm from a configuration change happens *during* the
transition, and that is the part of Batfish's blind spot that is **model scope**
(gap b) rather than **specification incompleteness** (gap a). Measuring only
steady state means the study can only ever observe gaps (a) and (c). If the
measured false-pass rate turns out to be entirely gap (a), the honest
conclusion is "write more properties" — there is no irreducible component and
no argument for a risk layer. Distinguishing those two outcomes requires
looking at the transition, so the harness now does.

### What is recorded

During the convergence poll loop, per poll:

- elapsed time, RIB route counts per router, OSPF neighbour states
- **one ICMP probe** hostA → hostB (the same pair P01 names), count 1

Summarised per run in `transient.json` and in the Phase 3 summary:

| field | meaning |
|---|---|
| `seconds_to_converge` | as v1.1.0 |
| `rib_changes_total` | RIB count changes summed over routers and polls |
| `adjacency_flaps_after_full` | a neighbour reached Full and later was not |
| `probe_polls` / `probe_unreachable_polls` | transient reachability samples |
| `transient_outage_after_reachable` | unreachable AFTER having been reachable |
| `flapped` | any adjacency flap after Full |

### The v1.2.0 outcome

A candidate is **HARMFUL under v1.2.0** iff

- it is HARMFUL under v1.1.0, **or**
- `flapped` is true, **or**
- `transient_outage_after_reachable` is true.

Everything else is unchanged, including the treatment of NO_CONVERGENCE,
UNDETERMINED and EXECUTION_FAILED.

### Why this is not results-driven

No pilot-v2 candidate has an outcome under either definition. Zero labels
exist. The change is forced by a gap in what the instrument can observe —
identified by external review of the design, not by any candidate's result
being inconvenient — and it is recorded here before the instrument is run.

A transient outage before traffic has flowed at all is **not** counted: that is
a network still coming up, not a regression. Only an outage after reachability
was already observed counts, which is what makes the signal a *transition*
rather than a slow start.
