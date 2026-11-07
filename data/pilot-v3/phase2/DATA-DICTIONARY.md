# Phase 2 data dictionary

Everything Batfish said about the 50 candidates. **No labels, no risk scores, no
research target.** Phase 4 does cleaning, feature selection and leakage analysis;
this phase only records.

Every field is tagged with one of four **classes**:

| Class | Meaning |
|---|---|
| **CONFIG** | configuration / topology information |
| **VERIFY** | a Batfish verification result |
| **META** | run metadata — how and when it was collected |
| **EVIDENCE** | the supporting detail behind a verdict |

and one **X-eligibility**:

| Eligibility | Meaning |
|---|---|
| **OK** | may be used as a model input |
| **BANNED** | must never enter X — see `docs/LEAKAGE.md` |
| **KEY** | join key / identifier, not an input |

---

## Files

| File | Grain | Purpose |
|---|---|---|
| `batfish_summary.csv` | one row per candidate (50) | the browsable overview |
| `batfish_properties.csv` | one row per (candidate, property) (600) | long format, one verdict per row |
| `batfish_questions_index.csv` | one row per (candidate, question) (850) | which questions ran, how long, row counts |
| `run_metadata.json` | one object | versions, platform, spike verdict, timings |
| `spike_result.json` | one object | the compatibility gate's verdict |
| `raw/<CID>/record.json` | one per candidate | the merged record, exactly as written |
| `raw/<CID>/questions/<q>.json` | 17 per candidate | **complete** DataFrame of every question, as records |
| `raw/<CID>/properties.json` | one per candidate | full evaluation incl. hop-by-hop traces |
| `raw/<CID>/differential.json` | one per candidate | differentialReachability vs incident and vs golden |

Nothing in `raw/` is summarised or truncated. The CSVs are rollups **of** it, not
replacements **for** it. Parquet is deliberately not used: it would add a
`pyarrow` dependency to the venv for no benefit at this size.

---

## batfish_summary.csv

### Identifiers

| Column | Class | X | Notes |
|---|---|---|---|
| `candidate_id` | META | KEY | `C-0001`…`C-0050` |
| `incident_id` | META | KEY | the BEFORE state this repair responds to. **Group by this when splitting.** |
| `prov_fault_family_BANNED` | META | **BANNED** | generator provenance; predicts the label by construction |
| `prov_repair_id_BANNED` | META | **BANNED** | same |
| `batfish_snapshot_name`, `reference_snapshot_name` | META | KEY | names inside the Batfish service |

### Run status

| Column | Class | X | Notes |
|---|---|---|---|
| `run_status` | META | OK | `OK` / `DATAPLANE_ERROR` / `ERROR` |
| `run_error` | META | OK | exception text, or empty |
| `run_seconds` | META | OK | wall time for this candidate |
| `questions_errored` | META | OK | `;`-joined names of questions that threw |

### Parse health — CONFIG

`parse_files_total`, `parse_files_passed`, `parse_ok`, `parse_warning_rows`,
`init_issue_rows`, `undefined_reference_rows`, `unused_structure_rows`,
`defined_structure_rows`.

All X-eligible. `parse_warning_rows` matters more than it looks: every warning is
a line of configuration Batfish threw away, so a candidate with warnings is one
where the model and the running network already differ before anything else
happens.

### Modelled network — CONFIG

`nodes_parsed`, `interfaces_total`, `interfaces_active`, `ip_owner_rows`,
`layer3_edge_rows`, `route_rows`, `ospf_session_rows`,
`ospf_sessions_established`. All X-eligible.

### Verification result — VERIFY

| Column | X | Notes |
|---|---|---|
| `spec_n`, `spec_pass`, `spec_fail`, `spec_error` | OK | counts over the 5 SPEC properties |
| `batfish_spec_verdict` | OK | **the gate.** `PASS` / `FAIL` / `ERROR` / `INVALID` |
| `oracle_only_n/pass/fail/error` | OK | counts over the 7 oracle-only properties |
| `batfish_oracle_only_verdict` | OK | *analysis only* — in a real deployment nobody asked these |
| `verdict_P01` … `verdict_P12` | OK | per-property `PASS`/`FAIL`/empty |
| `status_P01` … `status_P12` | OK | per-property `OK`/`ERROR` |
| `loop_rows`, `multipath_inconsistency_rows`, `subnet_multipath_inconsistency_rows` | OK | VERIFY |

**The four verdict values are not interchangeable:**

- `PASS` — every SPEC property held. This is the false-pass **denominator**.
- `FAIL` — Batfish found a genuine SPEC violation.
- `ERROR` — the harness failed. Says nothing about the network. Exclude, don't count as FAIL.
- `INVALID` — the snapshot did not parse cleanly, so the verdict is meaningless.

Collapsing `ERROR` or `INVALID` into `FAIL` would turn infrastructure flakiness
into evidence about networks. `verify_phase2.py` CHECK 5 enforces the separation.

### Differential — VERIFY

| Column | X | Notes |
|---|---|---|
| `diff_vs_incident_rows`, `diff_vs_incident_status` | OK | flows whose fate changed vs the broken state. Legitimate: you have the current config and the proposed change at inference time. |
| `diff_vs_golden_rows_BANNED`, `diff_vs_golden_status` | **BANNED** | vs the healthy network. Collected for analysis; if you had the healthy config you would just deploy it. |

---

## batfish_properties.csv

One row per (candidate, property). `property_id`, `kind`, `in_spec`, `text`,
`status`, `verdict`, `error`, `counterexample_count`, `seconds`, `extra_json`.

`extra_json` is per-kind and deliberately unflattened — dispositions and path
node lists for reachability, observed vs expected OSPF pairs, which nodes are
missing a route, which interfaces are down. Class EVIDENCE, X-eligible after
Phase 4 decides how to encode it.

`verdict` is empty **if and only if** `status == "ERROR"`.

---

## batfish_questions_index.csv

One row per (candidate, question): `question`, `status`, `row_count`, `seconds`,
`error`, `columns`. An index into `raw/<CID>/questions/`, not a substitute for it.

---

## raw/&lt;CID&gt;/properties.json — EVIDENCE

The valuable part. For every reachability and path property it carries the
**full hop-by-hop trace**: every hop, every step, every action, plus the
disposition. The verdict is one bit; the trace explains it. When Phase 3
disagrees with Phase 2 about a candidate, this is what gets read.

---

## Known limits of this dataset

1. **Emulator-bound, and not even that yet.** Phase 2 is the static verifier only. Nothing here has been executed.
2. **The oracle-only verdicts are counterfactual.** Recording them lets Phase 4 separate "Batfish could not have known" from "nobody asked". They are not part of the gate and must not be treated as if an operator had them.
3. **The differential flow is one src/dst pair** (`10.10.0.10` → `10.20.0.0/23`). Anything outside that header space was never searched.
4. **Provenance columns are in the CSV for human browsing.** They carry `_BANNED` suffixes and `verify_phase2.py` CHECK 9 enforces the marking, but nothing stops `pd.read_csv().drop(columns=...)` being forgotten. Drop them at load time in Phase 4, once, in one place.
