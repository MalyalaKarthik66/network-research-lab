# V4 readiness audit checklist

For every item, record **evidence** (a file path, command output or line reference) and one verdict: PASS, FAIL or
UNVERIFIED. Any FAIL or UNVERIFIED on a launch condition (§L) means FINAL NO-GO.

## A. Scientific question
- The implementation measures **transient** disruption (T1), not steady-state r.
  - broken_excess must subtract the final state (`v4lib/targets.py`).
  - r is used only as an instrument-validity check.
- The question has not drifted back to V2 residual-harm labels or to V3 blast radius.

## B. Preregistration and amendments
- Read prereg §0–§20 and every §18 amendment row.
- For each rule, state whether it was original, an amendment (with date and commit), or undocumented.
- **Look for changes made after data existed:**
  - smoke 1 existed before D1–D9;
  - smoke-2 values existed before any post-A3 amendment.
- Any amendment written after seeing smoke values must say so.
- Git history must be linear and unrewritten. Hashes in `PREREG-APPROVAL.json` and `PILOT-FREEZE.json` must match
  the files.

## C. D1–D9 in code (`v4lib/gates.py`, `config/pilot_decisions.json`, tests)
- **All gates:** thresholds, inequality direction and strictness, denominators, missing data, invalid runs,
  NOT_EVALUABLE → NO-GO.
- **D1:** pooled no-op maximum, the 6.944e-4 lower bound, replicate median, strict `>`.
- **D2:** denominator = all 20; D7-ineligible changes count as not above.
- **D3:** the variance formula (MSW, MSB, n0), the 0.50 threshold, the zero clauses.
- **D4:** untested, capped. GO must be unreachable.
- **D5:** check each of these:
  - LOTO folds by topology only;
  - OLS fitted on training folds only;
  - maximum over B2–B6 (selection optimism biases toward KILL, the conservative direction);
  - a baseline that exactly or nearly reconstructs T1;
  - leakage of test-topology information into features;
  - point estimate ≥ 0.80 kills.
- **D6:** median over population final attempts, `> 180`; the threshold is never changed.
- **D7/D8:** ≥ 4/5 per change; ≥ 90 % of planned runs, where NOT_RUN counts as invalid.
- **D9:** 4/4 valid AND above the floor; invalid counts as not above.
  - **Verify controls demonstrate the intended signal** (see §D9 below).

## D9. Positive-control investigation (mandatory while the smoke-2 zeros are unexplained)
1. **Recompute in memory** (no writes) with `analysis/extract_runs.extract(adir, run.json, change)` for every
   smoke-2 positive control. Compare T1, T2, the timeseries and the diagnostics with `SMOKE2-VALIDATION.json`.
2. **Read the event sequences** in the raw monitor logs, per router, around the link event: link down, route
   deletes and adds, nexthop events, timestamps.
3. **Replay step by step** and list every state's broken_excess, and which flows are broken in golden, transient
   and final states.
4. **Cross-check** the `fib_polls.json` dumps and `ospf_neighbours.json`.
5. **Test each hypothesis** in `v4-current-state.md` §5 and classify the cause:
   - implementation bug;
   - invalid positive-control construction;
   - topology/mechanism interaction;
   - genuine zero.
6. **If a real bug:** fix it, add a regression test, rerun engineering validation, log an amendment, re-approve and
   re-freeze.
7. **If the construction is invalid:** document the mechanism, propose the minimum amendment for user approval,
   and never pick a replacement by its measured T1 alone.
8. **If a genuine zero:** NO-GO. Never lower the floor or change T1.

## E. Target and instrument
Check each of:
- t0 = the first push start;
- pre-change events invalidate the run;
- no events after t_end;
- piecewise-constant integration;
- the settle rule;
- the observation window;
- the final state equals the replay end state;
- the golden carried count equals the analytic count.

Check the kernel semantics coverage:
- admin down;
- carrier loss;
- nexthop objects;
- ECMP members;
- blackhole;
- linkdown flags.

Checks 1–13 must all be implemented and tested (`tests/test_core.py`, `tests/test_smoke_regression.py`,
`audit/2026-09-15-instrument-unit-checks/`).

Look for silent-change blind spots and cross-router timestamp artefacts (compare T1 with T1_merge10ms).

## F. Experimental design
Check each of:
- 4 topologies × 5 roles, balanced;
- mechanism crossed with topology;
- seeded shuffled order;
- controls isolated from the population (`kind` filters);
- the replicate estimand (§20) matches what G3 measures;
- the selection at analytic extremes limits prevalence claims.

## G. Features and leakage
- Every column in `analytic.FEATURE_COLUMNS` is computable from configurations before deployment.
- Mechanism is a function of the config diff.
- No IDs, role, order, topology name, telemetry, timing, measured targets, predictions, repair class or fault family
  in X.
- ML never enters the decision.

## H. Statistics
Check each of:
- pooled LOTO R²;
- the change-level bootstrap (whole changes resampled);
- permutation Spearman;
- variance components with unequal k;
- edge cases (zero variance, too few rows).

No procedure may be silently substituted for the preregistered one.

## I. Execution and retries
Check each of:
- the Batfish gate (population and no-op PASS, positives FAIL, r_match);
- the artifact lock;
- cleanup and teardown;
- the clean-host guard;
- LAB_INVALID and NO_CONVERGENCE handling;
- no retry after `change_applied`;
- attempts preserved;
- INCOMPLETE vs INCOMPLETE_AFTER_CHANGE.

Also: the convergence timeout overrun. It is operational, but it matters for duration.

## J. Runtime (G5)
- Break wall time into phases for smoke 1 and smoke 2 (`run.json`: deploy, convergence_wall_s, observation_s,
  remainder).
- Project the pilot's median against 180 s.
- Diagnose only; never re-threshold.

## K. Isolation, freeze and provenance
Run each of:
- `git diff --name-status 6efbdb0 HEAD` shows no V2/V3 path modified;
- `git diff --quiet HEAD -- data nrl pipeline`;
- `tests/test_evidence_preserved.py`;
- `validate_smoke.py --no-write`.

Freeze checks:
- `v4lib/freeze.verify` passes on BOTH Windows and WSL;
- the freeze covers all executing and analysis code, the nrl dependencies, config, manifests and artifacts;
- the register is well-formed.

**A passing freeze proves only that the frozen state is intact. It does not prove that state is scientifically
ready.**

## L. Launch conditions (ALL required for FINAL GO)
1. Every offline suite passes, and preserved smoke 1 validates (89/89).
2. Approval, freeze and the clean host verify in WSL. The runner refuses without the token (exit 2).
3. V2/V3 are untouched; smoke evidence is unchanged; the Git tree is clean at a committed, frozen state.
4. The instrument is validated on every mechanism and control type in engineering runs, with no unexplained
   validity or replay failure.
5. **Every positive-control type demonstrably produces the intended transient signal**, or a logged, user-approved
   amendment resolves why not and is revalidated. Unexplained zeros → NO-GO.
6. No known blocker predetermines the pilot outcome through an instrument or design defect: D9 by construction,
   systematic invalidity, or an impossible D8.
7. Every amendment is documented honestly, with its timing relative to the data that existed when it was written.
8. No threshold, target, population or feature was changed after seeing outcomes without disclosure and a
   scientific justification.
9. The G5 runtime risk is diagnosed and disclosed to the user. G5 itself is decided only by the pilot.

## M. Publication validity (report, even if GO)
Report on each of:
- which claims the pilot can support (`v4_transient/docs/V4-PAPER-READINESS.md`);
- the residual threats: single host, 4 topology clusters, designed population, FIB-level loss rather than packet
  loss;
- whether a NO-GO would be reported honestly as a negative result.

End with exactly `FINAL GO` or `FINAL NO-GO`.
