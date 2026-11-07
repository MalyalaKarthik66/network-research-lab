# Surprises

Every time Batfish does something you did not predict, it goes here -- whether
it turned out to be your misunderstanding or a real property of the tool.

Rules:

1. Write the entry BEFORE you work out the explanation. The prediction you had
   is the valuable part and you will lose it the moment you understand why you
   were wrong.
2. One entry per surprise. Do not merge them.
3. A surprise that turned out to be your own mistake still counts. Those are
   the ones that show where the mental model was wrong.

Template:

```
## S-NNN  <one-line title>

**Date:**
**Snapshot / script:**

**What I predicted:**

**What actually happened:**

**Explanation (fill in later):**

**Does this change how I would trust a verification result? How?**
```

---

## S-001  FRR has no packet ACLs, so an entire fault family is unavailable

**Date:** 2026-08-25
**Snapshot / script:** design of `nrl/faults.py`

**What I predicted:** that ACL misconfiguration would be one of the richest
fault families, as it was in the Phase-0 Cisco IOS material -- wrong wildcard
masks, shadowed rules, wrong direction.

**What actually happened:** FRR `access-list` / `prefix-list` / `route-map` are
ROUTE filters, not packet filters. Packet filtering on Cumulus is
`/etc/cumulus/acl/policy.conf` -> iptables -> hardware, which is not part of the
concatenated format Batfish reads. Injecting an iptables rule would mean the
container enforces something the snapshot cannot contain.

**Explanation:** FRR is a routing daemon suite. The Cisco mental model of "the
router config file contains the firewall rules" does not transfer.

**Does this change how I would trust a verification result? How:** yes, and in
a direction worth writing down. On this platform there is an entire class of
policy that Batfish structurally cannot see, because it is not in the file it
reads. That is not a Batfish limitation -- it is a limitation of what the
artifact contains. A verification result is bounded by the artifact as much as
by the question asked, and I had not separated those two before.

## S-002  A failed candidate can disappear instead of showing up as failed

**Date:** 2026-08-25
**Snapshot / script:** `pipeline/verify_phase2.py` CHECK 3, found via a
synthetic dataset in /tmp

**What I predicted:** that a completeness check counting rows per candidate
would obviously catch a candidate with missing rows.

**What actually happened:** it did not. The check built a Counter over the
candidate ids *present in the CSV*. A candidate with zero rows never enters the
Counter at all, so `n != 12` is never evaluated for it. 588 of 600 property rows
and 833 of 850 question rows were reported as complete.

**Explanation:** counting over observed keys can only detect wrong counts, never
absent ones. The count has to be taken over the EXPECTED key set.

**Does this change how I would trust a verification result? How:** yes, and it
generalises well beyond this script. It is the same shape as the Batfish lesson
from Phase 0 -- an empty answer means either "the property holds" or "the
question never reached anything". Absence and success look identical unless
something independent asserts what should have been there. Worth remembering
when Phase 3 counts converged labs, and worth a sentence in the paper's
methodology: completeness was checked against the manifest, not against the
collected rows.

## S-003  Batfish lowercases hostnames, and my check restated instead of derived

**Date:** 2026-08-25
**Snapshot / script:** `pipeline/spike_frr_batfish.py` CHECK 3/4, first real run

**What I predicted:** that interface addresses either survive the concatenated
format or they do not, and the check would tell me which.

**What actually happened:** the check reported 15 of 21 addresses missing, for
corea, coreb, edgea and edgeb. wan1 and wan2 "passed". The addresses were all
present -- `ospfSessionCompatibility` in the same output showed every one of
them. Batfish lowercases hostnames, my expectation dict was keyed in mixed case,
and wan1/wan2 only passed because they contain no uppercase letters.

**Explanation:** the check hardcoded expected values instead of deriving them
from the same model that produced the artifact. A hardcoded expectation is a
second source of truth, and it drifted from the first one immediately.

**Does this change how I would trust a verification result? How:** yes, and the
lesson is uncomfortable because the failure was loud and confident and wrong. A
verifier that restates what it is verifying can only tell you whether you typed
the same thing twice. Every expectation in the spike is now derived from the
nrl Scenario object. This is worth a line in the paper's threats-to-validity:
the harness itself is a source of error, and a red result deserves the same
scrutiny as a green one.

## S-004  Batfish accepted an FRR access-list and modelled nothing, silently

**Date:** 2026-08-25
**Snapshot / script:** incident I-10 (retired), `definedStructures` on corea

**What I predicted:** that if Batfish could not handle the FRR
`access-list` + OSPF `distribute-list` I would see it in `parseWarning` -- that
being the whole point of running parseWarning on every snapshot.

**What actually happened:** zero parse warnings, zero initIssues, file status
PASSED, and `definedStructures` returned only interfaces. The construct was
accepted by the grammar and dropped by the model.

**Explanation:** parsing and modelling are different stages. A line can be
grammatically recognised and still have no representation in the
vendor-independent model. `parseWarning` covers the first gap, not the second.

**Does this change how I would trust a verification result? How:** substantially.
I had been treating "zero parse warnings" as the evidence that the model
contains my configuration. It is not -- it only means nothing was
grammatically rejected. The only sound check is a positive one: assert the
construct is present in the model. This is the same shape as S-002 (absence
looks like success) and as the Phase-0 lesson about empty DataFrames. Three
independent instances of one idea now, which makes it a methodology paragraph
rather than an anecdote.

## S-005  `link-down yes` is valid ifupdown2 and invalid Batfish -- loudly

**Date:** 2026-08-25
**Snapshot / script:** spike CHECK 1, incidents I-01 and I-02

**What I predicted:** that expressing admin-down in the interfaces file would be
read by both tools, since it is standard ifupdown2 syntax.

**What actually happened:** `parseWarning` -- "This syntax is unrecognized",
parser context `cumulus_interfaces_configuration`. Batfish still knew the
interface was down, because the same state was also written as `shutdown` in
frr.conf, so the artifact happened to be redundant.

**Explanation:** Batfish's cumulus_interfaces grammar covers a subset of
ifupdown2.

**Does this change how I would trust a verification result? How:** less than
S-004 does, and that contrast is the point. This failure was LOUD -- one grep of
parseWarning found it. S-004's access-list failure was silent. Both were the
same underlying problem, "the model does not contain what I wrote", and only one
of them was survivable by the checking I had. I have removed the redundancy:
admin state now has exactly one representation, `shutdown` in frr.conf.

## S-006  Batfish's `Active` is derived, and it was right where I was wrong

**Date:** 2026-08-25
**Snapshot / script:** spike CHECK 3, I-01/wan2:eth1 and I-02/edgeb:eth1

**What I predicted:** that `interfaceProperties.Active` reports the configured
admin state, so an interface with no `shutdown` should read Active=True.

**What actually happened:** two mismatches, both on the PEER of a shut
interface. Batfish reported wan2:eth1 inactive because wan1:eth2 -- its
layer-1 neighbour -- is shut.

**Explanation:** with a layer1_topology.json supplied, Batfish models carrier:
a link with one end down has no line protocol at either end. That is correct,
and more faithful than what I expected. My expectation was the naive one.

**Does this change how I would trust a verification result? How:** it changes
what I think a "mismatch" means. Two of the three coverage failures in this run
were my model of Batfish being wrong, not Batfish being wrong -- and I would
have "fixed" a correct behaviour if I had reacted to the red result without
reading it. The expectation now accounts for peer state, which incidentally
means the check validates Batfish's link-state propagation too.

## S-007  My own normaliser produced 131 false mismatches. Again.

**Date:** 2026-08-25
**Snapshot / script:** spike CHECK 3, ospf_network

**What I predicted:** nothing -- I had already been burned once (S-003) and
believed the comparison was now derived rather than hardcoded.

**What actually happened:** 131 of 131 reported as mismatched, every one of them
`want point-to-point got POINT_TO_POINT`. The normaliser stripped `-` and
lowercased but did not strip `_`, so `point_to_point != pointtopoint`.

**Explanation:** Batfish returns enums in SCREAMING_SNAKE; the artifact writes
vendor syntax. Two representations of the same value, compared with a
hand-rolled string transform written inline at the comparison site.

**Does this change how I would trust a verification result? How:** this is the
second time in one session that MY harness produced a confident false negative,
after S-003. Neither was a Batfish problem. Both were comparison code written
inline rather than as a named, separately-tested function. `same_value()` now
exists and has unit assertions. For the paper: harness error and system error
are not the same thing and my results section needs to be able to tell them
apart -- which is exactly what the run_status/ERROR separation in Phase 2 is
already built to do, and I should say so explicitly.

## S-008  I pinned a container image tag that does not exist

**Date:** 2026-08-25
**Snapshot / script:** `nrl/emit.py`, Phase 3 setup

**What I predicted:** that `quay.io/frrouting/frr:8.4.4` was a real image,
because it looked like one.

**What actually happened:** `docker pull` -> "not found". The Docker Hub
registry API shows `frrouting/frr` publishes `v8.4.0` and `v8.4.1` -- with a `v`
prefix -- and nothing after December 2022. The value I wrote was wrong on
registry, prefix and version simultaneously, and had sat in the artifact through
Phase 1 verification, the spike and all of Phase 2 without anything noticing.

**Explanation:** nothing in Phases 1-2 touches the container image. Batfish
never reads `topology.clab.yml`. Sixteen verification checks passed over an
artifact containing a reference that could never work, because no consumer of
those checks depended on it.

**Does this change how I would trust a verification result? How:** yes, and it
is the sharpest instance yet of the project's own thesis. Every check passed.
The specification -- the set of things being checked -- simply did not include
"the images referenced actually exist". That is not a verifier being wrong, it
is a property nobody wrote down, and it is precisely what the paper claims about
network verification. Worth citing in the intro as a lived example rather than a
hypothetical: the artifact was verified, the verification was sound, and the
thing was still broken.

## S-009  The convergence detector fired before convergence started

**Date:** 2026-08-25
**Snapshot / script:** Phase 3, golden lab, first real Containerlab run

**What I predicted:** that "the RIB has not changed for three consecutive polls"
was a sound definition of converged, and that the golden lab would come up clean.

**What actually happened:** golden reported converged at 11.4 s after exactly 3
polls -- the algorithmic minimum -- and then measured a network that had not
finished converging. P01 (hosta ping hostb) showed 100 % loss; P02, pinging the
SAME address from the SAME host a few seconds later, showed 0 % loss and a
successful TCP connect. P08 counted 5 of 6 adjacency pairs. P09/P10 found routes
on 1 of 6 routers. The network was healthy the whole time.

**Explanation:** at t=0 the RIB contains connected routes only, because OSPF has
not yet started adding anything. "Unchanged for three polls" is therefore
trivially true on the pre-convergence plateau. The test could not distinguish
"finished changing" from "not yet started".

**Does this change how I would trust a verification result? How:** yes, and it
is the sharpest case yet, because this one would have silently produced a
plausible dataset. Every one of the 50 harm labels is "held in golden, fails in
candidate". A golden reference measured mid-convergence has properties
spuriously false, which removes them from the set G and makes real regressions
in candidates invisible -- the false-pass rate would have come out too LOW, in
the direction that makes the paper's headline number look less interesting and
more publishable-sounding. I would not have been suspicious of it.

The general shape, for the third time in this project (S-002, S-004, S-008): a
test that cannot distinguish "condition satisfied" from "condition never
evaluated". Absence and success are indistinguishable unless something
independent asserts what should have been there. Here the independent assertion
is elapsed time exceeding the OSPF dead interval.

## S-010  The two phases were measuring different interface sets

**Date:** 2026-08-25
**Snapshot / script:** Phase 3 full run, P12, found via the exact_revert control

**What I predicted:** that "no interface is administratively down" meant the
same thing to Batfish and to the emulator, since both read the same artifact.

**What actually happened:** across the ten exact_revert candidates -- which are
BYTE-IDENTICAL to golden, so all twelve properties must hold in all ten -- P12
failed five times. Eleven of twelve properties were perfectly stable; only P12
flipped. The interfaces it named were `clab-3afeb34c`, `clab-fdce9567`,
`coreb:clab-25141c46` ... random hex, each appearing exactly once. They are
Containerlab's transient veth staging stubs, plus eth0, the management link.

**Explanation:** FRR's `show interface json` reports the whole namespace.
Batfish only knows the four interfaces in the configuration. The emulator was
evaluating P12 over a larger, partly RANDOM set. The property text was the same
in both phases; the domain of quantification was not.

**Does this change how I would trust a verification result? How:** this is the
most useful thing the pilot has produced so far, and it is not about Batfish at
all. Two tools agreed on a property's wording and disagreed on its scope, and
nothing in fifteen Phase-1 checks, thirty Phase-2 checks or thirty-five Phase-3
checks noticed, because every check verified that the property was MEASURED, not
that the two measurements ranged over the same set.

It only surfaced because exact_revert is byte-identical to golden and therefore
functions as an accidental control -- an invariant that must hold, checked
against reality. Every future property needs one of those. For the paper: a
comparison between a model and a system is only valid over the domain both
represent, and "same artifact" does not by itself guarantee "same domain".

## S-011  FRR echoed back `shutdown` and left the interface up

**Date:** 2026-08-25
**Snapshot / script:** Phase 3 run 2, incident I-01, wan1 eth2

**What I predicted:** that a runtime check comparing the container's
`show running-config` against the artifact proved the emulator was running the
network Batfish analysed. It passed on all 61 labs, twice.

**What actually happened:** I-01 and I-02 -- the two iface_down incidents --
broke NOTHING. Zero golden properties failed. Both reported 6 OSPF adjacency
pairs when shutting the primary WAN link must leave 5. Digging in:

  artifact frr.conf : interface eth2 ... shutdown
  show running-config: interface eth2 ... shutdown     <- delivered
  FRR show interface: eth2 admin='up' oper='up'        <- NOT in effect
  ip addr           : eth2 <BROADCAST,MULTICAST,UP,LOWER_UP> state UP
  ospf neighbor     : 10.255.0.4 Full/- on eth2

FRR parsed `shutdown`, stored it, echoed it back, and never applied it to a veth
that Containerlab moved into the namespace after the daemon read its config.

**Explanation:** my runtime check compared config TEXT. Text present proves the
container was GIVEN the configuration. It does not prove the configuration is IN
EFFECT. Batfish models `shutdown` as an inactive interface -- the spike verified
that, 231 checks, 0 mismatches, including deactivating the peer. So for the
entire iface_down family the verifier and the emulator were analysing different
networks, which is the one confound this whole architecture exists to prevent.

**Does this change how I would trust a verification result? How:** more than
anything else so far. The same-artifact guarantee had three layers -- byte
identity of the files, hash verification after staging, and running-config
comparison -- and all three passed while the two tools ran different networks.
Every layer verified TRANSPORT. None verified EFFECT.

For the paper this is a limitation that applies to any model-vs-emulator study,
including ones that do not notice: proving the device received the configuration
is not proving the device implemented it. The fix is a state assertion --
compare the model's intended admin state against the interface state the device
reports -- and it belongs in the methodology, not the appendix.

Fourth instance of the same shape (S-002, S-004, S-008, S-010): a check that
cannot distinguish "condition satisfied" from "condition never evaluated".

## S-012  Unreachable was scored as looping

**Date:** 2026-08-25
**Snapshot / script:** Phase 3 run 3, P07, candidates C-0038/39/40

**What I predicted:** that the six false passes violating a SPEC property were
model-vs-device divergence -- Batfish asked, Batfish answered, emulator
disagreed -- and therefore the strongest finding in the pilot.

**What actually happened:** three of the six were my measurement. P07 (no
forwarding loops) ORed `max_hops_reached` into its loop criterion. A blackholed
destination returns twelve rows of `*` and hits the hop limit, so unreachability
scored as a loop. The stored evidence says it plainly:
`loop_suspected=False, max_hops_reached=True`. The loop heuristic was correct;
the property that consumed it was not. Batfish's detectLoops said no loop and
was right.

**Explanation:** the two phases were computing different functions under one
property name. Batfish P07 = detectLoops, a proof. Emulator P07 = a traceroute
heuristic that also fired on unreachability. Same name, different semantics --
the same failure as S-010, where P12 shared a name across different domains.

**Does this change how I would trust a verification result? How:** it changes
what I think the exact_revert control can do. That control catches
NON-DETERMINISM: the same config measured twice giving different answers. It
cannot catch SYSTEMATIC mis-measurement, where both phases are consistently
wrong in the same way every time. P07 was stable across all three runs and
stably wrong.

What caught it was comparing Batfish against the emulator property by property
and investigating every disagreement rather than reporting the total. That has
to be a standing step, not something done once because a number looked odd:
26 disagreements, all in the optimistic direction, and roughly half were my own
harness. Any paper reporting a model-vs-reality gap needs to show it audited the
disagreements individually, or the number is just the sum of its bugs.

## S-013  "Can ping" is bidirectional; Batfish reachability is not

**Date:** 2026-08-25
**Snapshot / script:** Phase 4, P05 audit

**What I predicted:** that the 9 optimistic P05 disagreements were either real
model-vs-device divergence or a sixth harness bug.

**What actually happened:** neither, exactly. All 9 are candidates of I-09
(static_wrong_nexthop) and I-10 (static_route_loop) plus one iface_down case.
All show 100% packet loss on the return probe. For C-0003 the FORWARD direction
also shows 100% loss, so the network genuinely cannot carry the traffic.

Batfish's P05 asks: can a packet get from hostb to hosta? Unidirectional; it
traces one flow. The emulator's P05 runs `ping`, which needs the ECHO REQUEST to
arrive AND the ECHO REPLY to come back. The faults break the hosta-ward
direction, so the reply never returns and ping reports 100% loss while Batfish's
one-way trace succeeds.

**Explanation:** the property text says "hostb can ping hosta". Ping is
round-trip by definition, so the EMULATOR matches the text and my Batfish
evaluator does not -- I implemented a bidirectional property with a
unidirectional query.

**Does this change how I would trust a verification result? How:** it is the
third instance of one pattern (S-010 P12 scope, S-012 P07 loops-vs-unreachable,
now S-013 P05 direction): the two phases share a property NAME and compute
different FUNCTIONS. Same words, different semantics, and every completeness
check passes because both phases did measure something.

Three instances is a methodology, not an anecdote. Any model-vs-system
comparison needs, per property, an explicit statement of the function each side
computes and a check that they are the same function -- not merely that both
produced a value. That belongs in the paper as a named threat to validity.

Consequence here: all 9 sit in the batfish=FAIL bucket, so the 24 passing
candidates and the 12/12 split are UNAFFECTED. But the "21 optimistic
disagreements, 0 pessimistic" headline must not be reported as 21 instances of
model-vs-device divergence. After audit it is far fewer.


## S-014 -- the config diff IS the repair operator (2026-09-02)

**What surprised us.** Before spending a single hour of Batfish or Containerlab
time on pilot-v2, `audit_dataset.py` asked a question that needs no labels: can
`repair_class` -- which is banned from X -- be recovered from the features that
ARE in X? Worst-case one-vs-rest grouped-CV AUC came back at **0.999**, against
a contamination threshold of 0.85 set in advance.

**Why it matters.** `repair_class` largely determines harm by construction:
correct repairs mostly measure SAFE, regressive ones mostly HARMFUL. If the
features determine the class, then a risk model trained on them predicts harm by
recovering the GENERATOR, not by understanding the network. That is pilot-v1's
`exact_revert` shortcut in a new form -- and the whole v2 redesign existed to
remove exactly that.

**Where it lives.** `diagnose_shortcut.py`, group ablation:

    chg_ (config diff)     16 features   worst AUC 0.995
    g_   (graph, Tier A+)  28 features   worst AUC 0.944
    cov_ (spec coverage)    8 features   worst AUC 0.766
    ALL                    52 features   worst AUC 0.999

    without chg_   0.951      without g_   0.997      without cov_  0.999

No single column is a tag -- the strongest is `chg_touches_cost` at 0.824. The
signature is DISTRIBUTED, and **no leave-one-group-out subset falls below
0.95**. Only `cov_` alone is under the threshold, and only barely.

**The mechanism.** Each repair class uses a systematically different set of
config constructs, because that is what makes it correct, regressive or
incomplete: correct repairs adjust cost, regressive ones shut or blackhole or
re-area, incomplete ones add a static or a description. The construct mix IS
the operator vocabulary. One instance was fixable -- every `RR-*` operator
damaged a DIFFERENT device, making `devices_touched >= 2` a near-label at AUC
0.890; adding same-device variants dropped it to 0.777. The rest is not
fixable by adding more operators of the same kind.

The graph features were added to give a model topological signal without a GNN.
They inherit the signature too (0.944), because operators change the graph in
operator-specific ways: a shutdown removes an edge, a cost edit does not.

**Does this change how we would trust a verification result? No -- but it
changes what the dataset can support.** The measurement study is untouched: the
false-pass rate, the a/b/c decomposition and the specification-completeness
sweep involve no model. What is compromised is the learned-risk-model arm.

**What is still open, and what Phase 2 answers.** This audit could only test the
features that exist before Batfish runs. Tier B and Tier C -- Batfish's own
outputs and its verdicts on the oracle-only properties -- are measurements of
the AFTER network rather than descriptions of the edit, and `docs/LEAKAGE.md`
has always treated them as eligible. Whether they carry the same signature is
unknown until Phase 2 exists, and it is the question that decides whether a
usable risk score exists at all. Re-run the audit against them the moment
`phase2/batfish_summary.csv` is written.

**Consequence for the paper.** Three instances of one methodology now
(S-010/S-012/S-013 were "same property name, different function"; this is
"same feature, different meaning"). A synthetic repair corpus encodes its
generator in the config diff so completely that a learned risk model measures
the generator. That belongs in the paper as a named threat to validity for
ML-for-networking datasets generally, not as a footnote about ours -- and it is
a stronger argument for bounding residual risk than for predicting it.


## S-015 -- P08's `expected` was never read on the Batfish side (2026-09-03)

**What surprised us.** The golden-property gate's negative control NC4 asks for
`spec.n_adjacencies + 1` OSPF adjacencies and must FAIL on a healthy golden. It
returned **PASS on all twenty topologies**.

**Why.** `bf_eval`'s `ospf_adjacencies` evaluator never read `prop["expected"]`.
It compared the observed adjacency SET against `expected_ospf_pairs(spec)` and
ignored the count entirely, so changing `expected` from n to n+1 had no effect
on the verdict. Meanwhile `p3_eval`'s version compares the COUNT
(`full_adjacency_pairs == prop["expected"]`).

**Two defects, not one.**

1. A parameter that `properties_for()` resolves per topology and `as_yaml()`
   records in the frozen document was **dead code** in one of the two
   evaluators. A parameter nothing reads is not a parameter, and the frozen
   `properties.yml` was documenting a value that had no effect on Phase 2.
2. P08 computed a **different function in Phase 2 than in Phase 3** -- set
   equality versus count equality -- across the two phases whose disagreement
   IS the measurement. Same property id, two meanings.

**This is the fourth instance of one pattern.** S-010 (P12 scope), S-012 (P07
loops versus unreachable), S-013 (P05 direction), now S-014's sibling here. Any
model-versus-system comparison needs, per property, an explicit statement of
the function each side computes and a check that they are the same function --
not merely that both produced a value. Three instances was a methodology; four
means the check belongs in the harness, not in a reviewer's head.

**Direction of error.** The Batfish check was STRICTER (set equality implies
count equality), so it made Phase 2 more conservative rather than optimistic.
No collected data is invalidated -- pilot-v1's P08 results stand. But the
negative control was inert, which means the gate's PASSes on P08 carried no
information about whether the parameter worked.

**Fix.** `bf_eval` now checks the count as well as the set, and records
`n_pairs`, `expected_count` and `count_matches` in the evidence. NC4
discriminates again.

## S-016 -- a symmetric topology has no primary path (2026-09-03)

**What surprised us.** P06 ("hosta->hostb uses the primary path") FAILED on the
goldens of `t16_pop14` and `t17_metro13` -- networks that are healthy by
construction.

**Why.** Both topologies had two EQUAL-COST paths between the hosts.
`t16_pop14`: the route-reflector chain `pe1->rr1->rr2->pe3` cost 30, exactly the
same as the P-core `pe1->p1->p2->pe3`. `t17_metro13`: a ring with uniform link
costs, so `m1->m2->m3->m4->m5` and `m1->m8->m7->m6->m5` are both 40.

`primary_path` is computed by Dijkstra, which returns ONE path and breaks ties
arbitrarily. P06 then requires every trace to traverse it, and under ECMP half
the traces take the other branch. **The property was right and the topology was
wrong** -- there is no "primary path" in a network with two equal best paths.

**Caught before any label existed**, by a gate that exists precisely because a
property failing on a healthy network is measuring something other than its
text. Had this reached Phase 2, every candidate of those two topologies would
have inherited a P06 that fails for reasons unrelated to the candidate.

**Fix.** Costs adjusted to break both ties (rr chain 10 -> 20; the far half of
the metro ring 10 -> 20), both of which are also more realistic. And the
condition is now a BUILD-TIME test: `test_graphfeat.py` CHECK 1b asserts every
design topology has exactly one shortest ingress->egress path, so a future
topology cannot reintroduce it.


## S-017 -- the completeness check ignored the run's own filter (2026-09-03)

**What surprised us.** Stage 1 ran 46 candidates deliberately, via `--only`.
`verify_phase2` reported four failures: "1,433 manifest candidates missing".
Nothing was missing. 46 of 46 requested candidates were processed, zero errors,
zero ledger duplicates, and a 20 PASS / 26 FAIL split.

**Why.** CHECK 2 and CHECK 3 derived the expected set as EVERY candidate in the
manifest, with no reference to what the run was asked to do. Any restricted run
-- a stratified validation batch, or any of the four planned `--batch-size 500`
batches -- fails it by construction.

**This is defect B1 for the second time.** The same shape was found and fixed in
`verify_phase3.py`: the expectation must be recomputed from the manifest AND the
run's declared eligibility filter. When `verify_phase2.py` was inspected during
that work it was judged "manifest-derived, v2-ready" on the strength of CHECK 2
reading the manifest -- without considering the batched case. Reading the code
that computes an expectation is not the same as checking the expectation is
right for every way the run can be invoked.

**Direction of error: pessimistic.** It cried wolf on good data, which is the
harmless direction, but a verifier that fails on every batched run is a verifier
that gets ignored -- and then it is not there when it matters.

**Fix.** `run_phase2` records `candidate_filter`, `limit` and `batch_size` in
`run_metadata.json`; `verify_phase2` recomputes the eligible set from the
manifest and those, reports un-run eligible candidates as REMAINING when the run
was batched, and fails only when candidates are missing from an unbatched run or
present outside the expected set.

---

## S-018 -- the lab name was rebuilt instead of read (2026-09-03)

**What happened.** The first real Phase 3 run on pilot-v2 came back 29/29
`CONTAINERS_MISSING`. Every containerlab deploy had actually SUCCEEDED --
`clab_deploy.json` records `rc=0` and the containers were running as
`clab-nrlv2-golden-t01_chain4-corea`. `run_one` then computed
`lab = f"nrl-{run_id.lower()}"` and asked `docker ps` for
`clab-nrl-golden-t01_chain4-corea`, which does not exist.

**Why.** pilot-v1 named its labs `nrl-<id>`; `build_pilot_v2.py` names them
`nrlv2-<id>`. The artifact states its own name on the first line of
`topology.clab.yml` -- the deploy used that name, the lookup re-derived a
different one. This is the fourth defect of the same shape this session (B5,
B6, the `kind` sniffing, now this): an identity that the artifact already
carries was reconstructed from a string instead of read.

**Direction of error: loud, by luck.** Every lab failed visibly. Had the two
naming schemes overlapped for some subset, the run would have silently
measured the wrong labs.

**Second defect, found by the first.** The per-batch golden control reported
`3 golden run(s), ALL IDENTICAL` -- on three runs that had identically FAILED.
It compared property vectors across all golden rows without checking that any
of them had executed, so empty vectors compared equal. A control that passes on
its own absence is the exact failure mode this project exists to study.

**Fix.** `lab_name_from_artifact()` parses `name:` out of the staged
`topology.clab.yml` and raises if it is missing -- no fallback derivation.
`golden_control()` considers only rows with `run_status == "OK"` and reports
VACUOUS at zero or one completed golden. `verify_phase3` CHECK 11's leak scan
matched `clab-nrl-` and so missed every `clab-nrlv2-*` container; widened to
`clab-nrl`. `pipeline/test_gates.py` now asserts three identical failures do
NOT report ALL IDENTICAL.

**Open design question, not changed here.** `_done(rid)` is "run.json exists",
so a run that failed for infrastructure reasons is permanently DONE and is
never retried; the 29 records above have to be moved aside by hand before the
re-run. That is disk-as-state working as specified, but it means any transient
Docker failure silently removes a candidate from the dataset. Flagged, not
altered -- it is a frozen decision and changing it is a methodology change.

---

## S-019 -- the replicate arm ran and measured nothing (2026-09-03)

**What happened.** `--replicate 10` deployed ten labs, all OK, ~14 minutes of
emulator time. The batch printed `this batch: 0 items`, SAFE 0, HARMFUL 0, and
`containerlab_outcomes.csv` stayed at 20 rows. `verify_phase3` passed 38 of 39
checks. Nothing anywhere said the label-noise floor had not been computed.

**Why.** Both dataset loops in `build_datasets` iterate
`manifest["candidates"]`. A replicate run id is `<base>~r1`, which is not in the
manifest, so replicates produced measurement rows and no delta or outcome rows.
The arm's entire purpose -- does an identical config re-label identically -- was
never evaluated. This is the S-018 golden control again in a different place:
the work ran, the report was green, and the quantity was absent.

**What it was hiding.** Computing it by hand: **9 of 10 replicates reproduced
their outcome; C-01361 flipped SAFE -> HARMFUL.** A 10% label-noise floor,
found only because the arm was audited rather than trusted.

**The flip has a mechanical cause, and it is not label noise in the usual
sense.** C-01361 measured 16 full OSPF adjacencies on its first run and 15 on
the replicate; P08 (adjacency count) and P06 (must_traverse) both flipped.
`transitional_neighbors` deliberately treats an ABSENT neighbour as
non-transitional, because a faulted lab legitimately has adjacencies that
cannot form. But that makes "this adjacency has not come up YET" indistinguish-
able from "this adjacency never will", and `wait_for_convergence` returned at
the first eligible poll (50.6 s, min settle 45 s) because the RIB was already
byte-stable -- on t19_dualcore16 the sixteenth adjacency is redundant and adds
no new best routes, so its absence does not perturb the RIB at all. The harness
declared convergence on a network that was still converging.

**Fix (measurement only).** `containerlab_replicates.csv` is now written by
`build_datasets` with base vs replicate outcome, differing properties and both
adjacency counts; the batch summary prints the agreement rate and names every
flip; `verify_phase3` CHECK 8b fails if replicate labs ran without producing
rows, and reports the flip rate as a RESULT rather than gating on it.
`verify_phase3` CHECK 2's golden requirement is now scoped to topologies with
an executed candidate (B1's shape again: it failed every filtered collection by
construction).

**NOT fixed, deliberately.** Adding "the set of full adjacencies is unchanged
across the stable-poll window" as a fourth convergence condition would close the
race, but convergence is part of harm definition v1.1.0, which is frozen, and
changing it invalidates every label collected under it. Escalated to the user
as a methodology decision rather than made silently.

---

## S-020 -- ospfd bound to nothing, and every check said OK (2026-09-03)

**Correcting S-019.** S-019 attributed the C-01361 label flip to a convergence
race: the sixteenth adjacency coming up late while the RIB stayed byte-stable.
That diagnosis was WRONG, and the fix built on it (a fourth convergence
condition requiring the adjacency count to be stable) was written, tested, and
reverted -- the test that was supposed to demonstrate it disproved it instead.
The recorded poll history shows the replicate at 15 adjacencies from t=16.6 s
to t=50.6 s: stable for 34 seconds and six consecutive polls. No stability
condition can catch that, because nothing was moving.

**What actually happened.** On the replicate, `b1:eth2` is missing from
`show ip ospf interface json` entirely. The interface exists, is
administratively and operationally up, and carries its correct address
10.29.10.1/30. FRR's interface table also holds a stale down entry named
`clab-fd812620`. Containerlab wires a node by creating the veth inside the
container under a temporary name and renaming it to `eth2` afterwards; ospfd
read its configuration inside that window, bound nothing to `eth2`, and never
retried. The b1--aggb adjacency therefore could not form, P08 and P06 failed,
and the candidate was labelled HARMFUL instead of SAFE.

**Every existing check passed on that lab, and each was right to.**
`verify_running_config` compares configuration text -- identical.
`verify_addresses` compares addresses -- all present.  `interfaces_down`
deliberately ignores `clab-*` stubs, because counting them once made P12
non-deterministic. Convergence reported OK because nothing was transitional and
the RIB was stable. Not one of them asked whether ospfd was actually running on
the interfaces the artifact puts in OSPF.

**The label was wrong, not noisy.** This matters for how it is reported: the
replicate arm measured 1 flip in 10 and that reads as a 10% label-noise floor,
but the flip was a defective lab, not stochastic ground truth. Reporting it as
noise would have understated the achievable accuracy AND hidden a measurement
bug. The noise floor is unmeasured until Stage 1 is re-run.

**Fix.** `clab.verify_ospf_binding(state, scenario)` requires every interface
the artifact places in an OSPF area -- and that is administratively and
operationally up -- to appear in ospfd as `ospfEnabled`. A run that fails it is
`LAB_INVALID`, which becomes `EXECUTION_FAILED` downstream and is excluded from
y rather than labelled. `verify_phase3` CHECK 5 fails if any run was LABELLED
on such a lab, and prints NOT MEASURED on datasets predating the column instead
of passing vacuously.

**The scoping was found the same way the bug was.** The first version of the
check flagged 3 of 38 runs. Two were `iface_down` incidents where ospfd
correctly drops an interface whose link is down -- that is v1.0.0's "every
expected adjacency must be Full" mistake in a new place, and it fails every
genuinely faulted lab by construction. Restricting the check to operationally-up
interfaces leaves exactly one flagged run: C-01361~r1. `pipeline/
test_lab_validity.py` replays both real runs off the captured state and asserts
the good one passes, the bad one is caught, and both `iface_down` incidents are
not flagged.

**Rate.** 1 of 38 Stage 1 runs, ~2.6%. Against a budget of ~1,800 labs that is
roughly 45 invalid labs. They are now detected and excluded rather than silently
mislabelled, but a retry-on-invalid would recover them; not implemented, and
flagged to the user as a budget decision.
