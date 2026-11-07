# Research history — why each arm ended as it did

Before relying on any claim below, read the cited source.

## 0. The original idea (never lose this)

**What Batfish gives.** Batfish verifies a proposed configuration change against specified properties
(PASS/FAIL).

**The gap.** Several candidate repairs can all PASS, yet behave differently when executed.

**Research question.** *When Batfish says PASS, how confident should we be that the change is actually safe when
executed in a real or emulated network?*

**ML task.** A calibrated residual risk **P(HARM | Batfish PASS, pre-deployment evidence)**.
- **Use:** a ranking and prioritization signal among Batfish-PASS candidates (A 5 %, B 75 %, C 70 % → prefer A).
- **Not:** a replacement for Batfish.
- **Ground truth:** execution in Containerlab/FRR, never the assumption that PASS means safe.

**Sources:**
- `docs/RESEARCH-PLAN-v2.md`, `docs/FINAL-PLAN.md`, `docs/HARM-DEFINITION.md`, `docs/LEAKAGE.md`
- `RESEARCH_STATE_REPORT.md`, `docs/PROJECT-HANDOFF.md`
- the hostile-review docx in `docs/`

## 1. V1 / V2 — residual-harm arm (`data/pilot-v1`, `data/pilot-v2`, `docs/ANALYSIS-PLAN.md`)

**Design.** Candidate repairs for injected incidents:
1. Batfish verdicts on a golden property suite.
2. Containerlab/FRR execution as ground truth for harm.
3. Learn P(harm | PASS, pre-deployment features).

**Stage 1** (`docs/STAGE1-REPORT.md`, `RESEARCH_STATE_REPORT.md` §2, §5):
- the apparatus met 6/7 GO criteria;
- **repair_class predicted the label with AUC ≈ 0.999**, a generator-provenance shortcut.

**Stage 2 and leakage.** Stage 2 and the leakage machinery (`STAGE2-VERIFICATION-REPORT.md`, `docs/LEAKAGE.md`,
`check_leakage.py`) banned provenance features from X.

**Verdict** (2026-09-11, `analysis/interim`; summarized in `docs/V4-PIVOT-AND-EXPANSION-PLAN.md` §3, §8, and in
`docs/ANALYSIS-PLAN-V3.md` §422 "that is the v2 arm, and its verdict is NO-GO"):
- **BAD — SHORTCUT-ONLY.**
- ML exploited generator, configuration, repair-class and spec-completeness signals, not operational harm.
- **V2 is not evidence for the original hypothesis.**

**Lessons carried forward:**
- ban provenance features and derived shortcuts;
- report a shortcut-only model beside the full model;
- split by group (topology);
- verify the Batfish gate on the actual corpus.

## 2. V3 — steady-state blast radius (`docs/ANALYSIS-PLAN-V3.md`, `data/pilot-v3`, `analysis/v3_*`)

**Question.** Among changes passing the Batfish SPEC gate, predict the blast radius
**r = (broken + rerouted) / golden-carried flows**.

**Corpus.** 151 candidates on 12 ECMP-free topologies, 151/151 SPEC-PASS. The amendments are 12.1–12.4 in Git
history; the final gates are commit `6efbdb0`.

**Decisive finding** (`docs/V4-PIVOT-AND-EXPANSION-PLAN.md` §17, §22; `analysis/v3_expansion_planning/batfish_computes_r.*`;
`analysis/v3_claude_final/FINAL-CLAUDE-V3-AUDIT.md`):
- r is computed **exactly** from the Batfish RIB and forwarding model, and from the analytic `nrl/severity.Fabric`.
- A mechanism × P06 lookup already reaches R² 0.794.
- The learned increment was +0.054 with a CI touching 0.
- Tier C failed calibration.

**Conclusion.** "ML reproduces, less accurately, a quantity the verifier computes exactly." V3 was stopped.
**V3 is not ML evidence.**

**Lesson.** Always test whether the target is analytically reconstructable before learning it. A high R² on a
computable target is a warning, not a result.

## 3. V4 — transient disruption (`v4_transient/`, `docs/V4-PIVOT-AND-EXPANSION-PLAN.md` §23–§43)

**Question.** Can pre-deployment evidence predict **transient** traffic disruption during convergence after a
Batfish-SPEC-PASS change?

**Target T1** (prereg §1):
- the integral over time of broken_excess(t);
- broken_excess(t) = the fraction of golden-carried flows that are BROKEN (NO_ROUTE/LOOP/BLACKHOLE) at t but not
  broken in the final state.

**Why it could be outside the verifier.** Steady-state damage is subtracted by construction. What remains depends on
convergence dynamics and event ordering. The whole value of V4 rests on showing that T1 is:
- measurable (G1/D2);
- repeatable (G3/D3);
- host-stable (G4/D4);
- NOT reducible to the analytic baseline (G2/D5);
- affordable (G5/D6);
- measured by an instrument that sees a known disruption (D9).

**Stage 1 pilot.** A feasibility pilot with kill gates, preregistered; the design and chronology are in
`references/v4-current-state.md`.

## 4. Cross-cutting principles learned the hard way

1. **Shortcut / provenance leakage** can fake prediction (V2).
2. **Analytic reducibility** can make ML redundant (V3).
3. **Instrument blind spots** can fake zeros. V4 audit B1: the kernel flushes routes on link down without events.
4. **Engineering validity is not control validity.** The previous Claude GO (2026-09-15) passed every engineering
   check while two positive controls showed zero signal.
5. **Amendments made after data exist** must say so. Git commits are the only independent chronology anchors;
   V4 history before `399b39b` rests on file hashes and timestamps.
