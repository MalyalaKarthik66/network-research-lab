# External review prompts

Paste ONE of these into Perplexity Pro / Gemini Pro / ChatGPT, and attach both
`RESEARCH-PLAN-v2.md` and the summary message that accompanied it.

Use the **universal prompt** everywhere. Then append the **tool-specific block** for
whichever tool you are in. Bring all responses back for comparison.

---

## UNIVERSAL PROMPT

```
You are reviewing a research plan for a Computer Networks + machine learning paper written
by a 3rd-year undergraduate, targeting IEEE NOMS / CNSM / TNSM / IM. I am attaching (1) the
full design document and (2) the summary that accompanied it.

CONTEXT — the project in one paragraph:
Batfish is a formally sound static network configuration verifier: it proves the properties
it is asked about, over a converged-steady-state model of the configuration. The project
measures how often a configuration repair that PASSES a Batfish specification still causes
operational harm when actually executed in Containerlab (real FRRouting daemons, real
convergence). It then tries to predict that residual risk from pre-deployment features, and
to bound it with conformal risk control. The measured quantity is P(harm | verification
PASS). A pilot on one topology gave 50% (12 SAFE / 12 HARMFUL among 24 PASS candidates).
The v2 dataset is 10 topologies, 100 incidents, ~1,793 candidates.

YOUR ROLE:
Act as a hostile but fair reviewer for the target venue. Your job is to find what is WRONG,
not to encourage. Do not praise the plan. Do not summarize it back to me. Assume every
claim is unverified until you check it. If you agree with something, say so in one line and
move on; spend your output on disagreements.

Explicitly: I am NOT looking for validation. A response that mostly agrees is a failed
review. If you genuinely agree with everything, say that plainly and then argue the
strongest possible case AGAINST the plan anyway, so I can see what a real reviewer would
attack.

CHECK THESE SPECIFIC CLAIMS. For each, state AGREE / DISAGREE / UNCERTAIN, give your
reasoning, and rate severity (blocking / major / minor):

1. NOVELTY. The plan claims arXiv 2608.11340 "Self-evolving network verifiers" (Aug 2026)
   uses the same apparatus (differential testing of a symbolic verifier against Batfish and
   Containerlab-emulated FRR oracles) and therefore kills the claim "first to compare a
   model-based verifier against an emulator". Verify this paper exists and says that. Then
   search independently for ANY work that measures P(harm | verifier PASS), or that
   quantifies a disagreement rate between a static network verifier and an emulator or real
   devices. If such work exists, the project's first contribution is dead — tell me.

2. THE SURVIVING NOVELTY CLAIM. The plan says the defensible claims are: (a) first
   quantification of P(harm | verification PASS) across topologies and fault families; (b) a
   specification-completeness sweep separating recoverable from irreducible residual risk;
   (c) first application of conformal risk control to network change management; (d) an
   autonomy–risk curve. Is (c) actually true, or has conformal risk control already been
   applied in network operations? Is any of these too weak to carry a paper?

3. THE FATAL OBJECTION. The specification under test is 5 hand-written properties out of a
   12-property oracle. A reviewer will say the false-pass rate measures the weakness of a
   hand-written spec, not a property of verification — especially since Config2Spec (NSDI
   '20) mines near-complete specifications automatically. The plan's answer is a
   "specification-completeness sweep": recompute the false-pass rate for every subset of the
   oracle used as the spec, and plot rate vs spec size. Does that actually answer the
   objection? Is the sweep statistically valid given that the subsets are nested and
   non-independent, and that the same candidates appear in every subset's estimate? How
   should multiplicity and dependence be handled?

4. SAMPLE-SIZE ARITHMETIC. The plan argues a 10-bin reliability diagram is unachievable: for
   an observed harm rate within ±5 percentage points at 95% confidence near p=0.1 you need
   n≈138 per bin, so 10 bins needs ~1,380 evaluation candidates, implying ~6,900
   verification-PASS candidates and roughly 190 hours of emulator time. It therefore
   recommends 4 equal-frequency bins plus a continuous reliability curve. Check the
   arithmetic and the conclusion. Is 4 bins right, or is there a better small-sample
   approach to assessing calibration?

5. CALIBRATION METHOD. Platt scaling rather than isotonic regression, on the grounds that
   isotonic overfits below roughly 1,000 calibration points, with a calibration fold of
   ~170. Agree? Would beta calibration, temperature scaling, or a Bayesian approach be
   better at this n? The plan also proposes NESTED grouped cross-validation to obtain
   out-of-fold calibrated predictions for all ~860 candidates instead of evaluating on a
   single 170-row test fold. Is that legitimate, or does pooling out-of-fold predictions
   from different calibrators introduce a bias?

6. CONFORMAL VALIDITY. Candidates are clustered by incident (5–20 candidates share one
   fault, one BEFORE state, and most of their config), so candidate-level exchangeability
   fails. The plan proposes calibrating at the INCIDENT level (one nonconformity score per
   incident) and notes that with ~20 calibration incidents the finite-sample correction
   ~1/(n+1) means α below about 0.05 is unsupportable. Is incident-level calibration the
   right fix? Name the specific cluster/group-conformal method that should be used and cite
   it. Is the α claim correct?

7. ARCHITECTURE. The plan rejects a CNN (no canonical node ordering, so an adjacency-matrix
   "image" is permutation-sensitive; ~700 training rows vs 10^4–10^6 parameters; the useful
   signal is graph-theoretic scalars). It rejects a GNN as primary (right inductive bias,
   wrong sample requirement) and recommends gradient-boosted trees on tabular features plus
   HAND-COMPUTED graph features (betweenness of changed device, distance to primary path,
   bridge/cut-edge status, edge connectivity before/after, change in shortest-path count),
   with a small GNN as a declared ablation. Agree or disagree, with reasoning about sample
   size. If you think a GNN is worth it at n≈700, say what would make it work.

8. BUDGET ALLOCATION. The plan says emulator cost scales with CANDIDATES not TOPOLOGIES, so
   it recommends going from 10 topologies × 10 incidents to 20 topologies × 5 incidents at
   the same ~1,800-candidate budget, doubling leave-one-topology-out folds for free. Any
   statistical downside to fewer incidents per topology?

9. CONTROL ARM. 150 Batfish-FAIL candidates are proposed to bound the "verifier is
   pessimistic" rate, justified by the rule of three (0 observed in 150 → 95% upper bound
   ~2%). Is 150 the right number, and is the rule of three the right instrument here?

10. LABELS. Emulator outcomes are HARMFUL / SAFE / NO_CONVERGENCE / UNDETERMINED /
    EXECUTION_FAILED. The plan maps NO_CONVERGENCE to harmful=1 in the primary analysis and
    EXCLUDES UNDETERMINED and EXECUTION_FAILED (currently the code silently maps all three to
    safe=0). Is that the right treatment? Does excluding UNDETERMINED bias the estimate, and
    if so in which direction?

11. THE LIKELY OUTCOME. The pilot found no learnable model once a trivial shortcut class was
    removed, and a non-learned rule ("predict harmful iff any oracle-only property fails in
    the verifier") beat every model with 7/12 recall and zero false alarms. The plan predicts
    this replicates and argues the negative result is publishable if framed as
    "risk is not predictable from these features, therefore bound it rather than predict it".
    Is that actually publishable at the target venues, or is it a workshop paper?

THEN ANSWER THESE THREE QUESTIONS DIRECTLY:

A. What are the THREE things in this plan most likely to be wrong? Rank them.
B. What is MISSING that neither the plan nor I have considered at all?
C. If you were reviewing the resulting paper for NOMS/CNSM/TNSM, what would be your single
   strongest reason to reject it, and could the plan as written survive that objection?

CITATION RULES — IMPORTANT:
- Give a working URL or DOI for every paper you name. No URL means you do not name it.
- If you cannot verify a paper exists, say "UNVERIFIED" next to it. Do not present a
  plausible-sounding title as established fact.
- Prefer 2023–2026 work. State the venue and year.
- If your search finds nothing on a topic, say "search inconclusive" rather than concluding
  the space is empty.

OUTPUT FORMAT:
- Section 1: the 11 numbered claims, each as AGREE/DISAGREE/UNCERTAIN + severity + reasoning.
  Two to five sentences each. No preamble.
- Section 2: answers to A, B, C.
- Section 3: papers table — title | venue/year | URL | why it matters | verified? (Y/N)
- Section 4: anything you would change about the plan that I did not ask about.

Be concise. I would rather have five sharp disagreements than twenty paragraphs of
agreement.
```

---

## TOOL-SPECIFIC ADD-ONS

Append the relevant block to the end of the universal prompt.

### Perplexity Pro

```
ADDITIONAL INSTRUCTIONS FOR THIS TOOL:
Weight your effort heavily toward claims 1, 2 and 3 — the literature. Search
arXiv (cs.NI, cs.LG), ACM DL, IEEE Xplore, USENIX, and Semantic Scholar. Run at least these
queries and report what each returned:
  - network verification false pass rate emulation ground truth
  - Batfish emulator disagreement empirical measurement
  - configuration change risk prediction calibrated probability networking
  - conformal prediction OR conformal risk control network operations configuration
  - LLM network configuration repair verification benchmark
  - specification incompleteness network verification empirical
  - "verification passes" outage network configuration study
Report the CLOSEST 10 papers, not the most numerous. For each, state in one sentence why a
reviewer could or could not say "this has already been done". Flag any paper published after
August 2026 that the plan cannot have seen.
```

### Gemini Pro

```
ADDITIONAL INSTRUCTIONS FOR THIS TOOL:
Weight your effort toward claims 4, 5, 6, 9 and 10 — the statistics. Show your working on
the sample-size arithmetic in claim 4 and either confirm or correct it with explicit
formulas. For claim 6, give the precise conformal construction you would use for clustered
data, with the coverage statement written out mathematically and a citation. For claim 10,
reason explicitly about the direction of bias from excluding UNDETERMINED outcomes. Where the
plan states a rule of thumb (isotonic needs ~1,000 points; n≈138 per bin), verify it
numerically rather than accepting it.
```

### ChatGPT (GPT-5 / o-series)

```
ADDITIONAL INSTRUCTIONS FOR THIS TOOL:
Weight your effort toward claims 3, 7 and 11, and toward question C — the framing and the
review outcome. Write the most damaging one-paragraph reviewer rejection you can construct
against this paper as planned, using only the information in the attached document. Then
state whether the plan already contains a defence, and if it does not, what would have to be
added. Also stress-test the experimental design for confounds I have not named: the repairs
are synthetically generated by parameterised operators, the topologies are generated by one
function, and the harm labels come from a single emulator run per candidate.
```

---

## WHAT TO BRING BACK

For each tool, bring back the whole response. When comparing, I will be looking for:

- **Any claim where two or more tools DISAGREE with the plan.** Those are the real findings.
- **Any paper found that measures P(harm | verifier PASS).** That is the project-ending
  result and it must be checked properly, not dismissed.
- **Unanimous agreement on any claim.** That is a warning sign, not a comfort — it usually
  means the question was phrased so that agreement was the easy answer.
- **Citations that appear in only one tool's response.** Those are the most likely to be
  hallucinated; they get verified before they go anywhere near the paper.
```
