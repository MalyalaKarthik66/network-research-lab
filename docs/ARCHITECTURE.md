# Phase 1 architecture and decision record

## 1. The same-artifact requirement, and how it is actually satisfied

The failure this design exists to prevent: Batfish analyses configuration A,
Containerlab runs configuration B, and every disagreement between them is
confounded by the A→B translation rather than being the phenomenon under study.

"Use the same vendor on both sides" is necessary and **not sufficient**. Even
with FRR on both sides there is a residual transformation, because Containerlab
mounts `/etc/network/interfaces` and `/etc/frr/frr.conf` as separate files while
Batfish reads them concatenated with marker lines.

The resolution here is stronger than same-vendor. It is **same bytes**:

```
  artifact/devices/<node>/interfaces ──┬─→ bind-mounted read-only into the
                                       │   container as /etc/nrl/interfaces,
                                       │   applied by bin/apply-interfaces.sh
                                       └─→ embedded VERBATIM in the Batfish
                                           snapshot

  artifact/devices/<node>/frr.conf   ──┬─→ bind-mounted to /etc/frr/frr.conf
                                       └─→ embedded VERBATIM in the snapshot
```

`nrl/emit.py:emit_batfish_snapshot()` adds exactly two things to those bytes: a
leading hostname line and a ports.conf stub. Nothing is rewritten, reordered or
regenerated. Both source files already begin with the marker line Batfish looks
for, which is why nothing else is needed.

`nrl/emit.py:extract_batfish_sections()` is its inverse.
`pipeline/verify_pilot.py` CHECK 2 uses it to prove, per device per candidate,
that the snapshot contains byte-identical content to what the container mounts.
That check currently passes for all 366 device configs in the pilot. **This is
the same-artifact guarantee, and it is machine-checked rather than asserted.**

Interface addressing deserves its own note. The `frrouting/frr` image does not
process `/etc/network/interfaces`; a normal Containerlab lab would set addresses
with `exec: ip addr add ...` directives written into the topology file. That
would be a second source of truth and would break the guarantee. Instead
`bin/apply-interfaces.sh` parses the artifact's own `interfaces` file inside the
container. The subset of ifupdown syntax it understands is documented in that
script and in `nrl/render.py:IFACE_SUBSET`; the generator emits only that subset.

## 1b. Byte-identity is necessary and NOT sufficient — the F10 lesson

The first spike run (2026-08-25) proved this the hard way. The artifact was
byte-identical by CHECK 2 of `verify_pilot.py`, parsed cleanly — 6/6 files
`PASSED`, format `CUMULUS_CONCATENATED`, **zero parse warnings, zero
initIssues** — and Batfish still did not model the `access-list` and OSPF
`distribute-list` that fault family F10 depended on. `definedStructures` on
corea returned only interfaces.

No warning. No error. The construct was accepted and silently discarded.

That is a *semantic* divergence hiding underneath a *byte-level* guarantee:
Containerlab would have enforced the filter while Batfish could not see it, so
every disagreement about F10 candidates would have been an artefact of the
model gap rather than the phenomenon under study — precisely the confound this
whole design exists to eliminate.

**The fix is a coverage check, not a byte check.** `spike_frr_batfish.py`
CHECK 3 now walks the nrl Scenario model for all 11 snapshots and asserts that
every construct the renderer emitted — interface addresses, admin state, OSPF
area / cost / passive / network-type, static routes, named structures — is
present in Batfish's model with the value we wrote. Expectations are derived
from the model, never hardcoded.

The rule this establishes: **a construct may only appear in the artifact if
both tools observably represent it.** Anything else gets retired, and F10 was.

## 1d. Construct capability table — what the artifact may contain

Established by running the spike, not by reading documentation. A construct may
appear in the artifact only if BOTH tools observably represent it.

| Construct | Batfish | Evidence |
|---|---|---|
| `address` in interfaces file | **yes** | 231/231 matched across 11 snapshots |
| `alias` in interfaces file | yes | description surfaces in the model |
| `shutdown` under `interface` (frr.conf) | **yes** | down state propagated to the L1 peer |
| `link-down yes` in interfaces file | **NO** | `parseWarning`: "This syntax is unrecognized" |
| `ip ospf area` | **yes** | 230/230 matched |
| `ip ospf cost` | **yes** | 164/164 matched |
| `passive-interface` | **yes** | 230/230 matched |
| `ip ospf network point-to-point` | **yes** | 131/131 matched |
| `ip ospf network broadcast` | **NO** | `parseWarning`, parser context `siipo_network_p2p` |
| `ip route ... <nh>` / `blackhole` | **yes** | modelled as `discard`/`null_interface`, AD 1 |
| `access-list` (FRR) | **NO — silently** | zero parse warnings, absent from `definedStructures` |
| OSPF `distribute-list` | **NO — silently** | same |

The last two rows are the dangerous ones and the reason CHECK 3 exists. The two
`NO` rows above them are the *safe* kind of failure: Batfish complained. A
construct that fails loudly costs an afternoon; one that fails silently costs a
dataset.

**Admin state has exactly one representation:** `shutdown` in frr.conf. The
interfaces file carries addressing only, and `bin/apply-interfaces.sh` sets
addresses and deliberately does not touch link state, so it cannot race zebra
over the very thing fault families F01/F02 inject.

## 1c. Node names are lowercase everywhere

Batfish lowercases hostnames (`hostname corea` → node `corea`). The first spike
hardcoded mixed-case names and reported 15 false address failures for
corea/coreb/edgea/edgeb while wan1/wan2 "passed" only because they contain no
uppercase letters. The addresses were present the whole time.

Two changes followed. The topology now uses lowercase node names throughout, so
identifiers are literally identical in Batfish, Containerlab and our records —
no `.lower()` on any Phase 3/4 join, and no chance of silently dropping rows on
one. And every comparison normalises case defensively regardless.

A related trap, caught during the rebuild: Windows filesystems are
case-INSENSITIVE, so regenerating into an existing tree writes correct content
into directories that keep their old names (`devices/coreA/` serving
`devices/corea/`). Harmless on Windows, broken inside a Linux bind-mount.
`build_pilot.py` now refuses to run in that state and `verify_pilot.py`
CHECK 3b asserts on-disk names match the model exactly.

## 1e. Build scope vs runtime scope, and the artifact digest

`data/pilot-v1/` holds two kinds of content and conflating them broke a check:

| Scope | Paths | Owner | Deterministic? |
|---|---|---|---|
| **build** | `reference/`, `incidents/`, `candidates/`, `properties.yml`, `manifest.json` | Phase 1 | yes — locked and rebuild-compared |
| **runtime** | `phase2/`, `phase3/`, `phase4/` | the phase that wrote it | no — timestamps, tool versions, measurements |

`pilot.lock.json` originally hashed *every* file under the pilot, so once the
spike had written `phase2/spike_result.json` a Phase-1 reproducibility check
failed simply because a Phase-2 tool had run. The check was right; the scope was
wrong. `nrl/manifest.py:in_build_scope()` is now the single definition, imported
by both the builder and the verifier.

**The more dangerous problem underneath it.** `build_pilot.py --force` left
`phase2/` in place while regenerating the artifacts it was computed from — so a
GO verdict could survive a rebuild and wave Phase 2 through against a pilot that
no longer existed. Silent, and worse than the failing check that exposed it.

Closed with an **artifact digest**: one sha256 over every in-scope file hash,
written to `pilot.lock.json`, stamped into `spike_result.json` when the spike
runs, and copied into `run_metadata.json` by Phase 2.

- `build_pilot.py` warns loudly when downstream output exists and is now stale
- `run_phase2.py` refuses if the spike's digest differs from the lock's
- `verify_phase2.py` asserts the dataset was collected from the artifact on disk

Scoping was not a weakening. Verified by negative test: corrupting one byte of
`candidates/C-0007/.../frr.conf` still fails CHECK 2 and CHECK 8; an extra file
inside `candidates/` still fails the stale check; the digest gate fires on a
mismatched verdict and only then.

## 1f. Two digests, because two consumers depend on different things

| Digest | Covers | Gates |
|---|---|---|
| `snapshot_digest` | `*/batfish-snapshot/*` only | the spike, and Phase 2 |
| `artifact_digest` | every in-scope file | Phase 3 |

Batfish reads `batfish-snapshot/` and nothing else. It never sees
`topology.clab.yml`, the host setup scripts, or a container image tag. Gating
Phase 2 on the full artifact digest meant that correcting a wrong container
image — something Batfish cannot observe — invalidated a Batfish dataset that
was still entirely valid.

Each consumer is now gated on exactly what it depends on. Verified by
construction: changing only `FRR_IMAGE` moves `artifact_digest` and leaves
`snapshot_digest` untouched.

## 2. Decision: FRR, not Arista cEOS — provisional, gated

FRR is chosen because Containerlab runs it natively, it is free, and it costs
tens of megabytes per node rather than 1–2 GB, so 15–20 nodes fit in 16 GB.

This is **provisional**. `pipeline/spike_frr_batfish.py` is the gate and it has
not been run on this machine. If it returns STOP, the fallback is Arista cEOS,
which Batfish parses excellently but which caps the topology at four or five
nodes — a cap that changes which topology is buildable at all. `nrl/render.py`
is the only module that would need a second emitter.

## 3. Decision: no packet ACLs anywhere in the pilot

FRR `access-list`, `prefix-list` and `route-map` are **route** filters. Packet
filtering on Cumulus lives in `/etc/cumulus/acl/policy.conf` → iptables, which
is not part of the concatenated format Batfish reads.

So an ACL fault family on FRR would mean injecting an iptables rule the
container enforces and the snapshot cannot contain — a direct violation of
section 1. Packet-filter faults require cEOS. Until the spike decides, every
fault family in `nrl/faults.py` is routing-layer only.

This is a genuine narrowing of the fault space and it should be stated in the
paper's limitations rather than discovered by a reviewer.

## 4. Decision: OSPF only, no BGP, in pilot-v1

Batfish's FRR grammar coverage is partial and unverified on this machine. Every
protocol added is parse risk against an unmeasured baseline. BGP is deferred to
pilot-v2, gated on the spike passing. The registered T2 topology specifies eBGP
across the WAN; this is a **deliberate deviation for the pilot**, recorded here
rather than silently made.

## 5. Decision: full determinism, not a seeded sample

10 incidents × 5 repair operators = 50, enumerated. No sampling anywhere. The
`--seed` flag is recorded in `pilot.lock.json` for forward compatibility with
stochastic operators but pilot-v1 does not consume it. Determinism is a stronger
reproducibility property than a fixed seed and is preferred while the operator
library is small enough to enumerate. `verify_pilot.py` CHECK 8 proves it by
rebuilding into a temporary directory and comparing every file hash.

## 6. Decision: programmatic mutation, not an LLM, for the pilot

Per the Phase 1 brief. The consequence must be stated plainly, because it bounds
what the pilot can claim: **false-pass rate is a property of the repair
distribution, not of Batfish.** A rate measured over synthetic mutations is not
the rate an LLM-driven repair loop would produce. The pilot measures whether the
pipeline works and whether the phenomenon exists at all; a headline false-pass
number for the paper needs a repair distribution someone would defend.

`nrl/repairs.py` is written so an LLM-backed operator drops in as one more entry
in `REPAIRS` without touching anything else.

## 7. What the artifact tree looks like

```
data/pilot-v1/
├── properties.yml              the frozen suite (spec vs oracle)
├── manifest.json               index of all 50 candidates
├── pilot.lock.json             sha256 of every file; the reproducibility proof
├── reference/golden/           the healthy network
│   ├── artifact/{devices,bin,topology.clab.yml}
│   └── batfish-snapshot/{configs,batfish/layer1_topology.json}
├── incidents/I-01..I-10/       the BROKEN networks = Phase 3 BEFORE state
│   ├── fault.json
│   ├── golden_to_faulted.diff
│   ├── artifact/  └── batfish-snapshot/
└── candidates/C-0001..C-0050/  the REPAIRED networks = Phase 3 AFTER state
    ├── meta.json
    ├── diffs/{faulted_to_candidate,golden_to_candidate}.diff
    ├── artifact/  └── batfish-snapshot/
```

Every candidate names its BEFORE state at `artifact.before_state`. Phase 3 boots
the incident artifact, measures, boots the candidate artifact, measures again.

## 8. Known property of the pilot: 41 distinct networks, not 50

The `R-exact_revert` operator produces the golden configuration for every
incident, so 10 of the 50 candidates share one device-config set. They are still
50 distinct experiments — the BEFORE state and therefore the config diff differ
per incident — but only 41 distinct AFTER networks are booted. This is recorded
rather than engineered away: reverting the change is the most realistic repair
an operator makes, and suppressing it to inflate diversity would bias the pilot.
`verify_pilot.py` CHECK 5 asserts this is the *only* duplication.
