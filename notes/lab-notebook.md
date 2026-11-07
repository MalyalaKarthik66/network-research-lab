# Lab notebook

Dated entries. One per working session, even short ones. Month-6 writing depends
entirely on month-1 notes, and reconstructed notes are worth almost nothing.

Template:

```
## YYYY-MM-DD

**Goal for this session:**

**What I ran:**

**What happened:**

**What broke, and the exact error text:**

**What I changed to fix it:**

**What I still do not understand:**

**Time spent:**
```

---

## 2026-08-07 -- Phase 1 scaffolded

**Goal:** stand up the Batfish verification environment and work through
Modules 1-10.

**Environment to record once Module 1 passes:**

- Windows version:
- Docker Desktop version:
- `batfish/allinone` image digest (from `docker images --digests`):
- Python version:
- pybatfish version:

**Not yet run.**

## 2026-08-25 -- Phase 1 pilot infrastructure built

**Goal:** clean the repo, resolve the same-artifact requirement, and generate a
reproducible 50-candidate pilot.

**What was built:** `nrl/` generator package, `pipeline/` entry points,
`data/pilot-v1/` (golden + 10 incidents + 50 candidates), three decision
documents under `docs/`.

**Verified locally (no Docker):** 15/15 checks in `verify_pilot.py`, including
the byte-level same-artifact proof across 366 device configs and a
byte-identical rebuild.

**NOT verified — needs my machine:**
- Does Batfish parse the FRR artifact? -> `pipeline/spike_frr_batfish.py`
- Does `containerlab deploy` boot the lab and form 6 OSPF adjacencies?

**Constraint discovered:** FRR access-lists / prefix-lists / route-maps are
ROUTE filters. Packet filtering on Cumulus lives in
`/etc/cumulus/acl/policy.conf` -> iptables, outside the format Batfish reads.
So no packet-ACL fault families on FRR without violating the same-artifact
property. All 10 fault families are routing-layer. -> surprises.md S-001.

**Environment to record when the spike runs:**
- Docker Desktop version:
- `batfish/allinone` image digest:
- FRR image digest (currently pinned only by tag, quay.io/frrouting/frr:8.4.4):

**Time spent:**

## 2026-08-25 (later) -- Phase 2 implemented, NOT YET RUN

**Built:** `nrl/bf_eval.py` (property -> Batfish query, full serialisation),
`pipeline/run_phase2.py`, `pipeline/verify_phase2.py`,
`docs/PHASE2-DATA-DICTIONARY.md`. Patched `spike_frr_batfish.py` to persist its
verdict to `phase2/spike_result.json`; `run_phase2.py` refuses to start unless
that says GO.

**Tested locally without Docker:** built a synthetic phase2 dataset in /tmp
using the real `build_records`/`write_csv` code paths, including a harness
error, a parse failure and a per-property error. 29/29 verifier checks pass on
a well-formed dataset; the verifier correctly FAILS on missing rows, duplicate
candidate ids, and inconsistent gate arithmetic.

**Bug the mock caught:** a candidate whose harness errored produced ZERO
property/question rows and simply vanished from the per-candidate counts
(588/600 and 833/850 slipped through as "fine"). Fixed on both sides --
`normalise_questions`/`normalise_props` emit ERROR placeholders, and the
verifier now counts against the expected candidate list rather than the ids
present in the CSV. -> surprises.md S-002.

**NOT RUN -- needs my machine:** the spike, and Phase 2 itself. No real Batfish
output exists yet.

**Record when the spike runs:**
- batfish/allinone image digest:
- pybatfish version:
- spike verdict:
- parse warning count:

**Time spent:**

## 2026-08-25 (later still) -- first real spike run; fixes

**Ran:** `pipeline/spike_frr_batfish.py` against the real artifact.

**Genuinely good news:** the same-artifact pipeline works. 6/6 files PASSED,
format CUMULUS_CONCATENATED, ZERO parse warnings, zero initIssues, 12 OSPF
session rows all ESTABLISHED (6 adjacencies), correct metrics (10.20.0.0/24 at
60 via the primary; backup at 110), static blackhole modelled as
discard/null_interface at admin distance 1.

**Three defects found:**
1. Spike hardcoded mixed-case node names -> 15 false address failures.
   Batfish lowercases hostnames. -> S-003
2. F10 (access-list + distribute-list) accepted with no parse warning and not
   modelled at all. -> S-004, family retired and replaced.
3. `V["parse"]` was a numpy.bool_ from `.all()`, so json.dumps crashed and no
   spike_result.json was written.

**Fixed:** lowercase node names everywhere; F10 replaced with
`ospf_network_type_mismatch`; spike rewritten to derive expectations from the
nrl model and to check CONSTRUCT COVERAGE across all 11 snapshots; bool coercion
plus `default=str` on the verdict write; case-insensitive-filesystem guard in
build_pilot + verify_pilot CHECK 3b.

**Still to run:** delete data/pilot-v1, rebuild, re-verify, re-spike.

**Record when the spike goes GO:**
- batfish/allinone image digest:
- pybatfish version:
- observed Batfish schema (spike writes it to spike_result.json):

**Time spent:**

## 2026-08-25 (evening) -- spike STOP triaged; three fixes

**Spike result:** STOP. parse / coverage / f10_observable failed.

**Triage -- only ONE was a real artifact problem:**
1. `ospf_network` 131/131 "mismatches" -- my normaliser stripped `-` but not
   `_`. POINT_TO_POINT vs point-to-point. -> S-007
2. `active` 2 mismatches -- Batfish deactivates the PEER of a shut interface
   (layer-1 carrier modelling). Batfish right, my expectation wrong. -> S-006
3. `link-down yes` unparsed (loud) -> S-005; `ip ospf network broadcast`
   unparsed (loud), so F10 was invisible to Batfish and had to be retired a
   SECOND time.

**Fixes:** `same_value()` extracted and unit-asserted; active expectation is now
peer-aware and prefers Admin_Up; `link-down yes` removed so admin state lives
only in frr.conf; apply-interfaces.sh no longer touches link state (was racing
zebra); F10 replaced with `static_route_loop`, built only from constructs the
spike has proven -- a /32 static on edgeb pointing back at coreb.

**Added:** construct capability table in docs/ARCHITECTURE.md, evidence-based.

**Rebuilt + verified in a scratch tree:** 16/16 PASS, 50 candidates, 41 distinct
device-config sets.

**Still to run on my machine:** rebuild in place, re-verify, re-spike.

**Record when the spike goes GO:**
- batfish/allinone image digest:
- pybatfish version:
- coverage counts per construct:

## 2026-08-25 (night) -- build/runtime scope separation

**Symptom:** verify_pilot 15/16. Only failure: "fresh rebuild is byte-identical"
differed by `phase2/spike_result.json`.

**Cause:** pilot.lock.json hashed every file under data/pilot-v1, including
Phase-2 runtime output. The rebuild into a temp dir has no phase2/, so the sets
differed. The check was correct; the scope was wrong.

**Fixed:** `nrl/manifest.py:in_build_scope()` -- one definition, imported by
builder and verifier. Lock covers reference/, incidents/, candidates/,
properties.yml, manifest.json only. phase2/3/4 excluded as runtime output.

**Worse problem found while fixing it:** `--force` regenerated the artifacts but
left phase2/ untouched, so a GO verdict could outlive the artifact it was about
and wave Phase 2 through. Closed with an artifact_digest (sha256 over all
in-scope hashes): written to the lock, stamped into spike_result.json, copied
into run_metadata.json. build_pilot warns on stale downstream output;
run_phase2 refuses on digest mismatch; verify_phase2 asserts the dataset matches
the artifact on disk.

**Negative-tested (scratch tree):** corrupting one byte of a candidate config
still fails CHECK 2 + CHECK 8; a stray file inside candidates/ still fails the
stale check; the digest gate fires only on mismatch. 16/16 with a phase2 file
present.

**Next:** rebuild in place, re-verify, re-spike.

## 2026-08-25 -- Phase 2 COMPLETE; Phase 3 implemented

**Phase 2 result:** 50/50 processed, 24 PASS / 26 FAIL / 0 ERROR / 0 INVALID,
verify_phase2 30/30. Zero parse warnings across every candidate.

**RECORD THESE:**
- batfish/allinone digest: sha256:09817554db90e2f2674b72562c2d659427094187de0a3dfc23534ab58bf26207
  (image is 13 months old -- PINNED, do not `docker pull` again mid-project)
- artifact digest: 0a96bea0fabe028c...
- pybatfish version: (from phase2/run_metadata.json)

**Denominator for the false-pass rate: 24.** Better than feared -- P08 is a
strong gate but not fatal.

**Phase 3 built:** nrl/clab.py (execution layer), nrl/p3_eval.py (12 properties
measured against the running network), pipeline/run_phase3.py (61 labs, gated,
resumable), pipeline/verify_phase3.py (34 checks), docs/PHASE3-SETUP.md,
docs/PHASE3-DATA-DICTIONARY.md.

**Tested without Docker:** synthetic 61-run dataset in /tmp exercising the real
build_datasets + verify code paths, including a NO_CONVERGENCE run, a
measurement error, and a DEPLOY_FAILED run. 34/34 on a well-formed dataset;
correctly FAILS on a runtime-config mismatch, an off-vocabulary outcome, and a
pre-assigned label.

**Bug the mock caught (again):** a DEPLOY_FAILED run produced zero measurement
rows -- 720/732. Same shape as S-002. Fixed with placeholder_measurements() in
the runner plus a defensive fill in build_datasets.

**NOT RUN -- needs WSL:** all 61 labs. Budget 2.5-4h.

## 2026-08-25 -- image tag corrected; dual digest introduced

**Blocker:** `docker pull quay.io/frrouting/frr:8.4.4` -> not found. Verified
against the Docker Hub registry API: the real image is `frrouting/frr:v8.4.1`
(note the `v`, and Docker Hub not quay). -> S-008

**Changed:** FRR_IMAGE -> frrouting/frr:v8.4.1; FRR_VERSION -> 8.4.1 so the
`frr version` line in frr.conf matches what actually runs.

**Also introduced snapshot_digest** alongside artifact_digest. Batfish reads
only `batfish-snapshot/`, so it should not be invalidated by a container image
change it cannot see. Verified: changing only FRR_IMAGE moves artifact_digest
and leaves snapshot_digest identical.

**Consequence this time:** FRR_VERSION lives inside frr.conf, which IS in the
snapshot, so the snapshot digest DOES change and Phase 2 must be re-run. ~16 min.
From now on, image-only changes will not cost a Phase 2 re-run.

**Containerlab installed:** 0.79.0. docker-ce 29.7.2 native in the `clab` distro,
Docker Desktop integration off.

## 2026-08-25 -- Phases 1-2 re-run clean on the corrected artifact

**Windows run (user):** build -> verify_pilot 16/16 -> spike GO (all 6 checks,
0 parse warnings, construct coverage clean across all 11 snapshots) ->
run_phase2 50/50 in 569s, 24 PASS / 26 FAIL / 0 ERROR / 0 INVALID ->
verify_phase2 30/30.

Denominator for the false-pass rate is 24, unchanged from the previous run.

**Cross-platform reproducibility result worth keeping:** snapshot_digest
computed independently on Windows and on a Linux sandbox agreed byte-for-byte
(f8a1b1d9a607e003fa0e...). The generator is deterministic across OSes, not just
across runs on one machine. Worth one line in the paper's artifact-availability
statement.

**Defect found and fixed before starting Phase 3:** artifact_digest was NOT
stable across two identical rebuilds -- 51 files (50 meta.json + manifest.json)
carried created_utc, the same 51 that CHECK 8 already excluded for that reason.
So the Phase 3 gate was keyed on a build clock: any harmless rebuild would have
invalidated a completed 3-hour Phase 3 dataset. Timestamps moved to
pilot.lock.json (built_utc), which is excluded from its own hash. Verified: two
rebuilds now agree on both digests with 0 differing files, and verify_pilot
CHECK 8 now compares every in-scope file instead of excluding 51 -- strictly
stronger.

**Consequence:** rebuild + re-spike needed (~3 min). Phase 2 is NOT affected,
because snapshot_digest is unchanged.

## 2026-08-25 -- Phase 3 golden FAILED; convergence criterion fixed

**Preflight:** clean. native docker-ce, containerlab 0.79.0, both images with
resolved digests:
- frrouting/frr@sha256:0f8c174d95add7916101077d4716822552c758b8ff3d2dcb55104f6534202e3e
- alpine@sha256:6baf43584bcb78f2e5847d1de515f23499913ac9f12bdf834811a3145eb11ca1

**Golden result:** status OK, staging 23 files verified, 9/9 containers,
runtime_config_match OK, addresses OK -- but converged=true at 11.4s and THREE
properties false: P01, P08, P09/P10. Diagnosis: measured mid-convergence, not a
network fault. Evidence: P02 pings the same address as P01 seconds later with 0%
loss; P06 shows the correct primary path; P07/P11 pass. -> S-009

**Fixed:** convergence now requires elapsed >= 45s AND no transitional OSPF
neighbour AND RIB stable over 3 polls. Timeout 120 -> 180s. HARM-DEFINITION
bumped 1.0.0 -> 1.1.0 with a dated rationale; the v1.0.0 text is retained.

Also recorded honestly in that doc: v1.0.0's stated criterion ("every expected
adjacency Full") was never implementable for faulted labs and was never
implemented. That divergence should have been recorded when it was made.

**Legitimacy of changing a frozen definition:** exactly one lab had run
(golden), which produces zero outcome rows. No harm label existed for any
candidate. The change was forced by a measurement that contradicted its own
evidence, not by an inconvenient result.

**Cost:** ~45s extra per lab; 61 labs ~= +45 min. Expect ~1.5-2.5h total.

**Golden run under v1.0.0 is VOID -- delete phase3/ and re-run.**

## 2026-08-25 -- Phase 3 COMPLETE (61/61, 35/35 checks). Result NOT yet trustworthy.

**Run:** 61 labs in 99m. All run_status OK. Same-artifact verified at runtime on
every lab (running-config + addresses). No leaked containers.
outcome_harm_v1: HARMFUL 40 / SAFE 10. Crude false-pass rate 18/24 = 75%.

**75% is in the ">60% -- debug the oracle" band of the gate table. Debugged.**

**Control that exposed it:** the 10 exact_revert candidates are byte-identical
to golden, so all 12 properties must hold in all 10. Observed: all converged
~45.4s with adj=6; 11 of 12 properties stable; P12 failed in 5 of 10. -> S-010

**Cause:** P12 read FRR's whole interface namespace -- including eth0 and
Containerlab's random transient veth stubs (clab-<hex>). Batfish evaluates P12
over the 4 configured interfaces only. Different domains, so the columns were
not comparable. FIXED: interfaces_down() now scoped to the artifact; skipped
names recorded in extra.ignored_non_artifact_interfaces.

**Expected effect:** P12 was the sole violation in 6 of the 18 false passes, so
the rate should land near 12/24 = 50% on a re-run. To be confirmed by
measurement, not assumed.

**Second finding, NOT a bug -- a definition question for the paper:** 24 of the
40 HARMFUL are harmful ONLY because the original fault was never fixed
(property failed BEFORE and still fails AFTER). 6 are genuine new regressions,
10 are both. Restricted to the 18 false passes: 9 unrepaired-only, 4 new
regression, 5 both. Both decompositions were pre-registered in the deltas
schema. RECOMMENDATION: do not change harm-definition v1.1.0 now that labels
exist; report vs-golden as primary and vs-before as a pre-registered sensitivity
analysis.

**Anomaly:** C-0047 wall 932s with P02 at 592s and P05 at 260s, against
subprocess timeouts of 25s/20s. Wall clock advanced while the process did not --
almost certainly the host suspended mid-run. Its measurements are suspect; the
re-run will clarify. Consider disabling sleep for the next run.

## 2026-08-25 -- Phase 3 run 2: oracle fixed, then a deeper defect found

**Run 2:** 61 labs, 85m, all OK, 35/35 checks. SAFE 16 / HARMFUL 34.
Crude false-pass rate 12/24 = 50%.

**Control now clean:** all 10 exact_revert candidates SAFE, zero property flips,
golden clean. The P12 scoping fix worked; the oracle is reproducible.

**2x2:**            SAFE  HARMFUL
      batfish PASS    12       12
      batfish FAIL     4       22
  P(harm | FAIL) = 85%, P(harm | PASS) = 50%. Verification is informative and
  far from sufficient -- which is the thesis, measured.

**BUT: I-01 and I-02 break NOTHING.** Both shut a primary-path interface and
both showed adj=6. FRR echoed `shutdown` back in show running-config while
reporting admin=up, kernel UP,LOWER_UP, and a Full OSPF neighbour on the
interface. -> S-011

FRR does not apply `shutdown` to a veth Containerlab moves into the namespace
after config load. Batfish models it as down. The two tools ran DIFFERENT
networks for the whole iface_down family (2 incidents, 10 candidates).

**Fixed:** (1) apply-interfaces.sh now enforces admin-down by reading
`shutdown` back out of frr.conf -- same single source of truth, not a new one;
(2) verify_running_config now compares interface STATE, not just config text,
and flags MISMATCH when the artifact and the container disagree. Verified: the
new check reports MISMATCH on exactly the I-01 case and OK when honoured.

**Digest impact (dual-digest paying off):** artifact_digest changed,
snapshot_digest did NOT. Re-spike + re-run Phase 3. Phase 2 stays valid.

**Also worth stating in the paper:** 10 of the 12 false passes involve P06,
the path property deliberately placed outside SPEC. The headline number is
dominated by one designed mechanism, and 10 of 12 are unrepaired-only rather
than new regressions. Report both decompositions; neither is "the" answer.

## 2026-08-25 -- Phase 3 run 3: dataset clean, mechanism attribution corrected

**Run 3:** 61 labs, 90m, all OK, 35/35 checks. SAFE 12 / HARMFUL 38.
False-pass rate 12/24 = 50%.

**All controls pass:** exact_revert 10/10 SAFE, golden clean, every incident
now breaks something (I-01 adj=5, I-02 adj=5 -- the shutdown fix worked), and
CHECK 5 now includes the STATE assertion and passed on all 61 labs. The
same-artifact guarantee now holds at state level, not just file level.

**2x2:**            SAFE  HARMFUL
      batfish PASS    12       12     P(harm|PASS) = 50%
      batfish FAIL     0       26     P(harm|FAIL) = 100%
  Batfish has ZERO false alarms. Every rejection was genuinely harmful.

**Per-property Batfish vs emulator, 600 comparisons:**
  agree 574, batfish-optimistic 26, batfish-pessimistic 0.
  Every single disagreement is in the optimistic direction. That is the
  theoretically expected signature of a sound-but-incomplete model and it is
  the cleanest single result the pilot has produced.

**But 3 of the 26 were my bug.** P07 ORed max_hops_reached into its loop
criterion, so a blackholed destination (12 rows of '*') scored as a loop.
-> S-012. Fixed: loops and unreachability are now separate.

**Corrected decomposition of the 12 false passes (to confirm on re-run):**
  ~9  specification incompleteness -- only oracle-only properties broke,
      dominated by P06, the path property deliberately outside SPEC
  ~3  model-vs-device divergence -- C-0013/14/15, where FRR refuses an OSPF
      adjacency across mismatched subnets on a POINT-TO-POINT link while
      Batfish models it as forming. RFC 2328 does not check the network mask
      in hellos on p2p links, so Batfish follows the RFC and FRR is stricter.
      NEEDS CONFIRMATION before being claimed.

**Standing methodology change:** comparing Batfish against the emulator property
by property, and investigating every disagreement individually, is now a
required step -- not optional. Half of the raw disagreement count was harness
error. See S-012.

## 2026-08-25 -- PHASE 3 COMPLETE (run 4)

**Run 4:** 61 labs, 90m, all run_status OK, verify_phase3 35/35.
SAFE 12 / HARMFUL 38. False-pass rate 12/24 = 50%.

**Every control passes:**
- exact_revert (10 configs byte-identical to golden): 10/10 SAFE
- golden: 0 failing properties
- incidents breaking nothing: none
- artifact STATE matches container state on all 61 labs (CHECK 5)
- no leaked containers

**Stability confirmed:** the P07 fix changed ZERO labels -- run 3 and run 4 both
give 12 SAFE / 38 HARMFUL. Predicted in advance, because P07 was never the sole
violation for any candidate. What the fix changed is mechanism attribution,
which is what the paper argues about.

**HEADLINE RESULT -- Batfish vs emulator, 600 property comparisons:**
    agree 576   batfish-optimistic 21   batfish-pessimistic 0
  Every disagreement is optimistic. Batfish never claims a property fails when
  the emulator says it holds. That is the theoretically expected signature of a
  sound-but-incomplete model, measured rather than assumed.
  Optimistic by property: P05=9, P06=5, P08=3, P01=1, P02=1, P09=1, P10=1.

**2x2:**            SAFE  HARMFUL
      batfish PASS    12       12     P(harm|PASS)=50%
      batfish FAIL     0       26     P(harm|FAIL)=100%, zero false alarms

**The 12 false passes decompose cleanly:**
   9  specification incompleteness -- only oracle-only properties broke.
      Dominated by P06, the path property deliberately outside SPEC.
   3  model-vs-device divergence -- C-0013/14/15, all I-03 (iface_wrong_addr),
      all leaving the subnet mismatch unrepaired. Batfish models the OSPF
      adjacency as forming across mismatched subnets on a POINT-TO-POINT link
      (RFC 2328 does not check the mask in hellos on p2p); FRR refuses it.
      Isolated to one fault family and one mechanism. Confirm before claiming.

**Sensitivity (pre-registered):** of 38 HARMFUL, 31 unrepaired-only, 0
new-regression-only, 7 both. Of the 12 false passes: 10 unrepaired, 2 both.
The dominant mechanism is INCOMPLETE repair, not DESTRUCTIVE repair. State this
plainly; "verified changes cause harm" would overclaim.

**OPEN DATA-QUALITY ITEM before Phase 4:** P05 (hostb -> hosta return path) has
9 optimistic disagreements, the largest single group. Those candidates all sit
in the batfish=FAIL bucket so the headline is unaffected, but Phase 4 will
consume that column. Given that 5 of this session's 6 measurement bugs were
mine, audit P05 before trusting it -- same method that caught S-012: read the
raw probe evidence for each disagreement individually.

**Gate assessment:** 50% is above the 10-40% "ideal" band and well below the
60% "suspicious" band. Workable. 12 positives / 12 negatives among passing
candidates is a balanced problem. PROCEED.

## 2026-08-25 -- PHASE 4 COMPLETE. Answer: no model, and the reason matters.

**Ran:** pipeline/run_phase4.py + verify_phase4.py -> 25/25 checks pass,
including the leakage gate on all three tiers, LOIO grouping, bootstrap CIs,
permutation tests, Phases 1-3 untouched, and exact re-run determinism.

**P05 audit (first task):** the 9 optimistic P05 disagreements are a
DIRECTIONALITY SEMANTICS mismatch -- ping is round-trip, Batfish reachability is
one-way -- not model-vs-device divergence and not a harness crash. All 9 sit in
the batfish=FAIL bucket so the 24 and the 12/12 split are unaffected. -> S-013
Consequence: the "21 optimistic / 0 pessimistic" headline must NOT be reported
as 21 instances of divergence. After audit it is far fewer.

**Modelling result:** tier A (config-diff only) AUC-ROC 0.583 p=0.258 -- no
signal. Tier B 0.656 p=0.103 -- no signal. Tier C 0.747 p=0.026 -- but tier C is
Batfish answering MORE QUESTIONS, not a learned contribution.

**The decisive ablation:** the SAFE class is 83% R-exact_revert (10 of 12),
which are byte-identical to golden. Drop them and every model falls to <=0.542
with p>=0.469. The apparent signal is the shortcut "is this the revert?".

**Non-learned baseline beats the models:** "any oracle-only property FAILs in
Batfish" catches 7 of 12 harmful with ZERO false alarms, balanced acc 0.792.

**Decomposition -- the actual finding:** 7/12 of post-verification residual risk
is recoverable by widening the specification; 5/12 is not. The first is an
argument for better specs. Only the second argues for a learned risk layer, and
5 samples cannot support one.

**Gate status:** false-pass rate 50% clears the week-10 gate. The NEW blocker is
class structure, not rate. Needed before Phase 4 can be answered: a repair
distribution where SAFE is not mostly reverts (LLM-generated, or a much richer
mutation library), 50+ incidents rather than 10, ~1500 candidates. Conformal
risk control is not attemptable on 12 calibration points.


## 2026-08-26 -- pilot-v2 built; property-suite audit before batch 1

**Tried.** Rebuilt pilot-v2 under design C (10 topologies x 10 incidents ->
1,793 candidates, suite 1.1.0) after fixing the hardcoded P11 loopback and the
hardcoded router count in `spec_coverage_features`. Then audited the property
suite itself, which no gate had ever validated, before spending 5 h on Phase 2.

**Broke.** Six more instances of the same pattern, all in code written or
touched by the P11 fix:

1. `verify_golden_properties.py` -- the new gate -- had no completeness
   assertion. An empty manifest, or an `evaluate_all()` returning `[]`, would
   have printed "PASS -- every property holds on every golden" having evaluated
   nothing. The gate written to catch vacuous success was itself vacuous-capable.
2. `loopback_of()` recomputed the address as `10.255.0.<index>` instead of
   reading `spec.routers[node]`. That convention is only true for the ten
   `make_topology()` designs; legacy `t1` has edgeb at index 4 and router-id
   `.6`, so P11 on t1 would have targeted an address t1's edgeb does not own.
   The P11 defect, reproduced inside its own fix, one level up.
3. `as_yaml()` emitted `PER_TOPOLOGY` only where the placeholder was literally
   `None`. So P11 was published correctly while P08 kept `expected: 6` (true in
   4 of 10 topologies) and P06 kept `must_traverse: ['wan1','wan2']` -- true in
   **none** of them, since `primary_path` is Dijkstra-derived and includes the
   cores. The frozen document a reviewer reads contained two false lines.
4. `resolve()` fell back to `t2v1` on an unknown topology name. One typo or one
   stale manifest entry would have resolved P06, P08 and P11 to another
   network's values simultaneously, with every check still green.
   `test_topology_aware.py` **asserted this fallback as correct behaviour** --
   a passing test certifying a silent wrong-target.
5. `test_topology_aware.py` CHECK 1 ("pilot-v1 semantics are unchanged") had
   been FAILING since P11 was parameterised. Nobody re-ran it. A frozen-
   semantics check is only worth having if it is executed after every change to
   what it freezes.
6. `verify_pilot.py` and `spike_frr_batfish.py` still defaulted `--pilot` to
   `data/pilot-v1` -- the exact defect that once ran zero items and printed
   `ALL ITEMS COMPLETE`. Both are now `required=True`, and the spike prints the
   resolved pilot path and `snapshot_digest` in its header.

**Learned.** The lesson from P11 was recorded as "do not hardcode a topology
constant". That was too narrow. The actual lesson is **do not re-derive a fact
the model already stores**, and the corollary: *a fix is a change, so every
frozen-semantics test must be re-run after it.* Four of the six above were
introduced or left behind by the P11 fix itself.

Added: `PER_TOPOLOGY_PARAMS` (as_yaml refuses to publish a constant for a
topology-dependent parameter); an `ipOwners` target-ownership check in the
golden gate, which is the only check that can catch a false PASS, because
pinging the wrong router succeeds; a `--negative-control` mode asking four
properties that MUST fail on a healthy network; and a test that every
address-valued property's address is owned by the router it names, across all
14 specs.

**State.** `data/pilot-v2` on disk: 1,793 candidates, 100 incidents, 10 goldens,
`snapshot_digest f1a49e3c...`, `artifact_digest 16635513...`, no `phase2/`.
`properties.yml` will change by exactly three lines on rebuild (the three
PER_TOPOLOGY literals); `topology_resolved:` is byte-identical, so no resolved
value moved. `test_topology_aware.py` and `test_batching.py` both pass.
Nothing requiring Docker or Batfish has been run yet.
