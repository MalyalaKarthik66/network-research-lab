# Project handoff — "Trust but Verify the Verifier"

**Purpose.** Complete context for continuing this research in a new conversation.
Part 1 is the research (problem, gap, contributions). Part 2 is the
implementation (files, invariants, results, defects, current state).

**Last updated:** 2026-08-27
**Repository:** `C:\Users\karth\network-research-lab`
**Environment:** `.venv` only. Windows laptop, 16 GB RAM.

**To start a new thread:** attach or paste this file and use the starter prompt
in [§13](#13-starter-prompt-for-a-new-thread).

---

## Contents

**Part 1 — Research**
1. [The person and the constraints](#1-the-person-and-the-constraints)
2. [Thesis and research gap](#2-thesis-and-research-gap)
3. [Positioning against related work](#3-positioning-against-related-work)
4. [Contributions and fallback](#4-contributions-and-fallback)

**Part 2 — Implementation**
5. [Four-phase architecture](#5-four-phase-architecture)
6. [Repository layout](#6-repository-layout)
7. [Frozen specifications and invariants](#7-frozen-specifications-and-invariants)
8. [Dataset design C](#8-dataset-design-c)
9. [Results so far (pilot-v1, complete)](#9-results-so-far-pilot-v1-complete)
10. [Defect log — every silent failure found](#10-defect-log--every-silent-failure-found)
11. [Current state and exact next steps](#11-current-state-and-exact-next-steps)
12. [Open questions and risks](#12-open-questions-and-risks)
13. [Starter prompt for a new thread](#13-starter-prompt-for-a-new-thread)

---

# Part 1 — Research

## 1. The person and the constraints

3rd-year B.Tech student, AIML department, long-term focus on Machine Learning.
A Computer Networks professor assigned the class to find a research problem and
publish. Goal: **one genuinely novel, peer-reviewed publication (IEEE / ACM /
Springer tier) where AI is the core contribution, not decoration.**

Explicitly rejected: another generic intrusion-detection or traffic-
classification paper.

**Requested advising style: critical, IEEE-reviewer-like. Do not validate an
idea because it is his.** Started with almost no networking background, so
explanations should build from intuition — but the standard applied to the work
is a reviewer's, not a tutor's.

Hard constraints:

- Windows laptop, ~16 GB RAM. Free Colab / Kaggle GPU only.
- No lab, no cluster, no budget, no industry partner.
- ~6–8 months to submission.

A proposal that assumes a cluster is not a proposal.

## 2. Thesis and research gap

> **ML systems that act on networks do not know when they are wrong.**

The specific gap: when an LLM or automation system proposes a network
configuration repair, the standard safety story is "run it through a formal
verifier first." Published systems report that verification prevents
regressions. **Nobody has measured how often a change that PASSES verification
still causes operational harm.**

That residual risk has to exist, because verification is sound only with
respect to (a) the properties someone wrote down and (b) a model that excludes
time, hardware, and traffic. Both gaps are real and neither is quantified.

So the experiment is:

1. Generate network repairs (correct, incomplete, and regressive).
2. Verify each with **Batfish** (formal, config-only, converged steady state).
3. Execute each in **Containerlab** (real FRR routers, real convergence).
4. Measure **P(harm | verification PASS)** — the *false-pass rate*.
5. Learn to predict that residual risk, and use **conformal risk control** to
   give operators a tunable autonomy budget with a distribution-free bound on
   the number of harmful auto-applied changes.

Why Batfish is the right verifier to interrogate rather than blame: it is
*sound* with respect to the question asked and the model built. It is not a
model of the network. Three categories of blind spot, all deliberate:

- **Out of scope by design** — time (convergence, micro-loops, timer expiry,
  flap), traffic, telemetry.
- **Model vs device** — ECMP hashing, TCAM limits, platform quirks, control-
  plane packets crossing data-plane filters, partial grammar coverage.
- **Specification incompleteness** — it proves the properties you wrote.
  Properties you did not write are unexamined, not satisfied.

The paper's motivating demonstration already exists in `batfish/scripts/m10_limitations.py`:
an ICMP-only acceptance test PASSES on a network where HTTPS is completely
broken. The failure is in the specification, not the verifier — and no amount
of improving Batfish fixes it.

## 3. Positioning against related work

The direction **"Network Digital Twin based Self-Healing and RCA"** is dead —
every component is published: DT-assisted RCA (IEEE 2021–22), multi-agent LLM
netops in production (Meta's Confucius, SIGCOMM 2025), LLM config repair
benchmarked with formal verification (Cornetto, ETH Zürich 2026), safety-
constrained autonomous mitigation (STRATUS/TNR), and the GenAI+NDT framing
itself (ACM CSUR 57(6), 2025).

| Work | What they do | How this differs |
|---|---|---|
| **Cornetto** (ETH) | Measures whether the LLM's fix is correct | This measures whether the *verification* correctly identifies correctness. Complementary; usable as a data source. |
| **STRATUS / TNR** | Hard invariant: detect regression, roll back | TNR assumes reliable regression detection and clean rollback. Both are false in networks — reverting config does not un-flap a BGP session. This provides a probabilistic guarantee where those assumptions fail. |
| **Confucius** (Meta) | Reports validation prevents regressions | This quantifies how often it does not. |
| **CORA** | Same conformal machinery, mobile GUI domain | Cross-domain transfer is respectable but must be cited prominently in the intro with the difference stated. |

## 4. Contributions and fallback

**Claimed contributions:**

1. First empirical characterisation of the verification **false-pass rate** for
   LLM-proposed network repairs.
2. A domain-specific risk model and feature taxonomy for repair-harm prediction.
3. First application of **conformal risk control** to network operations.
4. The **autonomy–risk curve** as a risk-aware evaluation metric, replacing raw
   success rate, which hides harm.
5. Open dataset and harness.

**Fallback direction (live, not face-saving): "Calibrated Network Digital
Twins."** Wrap RouteNet-family models in conformal prediction; measure where
coverage breaks under topology / traffic-intensity / routing-policy shift;
propose a network-specific fix (weighted conformal with a topology-similarity
likelihood ratio, or Mondrian conformal with topology strata). BNN-UPC datasets
are public, RouteNet code is on GitHub, models train on free Colab, split
conformal is ~50 lines. First result achievable in ~6 weeks.

Anticipated reviewer objection to the fallback: *"this is just applying
conformal to an existing model."* The defence needs all three of: the shift
analysis is a new empirical finding, the decision-task evaluation shows
uncertainty changes outcomes, and the network-specific fix is a methodological
contribution. Without the third it is a workshop paper.

---

# Part 2 — Implementation

## 5. Four-phase architecture

| Phase | What it does | Output | Status |
|---|---|---|---|
| 1 | Build pilot: golden topologies, injected faults, candidate repairs | `data/pilot-*/` | v1 done, v2 rebuilt |
| 2 | Batfish verification of every candidate | `phase2/` | v1 done, v2 not started |
| 3 | Containerlab BEFORE/AFTER execution — harm ground truth | `phase3/` | v1 done, v2 not started |
| 4 | Assemble dataset, train + evaluate risk models | `phase4/` | v1 done |

**Toolchain (pinned):** Batfish `batfish/allinone`, pybatfish, FRR
`frrouting/frr:v8.4.1` (verified to exist via Docker Hub API — `8.4.4` does
not), Containerlab, Docker Desktop on Windows.

Batfish reads FRR through the **Cumulus concatenated** path: `/etc/network/interfaces`
+ `/etc/cumulus/ports.conf` + `/etc/frr/frr.conf` in one file per device, with
marker lines Batfish uses to find boundaries:

```
<hostname>
# This file describes the network interfaces
# ports.conf --
frr version
```

Interface IP addresses live in the **interfaces** section, not `frr.conf`. Feed
Batfish only `frr.conf` and it builds a network whose devices have no
addresses — every routing question returns empty and every reachability
question returns a confident wrong answer. This failure is silent.

## 6. Repository layout

```
network-research-lab/
├── nrl/                         # library
│   ├── topologies.py            # SINGLE SOURCE OF TRUTH for topology facts
│   ├── model.py, topology.py    # scenario model
│   ├── faults.py / faults_v2.py # fault injection (v2 = 10 families × N topologies)
│   ├── repairs.py / repairs_v2.py  # correct / incomplete / regressive repairs
│   ├── properties.py            # the frozen property suite (P01–P12)
│   ├── render.py, emit.py       # config rendering, artifact writing
│   ├── clab.py                  # Containerlab topology generation
│   ├── bf_eval.py               # Phase 2 property evaluation (Batfish)
│   ├── p3_eval.py               # Phase 3 property evaluation (Containerlab)
│   ├── batching.py              # partition / ledger / resume
│   ├── scenario_io.py           # scenario.json read/write round-trip
│   ├── manifest.py
│   └── phase4.py                # numpy-only LogReg / stump / majority, LOIO CV
├── pipeline/                    # executable entry points
│   ├── build_pilot.py           # v1 builder (frozen, do not break)
│   ├── build_pilot_v2.py        # v2 builder — 10 topologies
│   ├── verify_pilot.py          # 16 structural checks (NO Batfish, NO Docker)
│   ├── spike_frr_batfish.py     # FRR/Batfish semantic compatibility gate
│   ├── verify_golden_properties.py   # NEW: all properties must hold on goldens
│   ├── diag_p11.py              # loopback modelling diagnostic
│   ├── run_phase2.py  / verify_phase2.py
│   ├── run_phase3.py  / verify_phase3.py
│   ├── run_phase4.py  / verify_phase4.py
│   ├── test_topology_aware.py   # 7 check groups over 14 specs
│   └── test_batching.py         # 7 checks: resume, no duplicate execution
├── docs/
│   ├── ARCHITECTURE.md
│   ├── HARM-DEFINITION.md       # FROZEN v1.1.0
│   ├── LEAKAGE.md               # feature/split rules
│   ├── PHASE2-DATA-DICTIONARY.md, PHASE3-DATA-DICTIONARY.md
│   ├── PHASE3-SETUP.md, PHASE4-METHOD.md
│   └── PROJECT-HANDOFF.md       # this file
├── batfish/                     # Phase 1 learning material
│   ├── docs/PHASE1-MANUAL.md    # 10-module Batfish manual
│   ├── scripts/                 # m01–m10 + m09_frr_spike.py + run_all.py
│   └── snapshots/               # Cisco IOS teaching snapshots
├── notes/
│   ├── lab-notebook.md          # dated entries: tried / broke / learned
│   └── surprises.md             # every time Batfish surprised us -> paper motivation
├── data/pilot-v1/               # 50 candidates, phases 1-4 COMPLETE
├── data/pilot-v2/               # 1793 candidates, phase 1 only
└── paper/, experiments/, topologies/, containerlab/
```

### `nrl/topologies.py` — the single source of truth

`TopologySpec(name, links, routers, hosts, passive, primary_path, n_adjacencies)`.
`make_topology()` auto-assigns interfaces and subnets and computes
`primary_path` by **Dijkstra over OSPF cost**.

Ten design-C topologies:

| name | routers | adjacencies | shape |
|---|---|---|---|
| `t01_chain4` | 4 | 4 | linear chain |
| `t02_wan6` | 6 | 6 | two sites + WAN pair (mirrors pilot-v1) |
| `t03_dual8` | 8 | 9 | dual WAN paths |
| `t04_star5` | 5 | 5 | hub and spoke |
| `t05_ring6` | 6 | 6 | ring |
| `t06_mesh6` | 6 | 6 | partial mesh |
| `t07_tier7` | 6 | 6 | edge/agg/core tiers |
| `t08_chain8` | 8 | 8 | long chain |
| `t09_twin6` | 6 | 7 | twin backup paths |
| `t10_deep9` | 8 | 8 | deep hierarchy |

Plus legacy `T1, T2, T3` and `T2V1` (byte-identical to pilot-v1).

Addressing conventions that hold in **every** topology: hosts are
`10.10.0.10` (hostA), `10.20.0.10` (hostB), `10.21.0.10` (hostC). Router *i*
(1-based index in `spec.routers`) owns loopback `10.255.0.i` — **so loopback
addresses differ per topology and must never be hardcoded.**

Ten fault families (`faults_v2.py`): `iface_down`, `iface_wrong_addr`,
`ospf_area_mismatch`, `ospf_passive_transit`, `ospf_iface_removed`,
`ospf_cost_inversion`, `ospf_cost_excessive`, `static_blackhole`,
`static_wrong_nexthop`, `static_route_loop`.

Repair operators (`repairs_v2.py`) across three classes — **correct**
(`RC-cost_norm_k`, `RC-peer_cost_norm_k`, `RC-loopback_cost_k`,
`RC-renumber_peer`, `RC-equivalent_static`, …), **regressive**
(`RR-blackhole_other`, `RR-shutdown_other`, `RR-area_other`,
`RR-cost_inversion`, `RR-loop_other`, …), **incomplete** (`RI-cosmetic`,
`RI-static_specific`, `RI-overbroad_ospf`, `RI-wrong_device`,
`RI-partial_revert`, `RI-noop_route`, …).

## 7. Frozen specifications and invariants

### The same-artifact guarantee

The exact bytes Containerlab mounts are embedded verbatim in the Batfish
snapshot. Proven by an inverse function `extract_batfish_sections()` and
asserted by `verify_pilot.py` CHECK 2 over every device of every candidate.
Without this, Phase 2 and Phase 3 could be measuring different networks and the
false-pass rate would be meaningless.

### The two digests

| digest | covers | gates |
|---|---|---|
| `snapshot_digest` | `batfish-snapshot/` only | the spike, Phase 2 |
| `artifact_digest` | everything Containerlab mounts + metadata | Phase 3 |

Deliberately split so an irrelevant change does not invalidate good data.
Editing metadata, the property suite, or the clab topology moves
`artifact_digest` but leaves `snapshot_digest` intact — so an existing spike GO
stays valid. **If a change you expected to be snapshot-neutral moves
`snapshot_digest`, something touched device configs. Investigate before
proceeding.**

Timestamps live only in `pilot.lock.json` (`built_utc`), so rebuilds are
byte-identical.

### Build scope vs runtime scope

- **Locked, must be reproducible:** `reference/`, `incidents/`, `candidates/`,
  `properties.yml`, `manifest.json`
- **Runtime output, excluded from the lock:** `phase2/`, `phase3/`, `phase4/`

The builder tracks every file it writes and **refuses to write a lock** if the
directory walk finds any in-scope file it did not produce. If it blocks, delete
the output directory and rebuild — do not force past it.

### The property suite — `SUITE_VERSION 1.1.0`

Twelve properties. The gap between them is the entire experiment.

- **SPEC** (asked of Batfish in Phase 2): **P01, P02, P05, P07, P08**
- **Oracle-only** (measured in Containerlab in Phase 3): **P03, P04, P06, P09,
  P10, P11, P12**

| id | in spec | what it asserts |
|---|---|---|
| P01 | yes | hostA can ping hostB |
| P02 | yes | hostA can reach hostB on TCP/443 |
| P05 | yes | hostB can ping hostA (return path) |
| P07 | yes | no forwarding loops anywhere |
| P08 | yes | all OSPF adjacencies established (**per-topology count**) |
| P03 | no | hostA can ping hostC (second site-B LAN) |
| P04 | no | hostA can reach hostC on TCP/443 |
| P06 | no | hostA→hostB uses the primary path (**per-topology path**) |
| P09 | no | every router has a route to 10.20.0.0/24 |
| P10 | no | every router has a route to 10.21.0.0/24 |
| P11 | no | edgeA loopback reaches edgeB loopback (**per-topology address**) |
| P12 | no | no interface is administratively down |

A candidate that satisfies SPEC and violates something in oracle\SPEC is a
**false pass** — the quantity the project measures. The gap must stay designed
in and frozen, never widened after seeing results.

**Three properties resolve per topology and must come from the model, never a
constant: P06, P08, P11.** `properties.yml` records the resolved values under
`topology_resolved:` so the evaluated suite is reconstructable.

Changing suite *membership* changes the measured false-pass rate — any such
edit must bump `SUITE_VERSION` and be dated in `docs/HARM-DEFINITION.md`.

### Harm definition — `docs/HARM-DEFINITION.md` v1.1.0

Convergence policy: elapsed **≥ 45 s** (`MIN_SETTLE_S`) **AND** no transitional
OSPF neighbour **AND** RIB stable over 3 polls of 5 s; timeout 180 s. The 45 s
floor exists because convergence once fired at 11.4 s on a pre-convergence
plateau (S-009).

### Leakage rules — `docs/LEAKAGE.md`

- Provenance fields — `fault_family`, `repair_id`, `repair_class`,
  `incident_id` — are **banned from X**.
- Splits are **grouped, leave-one-incident-out**. Random splits put near-
  duplicate candidates from one incident on both sides.
- Report **AUC-PR** over AUC-ROC; classes are imbalanced.
- Features must be computable at inference time from the config diff alone.
- Any feature derived from topology structure **must be parameterised by the
  spec**. A denominator hardcoded to one topology's router count makes
  identical changes score differently for reasons unrelated to the change.

### Batching and resume

**An item is DONE if and only if its completion record exists on disk.** No
in-memory state, no separate progress file that can disagree.

- Phase 2: batches of 500. Phase 3: batches of 100, `--only-passing`.
- Fully resumable including mid-batch crash. `ledger duplicates` must be 0;
  a non-zero value invalidates the batch.
- Proven by `pipeline/test_batching.py` (7 checks, includes crash recovery).

## 8. Dataset design C

**10 topologies × 10 incidents per topology = 100 incidents → 1,793 candidates.**

Class balance: correct 450, regressive 453, incomplete 890.
Dropped at build time: `duplicate_after_config: 1307` — different `repair_id`s
that produce identical resulting configs. Deduplication matters: a duplicate
would appear twice with different provenance and leak through duplicate feature
rows.

Per-topology candidate counts: t01 172, t02 183, t03 183, t04 177, t05 183,
t06 182, t07 183, t08 178, t09 174, t10 178.

Projected cost: Phase 2 ≈ 5.2 h (4 batches of 500); Phase 3 ≈ 24.3 h
(10+ batches of 100, only Batfish-PASS candidates). Prior measurement:
~11.4 s/candidate on 6-router topologies; pilot-v2 goes to 8 routers, so treat
5.2 h as a floor.

## 9. Results so far (pilot-v1, complete)

50 candidates, one topology (T2), phases 1–4 finished and verified
(Phase 1 16/16, Phase 3 61/61 and 35/35).

**Ground truth:** 12 SAFE / 38 HARMFUL.

**The headline 2×2:**

| | SAFE | HARMFUL |
|---|---|---|
| Batfish **PASS** | 12 | 12 |
| Batfish **FAIL** | 0 | 26 |

→ **P(harm \| PASS) = 50 %**, P(harm \| FAIL) = 100 %.

**600 property comparisons:** agree 576, **Batfish-optimistic 21,
Batfish-pessimistic 0.** The error is entirely in the dangerous direction —
Batfish says "fine" about things that are broken, never the reverse.

**Phase 4 honest finding: no meaningful learned model.**
The SAFE class was 83 % `exact_revert`; excluding it collapsed every model to
≤ 0.542 AUC with p ≥ 0.469. Tier A/B/C feature sets, LogReg / decision stump /
majority baseline, leave-one-incident-out CV, bootstrap CI, permutation test —
nothing beat chance once the trivial class was removed.

A simple **spec-widening rule** caught **7 of 12** harmful PASS candidates with
**zero false alarms**, beating every learned model. Decomposition: 7/12 are
recoverable by widening the specification; **5/12 are not** — they need
execution.

**Report this rather than tuning until something looks publishable.** It is a
legitimate and interesting result, and it directly motivates the conformal-
risk-control contribution: if you cannot learn a sharp classifier, a
distribution-free bound on harmful auto-applied changes is exactly what an
operator needs instead.

## 10. Defect log — every silent failure found

**Every one of these passed a green check first.** The shared root cause is a
single pattern:

> **a check that cannot distinguish "condition satisfied" from "condition never
> evaluated."**

| # | Defect | How it hid |
|---|---|---|
| S-002 | Harness-errored candidate produced 0 rows | Vanished from counts; 588/600 looked complete |
| S-003 | Batfish lowercases hostnames | 15 false address failures |
| S-004 | FRR `access-list`/`distribute-list` accepted, modelled as nothing | **Zero parse warnings**; F10 retired |
| — | `ip ospf network broadcast` unparsed | F10 retired a second time |
| — | `link-down yes` unparsed by the interfaces parser | Admin state now lives only in `frr.conf` |
| S-008 | `frr:8.4.4` image did not exist | Led to the dual-digest split |
| — | `artifact_digest` unstable across rebuilds | 51 `created_utc` files; timestamps moved to the lock |
| S-009 | Convergence fired at 11.4 s on a plateau | Harm-def → v1.1.0, 45 s floor |
| S-010 | P12 counted Containerlab transient veth stubs | Scoped to artifact interfaces |
| S-011 | FRR echoed `shutdown` but left the interface UP | Config readback ≠ state; added a state assertion |
| S-012 | P07 ORed `max_hops_reached` | Unreachable scored as looping |
| S-013 | P05 used `ping` (round-trip) vs Batfish one-way | Semantics mismatch; all 9 cases in the FAIL bucket |
| — | `peer_map` global | `KeyError` on t01; would have **silently** compared the wrong peer on t02–t10 |
| — | Spike read stale snapshots from shared Batfish network `nrl-spike` | **2 of 7 checks validated the wrong pilot and reported PASS** |
| — | Only 3 of 10 fault families sampled | `static_route checked=0` printed as `ok` |
| — | `spec.transit` dropped the peer address | Static faults pointed at the node's own address |
| — | Both static families installed on the wrong router | Route was redundant, not faulty |
| — | `--force` left stale device directories | Lock hashed 6 files not part of the artifact (C-00161 kept `wan1`/`wan2` from a 6-router build while being a 4-router candidate) |
| — | `--pilot` defaulted to `data/pilot-v1` | Ran **zero** items, printed `ALL ITEMS COMPLETE` |
| — | `NETWORK` was a module constant `"nrl-pilot-v1"` | Two pilots would share one Batfish namespace; colliding snapshot names |
| — | **P11 hardcoded `10.255.0.6`** | Correct in 4 topologies, false FAIL in 3, **false PASS in 3** where `.6` existed but belonged to `wan3`/`wan4`/`coreb` |
| — | `spec_coverage_features` hardcoded 6 routers | **ML feature**; denominator wrong for 4- and 8-router topologies |
| — | `properties.yml` emitted `dst: None` | The frozen spec document was unreadable/unauditable |
| — | `verify_pilot` CHECK 8 rebuilt with the wrong builder | "63981 differ" — fixed via `lock["builder"]`/`build_args` |

**Gates that now exist because of these:**

1. `verify_pilot.py` — 16 structural checks including same-artifact, exact-case
   device names, address plan, non-empty diffs, leakage guard, byte-identical
   rebuild, file-level orphan detection.
2. `spike_frr_batfish.py` — per-pilot Batfish network, construct coverage where
   `checked=0` on a present construct is a **failure**, family-rotating sample
   covering all 10 families, negative control (loop rows must be 0 on golden).
3. `verify_golden_properties.py` — every property must PASS on every golden.
4. `test_topology_aware.py`, `test_batching.py` — including negative controls.

Two techniques do most of the work and should be reached for by default:

- **Negative control** — make the condition genuinely false and confirm the
  check fails. A check never observed failing has not been tested, only run.
- **Positive/golden control** — on input healthy by construction, everything
  must pass. A property failing there is measuring something other than its
  text.

## 11. Current state and exact next steps

### Verified on disk as of 2026-08-27

- `data/pilot-v1/` — complete through Phase 4. Do not modify.
- `data/pilot-v2/` — **rebuilt** after the P11 / feature / YAML fixes.
  - 100 incidents, 1,793 candidates, `suite_version 1.1.0`
  - `artifact_digest` = `16635513e3974827…` (changed, as expected)
  - `snapshot_digest` = `f1a49e3cf2c346b9…` — **unchanged from the pre-fix
    build**, confirming the property/metadata edits were snapshot-neutral
  - `properties.yml` contains the `topology_resolved:` block; spot-checked
    t01 → `10.255.0.4`, t03 → `10.255.0.8` (previously both `.6`)
  - **`phase2/` is absent** — deleted with the rebuild, so the spike verdict is
    gone and Phase 2 is hard-blocked until it is re-run.

### Not yet run (needed before any batch)

```powershell
python pipeline\verify_pilot.py             --pilot data\pilot-v2   # expect 16/16
python pipeline\spike_frr_batfish.py        --pilot data\pilot-v2   # expect GO
python pipeline\verify_golden_properties.py --pilot data\pilot-v2   # all 10 topologies PASS
python pipeline\run_phase2.py --pilot data\pilot-v2 --only C-00001,C-00020,C-00026,C-00173,C-00192,C-00198,C-00356,C-00375,C-00381,C-00539,C-00558,C-00564
```

The smoke sample is **stratified** — 4 topologies × 3 repair classes.
`--limit N` takes a contiguous slice of a topology-ordered manifest, i.e. one
topology and one repair class, which is why it is not used here. Acceptance
criteria: a **PASS/FAIL mix** (all-PASS means the checks are not
discriminating), zero ERROR/INVALID, zero ledger duplicates, and a measured
per-candidate time to extrapolate.

Then, **only with explicit approval:**

```powershell
python pipeline\run_phase2.py --pilot data\pilot-v2 --batch-size 500
python pipeline\run_phase3.py --pilot data\pilot-v2 --batch-size 100 --only-passing
```

### Known outstanding items

- `verify_pilot.py` and `spike_frr_batfish.py` **still default to
  `data/pilot-v1`** — the four runtime scripts were fixed to `required=True`,
  these two were not. Pass `--pilot` explicitly and check the header line.
- `run_phase2.py`'s BLOCKED message prints `python pipeline\spike_frr_batfish.py`
  with no `--pilot`; following it literally would spike pilot-v1.
- `nrl/topologies.resolve()` silently falls back to `t2v1` on an unknown name,
  and `bf_eval` does `spec = spec or T2V1`. All 1,793 manifest entries have
  valid topologies, so nothing is corrupt — but it is the same shape as the
  logged defects.
- The suite bump to 1.1.0 is **not yet dated in `docs/HARM-DEFINITION.md`**, and
  `notes/lab-notebook.md` has no entry for the pilot-v2 build. The edit is
  legitimate precisely because no pilot-v2 harm labels exist yet — write that
  down before they do.
- Consider whether `run_phase2` should write results into candidate `meta.json`
  (build scope) — it must not, or CHECK 8 breaks after Phase 2.

## 12. Open questions and risks

1. **Will the 50 % false-pass rate hold at n≈862 PASS candidates across 10
   topologies?** Everything depends on this number. A much lower rate weakens
   the motivation; a similar rate across topologies strengthens it considerably.
2. **Which fault families produce the most verifier blind spots?** Currently
   unanswered at scale — it is a paper section on its own.
3. **Is the learned-model negative result stable at scale?** If it is, the paper
   pivots to: risk is not learnable from config diffs alone, therefore bound it
   with conformal risk control rather than predict it. That is a stronger and
   more honest story than a mediocre classifier.
4. **Runtime risk:** ~1,903 snapshots in one Batfish network on a pinned image
   is untested; the largest prior Phase 3 run is 61 labs. Host suspend has
   already caused a 932 s wall-clock against a 25 s subprocess timeout.
5. **Is the professor willing to co-author?** Unresolved.
6. **Is a real network engineer available to sanity-check escalation packets?**
   Unresolved.

## 13. Starter prompt for a new thread

> I'm continuing my research project "Trust but Verify the Verifier" — measuring
> how often a network config change that passes Batfish verification still
> causes harm when executed in Containerlab, then predicting that residual risk.
>
> Read `docs/PROJECT-HANDOFF.md` in the connected `network-research-lab` folder
> for full context, then verify the current state against what is actually on
> disk before advising me — do not trust the document over the filesystem.
>
> Act as my Senior Network Engineer and Research Implementation Engineer, and as
> a critical IEEE reviewer. Do not validate an idea because it is mine.
>
> Standing constraints:
> - Do not weaken, bypass, override, or skip any existing gate. No
>   `--override-spike` or equivalent.
> - Preserve the same-artifact guarantee and the frozen Phase 1/2 specs.
> - Do not modify Phase 1–3 data or rerun completed labs.
> - Do not invent successful results. Clearly separate what you implemented and
>   tested from what needs me to run it.
> - Use `.venv` only. Ask before anything destructive.
> - Do NOT start a full Phase 2 or Phase 3 run without my explicit approval.
>   Stop after validation and report.
>
> Start by telling me the exact current state of `data/pilot-v2` and what the
> next command should be.

**Companion skill:** `silent-success-audit` encodes the auditing discipline in
§10 plus this runbook. Invoke it whenever a gate, test, or pipeline run reports
PASS and something expensive depends on that result being real.
