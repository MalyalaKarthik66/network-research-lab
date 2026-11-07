# Stage 1 — validation run — COMPLETE

**Date:** 2026-09-04
**Scope:** 2 topologies × 3 incidents (`t01_chain4`, `t19_dualcore16`), all 46
candidates through Phase 2, the 20 that passed the spec gate through Phase 3,
plus 10 replicate labs, 2 goldens and 1 golden replicate.
**Artifact digest:** `bfc81a2f4ed11af9` · **snapshot digest:** `ba54d5eb496f9c04`
**Suite:** `1.1.0` · **Harm definition:** `1.1.0` (unchanged — see S-020)

Stage 1 is a *plumbing* validation. It does not estimate anything the paper
will claim; it establishes that the apparatus measures what it says it measures.

---

## 1. Verdict against the pre-registered GO criteria (FINAL-PLAN §6)

| # | criterion | result | |
|---|---|---|---|
| 1 | Stage 0: 16/16 structural; golden gate PASS with negative control firing; shortcut AUC < 0.85 | 16/16 ✔, golden gate 240/240 ✔ with the control firing, **shortcut AUC 0.999 ✘** | **PARTIAL** |
| 2 | \|G\| = 12 on every topology in Containerlab | 12/12 on both | PASS |
| 3 | Phase 2 produces a PASS/FAIL mix | 20 PASS / 26 FAIL | PASS |
| 4 | Replicate label agreement ≥ 95% | **10/10 = 100%** | PASS |
| 5 | NO_CONVERGENCE < 5%; UNDETERMINED + EXECUTION_FAILED < 5% | 0% and 0% | PASS |
| 6 | `verify_phase2` and `verify_phase3` both pass | 30/30 and 42/42 | PASS |
| 7 | Seconds-per-lab within 2× of the 100 s assumption | 98.6 s main, 83 s replicate | PASS |

**Six of seven pass. Criterion 1 fails on its shortcut clause only, and that
failure belongs to Stage 0 and to the corpus, not to the apparatus (S-014).**
Stage 1's purpose — proving the measurement chain — is met. Proceed to Stage 2
with the learned-risk arm flagged as compromised.

---

## 2. What was measured

**False-pass rate on this slice: 4 / 20 = 20.0%**
Wilson 95% CI [8.1%, 41.6%]; clustered bootstrap resampling the 6 incidents,
95% CI [9.1%, 33.3%].

This is 20 candidates from 6 incidents on 2 topologies. It is a smoke-test
number, quoted here only to show the pipeline produces one in the plausible
band (FINAL-PLAN's continue-band is 10–60%). **It is not the paper's estimate
and must not be cited as one.**

| incident | topology | HARMFUL / PASS |
|---|---|---|
| I-00001 | t01_chain4 | 1 / 4 |
| I-00005 | t01_chain4 | 1 / 2 |
| I-00009 | t01_chain4 | 1 / 3 |
| I-00181 | t19_dualcore16 | 1 / 5 |
| I-00185 | t19_dualcore16 | 0 / 2 |
| I-00189 | t19_dualcore16 | 0 / 4 |

**Every violation is in an oracle-only property. None is in SPEC.**

| candidate | violated | in SPEC? |
|---|---|---|
| C-00006 | P06 | no |
| C-00039 | P06 | no |
| C-00060 | P06 | no |
| C-01333 | P03, P04 | no |

`spec_violations_vs_golden` is empty for all four — which is exactly the
structure the thesis predicts: the specification is satisfied and harm appears
only where the specification does not look. It is also a warning. Three of four
are the same property (P06, `must_traverse`), so on this slice the trivial rule
"predict HARMFUL iff an oracle-only property fails" would score perfectly. That
rule was already the pilot-v1 champion. Whether it survives 20 topologies and
10 fault families is a Stage 2/3 question.

**Replicate agreement: 10 / 10 (0 flips).**
Three of the ten replicated a HARMFUL label, so the agreement is not an artefact
of re-running only easy negatives. Caveat: 0/10 has a 95% upper bound of ~28%,
and 8 of the 10 were `t01_chain4` labs. **The label-noise floor is bounded but
not yet estimated.** Stage 4 budgets 40 replicates; that is what pins it down.

**Oracle stability:** 3 golden runs, identical property vectors.
**Lab validity:** 39/39 passed the S-020 OSPF-binding check.

---

## 3. Defects found and fixed during Stage 1

Stage 1 cost four defects, every one of which would have corrupted the full run
silently. All were found by auditing green results, not by anything failing.

**S-018 — the lab name was rebuilt instead of read.** `run_one` computed
`nrl-<run_id>`; the v2 builder emits `nrlv2-<id>`. Every deploy succeeded and
every `docker ps` lookup missed: 29/29 `CONTAINERS_MISSING`. *Also:* the
per-batch golden control reported "3 golden run(s), ALL IDENTICAL" on three
identical **failures** — empty property vectors compare equal. A control that
passes on its own absence.

**S-019 — the replicate arm ran and measured nothing.** Both dataset loops
iterate the manifest; `<base>~r1` is not in it, so ten labs produced
measurements and zero outcome rows. The batch reported COMPLETE and
`verify_phase3` passed 38/39 with the label-noise floor simply absent.

**S-020 — ospfd bound to nothing and every runtime check said OK.** On one
replicate, `b1:eth2` was missing from `show ip ospf interface` while up and
correctly addressed, with a stale `clab-fd812620` stub in FRR's interface
table: containerlab renames the veth after creating it, and ospfd read its
config inside that window. One adjacency could not form, P06 and P08 failed,
and the candidate was labelled HARMFUL instead of SAFE.
`verify_running_config`, `verify_addresses`, `interfaces_down` and the
convergence criterion all passed — correctly. None asked whether ospfd was on
the interfaces the artifact puts in OSPF. **This is why the first Stage 1 run's
"10% label-noise floor" was wrong: it was one broken lab, not stochastic ground
truth.**

**S-019's first diagnosis was wrong and is recorded as wrong.** The flip was
attributed to a convergence race; a fourth convergence condition was written,
tested, and reverted when the test disproved it — the poll history shows the
lab stable at 15 adjacencies for 34 seconds. The harm definition was left at
v1.1.0.

**Also fixed:** `verify_phase3` CHECK 2 demanded all 20 goldens on filtered
runs (B1's shape, third occurrence) and CHECK 11's leak scan matched
`clab-nrl-`, missing every `clab-nrlv2-*` container.

**Rate of invalid labs:** 1 in 77 across both Stage 1 attempts (~1.3%). They are
now excluded rather than mislabelled. At full budget that is ~23 labs lost.

---

## 4. Open issues carried into Stage 2

**S-014 — the shortcut, unresolved.** `repair_class` is recoverable from
pre-verification features at AUC 0.999 (`chg_` 0.995, `g_` 0.943, `cov_` 0.766;
no leave-one-group-out below 0.951). It is distributed across feature groups,
not a single tag: each repair operator uses a systematically different set of
config constructs. Adding same-device regressive operators moved
`chg_devices_touched` from 0.890 to 0.777 and left the joint AUC at 0.998.
Tier B/C (Batfish's own outputs) came back at 0.517, but at n=46 across 6
incidents that is underpowered, not clean.
**Consequence:** the measurement study — rate, a/b/c decomposition,
specification-completeness sweep, conformal bound — is untouched. The
*learned*-risk arm is compromised on this corpus and no additional data fixes
it, because the leak is in how repairs are generated. Re-measure Tier B/C at
Stage 2's n before deciding whether the learned arm is reportable.

**Decision needed — retry on `LAB_INVALID`.** Invalid labs are currently
detected and discarded (~23 labs at full budget). One automatic redeploy would
recover nearly all of them at ~90 s each. Retrying a lab until it passes a
validity check must be pre-registered, not added quietly — decide before
Stage 2, record the decision either way.

**Not implemented, deviation already reported:** the LLM-generated repair arm
(FINAL-PLAN §3.10) and the multi-area / redistribution protocol widening.

**Coverage:** Stage 1 exercised 2 of 20 topologies and 3 of 10 fault families.
18 goldens have never been run in Containerlab. The golden gate covers them
statically (240/240) but `|G| = 12` is confirmed only on two.

---

## 5. Stages 2, 3 and 4

Cost model from measured Stage 1 throughput: **~95 s per lab**, ~40 labs/hour.

### Stage 2 — first real estimate

Full Phase 2 on all ~1,793 candidates (Batfish only, ~2–5 h), then Phase 3 on
**150 PASS** stratified across all 20 topologies and 10 fault families (~4 h).

```bash
python3 pipeline/run_phase2.py  --pilot data/pilot-v2 --batch-size 500
python3 pipeline/verify_phase2.py --pilot data/pilot-v2
sudo -E python3 pipeline/run_phase3.py --pilot data/pilot-v2 \
  --workdir /root/nrl-run --only-passing --limit 150 --batch-size 40
python3 pipeline/verify_phase3.py --pilot data/pilot-v2
```

**Read at the gate:** first false-pass rate with a clustered CI; per-topology
spread; class balance; exclusion rate by topology and family; Manski bound
width; Batfish memory at ~1,800 snapshots; `|G| = 12` on all 20 goldens.
**Continue** if the rate is inside 10–60% and no verifier fails.
**Pause** on any verifier failure, a rate outside that band, or an exclusion
rate above 5%.

### Stage 3 — is the signal learnable at all

Phase 3 to **450 PASS** cumulative (+300 labs, ~+8.5 h).

**Read at the gate:** learning-curve points 2 vs 3; first calibration read;
shortcut ablation re-run at real n; a/b/c attribution stability.
**Stop collecting for the model** if the learning curve is flat from Stage 2 to
Stage 3 — redirect the remaining budget to the FAIL arm, replicates and the
completeness sweep, and write the negative result.

### Stage 4 — the full dataset

To **865 PASS** cumulative, plus **150 Batfish-FAIL controls**, **40
replicates** and the LLM arm if it is built (+~667 labs, ~+18.5 h).

Final analysis per `docs/ANALYSIS-PLAN.md` (frozen 2026-09-02): grouped
leave-one-incident-out CV, AUC-PR, Platt vs beta calibration chosen by
out-of-fold log-loss, Brier/Murphy decomposition, 4 equal-frequency reliability
bins plus a continuous curve, hierarchical conformal risk control calibrated at
the incident level with the α floor at 1/(K+1), Manski bounds for undecidable
outcomes, and the autonomy–risk curve.

### Total remaining

~30 h of emulator time and ~5 h of Batfish, against a measured 95 s/lab. The
budget closes.

---

## 6. What Stage 1 does **not** establish

- No model has been trained. Phase 4 has never run.
- 20 labelled outcomes is not a dataset. Nothing about predictability is known.
- The 20% rate is 6 incidents on 2 topologies.
- The noise floor is bounded (0/10) but not estimated.
- 18 topologies are unexercised in the emulator.
