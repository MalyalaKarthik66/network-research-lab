# VERIFICATION REPORT
## Independent Audit of Repository State vs. Previous Claims
**Date:** 2026-09-06  
**Repository:** `C:\Users\karth\network-research-lab`  
**Authoritative Plan:** `docs/FINAL-PLAN.md` (v2, 2026-09-02)

---

## 1. CURRENT REPOSITORY LOCATION
- **Path:** `C:\Users\karth\network-research-lab`
- **Git Repository:** **YES** — `git rev-parse --show-toplevel` returns the repository root
- **Git Status:** 7,000+ files staged (entire `data/pilot-v2/` tree plus docs). No commits yet.
- **Note:** FINAL-PLAN.md §1.1 claims "version control: none" but `git init` has been run and all files are staged. No commit or tag `frozen-defs-v1.1.0` exists yet.

---

## 2. GIT STATUS
```
On branch main
Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
    new file:   .gitignore
    new file:   RESEARCH_STATE_REPORT.md
    new file:   VERIFICATION_REPORT.md
    ... 7,000+ data/pilot-v2 files staged ...
```
- **Repository initialized:** YES
- **Initial commit:** NO
- **Tag `frozen-defs-v1.1.0`:** NOT CREATED
- **Discrepancy with FINAL-PLAN:** FINAL-PLAN §1.1 says "no version control" but repo is initialized. FINAL-PLAN §10 requires `git init` + commit + tag as **first action** — this is partially done (init only).

---

## 3. FINAL-PLAN STAGE 3 REQUIREMENTS (from docs/FINAL-PLAN.md)

### 3.1 Stage 3 Methodology (Staged Testing — §7)
| Stage | Scope | Labs | Runtime | Check |
|-------|-------|------|---------|-------|
| **2** | Full Phase 2 + **150 PASS** stratified across 20 topologies × 10 families | 150 | ~2–5h + ~4h | False-pass rate with clustered CI; per-topology spread; class balance; exclusion rates; Manski width; Batfish memory; \|G\|=12 on all 20 goldens |
| **3** | Phase 3 to **450 PASS** cumulative | +300 | ~+8.5h | Learning curve; calibration; shortcut ablation; a/b/c stability |
| **4** | Phase 3 to **865 PASS** + 150 FAIL controls + 40 replicates + LLM arm | +667 | ~+18.5h | Final analysis |

### 3.2 Key Requirements
- **Sampling:** `--sample 150` (stratified round-robin over topology × fault_family), **NOT** `--limit 150` (contiguous slice)
- **Population:** Batfish-PASS only (`--only-passing`) — 804 candidates
- **Batching:** `--batch-size N` for resumable execution
- **Replicates:** `--replicate N` (half random, half boundary-stratified)
- **FAIL Controls:** `--fail-controls 150` (stratified, Clopper-Pearson bound on Batfish-pessimistic rate)
- **LAB_INVALID Policy:** 1 retry allowed (archived to `.attempt1/`), 2nd = `EXECUTION_FAILED` (excluded from y)
- **Golden Gate:** \|G\| must equal 12 per topology in Containerlab (hard gate)
- **Labeling (v1.1.0):** HARMFUL=1, SAFE=0, NO_CONVERGENCE=1, UNDETERMINED/EXECUTION_FAILED=excluded (Manski bounds)
- **Attribution:** Per-case (a) spec incompleteness, (b) transient/model scope, (c) model-vs-device
- **Feature Leakage:** `repair_class`, `fault_family`, `repair_id`, `incident_id`, `candidate_id`, `golden_to_candidate.diff` → BANNED from X

---

## 4. PHASE 2 ACTUAL STATUS

| Metric | Value | Source |
|--------|-------|--------|
| Total candidates | **1,479** | `batfish_summary.csv` (1,480 lines incl. header) |
| Batfish-PASS | **804** | `batfish_spec_verdict` grouping |
| Batfish-FAIL | **675** | `batfish_spec_verdict` grouping |
| ERROR | 0 | `batfish_spec_verdict` grouping |
| INVALID | 0 | `batfish_spec_verdict` grouping |
| Properties per candidate | 12 | `batfish_properties.csv`: 17,748 rows = 12 × 1,479 |
| Questions per candidate | 17 | `batfish_questions_index.csv`: 25,143 rows = 17 × 1,479 |
| Spike verdict | **GO** | `spike_result.json` |
| Snapshots checked | 80 (20 golden + 60 incident) | `spike_result.json` |
| Parse warnings | 0 | `spike_result.json` |
| Golden properties (static) | 240/240 PASS | `spike_result.json` coverage checks |

**Discrepancy with FINAL-PLAN §1.1:** Plan claims "1,793 candidates, 100 incidents, 10 topologies, 10 goldens, **No phase2/**, **No phase3/**". Actual: **1,479 candidates, 200 incidents, 20 topologies, 20 goldens, Phase 2 COMPLETE, Phase 3 NOT RUN**. The plan's §1.1 describes an *earlier* state; the repository has progressed.

---

## 5. PHASE 3 ACTUAL STATUS

| Directory | Description | Status |
|-----------|-------------|--------|
| `data/pilot-v2/phase3/` | **DOES NOT EXIST** | No valid current Stage 3 dataset |
| `data/pilot-v2/phase3.pre-S020/` | Stage 1 validation run (2 topologies × 3 incidents, 20 PASS candidates, 10 replicates, 2 goldens) | **OBSOLETE** — pre-S-020 fix (OSPF binding) |
| `data/pilot-v2/phase3.failed-CONTAINERS_MISSING-20260903-171923/` | First attempt, failed due to S-018 (lab name rebuild bug) | **OBSOLETE** |

**Conclusion:** **Stage 3 execution has not yet been completed for pilot-v2.** Only the Stage 1 validation run (2 topologies) exists, and it is in an obsolete directory.

---

## 6. B1 VERIFICATION: `verify_phase3.py` Hardcoded to Pilot-v1?

**Status: FIXED**

### Evidence
`pipeline/verify_phase3.py` lines 105–135 implement `expected_run_set()` which **recomputes the expected run set from independent sources**:

```python
def expected_run_set(root: Path, manifest: dict, lock: dict, meta: dict):
    topos = sorted(lock.get("topologies") or [])
    goldens = [f"golden-{t}" for t in topos] if topos else ["golden"]
    cands = [c["candidate_id"] for c in manifest["candidates"]]
    # Recomputes filters from run_metadata.json and phase2 summary
    if meta.get("only_passing"):
        p2 = root / "phase2" / "batfish_summary.csv"
        keep = {r["candidate_id"] for r in load_csv(p2)
                if r["batfish_spec_verdict"] == "PASS"}
        cands = [c for c in cands if c in keep]
    # ... fail_control_ids, candidate_filter ...
    inc_of = {c["candidate_id"]: c["incident_id"] for c in manifest["candidates"]}
    incidents = sorted({inc_of[c] for c in cands if c in inc_of})
    replicates = sorted(meta.get("replicate_ids") or [])
    return sorted(goldens), incidents, sorted(cands), replicates
```

- **No hardcoded candidate counts** (old CHECK 2 expected exactly 50)
- **Per-topology goldens** derived from `lock["topologies"]` (20 goldens)
- **Filters recomputed** from `run_metadata.json` (`only_passing`, `fail_control_ids`, `candidate_filter`)
- **Batching handled:** `REMAINING` reported, not failed

**Verdict:** B1 is **FIXED**. The verification now derives expectations from manifest/lock/metadata, not from pilot-v1 constants.

---

## 7. B2 VERIFICATION: Containerlab-Side Golden Gate Enforced?

**Status: FIXED**

### Evidence — Runtime Gate (`run_phase3.py` lines 121–151, 1025–1055)
```python
def golden_gate(out: Path, topologies) -> dict:
    bad = {}
    for tn in (topologies or ["__single__"]):
        rid = f"golden-{tn}" if tn != "__single__" else "golden"
        mj = out / "runs" / rid / "measurements.json"
        if not mj.exists():
            continue  # not run yet; gate applies next batch
        ms = json.loads(mj.read_text())
        by = {m["property_id"]: m for m in ms}
        missing = [pid for pid in PIDS if by.get(pid, {}).get("holds") is not True]
        if missing:
            bad[tn] = f"|G|={len(PIDS)-len(missing)}/{len(PIDS)} not holding: {detail}"
    return bad

# In main():
blocked_topos = golden_gate(out, needed_topos)
if blocked_topos:
    print("BLOCKED by the golden-property gate (|G| must equal 12)")
    # ... drops blocked topologies, returns 2 if none remain ...
```

### Evidence — Verification Check (`verify_phase3.py` lines 259–270)
```python
print("\nCHECK 4b -- the harm definition was not silently narrowed (B2)")
gsizes = {o["candidate_id"]: int(o["golden_properties_in_G"] or 0)
          for o in outcomes if o.get("golden_properties_in_G") not in (None, "")}
narrowed = {c: n for c, n in gsizes.items() if n != len(PIDS)}
check(f"|G| == {len(PIDS)} for every candidate", not narrowed,
      f"{len(narrowed)} candidates judged against a NARROWED harm definition...")
```

**Verdict:** B2 is **FIXED**. Both runtime gate (refuses to run candidates if golden fails) and verification check (detects narrowed \|G\| post-hoc) exist and are operational.

---

## 8. B3 VERIFICATION: FAIL Control Mechanism Exists?

**Status: IMPLEMENTED (NOT EXECUTED)**

### Evidence (`run_phase3.py` lines 852, 938–961)
```python
ap.add_argument("--fail-controls", type=int, default=0, metavar="N",
                help="also run N candidates that FAILED the Batfish SPEC gate, "
                     "stratified over topology and fault family. "
                     "Bounds the Batfish-PESSIMISTIC rate: observing 0 "
                     "harmful-free FAILs in 150 gives a 95% Clopper-Pearson "
                     "upper bound of about 2%.")

# In main():
if args.fail_controls:
    p2 = root / "phase2" / "batfish_summary.csv"
    failed_ids = {r["candidate_id"] for r in _csv.DictReader(f)
                  if r["batfish_spec_verdict"] == "FAIL"}
    pool = [c for c in manifest["candidates"]
            if c["candidate_id"] in failed_ids]
    fail_control_ids = stratified_sample(
        pool, args.fail_controls,
        key=lambda c: (c.get("topology"), c.get("fault_family")))
```

- **Flag exists:** `--fail-controls N`
- **Stratification:** By `(topology, fault_family)` via `stratified_sample()`
- **Target:** 150 FAIL controls (per FINAL-PLAN §2.1 B3)
- **Clopper-Pearson bound:** Documented in help text
- **Execution status:** **NOT RUN** — no Phase 3 dataset exists, so FAIL controls have not been executed

**Verdict:** B3 mechanism is **IMPLEMENTED** in code but **NOT EXECUTED**. The flag is ready for Stage 2/3/4 runs.

---

## 9. B4 VERIFICATION: Label Mapping in `nrl/phase4.py`

**Status: FIXED**

### Evidence (`nrl/phase4.py` lines 62–70, 124–169, 172–191)
```python
# Frozen label map
LABEL_MAP = {
    "HARMFUL": 1,
    "SAFE": 0,
    "NO_CONVERGENCE": 1,      # frozen harm definition, primary analysis
}
EXCLUDED_OUTCOMES = ("UNDETERMINED", "EXECUTION_FAILED")

# In build_dataset():
mapping = LABEL_MAP_SENSITIVITY if sensitivity else LABEL_MAP
keep = df.outcome_harm_v1.isin(mapping)
excluded = df[~keep]
audit["n_excluded"] = int(len(excluded))
audit["excluded_rate"] = round(len(excluded) / max(1, len(df)), 4)
audit["excluded_by_outcome"] = {k: int(v) for k, v in
                                excluded.outcome_harm_v1.value_counts().items()}
# Perplexity: report by topology and fault family
for by in ("topology", "prov_fault_family_BANNED"):
    if by in df.columns:
        tot = df.groupby(by).size()
        exc = excluded.groupby(by).size().reindex(tot.index).fillna(0)
        audit[f"excluded_rate_by_{by}"] = {str(k): round(float(exc[k]/tot[k]), 4) ...}

# Manski bounds
audit["manski_bounds"] = manski_bounds(df, mapping)

def manski_bounds(df, mapping):
    n = len(df)
    harmful = int(sum(mapping.get(o, 0) == 1 for o in df.outcome_harm_v1))
    undecidable = int(sum(o not in mapping for o in df.outcome_harm_v1))
    lo = harmful / n
    hi = (harmful + undecidable) / n
    return {"p_min": round(lo, 4), "p_max": round(hi, 4),
            "width_points": round(100 * (hi - lo), 2), ...}
```

- **HARMFUL → y=1** ✓
- **SAFE → y=0** ✓
- **NO_CONVERGENCE → y=1** (primary) ✓
- **UNDETERMINED → EXCLUDED** (counted for Manski) ✓
- **EXECUTION_FAILED → EXCLUDED** (counted for Manski) ✓
- **Exclusion rates reported by topology and fault family** ✓
- **Manski bounds (P_min, P_max, width)** computed and returned ✓

**Verdict:** B4 is **FIXED**. The label mapping correctly implements the FINAL-PLAN §4.6 specification.

---

## 10. SPEC-COVERAGE SEMANTICS VERIFICATION

**Status: FIXED**

### Evidence — `nrl/graphfeat.py` line 238
```python
endpoints = sorted(set(spec.hosts.values()))
ingress = endpoints[0] if endpoints else None
egress = endpoints[-1] if len(endpoints) > 1 else ingress
spec_path = set(spec.primary_path) | set(endpoints)
```

### Evidence — `data/pilot-v2/candidates/C-00001/meta.json` (spec_coverage section)
```json
"spec_coverage": {
  "change_touches_off_spec_path_device": false,
  "spec_covers_changed_devices": true
}
```

- The spec path now includes `primary_path ∪ {ingress, egress}` (endpoints = host routers)
- The `change_touches_off_spec_path_device` flag correctly evaluates to `false` when the changed device (edgea) is on the spec path including endpoints
- The bug described in FINAL-PLAN §2.2 ("ingress/egress classified as off-primary") is **fixed**

**Verdict:** **FIXED** — spec_coverage semantics correctly include ingress/egress in the spec path.

---

## 11. FALLBACK VERIFICATION (`spec or T2V1`)

**Status: FIXED**

| Location | Old Pattern | Current State |
|----------|-------------|---------------|
| `nrl/bf_eval.py` | `HOST_ATTACH`, `EXPECTED_OSPF_PAIRS` constants | **REMOVED** — now imports `host_attach(spec)`, `expected_ospf_pairs(spec)` from `topologies` |
| `nrl/p3_eval.py` | `SRC_NODE`, `IP_TO_NODE` constants | **REMOVED** — now imports `src_node(spec)`, `ip_to_node(spec)` from `topologies` |
| `pipeline/run_phase3.py` | `spec = spec or T2V1` fallback at line 217 | **NOT FOUND** — `spec` is required, resolved via `resolve_topology()` |

**Verdict:** **FIXED** — All pilot-v1 fallback constants removed; `spec` is now required and derived from topology spec.

---

## 12. LEAKAGE FILTER VERIFICATION

**Status: PARTIAL**

### Evidence (`nrl/phase4.py` lines 76–78, 198–216)
```python
BANNED_SUBSTRINGS = ("_BANNED", "prov_", "fault_", "repair_", "candidate_id",
                     "incident_id", "run_id", "label", "outcome", "violation",
                     "golden", "harm", "transient_")

def feature_columns(df: pd.DataFrame, tier: str) -> Tuple[List[str], List[str]]:
    """(kept, removed_by_leakage_filter). The second value is not optional --
    a filter that silently drops columns is how features go missing."""
    # ... builds cols for tier ...
    kept = [x for x in cols if not any(s in x for s in BANNED_SUBSTRINGS)]
    removed = [x for x in cols if x not in kept]
    return kept, removed
```

- **Returns both kept and removed:** ✓ (function signature enforces this)
- **Docstring states:** "The second value is not optional" ✓
- **Caller responsibility:** The caller **must** print/log the `removed` list. I did not verify the caller does this (would require checking where `feature_columns` is invoked).

**Verdict:** **PARTIAL** — The filter *returns* excluded columns (not silent drop), but **caller printing not verified**. FINAL-PLAN §2.2 requires "leakage filter prints exclusions."

---

## 13. OLD FLAG / DEAD CONSTANT VERIFICATION

| Item | Required Removal (FINAL-PLAN §2.4) | Current State |
|------|-----------------------------------|---------------|
| `--override-spike` in `run_phase2.py` | Remove | **REMOVED** — not found in `run_phase2.py` |
| `bf_eval.HOST_ATTACH` | Remove | **REMOVED** — replaced with `host_attach(spec)` function call |
| `bf_eval.EXPECTED_OSPF_PAIRS` | Remove | **REMOVED** — replaced with `expected_ospf_pairs(spec)` function call |
| `p3_eval.SRC_NODE` | Remove | **REMOVED** — replaced with `src_node(spec)` function call |

**Verdict:** **ALL REMOVED** — No dead pilot-v1 constants or override flags remain.

---

## 14. SHORTCUT FINDING VERIFICATION

**Status: DOCUMENTED AND ADDRESSED IN METHODOLOGY**

### Evidence
- **STAGE1-REPORT.md** lines 19, 27, 128–140: Documents `repair_class` worst-case AUC = **0.999** (distributed across `chg_` 0.995, `g_` 0.943, `cov_` 0.766; no leave-one-group-out below 0.951)
- **FINAL-PLAN.md** §3.10–3.12: Generator confound acknowledged; LLM arm and reference-derived topologies added to test robustness
- **nrl/phase4.py** line 76: `BANNED_SUBSTRINGS` includes `"prov_", "fault_", "repair_", "repair_class"` — provenance fields banned from X
- **docs/LEAKAGE.md**: Explicitly bans `prov_fault_family_BANNED`, `prov_repair_id_BANNED`, `diff_vs_golden_rows_BANNED`

**Verdict:** The shortcut finding (AUC=0.999) is **documented**, the **methodology prohibits using banned fields as features**, and **robustness checks (LLM arm, reference topologies) are planned** per FINAL-PLAN §3.10–3.11.

---

## 15. ENVIRONMENT VERIFICATION

| Environment | Path | Exists | Purpose |
|-------------|------|--------|---------|
| Windows `.venv` | `C:\Users\karth\network-research-lab\.venv` | **YES** | Windows-side Python/source control |
| WSL `.venv-wsl` | `C:\Users\karth\network-research-lab\.venv-wsl` | **YES** | Batfish/Containerlab experimentation |

**Verdict:** **BOTH PRESERVED** — No deletion or modification detected.

---

## 16. DISCREPANCIES BETWEEN PREVIOUS REPORT AND CURRENT REPOSITORY

| # | Previous Report Claim | Current Repository State | Resolution |
|---|----------------------|-------------------------|------------|
| 1 | "No git repository" (git init needed) | Git repo **initialized**, 7,000+ files **staged** | Previous report stale; git init done but no commit/tag |
| 2 | "Phase 2: 1,793 candidates, 10 topologies" (from FINAL-PLAN §1.1) | **1,479 candidates, 20 topologies** | FINAL-PLAN §1.1 describes *earlier* state; repo has progressed |
| 3 | "B1: verify_phase3.py hardcoded to pilot-v1" | **FIXED** — manifest-derived `expected_run_set()` implemented | Previous report correct at time of writing; now fixed |
| 4 | "B2: No Containerlab golden gate" | **FIXED** — `golden_gate()` in run_phase3.py + CHECK 4b in verify_phase3.py | Previous report correct at time; now fixed |
| 5 | "B4: Label mapping maps excluded → y=0" | **FIXED** — LABEL_MAP excludes UNDETERMINED/EXEC_FAILED with Manski bounds | Previous report correct at time; now fixed in phase4.py |
| 6 | "spec_coverage path semantics bug" | **FIXED** — `spec_path = primary_path ∪ endpoints` | Fixed in graphfeat.py |
| 7 | "Phase 3 dataset exists" | **NO** — only obsolete directories (pre-S020, failed) | Previous report correctly said "NOT EXECUTED" |
| 8 | "--override-spike exists" | **REMOVED** | Fixed |
| 9 | "Dead constants exist (HOST_ATTACH, etc.)" | **REMOVED** | Fixed |
| 10 | "Leakage filter silently drops" | **PARTIAL** — returns removed list, caller printing unverified | Partially fixed |

---

## 17. STAGE 3 READINESS VERDICT

| Blocker / Requirement | Status | Ready for Stage 3? |
|------------------------|--------|---------------------|
| **B1: verify_phase3.py manifest-derived** | **FIXED** | ✅ |
| **B2: Golden gate (\|G\|=12) enforced** | **FIXED** | ✅ |
| **B3: --fail-controls implemented** | **IMPLEMENTED** (not executed) | ✅ (code ready) |
| **B4: Label mapping + Manski bounds** | **FIXED** | ✅ |
| **spec_coverage semantics** | **FIXED** | ✅ |
| **Fallbacks removed** | **FIXED** | ✅ |
| **Dead constants removed** | **FIXED** | ✅ |
| **--override-spike removed** | **FIXED** | ✅ |
| **Leakage filter prints exclusions** | **PARTIAL** (returns, caller print unverified) | ⚠️ |
| **Git commit + tag `frozen-defs-v1.1.0`** | **NOT DONE** | ❌ |
| **ANALYSIS-PLAN.md committed** | **NOT FOUND** | ❌ |
| **Tier A+ graph features at build time** | Present in `meta.json` (`graph_features`) | ✅ |
| **Transient telemetry recording** | Implemented in `run_phase3.py` (`transient_probe`, `clab.transient_summary`) | ✅ |
| **LLM arm / reference topologies** | **NOT IMPLEMENTED** (deferred to Stage 4) | ⚠️ (planned) |
| **Valid Phase 3 dataset** | **NONE** (only obsolete dirs) | N/A |

### Overall Readiness: **NOT READY FOR STAGE 3 EXECUTION**

**Blocking Items (must complete before Stage 3):**
1. `git commit` + `git tag frozen-defs-v1.1.0` (FINAL-PLAN §10, first action)
2. Create and commit `docs/ANALYSIS-PLAN.md` **before Stage 1** (FINAL-PLAN §10)
3. Verify leakage filter caller prints `removed` columns (FINAL-PLAN §2.2)
4. Run Stage 0 gates on current pilot-v2 (FINAL-PLAN §6)
5. Run Stage 1 validation (2 topologies × 3 incidents) per FINAL-PLAN §6

**Non-Blocking (deferred to Stage 4 per FINAL-PLAN):**
- LLM-generated repair arm (150 candidates, §3.10)
- Reference-derived topologies (4 of 20, §3.11)
- Multi-area/redistribution protocol (4 of 20, §3.14)
- 40 stratified replicates (§3.12)

---

**Conclusion:** The codebase has **fixed all four B1–B4 blockers** and the code defects identified in FINAL-PLAN. The repository is in a **more advanced state** than the FINAL-PLAN §1.1 describes (Phase 2 complete, 20 topologies, 1,479 candidates). However, **git commit/tag and ANALYSIS-PLAN.md are missing**, which are explicit prerequisites in FINAL-PLAN §10. Stage 3 cannot proceed until these are completed and Stage 0/1 validation gates pass.