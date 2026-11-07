# RESEARCH STATE REPORT
## Network Research Lab — Batfish Residual-Risk Study
**Date:** 2026-09-06  
**Repository:** `~/network-research-lab`  
**Current Stage:** Stage 2 COMPLETE — Stage 3 PLANNED, NOT EXECUTED  
**Authoritative Plan:** `docs/FINAL-PLAN.md` (v2, 2026-09-02)

---

## 1. CURRENT REPOSITORY STATE

### 1.1 Directory Structure (Key Paths)
```
network-research-lab/
├── docs/
│   ├── FINAL-PLAN.md              # Authoritative plan of record (v2, 2026-09-02)
│   ├── STAGE1-REPORT.md           # Stage 1 validation results
│   ├── RESEARCH-PLAN-v2.md        # Superseded by FINAL-PLAN.md
│   ├── PHASE2-DATA-DICTIONARY.md  # Phase 2 field definitions
│   ├── PHASE3-DATA-DICTIONARY.md  # Phase 3 field definitions
│   ├── LEAKAGE.md                 # Feature leakage rules
│   ├── HARM-DEFINITION.md         # Frozen harm definitions v1.1.0 / v1.2.0
│   └── PROJECT-HANDOFF.md         # Context document
├── pipeline/
│   ├── run_phase2.py              # Batfish verification (EXECUTED)
│   ├── run_phase3.py              # Containerlab execution (NOT YET RUN on v2)
│   ├── verify_phase2.py           # Phase 2 checks (PASSED 29/29)
│   ├── verify_phase3.py           # Phase 3 checks (NOT YET RUN on v2)
│   ├── diagnose_shortcut.py       # Shortcut diagnosis (EXECUTED)
│   ├── audit_dataset.py           # Dataset audit (PASSED)
│   ├── build_pilot_v2.py          # Pilot builder (EXECUTED)
│   └── ... (other scripts)
├── nrl/                           # Core library modules
├── batfish/
│   ├── snapshots.zip              # Reference snapshots
│   └── scripts.zip
├── data/
│   └── pilot-v2/                  # CURRENT PILOT (Phase 1 built, Phase 2 done)
│       ├── reference/             # 20 golden topologies (4 reference-derived)
│       ├── incidents/             # 200 incidents (10 fault families × 20 topologies)
│       ├── candidates/            # 1,479 candidate artifacts
│       ├── manifest.json          # Complete experiment manifest
│       ├── pilot.lock.json        # Lock file with digests
│       ├── properties.yml         # Property suite (12 properties, 5 SPEC / 7 oracle-only)
│       ├── phase2/                # PHASE 2 COMPLETE
│       │   ├── batfish_summary.csv           # 1,479 rows
│       │   ├── batfish_properties.csv        # 17,748 rows (12 × 1,479)
│       │   ├── batfish_questions_index.csv   # 25,143 rows (17 × 1,479)
│       │   ├── spike_result.json             # Verdict: GO
│       │   ├── run_metadata.json
│       │   └── DATA-DICTIONARY.md
│       ├── phase3.pre-S020/       # OBSOLETE — pre-S-020 fix attempt
│       └── phase3.failed-CONTAINERS_MISSING-20260903-171923/  # OBSOLETE
├── phase3-run*.log                # Stage 1 logs (2 topologies only)
└── README.md
```

### 1.2 Version Control
- **No git repository exists** (`.gitignore` present, no `.git`)
- FINAL-PLAN.md §10 requires `git init` + commit + tag `frozen-defs-v1.1.0` as **first action** before any further work

### 1.3 Virtual Environments
- Windows `.venv` (source control / git operations)
- WSL `.venv-wsl` (Batfish / Containerlab experimentation)
- **Both must be preserved; do not delete, recreate, or switch silently**

---

## 2. WHAT STAGE 1 ACCOMPLISHED

### 2.1 Scope
- 2 topologies × 3 incidents (`t01_chain4`, `t19_dualcore16`)
- 46 candidates through Phase 2; 20 PASS through Phase 3
- 10 replicate labs, 2 goldens, 1 golden replicate

### 2.2 GO Criteria Results (from FINAL-PLAN §6)

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Stage 0: 16/16 structural; golden gate PASS with negative control; shortcut AUC < 0.85 | **PARTIAL** — 16/16 ✔, golden 240/240 ✔, **shortcut AUC 0.999 ✘** |
| 2 | \|G\| = 12 on every topology in Containerlab | **PASS** — 12/12 on both |
| 3 | Phase 2 produces PASS/FAIL mix | **PASS** — 20 PASS / 26 FAIL |
| 4 | Replicate label agreement ≥ 95% | **PASS** — 10/10 = 100% |
| 5 | NO_CONVERGENCE < 5%; UNDETERMINED + EXECUTION_FAILED < 5% | **PASS** — 0% and 0% |
| 6 | `verify_phase2` and `verify_phase3` both pass | **PASS** — 30/30 and 42/42 |
| 7 | Seconds-per-lab within 2× of 100 s assumption | **PASS** — 98.6 s main, 83 s replicate |

**Six of seven pass.** Criterion 1 fails only on the shortcut clause, which belongs to Stage 0/corpus, not the apparatus.

### 2.3 Key Measurements from Stage 1
- **False-pass rate (smoke test):** 4 / 20 = 20.0%
  - Wilson 95% CI: [8.1%, 41.6%]
  - Clustered bootstrap (6 incidents): [9.1%, 33.3%]
  - Within preregistered 10–60% continuation band
- **Every violation in oracle-only properties** (P06 ×3, P03+P04 ×1); `spec_violations_vs_golden` empty for all
- **Replicate agreement:** 10/10 (0 flips), but 8/10 from same topology — noise floor bounded not estimated
- **Oracle stability:** 3 golden runs, identical property vectors
- **Lab validity:** 39/39 passed S-020 OSPF-binding check

### 2.4 Defects Found and Fixed During Stage 1
| ID | Defect | Impact |
|----|--------|--------|
| S-018 | Lab name rebuilt (`nrl-<run_id>`) instead of read from artifact (`nrlv2-<id>`) | 29/29 `CONTAINERS_MISSING`; golden control passed on 3 identical **failures** |
| S-019 | Replicate arm ran but produced **zero outcome rows** (manifest iteration skipped `<base>~r1`) | 10 labs burned, label-noise floor absent |
| S-020 | `ospfd` binding incomplete (containerlab veth rename race) — config/addresses OK, adjacency missing | 1 candidate flipped SAFE→HARMFUL; **first "10% label-noise" was a broken lab, not stochastic truth** |

### 2.5 Open Issues Carried into Stage 2
1. **S-014 — Shortcut unresolved:** `repair_class` recoverable at AUC 0.999 (distributed across feature groups)
2. **Retry policy on `LAB_INVALID`:** ~1.3% invalid rate → ~23 labs at full budget; one automatic redeploy would recover most — **must be pre-registered before Stage 2** (ANALYSIS-PLAN §14.1)
3. **LLM arm & multi-area protocol widening:** Not implemented (deferred per FINAL-PLAN §3.10, §3.11)
4. **Coverage:** 18 of 20 topologies unexercised in Containerlab; `|G|=12` confirmed only on 2

---

## 3. WHAT STAGE 2 ACCOMPLISHED

### 3.1 Execution
- **Command:** `python3 pipeline/run_phase2.py --pilot data/pilot-v2 --batch-size 400`
- **Verification:** `python3 pipeline/verify_phase2.py --pilot data/pilot-v2` → **29/29 PASS**
- **Runtime:** ~2,496 seconds (~41.6 min) on WSL

### 3.2 Final Dataset Counts
| Artifact | Rows | Description |
|----------|------|-------------|
| `batfish_summary.csv` | **1,479** | One row per candidate |
| `batfish_properties.csv` | **17,748** | 12 properties × 1,479 candidates |
| `batfish_questions_index.csv` | **25,143** | 17 questions × 1,479 candidates |
| `spike_result.json` | — | Verdict: **GO** (80 snapshots: 20 golden + 60 incident) |

### 3.3 Batfish Specification Verdict Distribution
| Verdict | Count |
|---------|-------|
| **PASS** | **804** |
| **FAIL** | **675** |
| ERROR | 0 |
| INVALID | 0 |
| Duplicates | 0 |

### 3.4 Phase 2 Verification Results (29 checks)
- Manifest = 1,479 candidates
- All 1,479 eligible and present
- No candidates outside expected set
- No duplicate candidate IDs
- Correct incident mapping
- 12 property rows per candidate (17,748 total)
- 17 question rows per candidate (25,143 total)
- Complete parse status (0 warnings)
- Genuine FAIL distinguished from ERROR
- `spec_verdict` PASS iff `spec_fail == 0`
- Raw evidence preserved (hop-by-hop traces sampled)
- No label/target/risk column in Phase 2
- Banned provenance fields preserved with `_BANNED` suffix
- Metadata complete

### 3.5 Population of Interest
- **Total candidates:** 1,479
- **Batfish-PASS (Stage 3 target population):** **804**
- **Batfish-FAIL (control arm target):** 675
- **Do not confuse 1,479 with 804** — the residual-risk problem conditions on Batfish PASS

---

## 4. GOLDEN / BATFISH VALIDATION STATUS

### 4.1 Batfish Spike (Compatibility Gate)
- **Status:** GO
- **Snapshots loaded:** 80 (20 golden + 60 incident)
- **Checks passed:**
  - Parse health (0 warnings across all snapshots)
  - Format (CUMULUS_CONCATENATED detected)
  - Construct coverage (address, active, OSPF area/cost/passive/network, static_route)
  - OSPF adjacency coverage (all topologies)
  - OSPF behavior
  - F10 loop observability
  - Static-route observability
- **Artifact digest:** `bfc81a2f4ed11af9df49ddc750f801d2e1b3cab323b1c484f8599aa51d1eebe3`
- **Snapshot digest:** `ba54d5eb496f9c044eba638c91044b91d5dba7ea4b871be39dafd59cb2e7bae6`
- **pybatfish version:** 2026.08.19.3660

### 4.2 Golden Property Verification
- **Topologies:** 20
- **Properties:** 12 (5 SPEC + 7 oracle-only)
- **Result:** **240/240 property instances PASS**
- **Negative control:** All 4 must-fail probes failed as expected
- **Conclusion:** Evaluator distinguishes valid golden behavior from negative controls

---

## 5. SHORTCUT DIAGNOSIS AND WHY `repair_class` AUC=0.999 MATTERS

### 5.1 Diagnosis Results (from `diagnose_shortcut.py` at n=1,479)
| Feature Group | Worst-case One-vs-Rest AUC |
|---------------|----------------------------|
| `chg_` (config-difference) | 0.995 |
| `cov_` (spec-coverage) | 0.766 |
| `g_` (graph Tier-A+) | 0.943 |
| **ALL** | **0.999** |

### 5.2 Leave-One-Group-Out
| Excluded Group | AUC |
|----------------|-----|
| without `chg_` | 0.951 |
| without `cov_` | 0.999 |
| without `g_` | 0.997 |

### 5.3 Tier B / C (Batfish Outputs)
| Tier | Features | Worst AUC |
|------|----------|-----------|
| B (Batfish metrics) | parse health, RIB/adjacency counts, differential reachability | ~0.842 |
| C (oracle-only verdicts) | Batfish verdicts on 7 oracle-only properties | ~0.876 |
| B + C | Combined | ~0.921 |

### 5.4 Why This Matters
- **This is NOT a software error** — the generator systematically uses different config constructs per repair operator
- **No single feature explains it** — the signature is distributed across groups
- **Consequence:** The *learned-risk arm* is compromised on this corpus; no additional data fixes it because the leak is in how repairs are generated
- **Measurement study is UNTOUCHED** — rate, a/b/c decomposition, spec-completeness sweep, conformal bound remain valid
- **Required action:** DO NOT TRAIN FINAL MODEL USING ALL FEATURES; `repair_class` and banned provenance fields (`prov_fault_family_BANNED`, `prov_repair_id_BANNED`, `diff_vs_golden_rows_BANNED`) must be excluded from X

---

## 6. CURRENT FEATURE-LEAKAGE / PROVENANCE RESTRICTIONS

### 6.1 BANNED from X (per `docs/LEAKAGE.md` and enforced by `verify_phase2.py` CHECK 9)
- All provenance fields: `fault_id`, `fault_family`, `fault_description`, `repair_id`, `repair_description`, `incident_id`, `candidate_id`
- Anything from `incidents/*/fault.json`
- `golden_to_candidate.diff` (comparing against healthy network — unavailable at inference time)
- In Phase 2 CSVs these appear with `_BANNED` suffix: `prov_fault_family_BANNED`, `prov_repair_id_BANNED`, `diff_vs_golden_rows_BANNED`

### 6.2 ELIGIBLE for X
- `meta.json → change_stats` (from `faulted_to_candidate.diff` alone — what's available at inference time)
- `meta.json → spec_coverage` (specification-coverage group)
- `meta.json → phase2_batfish` (all Batfish outputs — available before deployment)

### 6.3 Splitting Rule
- **Group by `incident_id`** — never split candidates from same incident across train/calibration/test
- Random splitting leaks and inflates scores; with conformal prediction it **voids the coverage guarantee**

### 6.4 Current Status
- Banned fields present in CSVs with `_BANNED` suffix (for human browsing)
- `verify_phase2.py` CHECK 9 enforces the marking
- **Phase 4 must drop them at load time, once, in one place**

---

## 7. CURRENT STATUS OF STAGE 3

### 7.1 NOT EXECUTED
- No `phase3/` directory exists in `data/pilot-v2/` with valid results
- Two obsolete directories exist: `phase3.pre-S020/` and `phase3.failed-CONTAINERS_MISSING-20260903-171923/`
- **No Containerlab execution has occurred on the full pilot-v2 dataset**

### 7.2 Blockers Identified in FINAL-PLAN.md (B1–B4) — NOT YET FIXED
| Blocker | Description | Status |
|---------|-------------|--------|
| **B1** | `verify_phase3.py` hardcoded to pilot-v1 (expects 50 candidates, single golden) | **UNFIXED** — must rewrite manifest-derived |
| **B2** | No Containerlab-side golden gate; harm definition can narrow silently (`|G|` drops) | **UNFIXED** — gate exists in `run_phase3.py` but `verify_phase3.py` CHECK 4b also needed |
| **B3** | FAIL control arm missing — need 150 FAIL controls stratified by topology/family | **UNFIXED** — `--fail-controls` flag exists in `run_phase3.py` but not exercised |
| **B4** | Label mapping: `phase4.build_dataset` maps NO_CONVERGENCE/UNDETERMINED/EXECUTION_FAILED → y=0 | **UNFIXED** — must exclude and report Manski bounds |

### 7.3 Code Defects from Audit (FINAL-PLAN §2.2)
- `spec_coverage_features` path semantics bug (ingress/egress misclassified as backup)
- `spec = spec or T2V1` fallbacks in `bf_eval`, `p3_eval`, `run_phase3.py:217`
- `phase4.BANNED_SUBSTRINGS` drops columns silently (must print exclusions)

---

## 8. WHAT STAGE 3 IS INTENDED TO DO

### 8.1 Purpose
Obtain **execution-side ground truth** (Dataset 3) for the 804 Batfish-PASS candidates, producing the label `Y = P(harm | candidate features, Batfish PASS)`.

### 8.2 Planned Execution (from FINAL-PLAN §7, Stage 2)
```bash
# Stage 2 of the staged testing plan (first real estimate)
python3 pipeline/run_phase2.py  --pilot data/pilot-v2 --batch-size 500
python3 pipeline/verify_phase2.py --pilot data/pilot-v2
sudo -E python3 pipeline/run_phase3.py --pilot data/pilot-v2 \
  --workdir /root/nrl-run --only-passing --sample 150 --batch-size 40
python3 pipeline/verify_phase3.py --pilot data/pilot-v2
```

### 8.3 Key Parameters
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `--sample 150` | **Stratified** across all 20 topologies × 10 fault families | `--limit 150` takes contiguous slice (one topology) — **wrong** |
| `--only-passing` | Run only Batfish-PASS candidates | FAIL candidates carry no info for risk model (pilot: P(harm\|FAIL)=100%) |
| `--batch-size 40` | Resumable batches | Interruption costs one lab, not the run |
| `--replicate 10` | 10 replicate labs (label-noise floor) | Half random, half boundary-stratified |
| `--fail-controls 150` | Batfish-FAIL controls | Rule out Batfish-pessimistic rate >2% (Clopper-Pearson) |

### 8.4 LAB_INVALID Policy (ANALYSIS-PLAN §14.1, pre-registered 2026-09-04)
- Detected before property measurement (OSPF binding check)
- Cannot be selected based on eventual label
- **One retry allowed** (archived under `runs/<id>.attempt1/`)
- Same artifact must be used (byte-verified via SHA256)
- Second `LAB_INVALID` → terminal `EXECUTION_FAILED`
- `EXECUTION_FAILED` excluded from primary Y analysis, reported
- Invalid rate >5% after retry = stop condition

---

## 9. WHAT THE 150-CANDIDATE SAMPLE REPRESENTS

### 9.1 Sampling Mechanism
- **Stratified round-robin** over `(topology, fault_family)` strata (deterministic seed: 20260902)
- Spans the **full design**: all 20 topologies, all 10 fault families
- Same sample chosen on every invocation → batched collection resumes inside **same** sample
- Chosen IDs recorded in `run_metadata.json` → `verify_phase3.py` recomputes expected set from them

### 9.2 What It Estimates
- First real false-pass rate estimate with **clustered bootstrap CI** (resampling incidents)
- Per-topology spread, class balance, exclusion rates by topology/family
- Manski bound width (P_min vs P_max)
- Batfish memory at ~1,800 snapshots
- `|G| = 12` confirmation on all 20 goldens

### 9.3 Continuation Gate
- **Continue** if rate ∈ [10%, 60%] and no verifier fails
- **Pause** on verifier failure, rate outside band, or exclusion rate >5%

---

## 10. LABEL DEFINITIONS

### 10.1 Primary: Harm Definition v1.1.0 (FROZEN, mechanical, recomputable)
| Containerlab Outcome | Primary Label (y) | Notes |
|----------------------|-------------------|-------|
| HARMFUL | **1** | Violates property in G (oracle properties holding on golden) |
| SAFE | **0** | No violations in G, no undetermined |
| NO_CONVERGENCE | **1** | Treated as harmful in primary analysis |
| UNDETERMINED | **EXCLUDED** | Counted for Manski bounds |
| EXECUTION_FAILED | **EXCLUDED** | Counted for Manski bounds |

### 10.2 Secondary: Harm Definition v1.2.0 (Pre-registered, sensitivity)
- Harmful if v1.1.0 harmful **OR** flaps/blackholes during convergence window
- Telemetry recorded: convergence time, RIB changes/router, adjacency transitions after first Full, reachability sampled every 5s
- **Both definitions kept distinct** — v1.1.0 stays primary for pilot-v1 comparability

### 10.3 Manski Partial-Identification Bounds
- P_min = HARMFUL / N
- P_max = (HARMFUL + UNDETERMINED + EXEC_FAILED) / N
- **Stop condition:** P_max − P_min > 10 percentage points → harness too fragile
- Exclusion rates reported **by topology and by fault family**

---

## 11. ATTRIBUTION DEFINITIONS (Per-Case, Pre-Registered)

Every harmful-after-PASS case attributed to exactly one:

| Category | Definition |
|----------|------------|
| **(a) Specification Incompleteness** | Batfish reported the violated oracle-only property as FAIL — verifier knew, nobody asked |
| **(b) Model Scope / Transient** | Batfish PASS, violation visible only in transient telemetry or resolves at steady state |
| **(c) Model-vs-Device** | Batfish PASS, violation persists at converged steady state |

- Data already collected; zero extra compute
- Reported as decomposition of the false-pass rate

---

## 12. WHAT WILL HAPPEN AFTER STAGE 3

### 12.1 Immediate Next Step: Small Feasibility / Model Diagnostic
- **NOT** immediate full Stage 4
- Purpose: Determine if Stage 3 ground-truth data contains enough **legitimate learnable signal** to justify Stage 4 compute budget
- Exploratory only — **not** the final reported model, **not** final calibration, **not** evidence hypothesis proven
- Must use **incident-grouped evaluation**
- Primary model: **Gradient-boosted trees** (scikit-learn `HistGradientBoosting` or LightGBM) on Tier A+/B/C
- CNN: **No** (no canonical node ordering, ~700 rows vs 10⁴–10⁶ params)
- GNN: **Declared ablation only** (≤50k params, heavily regularized)

### 12.2 If Learning Curve Flat (Stage 2 → Stage 3)
- **Stop collecting for the model**
- Redirect remainder to FAIL arm, replicates, LLM arm, spec sweep
- Write the negative result honestly
- "Machine learning" comes out of the title; reframe as measurement study

---

## 13. WHAT THE EVENTUAL STAGE 4 ANALYSIS WILL CONTAIN

### 13.1 Full Experiment Scope (FINAL-PLAN §8)
| Quantity | Expected |
|----------|----------|
| Main-arm candidates | ~1,800 |
| LLM-arm candidates | 150 (30 incidents, ≥10 topologies, all 10 families) |
| Batfish-PASS | ~865 main + ~72 LLM |
| HARMFUL / SAFE among PASS | ~430 / ~430 (at 50%) |
| Phase 3 candidate labs | ~937 |
| FAIL control labs | 150 |
| Replicate labs | 40 (20 random + 20 boundary-stratified) |
| Golden labs | 20 + per-batch replicates |
| **Total labs** | **~1,150** |
| Phase 2 runtime | ~2–5 h |
| Phase 3 runtime | **~32 h** at 100 s/lab (staged, resumable) |
| Phase 4 analysis | ~1–2 h |
| **Total** | **~35–39 h** |

### 13.2 Analysis Components (FINAL-PLAN §4.8–4.12)
- **Nested grouped 5-fold CV** (grouping by incident at every level)
- **Platt + Beta calibration** both fitted; selection by inner-split log loss (pre-registered); both reported
- **Isotonic NOT used** (O(n) effective params at n_cal ≈ 170)
- **Per-fold metrics (mean ± sd) primary**; pooled out-of-fold curve = visualization only
- **Inter-fold calibrator variance** reported
- **Calibration metrics:** Continuous reliability curve (clustered bootstrap band), Brier/Murphy, Spiegelhalter z, ECE (equal-frequency bins + bootstrap CI)
- **Discrimination:** AUC-PR primary, AUC-ROC secondary
- **Selection:** Per-incident top-1 accuracy, mean per-incident AUC, **regret vs random**
- **Decision usefulness:** Autonomy–risk curve with hierarchical conformal bound
- **Verification study:** 2×2 with Wilson intervals; P(harm\|PASS) overall/per-topology/per-family; generated vs reference; parametric vs LLM; a/b/c decomposition; Clopper-Pearson bound from FAIL arm; spec-completeness curve
- **Statistical methodology:** All bootstraps resample incidents (2,000); clustered permutation test for confirmatory sweep test; DeLong/paired bootstrap for AUC; McNemar for errors; pre-specified MDE for LOTO/LOFO; power on effective n

### 13.3 Hierarchical Conformal Risk Control
- Method: Dunn et al. (arXiv:1809.07441) + Principato et al. (arXiv:2411.13479)
- Subsampling variant, **max nonconformity score per incident**
- Exact quantile: q̂ = ⌈(K+1)(1−α)⌉-th order statistic; q̂ = ∞ if index > K
- Dedicated grouped split: **120 train / 40 calibration / 40 test** incidents → K=40, floor α≈0.024
- Topology-level variant (K=20, floor≈0.048) as conservative case

---

## 14. DISCREPANCIES BETWEEN OLDER DOCUMENTS AND CURRENT REPOSITORY

| Document | Claim | Current Repository | Resolution |
|----------|-------|-------------------|------------|
| `docs/RESEARCH-PLAN-v2.md` | 10 topologies, 10×10×~18 design | 20 topologies, 20×10×~9 design (1,479 candidates) | **FINAL-PLAN.md is authoritative** — reshaped per §3.4 |
| `docs/PROJECT-HANDOFF.md` | References pilot-v1 (50 candidates) | pilot-v2 (1,479 candidates) | **FINAL-PLAN.md §1.1** documents current state |
| `docs/PHASE3-SETUP.md` | May reference old lab naming (`nrl-<run_id>`) | Artifacts use `nrlv2-<id>`; `run_phase3.py` reads from artifact | Code fixed (S-018); docs may lag |
| Stage 1 report (§5) | Stage 2 command uses `--limit 150` | **FINAL-PLAN §7** correctly specifies `--sample 150` | **Use FINAL-PLAN** — `--limit` is wrong for stratification |
| `docs/LEAKAGE.md` | References 50 candidates, 10 incidents | 1,479 candidates, 200 incidents | Rules unchanged; scale different |
| `pipeline/run_phase3.py` (Stage 1 era) | Hardcoded pilot-v1 expectations | Rewritten with manifest-derived logic, stratified sampling, B2 gate | **Current code matches FINAL-PLAN intent** but B1/B4 not yet fixed in verifier |

### Critical Note
**FINAL-PLAN.md is the single plan of record** (supersedes RESEARCH-PLAN-v2.md and v1 of FINAL-PLAN). Older documents provide history/reasoning but **do not represent current methodology**. Conflicts are resolved in favor of FINAL-PLAN.md and current repository state.

---

## 15. POSSIBLE DATA-INTEGRITY / CODE-INTEGRITY CONCERNS

### 15.1 Data Integrity
| Concern | Evidence | Severity |
|---------|----------|----------|
| **No version control** | No `.git` directory; FINAL-PLAN requires `git init` as first action | **HIGH** — no history, no tag on frozen definitions |
| **Phase 2 spike digests** | `spike_result.json` artifact_digest matches `pilot.lock.json` ✓ | OK |
| **Obsolete Phase 3 directories** | `phase3.pre-S020/`, `phase3.failed-.../` exist but are stale | **LOW** — clearly named, not confused with current run |
| **Duplicate AFTER-configs dropped** | 321 duplicates dropped at build (manifest.json) | Documented, expected |

### 15.2 Code Integrity
| Concern | Location | Status |
|---------|----------|--------|
| **B1: `verify_phase3.py` hardcoded to pilot-v1** | `verify_phase3.py` CHECK 2, CHECK 8 | **UNFIXED** — will fail loudly after compute |
| **B2: Golden gate in `run_phase3.py` exists but `verify_phase3.py` CHECK 4b also needed** | Both files | **PARTIAL** — run-time gate exists, verification check exists |
| **B4: Label mapping in `phase4.build_dataset` maps excluded → y=0** | `nrl/phase4.py` (not read) | **UNFIXED** — must exclude and report Manski bounds |
| **`spec_coverage` path semantics bug** | `nrl/graphfeat.py` or similar | **UNFIXED** — ingress/egress misclassified as backup |
| **`spec or T2V1` fallbacks** | `bf_eval`, `p3_eval`, `run_phase3.py:217` | **UNFIXED** — make `spec` required |
| **Silent column drops in leakage filter** | `phase4.BANNED_SUBSTRINGS` | **UNFIXED** — must print exclusions |
| **`--override-spike` flag exists** | `run_phase2.py` | **UNFIXED** — FINAL-PLAN §2.4 says remove |
| **Dead pilot-v1 constants** | `bf_eval.HOST_ATTACH`, `EXPECTED_OSPF_PAIRS`, `p3_eval.SRC_NODE` | **UNFIXED** — FINAL-PLAN §2.4 says remove |

### 15.3 Experimental Integrity
- **Shortcut (AUC=0.999)** is a known threat to validity for the *learned* arm — documented, not hidden
- **No labels exist for v2** — methodological decisions still legitimate to make (FINAL-PLAN §1.2)
- **LLM arm and reference-derived topologies not yet implemented** — required by FINAL-PLAN §3.10, §3.11
- **Git repo initialization blocked** — must happen before any further execution

---

## 16. QUESTIONS AND AMBIGUITIES REQUIRING HUMAN REVIEW

### 16.1 Pre-Execution Decisions Required
1. **Git initialization:** FINAL-PLAN §10 lists `git init` + commit + tag `frozen-defs-v1.1.0` as first action. Should this be done now, before any code fixes?
2. **Retry policy for `LAB_INVALID`:** FINAL-PLAN §2.1 (S-014 follow-up) and ANALYSIS-PLAN §14.1 require pre-registration. Current code allows 1 retry (MAX_ATTEMPTS=2). Confirm this is the intended policy.
3. **LLM arm implementation:** FINAL-PLAN §3.10 requires 150 LLM-generated candidates across 30 incidents. Not yet implemented. When and how?
4. **Reference-derived topologies:** 4 of 20 topologies should be hand-derived (t11, t12, t15, t16 per manifest). Are these correctly implemented in `build_pilot_v2.py`?
5. **Multi-area/redistribution:** 4 topologies with second OSPF area or redistribution. Not yet visible in topology list.

### 16.2 Code Fixes Blocking Stage 3
6. **B1 fix priority:** Rewrite `verify_phase3.py` to be manifest-derived (expected set from lock + manifest + run_metadata + phase2 summary). This is a **hard blocker** — without it, verification fails after 24h compute.
7. **B4 fix priority:** Modify `nrl/phase4.py` label mapping to exclude UNDETERMINED/EXECUTION_FAILED and compute Manski bounds.
8. **`spec_coverage` path semantics:** Fix ingress/egress classification before Stage 3 (affects Tier A+ features).
9. **Remove `--override-spike` and dead constants** per FINAL-PLAN §2.4.

### 16.3 Methodological Clarifications
10. **Effective n computation:** FINAL-PLAN §4.10 requires recomputing all power numbers on effective n after Stage 0. What is the current effective n estimate?
11. **ANALYSIS-PLAN.md:** FINAL-PLAN §10 requires this dated and committed **before Stage 1**. Does it exist? (Not found in repository)
12. **Harm definition v1.2.0 pre-registration:** Must be dated and committed before any v2 label exists. Is this documented?

### 16.4 Infrastructure
13. **WSL environment:** Stage 3 must run in WSL (`.venv-wsl`). Is the WSL environment set up with docker-ce (not Docker Desktop)?
14. **Containerlab image digests:** `run_phase3.py` captures IMAGE_DIGESTS at preflight. Are FRR_IMAGE and HOST_IMAGE pinned correctly?

---

## 17. SUMMARY: READINESS ASSESSMENT

| Component | Status | Ready for Stage 3? |
|-----------|--------|---------------------|
| Pilot-v2 Phase 1 (structure) | ✅ Complete, verified | Yes |
| Pilot-v2 Phase 2 (Batfish) | ✅ Complete, 804 PASS, verified | Yes |
| Golden/Spike validation | ✅ GO, 240/240 properties | Yes |
| Shortcut diagnosis | ✅ Done, AUC=0.999 documented | N/A (known threat) |
| LAB_INVALID policy | ✅ Implemented in `run_phase3.py` | Yes |
| **B1: verify_phase3.py rewrite** | ❌ **UNFIXED** | **NO** |
| **B2: Golden gate verification** | ⚠️ Partial (run-time only) | **NO** |
| **B3: FAIL controls flag** | ✅ Flag exists in `run_phase3.py` | Yes (when invoked) |
| **B4: Label mapping fix** | ❌ **UNFIXED** | **NO** |
| Code defects (spec_coverage, fallbacks, silent drops) | ❌ **UNFIXED** | **NO** |
| Git repository / frozen definitions tag | ❌ **NOT DONE** | **NO** |
| ANALYSIS-PLAN.md committed | ❌ **NOT FOUND** | **NO** |
| LLM arm / reference topologies | ❌ **NOT IMPLEMENTED** | Deferred to Stage 4 |

### Bottom Line
**Stage 3 cannot be executed until B1, B2, B4, and code defects are fixed, git is initialized with frozen definitions tagged, and ANALYSIS-PLAN.md is committed.** The Stage 1 validation proved the apparatus works; Stage 2 produced the 804-candidate PASS population; but the verification and labeling infrastructure for Stage 3 is not yet ready for the full pilot-v2 scale.

---

## 18. RECOMMENDED NEXT ACTIONS (In Order)

1. **`git init` + initial commit + tag `frozen-defs-v1.1.0`** (FINAL-PLAN §10, first action)
2. **Create and commit `docs/ANALYSIS-PLAN.md`** dated before any label exists (FINAL-PLAN §10)
3. **Fix B1:** Rewrite `verify_phase3.py` expected-run-set logic to be manifest-derived
4. **Fix B4:** Update `nrl/phase4.py` label mapping — exclude UNDETERMINED/EXEC_FAILED, compute Manski bounds
5. **Fix code defects:** `spec_coverage` path semantics, remove `spec or T2V1` fallbacks, remove `--override-spike`, remove dead constants, make leakage filter print exclusions
6. **Verify Tier A+ graph features** present in `meta.json` at build time
7. **Confirm transient telemetry** recording in `clab.py` / `run_phase3.py`
8. **Run Stage 0 gates** on rebuilt pilot-v2 (if any fixes change artifacts)
9. **Only then:** Execute Stage 1 validation on 2 topologies × 3 incidents (FINAL-PLAN §6)
10. **Then:** Stage 2 (full Phase 2 + 150 PASS stratified) per FINAL-PLAN §7

---

*This report reflects the repository state as of 2026-09-06. It documents what exists, what is verified, what is planned, and what blocks progress. No experiments were executed, no files modified, no data regenerated during this inspection.*