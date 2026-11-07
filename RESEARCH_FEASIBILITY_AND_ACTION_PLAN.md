# Research Feasibility Assessment and Revised Action Plan: Batfish-Verified Network Repair Risk Ranking

**Date:** 2026-11-06  
**Repository Inspected:** `c:\Users\karth\network-research-lab` (branch `master`, HEAD `2030a7c`, plus untracked V4 pilot and post-hoc mechanistic/ML audit artifacts)  
**Target Document Evaluated:** `Batfish_ML_Risk_Ranking_Research_Plan.md` (v1.0, including Part XVII)  
**Historical Evidence Base:** [`PROJECT_HISTORY_AND_RESEARCH_EVOLUTION.md`](file:///c:/Users/karth/network-research-lab/PROJECT_HISTORY_AND_RESEARCH_EVOLUTION.md), V1–V4 raw/derived records, frozen preregistrations, and postmortem audits  
**Status:** Pre-implementation scientific viability audit, literature synthesis, and mandatory Go/No-Go gate specification. **No new Containerlab, Batfish, or ML training runs were launched.**

---

## Evidence Label Convention

Throughout this report, every factual claim, citation, calculation, and recommendation is tagged with an explicit epistemic status label:

| Label | Definition |
|---|---|
| **VERIFIED-REPO** | Directly read, inspected, or recomputed from files and code in `c:/Users/karth/network-research-lab` during this audit. |
| **RECORDED** | Stated in an existing committed or untracked project report, manifest, ledger, or audit file without re-running the underlying container/verifier job. |
| **VERIFIED-WEB** | Directly verified against live external repositories, dataset APIs (GitHub API, HuggingFace API, Mendeley API, BNN-UPC), or published academic papers during this audit. |
| **PUBLISHED-LIT** | Established result from peer-reviewed networking, formal verification, or machine learning literature. |
| **INFERENCE** | Logical or statistical deduction synthesized from multiple verified records. |
| **ASSUMPTION** | Explicit condition required for a feasibility estimate or future design step that has not yet been empirically proven. |
| **CONCLUSION** | Authoritative scientific judgment and recommendation of this audit. |

---

## 1. Executive Verdict & Scientific Honesty Statement

**CONCLUSION:**  
Pursuing `Batfish_ML_Risk_Ranking_Research_Plan.md` **as currently written**—specifically, attempting to train a CNN, GNN, or tabular regressor on pre-deployment topology and configuration features to predict a continuous composite runtime risk score $L_r = w_p P_r + w_d D_r + w_f F_r$ across Cornetto-derived topologies in Containerlab—**is scientifically infeasible in its current form and warrants a CONDITIONAL NO-GO / MANDATORY REDESIGN before any runtime compute is spent.**

However, **a redesigned, narrower research paper IS scientifically feasible and publishable** if and only if the project pivots from *"black-box ML prediction of continuous convergence duration/blast radius"* to one of two rigorously defensible formulations:

1. **Path A (Primary Technical Pivot — Update-Order-Aware Staged Verification & Ranking of Batfish-PASS Repairs):** Recognizing that a multi-device network repair is not a static snapshot $c_{i,j}$ but a **staged deployment pair** $(c_{i,j}, \sigma)$ where $\sigma = (u_1, u_2, \dots, u_k)$ is the router push sequence. In this formulation, a symbolic mixed-state control/data-plane model (and learned rankers evaluated strictly on top of it) ranks candidate repairs *and* their deployment sequences by transient forwarding-loop and blackhole exposure during asynchronous convergence.
2. **Path B (Guaranteed High-Rigor Benchmark & Negative/Boundary Paper — The Verification-to-Execution Gap):** Publishing the complete, preregistered four-generation investigation (V1–V4) alongside a Batfish-scale specification-completeness and repair-ranking benchmark, proving *analytically and empirically* why:
   - binary residual risk $P(\text{harm} \mid \text{PASS})$ on synthetic repair corpora is dominated by generator shortcuts ($AUC = 0.975$) and specification incompleteness ($76.2\%$ caught by a zero-parameter specification-widening rule);
   - steady-state blast radius $r$ is $100\%$ analytically redundant with Batfish ($26,738 / 26,738$ flows identical across $151 / 151$ candidates, $R^2 = 1.000$); and
   - continuous transient disruption magnitude $T_1$ separates into a *pre-deployment structural susceptibility condition* (symbolic mixed-state cycles) and a *runtime-timing realization factor* (LSA propagation and kernel FIB installation jitter) that static pre-deployment ML cannot uniquely identify.

### Summary of Why the Current Plan Must Change Before Execution

1. **Composite Target Contamination ($F_r$ Redundancy):** (**VERIFIED-REPO**) In Section 10 of `Batfish_ML_Risk_Ranking_Research_Plan.md`, the proposed target $L_r = w_p P_r + w_d D_r + w_f F_r$ mixes steady-state flow impact ($F_r$) with transient packet loss ($P_r$) and outage duration ($D_r$). Project V3 (`analysis/v3_independent/FINAL-INDEPENDENT-V3-AUDIT.md` and `docs/V4-PIVOT-AND-EXPANSION-PLAN.md` §17) already proved that Batfish's saved RIB (`routes.json`) and [`nrl/severity.py`](file:///c:/Users/karth/network-research-lab/nrl/severity.py) (`Fabric`) compute steady-state flow impact with **100% accuracy** ($26,738 / 26,738$ flows matched on $151 / 151$ candidates in $\approx 0.12\text{ s}$). Any target containing $F_r$ artificially inflates ML $R^2$ and ranking metrics by letting the model approximate a deterministic Dijkstra calculation.
2. **Unidentifiability of Continuous Transient Duration ($T_1, P_r, D_r$) from Static Configs:** (**VERIFIED-REPO**) In Project V4 (`analysis/V4-POSTMORTEM.md`, `v4_transient/analysis/mechanistic/RESEARCH_VIABILITY_AUDIT.md`, `v4_transient/analysis/mechanistic/MODEL3_REPORT.md`), only $1 / 20$ Batfish-PASS candidates (`V4C-04`) exceeded the frozen noise floor ($6.944 \times 10^{-4}$). Crucially, the post-hoc offline mechanistic models ([`analyze_mechanistic.py`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/mechanistic/analyze_mechanistic.py)) tested `V4C-04` ($T_1 \approx 0.0229$) against five exploratory multi-device candidates (`EX-V4-01` through `EX-V4-05`, $T_1 \in [3.85 \times 10^{-5}, 1.81 \times 10^{-4}]$). Both the mixed old/new forwarding model (`hybrid_state_features`) and the offline asynchronous convergence model (Model 3) predicted intermediate cycles for **all six cases**, with larger static cycle exposure for `EX-V4-05` ($57.4\%$ of flows) than for `V4C-04` ($6.25\%$ of flows). Why did `V4C-04` suffer $120\times$ more disruption? Because realized $T_1$ is governed by **runtime inter-container vtysh push latency, OSPF LSA flooding phase, SPF timer scheduling, and netlink FIB installation order**—variables that do not exist prior to deployment.
3. **Cornetto Dataset Incompatibility with Laptop Containerlab Execution:** (**VERIFIED-WEB**) Direct inspection of the live HuggingFace repository (`iprotogeros/cornetto-benchmark`, commit `cdf3d68ecc47b4afe63e6b3ca8f5c07821c191bd`) and GitHub repository (`nsg-ethz/cornetto`) reveals four hard blockers that the research plan overlooks:
   - **Scale vs. 16 GB RAM Constraint:** Across Cornetto's 231 scenarios, router counts range from **20 to 754 routers** with a **median of 69 routers**; only **4 scenarios** have $\le 20$ routers. On the project's 16 GB Windows/WSL2 host (7.6 GB WSL limit, tested up to 19 FRR containers in V3), running 69–754 router Containerlab topologies is physically impossible.
   - **Withheld Ground Truth:** In the public Cornetto release, **230 of 231 scenarios withhold `initial_configs/` (the working reference network) and `fault_metrics.csv`**; only `scenario-003` includes them.
   - **Vendor Syntax & Unmodeled Constructs:** Cornetto configs use **Cisco IOS syntax** with extended IP ACLs (`ip access-group ... in`), BGP (`as65001`...), and OSPF, evaluated via a **custom Batfish container** (`iprotogeros/batfish-allione:forwarding-analysis-0.1`). Our Containerlab pipeline runs FRR (`frrouting/frr:v8.4.1`) via the Cumulus concatenated format ([`nrl/render.py`](file:///c:/Users/karth/network-research-lab/nrl/render.py)), where Batfish **silently ignores FRR `access-list` / `distribute-list`** (Defect S-004 in [`docs/PROJECT-HANDOFF.md`](file:///c:/Users/karth/network-research-lab/docs/PROJECT-HANDOFF.md#L430-L436)) and does not model Linux `iptables` packet filters.

---

## 2. Forensic Audit of Project History (V1–V4): Evidence vs. Assumptions

To prevent repeating past failure modes, Table 1 synthesizes the verified forensic record across all four project iterations in `c:\Users\karth\network-research-lab`.

### Table 1: Forensic Cross-Version Audit (V1–V4)

| Dimension | V1 (`data/pilot-v1`) | V2 (`data/pilot-v2`) | V3 (`data/pilot-v3`) | V4 (`v4_transient/`) |
|---|---|---|---|---|
| **Primary Question** | Can we build a same-artifact Batfish $\leftrightarrow$ FRR measurement chain and predict binary harm? | What is $P(\text{harm} \mid \text{Batfish PASS})$ across 20 topologies, and can ML predict residual risk? | Can pre-deployment features predict continuous steady-state blast radius $r$ among SPEC-PASS changes? | Can pre-deployment features predict transient disruption area $T_1 = \int b_{\text{excess}}(t)\,dt$ during convergence? |
| **Population & Scale** | 1 topology (`T2`), 10 incidents, 50 candidates (41 distinct configs; 24 PASS). (**VERIFIED-REPO**) | 20 topologies, 200 incidents, 1,479 candidates (804 PASS; 301 executed in Stage 3; 299 decidable). (**RECORDED**) | 20 ECMP-free designs (12 primary built, 8 held-out unbuilt), 151 SPEC-PASS candidates (79 `cost`, 72 `blackhole`). (**VERIFIED-REPO**) | 4 topologies (`t05`, `t13`, `t14`, `t15`), 20 SPEC-PASS changes $\times 5$ replicates = 100 runs (99 valid) + 10 no-op + 4 pos controls. (**VERIFIED-REPO**) |
| **Measured Ground Truth** | 12 SAFE, 12 HARMFUL among 24 PASS ($50\%$). Phase 2 summary CSV on disk has a 3-row discrepancy vs. 24-row Phase 4 table. (**VERIFIED-REPO**) | $P(\text{harm} \mid \text{PASS}) = 80/299 = 26.76\%$ (95% Wilson $[0.221, 0.321]$). Gate 0 link-churn test: $0/40$ outcome flips (deterministic label). (**RECORDED**) | 91 distinct $r$ values; mean $0.1162$, max $0.4476$. Independent raw-RIB check ([`independent_r_check.py`](file:///c:/Users/karth/network-research-lab/analysis/v3_independent/independent_r_check.py)) matched $151/151$. (**VERIFIED-REPO**) | No-op controls: $10/10$ at $T_1 = 0$. Pos controls (non-partitioning shutdowns): $4/4 > \text{floor}$. Population medians $> \text{floor}$ ($6.944\times 10^{-4}$): **$1/20$ ($5\%$)** vs. $30\%$ gate. (**VERIFIED-REPO**) |
| **ML Performance vs. Baselines** | Excluding `exact_revert` collapsed LogReg/stump to $\text{AUC} \le 0.542$ ($p \ge 0.469$). Spec-widening caught $7/12$ with 0 FP. (**RECORDED**) | Apparent GBT $\text{AUC-PR} = 0.895$ was pure shortcut (`repair_class` recoverable at $\text{AUC} = 0.975$; Spearman $\rho = 0.905$ between contamination and performance). Clean `B_only` $\text{AUC-PR} = 0.291$ vs. $0.268$ base rate ($p=0.319$). Deterministic `spec_widening_rule` achieved $\text{AUC-PR} = 0.8137$ (61 TP, 1 FP). (**RECORDED**) | HGB LOTO $R^2 = 0.848$ (Tier C) and $0.744$ (Tier B). Zero-parameter lookup (`mechanism` $\times$ `P06`) achieved $R^2 = 0.794$ (beating Tier B). **Batfish RIB walk achieved $R^2 = 1.000$ ($26,738/26,738$ flows exact).** (**VERIFIED-REPO**) | Confirmatory ML (D5) was **not run** because D2/G1 ($1/20 < 6/20$) killed the pipeline as preregistered. Exploratory smoke ML ([`ML_EXPLORATORY_REPORT.md`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/ml_exploratory/ML_EXPLORATORY_REPORT.md)) had $0/16$ rows above floor. (**VERIFIED-REPO**) |
| **Root Scientific Failure Mode** | **Trivial class confound:** `exact_revert` dominated the safe class. | **Generator fingerprint leakage & deterministic target:** Synthetic repair operators encoded `repair_class`, which determined the label; residual harm was specification incompleteness, not stochastic risk. | **Analytic target redundancy:** Steady-state routing in a fixed OSPF/static network is a closed-form function (Dijkstra/SPF) that Batfish already computes exactly in $<8\text{ s}$. | **Population design & pre-deployment unidentifiability:** Selecting candidates by steady-state $r$ yielded $95\%$ sub-floor transients; realized $T_1$ duration depends on runtime timing/ordering absent from static configs. |

### Key Takeaway from the Forensic History

**INFERENCE:** Across four rigorously engineered versions (including 25+ silent-failure bugs caught and fixed in `PROJECT-HANDOFF.md` §10 and V4 Amendments A3–A5), **the engineering apparatus is not the bottleneck.** The Same-Artifact Guarantee ([`nrl/render.py`](file:///c:/Users/karth/network-research-lab/nrl/render.py)), the Batfish-to-FRR verification harness ([`pipeline/run_phase2.py`](file:///c:/Users/karth/network-research-lab/pipeline/run_phase2.py), [`pipeline/run_phase3.py`](file:///c:/Users/karth/network-research-lab/pipeline/run_phase3.py)), and the microsecond netlink FIB/link/nexthop replay engine ([`v4_transient/v4lib/fib.py`](file:///c:/Users/karth/network-research-lab/v4_transient/v4lib/fib.py), [`v4_transient/v4lib/targets.py`](file:///c:/Users/karth/network-research-lab/v4_transient/v4lib/targets.py)) are exceptionally well-built.  
Every scientific failure occurred at the **problem formulation boundary**:
- When the target is a **steady-state forwarding property** (V2 binary harm, V3 blast radius $r$), **formal verification or deterministic graph analysis solves it exactly**, leaving nothing for ML to learn except synthetic generator shortcuts.
- When the target is a **continuous runtime transient integral** ($T_1$ in V4), **runtime event timing and asynchronous daemon scheduling dominate the magnitude**, leaving static pre-deployment features unable to uniquely separate high-$T_1$ runs from low-$T_1$ runs that share the same structural cycle possibility.

---

## 3. Extensive Literature Review & Novelty Audit

To evaluate whether "ranking multiple Batfish-PASS network repair candidates by operational risk" is novel and defensible, we audited five intersecting bodies of peer-reviewed research (**PUBLISHED-LIT** / **VERIFIED-WEB**).

### 3.1 Formal Network Verification & Differential/Relational Change Analysis

1. **Batfish (Fogel et al., [USENIX NSDI 2015](https://www.usenix.org/conference/nsdi15/technical-sessions/presentation/fogel); Beckett et al., [ACM SIGCOMM 2023](https://dl.acm.org/doi/10.1145/3603269.3604872)):** Models converged control-plane and data-plane behavior from multi-vendor configuration files using Datalog and Binary Decision Diagrams (BDDs). Crucially, Batfish natively supports [`differentialReachability`](https://pybatfish.readthedocs.io/en/latest/notebooks/differentialQuestions.html) and route-table comparison between a reference snapshot and a candidate snapshot. As proven in our V3 audit (`batfish_computes_r.py`), Batfish's converged RIB model is **exact** for steady-state OSPF/static blast radius on FRR.
2. **Minesweeper (Beckett et al., [ACM SIGCOMM 2017](https://dl.acm.org/doi/10.1145/3098822.3098834)) & Plankton (Prabhu et al., [USENIX NSDI 2020](https://www.usenix.org/conference/nsdi20/presentation/prabhu)):** SMT-based and explicit-state model checkers for control-plane verification under all possible nondeterministic tie-breaks and link failures. Still restricted to *converged stable states* rather than transient convergence windows.
3. **Rela — Relational Network Verification (Xu et al., [ACM SIGCOMM 2024](https://dl.acm.org/doi/10.1145/3651890.3672238), [arXiv:2403.17277](https://arxiv.org/abs/2403.17277)):** Directly addresses network configuration changes at Alibaba Cloud scale ($>10^3$ routers) by compiling relational change specifications ("these flows change path; all other flows stay identical") into finite-state transducers. **Impact on our novelty:** Rela completely solves the static "did my configuration change cause unintended steady-state forwarding collateral damage?" problem formally and without ML.
4. **Campion (Tang et al., [ACM SIGCOMM 2021](https://dl.acm.org/doi/10.1145/3452296.3472925)) & SelfStarter (Kakarla et al., [USENIX NSDI 2020](https://www.usenix.org/conference/nsdi20/presentation/kakarla)):** Detect configuration outliers and behavioral differences across routers without requiring manual specifications.
5. **Config2Spec (Birkner et al., [USENIX NSDI 2020](https://www.usenix.org/conference/nsdi20/presentation/birkner)):** Automatically mines formal data-plane specifications (reachability, isolation, waypointing predicates) from a network's configuration using Batfish + Minesweeper.

### 3.2 Automated Configuration Synthesis, Repair, and Candidate Ranking

1. **CPR — Control Plane Repair (Gember-Jacobson et al., [ACM SOSR 2017](https://dl.acm.org/doi/10.1145/3050220.3050228)):** Formulates configuration repair as a MaxSMT problem over an abstract control-plane graph, ranking/selecting repairs by **minimum line/device modification cost** (syntactic minimality).
2. **AED — Automated Configuration Repair (Abhashkumar et al., [ACM CoNEXT 2020](https://dl.acm.org/doi/10.1145/3386367.3431297)):** Synthesizes repairs that satisfy policy specifications while optimizing multi-objective **operational manageability criteria** (minimizing number of changed devices, lines changed, and complexity). **Impact on our novelty:** AED already ranks/selects among multiple policy-compliant repairs using deterministic structural/manageability objectives! Therefore, claiming to be the "first to rank valid configuration repairs" without qualifying that prior work used deterministic syntactic/manageability objectives while we target runtime transient disruption would be factually incorrect and rejected by reviewers.
3. **SyNET (El-Hassany et al., [CAV 2017](https://link.springer.com/chapter/10.1007/978-3-319-63390-9_15)) & NetComplete (El-Hassany et al., [USENIX NSDI 2018](https://www.usenix.org/conference/nsdi18/presentation/el-hassany)):** Synthesize OSPF/BGP configurations from Datalog/SMT specifications.
4. **Cornetto (Protogeros et al., ETH Zürich NSG, [arXiv:2604.22513](https://arxiv.org/abs/2604.22513), [GitHub `nsg-ethz/cornetto`](https://github.com/nsg-ethz/cornetto)):** Benchmarks zero-shot, iterative-repair, RAG, and agentic LLMs on 231 misconfiguration scenarios (20–754 nodes), scoring repairs via Batfish against Config2Spec-mined predicates. Cornetto evaluates *functional steady-state correctness* of a single LLM output, not runtime transient disruption across competing Batfish-PASS repairs.

### 3.3 Transient Convergence, Microloops, and Safe Network Updates

1. **Order Matters & oFIB (François & Bonaventure, [IEEE INFOCOM 2005](https://doi.org/10.1109/INFCOM.2005.1498497); Shand, Bryant, Previdi, Filsfils, François & Bonaventure, [IETF RFC 6976](https://datatracker.ietf.org/doc/rfc6976/), 2013; [RFC 5715](https://datatracker.ietf.org/doc/rfc5715/), 2010; [RFC 8333](https://datatracker.ietf.org/doc/rfc8333/), 2018):** Prove mathematically that transient forwarding loops (microloops) during link-state IGP (OSPF/IS-IS) convergence occur when routers update their FIBs asynchronously such that the union of old and new shortest-path trees contains a directed cycle. Crucially, **RFC 6976 (oFIB)** proves that for any planned metric change or graceful link drain/bringup, **there exists a deterministic router-update ranking/ordering that eliminates transient microloops completely** by computing reverse-SPF/forward-SPF ranks!
2. **Consistent Network Updates (Reitblatt et al., [ACM SIGCOMM 2012](https://dl.acm.org/doi/10.1145/2342356.2342427)), zUpdate (Liu et al., [ACM SIGCOMM 2013](https://dl.acm.org/doi/10.1145/2486001.2486005)), & Dionysus (Jin et al., [ACM SIGCOMM 2014](https://dl.acm.org/doi/10.1145/2619239.2626307)):** Formalize per-packet and per-flow consistency during staged network updates and schedule dependency graphs dynamically in SDN/WAN environments.

### 3.4 Emulation, GNN Performance Digital Twins, and Deployment Safety

1. **CrystalNet (Liu et al., [ACM SOSP 2017](https://dl.acm.org/doi/10.1145/3132747.3132759)):** Microsoft's container/VM network emulator for validating production network changes prior to rollout.
2. **Gandalf (Li et al., [USENIX NSDI 2020](https://www.usenix.org/conference/nsdi20/presentation/li)):** Continuous deployment monitoring system at Microsoft Azure that uses post-deployment telemetry and statistical/ML anomaly detection to catch bad rollouts.
3. **RouteNet & RouteNet-Fermi (Rusek et al., [IEEE JSAC 2020](https://doi.org/10.1109/JSAC.2020.3000405); Ferriol-Galmés et al., [IEEE/ACM ToN 2023](https://doi.org/10.1109/TNET.2022.3230035)):** Message-passing GNNs over bipartite path-link graphs that predict steady-state queueing delay, jitter, and packet loss from traffic matrices and static routing paths.

### 3.5 Novelty Matrix & True Research Gap

| Prior Work / System | Multiple Candidate Repairs? | Batfish Formal Verification Gate? | Models Staged / Transient Convergence? | Containerlab / Real Daemon Execution? | Ranking / Risk Estimation Method |
|---|---|---|---|---|---|
| **Batfish / Rela** (NSDI'15, SIGCOMM'24) | No (single change) | Yes (exact steady state) | No (steady-state only) | No | Deterministic BDD / Transducer equivalence |
| **CPR / AED** (SOSR'17, CoNEXT'20) | Yes (synthesizes multiple) | Yes (SMT / policy spec) | No (steady-state only) | No | Deterministic MaxSMT (syntactic / device-count minimality) |
| **Cornetto** (arXiv:2604.22513) | LLM iterative retries | Yes (Config2Spec predicates) | No (steady-state only) | No | Pass/Fail predicate recovery fraction |
| **RFC 5715 / RFC 6976 (oFIB)** | No (single link/metric change) | No | **Yes** (transient microloops) | Analytical / IGP timers | Deterministic graph rank ordering |
| **RouteNet-Fermi** (ToN'23) | No | No | No (steady-state queueing) | OMNeT++ simulator | Bipartite Path-Link GNN |
| **Our Project V2 & V3** | Yes (synthetic operators) | Yes (`SUITE 1.1.0`) | No (steady-state after 45s) | Yes (Containerlab FRR) | Proved steady-state ML is shortcut-bound (V2) or analytically redundant with Batfish (V3) |
| **Our Project V4** | 20 single changes | Yes (`SUITE 1.1.0`) | **Yes** (netlink FIB replay $T_1$) | Yes (Containerlab FRR) | Proved $95\%$ of steady-state-selected changes have sub-floor $T_1$; static configs cannot predict runtime timing |
| **Defensible Gap (Proposed Redesign)** | **Yes** (multiple distinct Batfish-PASS repairs $\times$ update orders) | **Yes** (steady-state SPEC + exact $r$ filter) | **Yes** (staged device push + asynchronous LSA/FIB transitions) | **Yes** (Containerlab FRR microsecond FIB replay) | **Symbolic mixed-state cycle verifier + learned/conformal ranking of $(c_{i,j}, \sigma)$ pairs** |

**CONCLUSION ON NOVELTY:**  
- **What is NOT novel:** Ranking repairs by number of changed devices/lines (done by CPR and AED); checking whether a change reroutes or breaks steady-state flows (done exactly by Batfish `differentialReachability` and Rela); or proving that unordered OSPF metric changes can cause microloops (done by François & Bonaventure 2005 and RFC 6976).
- **What IS genuinely novel:** Investigating the **post-verification operational ambiguity** among multiple distinct configuration repairs $(c_{i,1}, \dots, c_{i,m})$ that all satisfy the same Batfish steady-state specification—specifically:
  1. Decomposing post-PASS operational risk into **specification incompleteness** (steady-state collateral rerouting/breakage $r_{\text{exact}}$, which Batfish can compute *if asked*), **structural transition hazard** (whether pushing $c_{i,j}$ under deployment order $\sigma$ induces mixed-state forwarding cycles or transient blackholes), and **aleatoric runtime realization** (duration governed by daemon/kernel scheduling); and
  2. Evaluating whether pre-deployment structural transition features (or learned models built on them) can rank $(c_{i,j}, \sigma)$ pairs to minimize transient disruption in Containerlab/FRR better than Batfish steady-state heuristics and syntactic minimality baselines (AED-style).

---

## 4. Deep Audit of External Datasets (Availability, Licensing, and Compatibility)

Section 12–16 and Part XVII (§67) of `Batfish_ML_Risk_Ranking_Research_Plan.md` propose a hybrid pipeline anchored on **Cornetto**, supplemented by **LCORE-D**, **GNNet 2021**, and **Batfish `test-networks`**. During this audit, we queried the live repositories and dataset APIs directly (**VERIFIED-WEB**). Every assumption in the plan regarding these datasets is tested below.

### 4.1 Cornetto (`nsg-ethz/cornetto` & HuggingFace `iprotogeros/cornetto-benchmark`)

- **Source & Provenance (**VERIFIED-WEB**):** GitHub [`nsg-ethz/cornetto`](https://github.com/nsg-ethz/cornetto) (`main` branch), HuggingFace [`iprotogeros/cornetto-benchmark`](https://huggingface.co/datasets/iprotogeros/cornetto-benchmark) (commit SHA `cdf3d68ecc47b4afe63e6b3ca8f5c07821c191bd`, 21,843 files), Paper [arXiv:2604.22513](https://arxiv.org/abs/2604.22513) (*"Benchmarking LLM-Driven Network Configuration Repair"*, Ioannis Protogeros, Rufat Asadli, Benjamin Hoffman, Laurent Vanbever, ETH Zürich NSG, 2026).
- **License (**VERIFIED-WEB**):** **MIT License** (`spdx_id: MIT` on both GitHub and HuggingFace dataset card YAML frontmatter; `Copyright (c) 2025 Rufat Asadli`). Legally reusable and modifiable with attribution.
- **Scenario vs. Unique Topology Count (**VERIFIED-WEB**):**
  - Contains **231 scenario directories** (`main_dataset/scenario-001` through `scenario-231`), constructed from **77 fault sets** (27 single-fault monosets + 50 pairwise-coverage multi-fault sets with $k \in \{2,\dots,8\}$ simultaneous faults) $\times$ **3 topology scale tiers** (Small $<50$ nodes, Medium $50\text{–}100$ nodes, Large $>100$ nodes) $= 231$ scenarios, sourced from the **Internet Topology Zoo** (Knight et al., 2011).
  - Across all 231 scenarios, there are **56 distinct router-count values** (e.g., 20 scenarios have 74 routers; 13 have 197 routers; 13 have 127 routers; 11 have 21 routers; 10 have 149 routers; 10 have 25 routers). **231 scenarios is NOT 231 unique topologies**; multiple fault scenarios share the same underlying Topology Zoo graphs.
- **Router Scale Distribution vs. Hardware Limits (**VERIFIED-WEB**):**
  - Minimum routers per scenario: **20**
  - Median routers per scenario: **69** (Mean: **86.4 nodes**; mean configuration size: **16.1K lines of code**, max **200.0K LoC**)
  - Maximum routers per scenario: **754**
  - Scenarios with $\le 20$ routers: **4 out of 231 ($1.7\%$)**
  - Scenarios with $\le 30$ routers: **56 out of 231 ($24.2\%$)**
  - **Critical Feasibility Impact:** On the researcher's 16 GB Windows laptop (WSL2 memory limit $\approx 7.6\text{ GB}$), Containerlab + FRR was validated up to 16–19 containers (`t19_dualcore16`). Running 69-router or 754-router Containerlab topologies on a single laptop will cause immediate host OOM or severe CPU thrashing that corrupts transient timing measurements.
- **Missing Ground Truth & Missing Repair Alternatives (**VERIFIED-WEB**):**
  - As documented in Cornetto's `README.md` and `EXAMPLE.md`, **230 of the 231 scenarios intentionally exclude `initial_configs/` (the working pre-fault reference configs $C_{\text{gold}}$) and `fault_metrics.csv`** to prevent LLM benchmark contamination. Only `scenario-003` (`asn-wrong_local_asn-small-001` on `BtEurope`, 24 routers) includes `initial_configs/`, `blueprint.yaml`, `scenario_summary.json`, `fault_metrics.csv`, and route/forwarding/predicate diff logs.
  - Each public scenario provides only `final_configs/configs/*.cfg` (the broken configs $C_{\text{broken}}$), `data_and_metrics/topology.json`, and `specifications/specifications_{2,5,10,20,50,75,100}pct.csv` (Config2Spec predicates across `Reachability`, `Isolation`, `Waypointing`, and `LoadBalancing`).
  - **Zero scenarios** include multiple alternative Batfish-PASS repair candidates (even `scenario-003` has only a single pre-fault golden config $C_{\text{gold}}$).
  - **Zero scenarios** include Containerlab/FRR snapshots or runtime telemetry.
- **Configuration Syntax & Construct Mismatch (**VERIFIED-WEB** & **VERIFIED-REPO**):**
  - Cornetto configs are in **Cisco IOS format** across 27 fault functions spanning **eBGP and iBGP** (route reflection, peer-groups, `local-preference`), **OSPF** (single- and multi-area), **IS-IS** (Level-1 and Level-1-2), **BGP $\to$ OSPF route redistribution**, **static routes**, **route-maps**, **prefix-lists**, and **extended IPv4 ACLs** (`ip access-list extended`, `ip access-group ... in`).
  - Furthermore, Cornetto requires a **custom Batfish Docker image** (`iprotogeros/batfish-allione:forwarding-analysis-0.1`) rather than standard `batfish/allinone`.
  - In our repository ([`docs/ARCHITECTURE.md`](file:///c:/Users/karth/network-research-lab/docs/ARCHITECTURE.md), [`docs/PROJECT-HANDOFF.md`](file:///c:/Users/karth/network-research-lab/docs/PROJECT-HANDOFF.md) §5 & §10), Containerlab runs **FRR (`frrouting/frr:v8.4.1`)** using the **Cumulus concatenated format**. Translating Cornetto's Cisco IOS + extended ACLs + IS-IS + BGP into FRR/Containerlab is a major engineering project with known silent-failure landmines (e.g., Defect S-004: Batfish silently ignores FRR `access-list`/`distribute-list`, and data-plane ACLs require `iptables` translation outside `frr.conf`).
  - **Verdict on Cornetto:** Can be used **only** by extracting the underlying **graph structures (`topology.json`)** for small topologies ($\le 20$–$25$ nodes) or for a **Batfish-only evaluation track**, NOT as a drop-in Containerlab/FRR configuration corpus.

### 4.2 LCORE-D (`data.mendeley.com/datasets/77sztrg5ks/2`)

- **Source & Provenance (**VERIFIED-WEB**):** Mendeley Data v2 (DOI: `10.17632/77sztrg5ks.2`, published 17 Dec 2025), authored by Akanksha Singh and Ratneshwer Gupta (Jawaharlal Nehru University).
- **License (**VERIFIED-WEB**):** **CC BY 4.0** (`Creative Commons Attribution 4.0 International`).
- **Exact File Inventory (**VERIFIED-WEB**, $4.1\text{ MB}$ compressed / $26.68\text{ MB}$ uncompressed across 8 CSV files):**
  1. `Fault Log/FAULT_LOG.csv` ($6,656\text{ bytes}$): Lists **69 induced fault events (`F01` to `F69`)** across `Core`, `Edge`, and `Access` fault domains (`Single/Multiple link failure`, `Misconfiguration`, `Routing Misconfiguration`, `Line card Failure`, `ICMP Blocked`, `Node failure`, `SNMP agent failure`).
  2. `LCORE-D R1.csv` ($3.91\text{ MB}$, $24,240$ rows, $42$ cols — `CORE-R1`)
  3. `LCORE-D R2.csv` ($2.93\text{ MB}$, $24,229$ rows, $32$ cols — `CORE-R2`)
  4. `LCORE-D R3.csv` ($4.42\text{ MB}$, $24,246$ rows, $51$ cols — `CORE-R3`)
  5. `LCORE-D R4.csv` ($3.75\text{ MB}$, $24,254$ rows, $47$ cols — `CORE-R4`)
  6. `LCORE-D R5.csv` ($3.62\text{ MB}$, $24,234$ rows, $42$ cols — `CORE-R5`)
  7. `LCORE-D R6.csv` ($4.13\text{ MB}$, $24,239$ rows, $51$ cols — `CORE-R6`)
  8. `LCORE-D R7.csv` ($3.92\text{ MB}$, $24,270$ rows, $42$ cols — `EDGE-MS`)
- **Fit & Limitations (**CONCLUSION**):** Represents **one single 7-router (`CORE-R1`..`R6` + `EDGE-MS`) GNS3 topology** monitored at 1-minute SNMP/ICMP intervals over 407 hours. Contains **no router configuration files, no GNS3 topology files, no Batfish snapshots, and no candidate repairs**. Completely unusable for training or evaluating a candidate-repair risk ranker.

### 4.3 Graph Neural Networking Challenge 2021 (`bnn.upc.edu/challenge/gnnet2021/dataset/`)

- **Source & Provenance (**VERIFIED-WEB**):** Barcelona Neural Networking Center (BNN-UPC) & ITU AI/ML in 5G Challenge, companion reader [`BNN-UPC/datanetAPI`](https://github.com/BNN-UPC/datanetAPI/tree/challenge2021).
- **License (**VERIFIED-WEB**):** Companion reader (`datanetAPI`) and RouteNet baselines are **Apache License 2.0**; the dataset webpage itself (`© 2023 Barcelona Neural Networking Center`) does not specify a standalone data license tag on the HTML page.
- **Exact Topology & Sample Counts (**VERIFIED-WEB**):**
  - **Training set (`6.9 GB`, MD5 `43594151cbddd968a5ebc38614999cd5`):** Generated via Palmer & Steffan power-law algorithm ($25\text{–}50$ nodes; webpage text describes 2 topologies at each of 6 sizes $[25,30,35,40,45,50]=12$ topologies, while the `datanetAPI` archive spans 50 topology instances and $120,000$ samples).
  - **Validation set (`2.2 GB`, MD5 `cd1da75419add2700607bbd44d4b0a66`):** $50\text{–}300$ nodes (webpage text describes 2 topologies at each of 26 sizes $=52$ topologies; `datanetAPI` archive contains 26 Topology Zoo graphs across 3 subsets totaling $3,120$ samples).
- **Fit & Limitations (**CONCLUSION**):** Generated by OMNeT++ packet-level simulation (`graphs/*.gml`, `routings/*.txt`, `traffic.txt`, `simulationResults.txt`) to predict steady-state per-path mean delay/jitter/loss under queueing policies (FIFO, SP, WFQ, DRR). Contains **no router configuration files, no routing protocol convergence, no Batfish verification, and no repair alternatives**. Do not spend time downloading or training on GNNet 2021 unless executing the "Calibrated Network Digital Twin" fallback direction (`PROJECT-HANDOFF.md` §4).

### 4.4 Batfish `test-networks` (`github.com/batfish/test-networks`)

- **Source & Provenance (**VERIFIED-WEB**):** GitHub [`batfish/test-networks`](https://github.com/batfish/test-networks) (`main` branch).
- **License (**VERIFIED-WEB**):** Repository license is **Apache License 2.0**, with [`THIRD_PARTY.md`](https://github.com/batfish/test-networks/blob/main/THIRD_PARTY.md) documenting upstream licenses: `internet2` (Apache-2.0 via `XJTU-NetVerify/Expresso` and MIT via `konne88/bagpipe`) and historical Batfish ZIPs (Apache-2.0).
- **Exact Inventory (**VERIFIED-WEB**):** 7 network directories under `networks/`:
  1. `google-freedome` (OSPF/BGP fabric generator + `small-bgp` and `small-ospf` snapshots with **106 routers** each, Apache-2.0)
  2. `internet2` (**10 Juniper router configs** `atla.conf`..`wash.conf`; `VALIDATION.md` notes partial parse warnings in Batfish)
  3. `internet2-expanded` (`two-copies` WAN composition snapshot with **20 routers**, Apache-2.0)
  4. `batfish-fattree20` (**500 routers**, Apache-2.0)
  5. `batfish-ring200` (**200 routers**, Apache-2.0)
  6. `batfish-jellyfish190` (**190 routers**, Apache-2.0)
  7. `batfish-fullmesh100` (**100 routers**, Apache-2.0)
- **Fit & Limitations (**CONCLUSION**):** Only `internet2` (10 routers) and `internet2-expanded` (20 routers) fit within laptop Containerlab scale (`google-freedome` has 106 routers and the four archived benchmarks have 100–500 routers). Useful as a topology-structure reference, not as a labeled repair dataset.

---

## 5. Critical Challenge of Assumptions in `Batfish_ML_Risk_Ranking_Research_Plan.md`

Per Part XVII (§64–68), we challenge every core assumption in `Batfish_ML_Risk_Ranking_Research_Plan.md` against the verified empirical evidence.

### Assumption 1: "A weighted composite loss $L_r = w_p P_r + w_d D_r + w_f F_r$ is a good primary target for ML ranking."
- **Challenge (**VERIFIED-REPO**):** This formula is **methodologically flawed** because it combines two fundamentally different causal regimes:
  1. $F_r$ (fraction of baseline-carried flows affected): If $F_r$ measures steady-state rerouted/broken flows (`r_final`), V3 proved that Batfish computes it with **zero error ($R^2 = 1.000$)** before deployment. Including $F_r$ in $L_r$ creates **partial analytic target redundancy**—an ML model will achieve high $R^2$ and high Kendall's $\tau$ simply by predicting $F_r$ from `r_exact` or graph centrality, masking complete failure on the transient components $P_r$ and $D_r$.
  2. $P_r$ (packet loss fraction) and $D_r$ (outage duration): In our V4 protocol (`PILOT-PREREGISTRATION.md` §1–2), steady-state broken flows are *subtracted* so that $T_1 = \int_0^{T_{\text{obs}}} b_{\text{excess}}(t)\,dt$ already integrates transient flow-fraction $\times$ duration into a single physical quantity (lost flow-seconds). Adding $P_r$, $D_r$, and $F_r$ with arbitrary weights $w_p, w_d, w_f$ double-counts correlated quantities and reintroduces the V3 redundancy trap.
- **Required Fix:** **Never mix steady-state impact and transient disruption in one composite target.** Use Batfish's exact steady-state impact (`r_exact`, `r_broken_exact`, `r_rerouted_exact`) as a **deterministic Stage-1 filter or explicit baseline**, and restrict any runtime target strictly to **excess transient disruption** ($T_1$ or binary/ordinal transient loop occurrence $E_{\text{loop}}$).

### Assumption 2: "Pre-deployment topology and configuration features can predict continuous runtime transient disruption across repairs."
- **Challenge (**VERIFIED-REPO**):** In [`v4_transient/analysis/mechanistic/RESEARCH_VIABILITY_AUDIT.md`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/mechanistic/RESEARCH_VIABILITY_AUDIT.md) (§5, Table "Identifiability Analysis") and [`MODEL3_REPORT.md`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/mechanistic/MODEL3_REPORT.md) (§10–13), our own repository already proved that continuous $T_1$ is **not identifiable** from static pre-deployment configuration and topology features alone. Specifically:
  - In `V4C-04` (`drain-lo` on `t05_ring6`, 4 routers pushed: `corea`, `coreb`, `wan1`, `wan2`), a transient forwarding loop (`corea -> wan1 -> corea` and `wan1 -> corea -> wan1`) persisted for $\sim 0.35\text{ s}$ to $0.57\text{ s}$, yielding median $T_1 = 0.02292$.
  - In `EX-V4-01` through `EX-V4-05`, offline mixed-state analysis ([`analyze_mechanistic.py`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/mechanistic/analyze_mechanistic.py)) proved that mixed old/new forwarding states *also* contain directed cycles (affecting $14.7\%$ to $57.4\%$ of flows), yet their realized runtime $T_1$ was $100\times$ smaller ($3.85 \times 10^{-5}$ to $1.81 \times 10^{-4}$, well below the $6.944 \times 10^{-4}$ noise floor).
  - **Why?** Because in `V4C-04`, the serial `vtysh` push order (`corea` pushed before `wan1` and `coreb`) combined with OSPF LSA flooding and SPF hold-time caused `corea` to install its new FIB entry pointing to `wan1` *while `wan1` still held its old FIB entry pointing to `corea`* for hundreds of milliseconds. In the exploratory cases, either the serial push order updated the downstream router first, or intra-router LSA flooding updated both routers within the same SPF window ($<10\text{ ms}$).
- **Required Fix:** A pre-deployment model cannot predict wall-clock milliseconds of kernel/daemon race conditions without modeling **the deployment sequence $\sigma$ (which router is pushed in what order, with what inter-device delay)** and **directional upstream/downstream update order** (the core theorem of [RFC 6976 / oFIB](https://datatracker.ietf.org/doc/rfc6976/)).

### Assumption 3: "Deterministic baselines are just simple heuristics (like changed-device count or steady-state impact) that ML can easily beat."
- **Challenge (**PUBLISHED-LIT** & **VERIFIED-REPO**):** In networking literature, the strongest deterministic baseline for transient disruption during planned configuration changes is **not** changed-device count—it is:
  1. **RFC 5715 Potential Microloop Fraction (`pml_flow_frac` in [`v4_transient/v4lib/analytic.py`](file:///c:/Users/karth/network-research-lab/v4_transient/v4lib/analytic.py#L70-L84)):** The fraction of carried flows whose source can reach a directed cycle in the union of old and new next-hop graphs $G_{\text{old}}(d) \cup G_{\text{new}}(d)$.
  2. **Order-Aware Staged Mixed-State Cycle Traversal (`hybrid_state_features` in [`analyze_mechanistic.py`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/mechanistic/analyze_mechanistic.py#L175-L230)):** Given a fixed serial push order $\sigma = (u_1, \dots, u_k)$, walking the forwarding graph at each intermediate stage $s \in \{1, \dots, k-1\}$ where routers $\{u_1, \dots, u_s\}$ use their new SPF table (or local interface cost update) and $\{u_{s+1}, \dots, u_k\}$ use their old SPF table.
  3. **RFC 6976 oFIB Rank Violation Count:** Counting how many router pairs $(u_a, u_b)$ in the push sequence $\sigma$ violate the loop-free reverse-SPF / forward-SPF update ordering rule!
- **Critical Implication:** If an order-aware deterministic graph algorithm (`oFIB_violations` + `hybrid_state_features`) predicts which repair $(c_{i,j}, \sigma)$ will loop with $R^2 \ge 0.80$ or pairwise ranking accuracy $\ge 90\%$, **then the symbolic algorithm IS the scientific contribution, and ML is unnecessary** (or serves only to weight/combine symbolic features when multiple mechanisms interact). The research plan must embrace this rather than hide from it.

### Assumption 4: "We can easily generate 3–5 semantically valid Batfish-PASS repairs per incident across 200–300 incidents without generator shortcuts."
- **Challenge (**VERIFIED-REPO**):**
  - In V2 (`analysis/interim/VERDICT.md`), generating repairs from parametric templates (`correct`, `incomplete`, `regressive`) allowed a GBT to recover `repair_class` at **AUC = 0.975** and `fault_family` at **AUC = 0.9975**, completely invalidating the learned model.
  - In V3 (`docs/ANALYSIS-PLAN-V3.md` §12.1.2), attempting to fix this by drawing all classes from overlapping severity quantiles caused **59 of 64 deduplicated repairs to be cross-class collisions**, rendering `repair_class` void, while `mechanism` (`cost` vs. `blackhole`) was still recoverable at **AUC = 1.000**.
  - Furthermore, if Incident $i$ is "Link $(u,v)$ failed or is overloaded, restore reachability and move traffic off $(u,v)$," what are 3–5 *genuinely distinct* repairs that all pass the **same** Batfish specification?
    - Repair 1: Increase OSPF cost on single link $(u,v)$ (`cost-single`).
    - Repair 2: Increase OSPF cost on $(u,v)$ and tune an upstream/downstream backup link cost to balance paths (`cost-paired`).
    - Repair 3: Drain router $u$ by raising OSPF cost on all its transit interfaces (`node-drain`) pushed in **alphabetical order** $\sigma_{\text{alpha}}$.
    - Repair 4: Same `node-drain` (or multi-router metric adjustment) pushed in **reverse / oFIB-compliant order** $\sigma_{\text{oFIB}}$ vs. **anti-oFIB order** $\sigma_{\text{anti}}$.
    - Repair 5: Static route override or ECMP tie-breaking cost adjustment.
  - Notice that if all repairs of type "single-link cost increase on a leaf link" have $T_1 = 0$ and all repairs of type "4-router anti-oFIB drain" have $T_1 > 0$, a naive model will simply learn `n_devices_pushed`! Therefore, **within-mechanism and within-device-count candidate pairs** (e.g., two 3-router repairs with different topological positions or push orders) are mandatory.

---

## 6. Architecture Comparison: Deterministic Methods vs. Tabular ML vs. GNNs vs. CNNs

The user requested an objective, evidence-backed comparison of **deterministic methods**, **tabular ML**, **GNNs**, and **CNNs**, recommending only what the evidence justifies.

### Table 2: Comparative Evaluation of Modeling Paradigms for Candidate Repair Ranking

| Method Family | How It Represents a Candidate Repair $(G_i, C_i^0, c_{i,j}, \sigma)$ | Theoretical & Empirical Strengths | Fatal Weaknesses / Risks in This Domain | Evidence from Repo & Literature | Recommendation |
|---|---|---|---|---|---|
| **1. Deterministic / Symbolic Baselines** (Batfish `r_exact`, RFC 5715 `pml_flow_frac`, Staged Mixed-State Walk, RFC 6976 oFIB Rank Check) | Exact shortest-path DAGs $G_{\text{old}}(d), G_{\text{new}}(d)$ and intermediate staged forwarding graphs $G^{(s)}(d)$ under push order $\sigma$. | Zero training data needed; $100\%$ topology-size invariant; $R^2 = 1.000$ on steady-state $r$; directly captures causal mechanism of transient microloops (cycle in mixed FIB state). | Cannot natively calibrate noisy timing interactions when multiple mechanisms (e.g. OSPF timers + link down + static route) compete without empirical weights. | V2 `spec_widening_rule` beat all ML ($\text{AUC-PR}=0.814$); V3 Batfish RIB walk beat all ML ($R^2=1.000$); V4 Model 2/3 reconstructed `V4C-04` loop. (**VERIFIED-REPO**) | **MANDATORY PRIMARY BASELINE & FEATURE GENERATOR.** Must be implemented first; ML is justified *only* if it beats this on held-out topologies. |
| **2. Tabular ML & Pairwise Rankers** (LightGBM / XGBoost / `HistGradientBoosting`, `XGBRanker`, Random Forest, Ridge/Lasso) | Fixed-length vector of permutation-invariant graph scalars, config-diff descriptors, Batfish steady-state summaries, and symbolic staged-transition features. | Sample-efficient at $N \in [200, 1500]$ candidates across $12\text{–}48$ topologies; handles nonlinear interactions between symbolic cycle exposure, path length delta, and device count; supports grouped conformal intervals. | Can easily exploit generator shortcuts if features encode operator identity; cannot learn raw graph motifs not summarized in the feature table. | In V3, `HistGradientBoosting` and `RandomForest` achieved LOTO $R^2 = 0.848 / 0.845$ on 12 topologies (`FINAL-INDEPENDENT-V3-AUDIT.md` §7). All 3 external reviews in `FINAL-PLAN.md` §4.7 endorsed GBT as primary. (**VERIFIED-REPO**) | **RECOMMENDED PRIMARY LEARNED MODEL** (specifically pairwise ranking / regression via GBT + Ridge + RF on permutation-invariant features). |
| **3. Graph Neural Networks (GNNs)** (Message-Passing GNN / RouteNet-style Edge-Node GNN) | Routers as nodes $V$, links as directed edges $E$ with attributes $(\text{cost}_{\text{old}}, \text{cost}_{\text{new}}, \Delta\text{cost}, \text{push\_rank})$, plus global/flow readout. | Naturally permutation-equivariant ($f(P A P^\top, P X) = f(A, X)$); operates directly on variable-sized network graphs without padding. | **Severe small-cluster overfitting:** When grouped by topology, the effective sample size of independent graphs is $N_{\text{topo}} \in [12, 48]$, not $N_{\text{candidates}}$. Standard MPNNs also struggle to detect long directed cycles unless augmented with explicit path/walk features. | `FINAL-PLAN.md` §4.7 and `V4-PIVOT-AND-EXPANSION-PLAN.md` §32 both concluded GNNs are data-starved at $\le 48$ topologies (`torch` is not even installed in `.venv`). (**VERIFIED-REPO**) | **SECONDARY ABLATION ONLY** (tiny parameter-shared edge-conditioned GNN, $\le 20\text{k}$ params, run *only* if Gate G2 passes and $N_{\text{topo}} \ge 30$). |
| **4. Convolutional Neural Networks (CNNs)** (2D ConvNet over $N \times N$ adjacency/cost/path matrices) | Pads topology to $N_{\max} \times N_{\max}$ multi-channel tensor (e.g., $\text{Ch}_1 = A_{\text{old}}, \text{Ch}_2 = A_{\text{new}}, \text{Ch}_3 = \Delta\text{FIB}$). | Familiar deep learning architecture; can process dense all-pairs matrices if canonically ordered. | **Fundamentally mismatched inductive bias:** 2D spatial translation invariance ($3\times 3$ local pixel patches) has no physical meaning in an unordered adjacency matrix! Permuting router IDs changes the image completely ($f(P A P^\top) \ne f(A)$), and zero-padding leaks topology size $N$. | All 3 external reviews in `FINAL-PLAN.md` §4.7 ("CNN: no... All three reviewers agreed without reservation") and `PROJECT_HISTORY_AND_RESEARCH_EVOLUTION.md` §9 rejected CNNs for unordered network graphs. (**VERIFIED-REPO**) | **DO NOT USE AS A PRIMARY MODEL.** Drop CNN from the paper's core claims; at most include a 1-paragraph permutation-sensitivity negative baseline if required by an advisor. |

**CONCLUSION ON MODEL SELECTION:**  
The evidence unequivocally supports **Deterministic Symbolic Transition Analysis + Tabular Gradient-Boosted Ranking (`HistGradientBoosting` / Pairwise Ranker) + Grouped Conformal Prediction** as the core methodology, with a lightweight **Edge-Conditioned GNN** as an optional ablation if and only if the dataset reaches $\ge 30$ independent topologies. **CNNs should be removed from the primary research plan** unless explicitly required by a course rubric, in which case their non-invariance under node permutation must be demonstrated and contrasted against permutation-invariant tabular/GNN models.

---

## 7. Evidence-Based Feasibility Estimates (With Explicit Assumptions & Uncertainty)

In accordance with the prompt's strict honesty rule (*"Give separate evidence-based feasibility estimates for building the study, obtaining useful predictive results, and producing a publishable contribution. Explain the assumptions and uncertainty behind each estimate; never guarantee success or invent confidence"*), Table 3 provides structured, evidence-grounded feasibility ranges across the three dimensions.

> **Epistemic Note on Probability Ranges:** The percentage bands below are **subjective epistemic probability ranges** conditioned on the repository's measured throughput, error rates, and mathematical identifiability proofs—they are **not** frequentist guarantees.

### Table 3: Three-Dimensional Feasibility Assessment

| Dimension | Option 1: Original Plan As Written (`Batfish_ML_Risk_Ranking_Research_Plan.md`: Cornetto + $L_r$ + CNN/GNN on Continuous Runtime Loss) | Option 2: Redesigned Path A (Staged Update-Order-Aware Transient Risk Ranking on Controlled Multi-Family Topologies + Symbolic/Tabular ML) | Option 3: Redesigned Path B (Verification-to-Execution Gap, Spec-Completeness & Mechanistic Boundary Benchmark Paper — V1–V4 Synthesis + Batfish Scale) |
|---|---|---|---|
| **1. Feasibility of Building & Executing the Pipeline** | **Low–Moderate (25% – 40%)** | **High (80% – 90%)** | **Very High (90% – 95%)** |
| *Evidence & Assumptions for Dim 1* | **Why Low:** Cornetto's public dataset withholds `initial_configs/` for $230/231$ scenarios, uses Cisco IOS + ACLs + BGP + custom Batfish, and has a median of 69 routers (up to 754), which cannot run in Containerlab on a 16 GB laptop (**VERIFIED-WEB**). Building an IOS-to-FRR+`iptables` translator for 70-router networks will fail hardware and parser gates. | **Why High:** Reuses the already-validated FRR/Containerlab/Batfish toolchain (`verify_pilot` 16/16, V4 netlink FIB replay 99/100 valid runs, median runtime $100.6\text{ s}$) on topologies scaled to $6\text{–}18$ routers across 6 families (including subsampled Topology Zoo graphs $\le 18$ nodes). Assumes ~80–150 CPU-hours of Containerlab execution. (**VERIFIED-REPO**) | **Why Very High:** V1–V4 data already exist on disk and are audited; scaling the specification-completeness and staged-cycle analysis to 30–60 topologies in Batfish + offline symbolic replay takes $<10\text{ hours}$ on a single laptop with zero Containerlab OOM risk. (**VERIFIED-REPO**) |
| **2. Feasibility of Obtaining Useful Predictive ML Results (Beating Strongest Deterministic Baseline on Held-Out Topologies)** | **Very Low (< 10% – 15%)** | **Low–Moderate (30% – 50% for ML beating Symbolic; 70% – 85% for Symbolic + ML beating Steady-State Batfish)** | **N/A (Diagnostic / Negative ML + Positive Symbolic/Conformal Finding by Design)** |
| *Evidence & Assumptions for Dim 2* | **Why Very Low:** (a) Any steady-state component $F_r$ in $L_r$ is beaten by Batfish exact RIB walk ($R^2 = 1.000$, V3); (b) without controlling or modeling push order $\sigma$, continuous transient $T_1$ is unidentifiable from static configs (V4 Mechanistic Audit). Either the deterministic baseline wins ($R^2 \to 1$) or noise dominates ($R^2 \le 0$). | **Why Moderate & Uncertain:** When we control/record router push order $\sigma$ and generate multi-device repairs (`cost-paired`, `node-drain`, `ECMP-tie`, `area/redist`), symbolic staged-cycle features (`oFIB_violations`, `hybrid_cycle_exposure`) will strongly beat steady-state Batfish ($70\%\text{–}85\%$ likely). However, whether a *learned* GBT/GNN beats the *best symbolic staged-SPF rule* on held-out topologies (Gate G2) is genuinely uncertain ($30\%\text{–}50\%$) because mixed-state loop formation combined with FRR timer interactions may either be mostly captured by symbolic rules or too noisy across topologies. | **Why Robust:** Does not depend on ML beating symbolic verification; instead, rigorously proves *where* ML fails (generator shortcuts in V2, analytic redundancy in V3, timing unidentifiability in V4) and provides a symbolic + conformal decision framework. |
| **3. Feasibility of Producing a Defensible, Publishable Research Contribution** | **Low (15% – 25%)** | **Moderate–High (65% – 80%)** *(if preregistered so either Symbolic or ML winning is a valid systems contribution)* | **High (75% – 85%)** *(at IEEE NOMS / CNSM / IFIP Networking / NetAI Workshop / IEEE Access / COMNET)* |
| *Evidence & Assumptions for Dim 3* | **Why Low:** High risk of repeating V2 (generator leakage) or V3 (reviewers point out Batfish/Rela already computes steady-state impact) or V4 (95% zeros). | **Why Moderate–High:** If framed as **"Staged-Update Risk Ranking of Verified Network Repairs"** where *both* the symbolic mixed-state cycle analyzer and the ML ranker are contributions of the paper (evaluating when ML adds value over symbolic rules and when symbolic rules suffice), the paper succeeds **whether ML beats the symbolic rule by $+0.10$ NDCG or whether the symbolic rule dominates!** | **Why High:** Empirical measurement + negative/boundary ML papers with rock-solid reproducibility (byte-identical artifacts, 40/40 verifiers, microsecond kernel FIB replay, open dataset) are well-received at systems/network management venues (NOMS, CNSM, IM) when framed around verification completeness and deployment safety. |

---

## 8. Exact Changes Required to `Batfish_ML_Risk_Ranking_Research_Plan.md`

To turn `Batfish_ML_Risk_Ranking_Research_Plan.md` into a scientifically defensible study, the following **10 mandatory modifications** must be made to the plan before writing or running any experiment code:

### Table 4: Mandatory Revisions to the Research Plan

| Plan Section | Original Proposal in `Batfish_ML_Risk_Ranking_Research_Plan.md` | Defect / Scientific Risk | Required Modification |
|---|---|---|---|
| **§8 & §9 (Experimental Unit)** | Experimental unit is a static candidate configuration $c_{i,j}$ for incident $i$. | Ignores that transient loops in multi-router repairs depend critically on the **router deployment sequence $\sigma$** (`V4C-04` forensic proof + RFC 6976). | Redefine the experimental unit as a **staged repair plan** $p_{i,j} = (c_{i,j}, \sigma_{i,j})$, where $c_{i,j}$ is a Batfish-PASS config and $\sigma_{i,j}$ is the explicit, logged router push sequence. Include both order-varied repairs (same config, different push order) and config-varied repairs (different configs, canonical push order). |
| **§10 (Target Definition)** | Composite loss $L_r = w_p P_r + w_d D_r + w_f F_r$ combining steady-state affected flows $F_r$ with transient loss/duration. | $F_r$ is $100\%$ computable by Batfish (`r_exact` in V3, $R^2=1.000$). Including $F_r$ creates analytic target redundancy. | **Remove $F_r$ from the predicted target.** Treat steady-state blast radius `r_exact` as a deterministic Batfish output (either constrain all repairs for incident $i$ to have acceptable steady-state behavior, or use a two-stage lexicographic ranker where Stage 1 is exact Batfish steady-state impact and Stage 2 predicts **purely transient disruption**). Define the primary transient target as **Order-Conditioned Transient Disruption Area $T_1 = \int_0^{T_{\text{obs}}} b_{\text{excess}}(t)\,dt$** (with **within-incident pairwise rank $z_{a,b}$** under margin $\delta = 6.944\times 10^{-4}$ as the primary ranking metric) and **Transient Loop Occurrence $E_{\text{loop}} \in \{0,1\}$** as the primary binary event target. |
| **§12–16 (Datasets)** | Use Cornetto (231 scenarios) as primary configuration source; use LCORE-D and GNNet 2021 as complementary datasets. | Cornetto withholds `initial_configs` for $230/231$ scenarios, uses Cisco IOS + ACLs + BGP, and has median 69 routers (up to 754), breaking 16 GB laptop Containerlab limits. LCORE-D and GNNet have zero config repairs. | **Drop LCORE-D and GNNet 2021 completely.** Use **Internet Topology Zoo** subsampled graphs ($\le 18$ routers), Cornetto's small graph topologies (`topology.json` with $\le 20$ nodes, rendered natively into our verified FRR/Cumulus format), and our 6 procedural topology families (`chain/ladder`, `ring/metro`, `partial-mesh`, `campus/dual-core`, `Clos/ECMP`, `WAN/Topology-Zoo`) so the Same-Artifact Guarantee holds $100\%$. |
| **§18–20 (Candidate Generation)** | Generate 3–5 repairs per incident across 10 mechanisms (including redistribution, route policy, admin link state). | `distribute-list`/`access-list` are silently ignored by Batfish for FRR (Defect S-004); `shutdown` fails `P08` ($100\%$ in V3); blackholes have $T_1 = 0$ by definition. | Restrict candidate generation to constructs verified $100\%$ compatible between Batfish and FRR: (1) single-link OSPF cost tuning, (2) paired/multi-link symmetric/asymmetric cost tuning, (3) multi-router node drain (`cost` $\times 20$ on all interfaces of a transit router) under varied push orders $\sigma$, (4) ECMP tie-making/tie-breaking cost changes, and (5) secondary-area / static next-hop reroutes that preserve final reachability (`r_broken_exact == 0`). **Require every candidate to satisfy `r_broken_exact == 0` in the final state** so $T_1$ is never suppressed by permanent breakage. |
| **§22 (Pre-Deployment Features)** | Lists general topology, diff, and structural transition features without formalizing update order. | Without push-order features, Model 2/3 in V4 could not separate `V4C-04` from `EX-V4-01..05`. | Formalize **Group D (Order-Aware Symbolic Transition Features)**: (1) `pml_flow_frac` (RFC 5715 union-graph cycle fraction), (2) `staged_cycle_states` and `staged_cycle_flow_frac` (exact walk of intermediate states $s=1\dots k-1$ under push sequence $\sigma$), (3) `ofib_rank_violations` (number of pushed router pairs violating RFC 6976 reverse-SPF safe ordering), (4) `inter_router_push_hop_distance` (hop distance between consecutively pushed routers in $\sigma$), and (5) `ecmp_transient_split_delta`. |
| **§25 (Runtime Protocol)** | Fixed deployment order; poll forwarding/traffic behavior. | In V4, all routers were pushed in alphabetical name order (`sorted(push_plan)` in `PILOT-PREREGISTRATION.md` §4) with uncontrolled `docker exec` inter-router spacing, confounding router name with update order! | **Never tie push order solely to alphabetical router names!** Explicitly parameterize the push sequence $\sigma = (u_1, \dots, u_k)$ and fix a controlled inter-device push cadence $\Delta t_{\text{push}}$ (e.g., $\Delta t_{\text{push}} = 0.25\text{ s}$ or serial `vtysh` completion barrier with logged microsecond timestamps $t_{\text{push}}(u_m)$). |
| **§32–35 (Models & Baselines)** | Emphasizes CNN as "Main architecture candidate", GNN as comparator, and simple heuristics as deterministic baselines. | CNN violates node-permutation invariance; GNN overfits small topology counts; strongest deterministic baseline is symbolic staged-SPF / oFIB, not device count. | **Demote/remove CNN** (or relegate to a permutation-failure demonstration). Elevate **Symbolic Staged-SPF (`hybrid_cycle_flow_frac` + `ofib_rank_violations`)** to the **Primary Deterministic Baseline (B_sym)** alongside Batfish `r_exact` (B_bf) and RFC 5715 `pml_flow_frac` (B_pml). Make **Gradient-Boosted Trees / Pairwise Ranker (LightGBM / `HistGradientBoosting`)** the primary ML model, and keep a small **Edge-Conditioned GNN** as an exploratory ablation. |
| **§37 (Ranking Metrics & Tie Handling)** | Uses NDCG@k, Top-1 rate, Kendall's $\tau$, Regret@1, with optional tie margin $\delta$. | If $4$ of $5$ candidates for an incident have $T_1 < 6.944\times 10^{-4}$ (noise floor), standard Kendall's $\tau$ and Top-1 rank arbitrary noise! | **Mandate tie-aware ranking metrics** using the frozen resolution floor $\delta = 6.944 \times 10^{-4}$: two candidates $a, b$ with $|T_1(a) - T_1(b)| \le \delta$ are an **operational tie**. Report **Tie-Aware Pairwise Accuracy** (on pairs with $|T_1(a) - T_1(b)| > \delta$), **Safe-Top-1 Rate** (probability that the model's top-1 choice is within $\delta$ of the true minimum-loss candidate), and **Mean Decision Regret ($\text{Regret}@1$ in flow-seconds)**. |
| **§52 (Phase 7 Pilot)** | Run 8–12 topologies, 3–5 repairs per incident, check prevalence. | Does not include an **offline mechanistic discrimination gate** before running Containerlab! | Insert **Gate G0 (Offline Symbolic Discrimination Gate)** and **Gate G1 (24-Candidate Micro-Falsification Pilot)** *before* any 8–12 topology pilot. |
| **§58–59 (Contribution Framing)** | Frames paper around "ML risk ranking" with a negative-result fallback. | If symbolic staged-SPF (`B_sym`) achieves $0.90$ pairwise accuracy and ML achieves $0.91$, a pure "ML paper" looks incremental. | Frame the paper as **"Beyond Steady-State Verification: Staged-Update Risk Analysis and Ranking of Batfish-Verified Network Repairs."** Present *both* the pre-deployment symbolic staged-transition analyzer and the learned/conformal ranker as core contributions of the framework. |

---

## 9. Objective Go/No-Go Gates and Smallest Decisive Falsification Experiment

Before launching any large-scale data collection, the project must pass a strict sequence of **five falsifiable Go/No-Go gates (G0–G4)**.

### 9.1 What Is the Smallest Experiment That Could Decisively Falsify the New Hypothesis?

**CONCLUSION (The Decisive Falsification Experiment — Gate G0 + Gate G1):**  
The core scientific hypothesis of the redesigned study is:
> *Among multiple candidate repairs $(c_{i,j}, \sigma_{i,j})$ for the same incident $i$ that all pass Batfish steady-state verification and preserve final reachability (`r_broken_exact == 0`), pre-deployment structural and order-aware features can reliably rank which candidate repairs will induce above-floor transient disruption ($T_1 > 6.944 \times 10^{-4}$) vs. near-zero transient disruption in Containerlab/FRR.*

We can test and potentially **falsify this hypothesis in under 2.5 hours of compute** using a two-step micro-experiment:

1. **Step 1 — Offline Gate G0 (Zero Containerlab Compute, ~15 minutes):**
   - Take the existing 6 forensic cases (`V4C-04` and `EX-V4-01` through `EX-V4-05`) plus 6 incident scenarios across 3 topologies (`t05_ring6`, `t14_ladder8`, `t15_campus12`), each with 4 Batfish-PASS repair alternatives (including: (a) single-link cost repair, (b) paired-link cost repair, (c) multi-router drain in **oFIB-safe push order** $\sigma_{\text{safe}}$, and (d) the *exact same* multi-router drain in **anti-oFIB push order** $\sigma_{\text{anti}}$).
   - Enhance [`v4_transient/analysis/mechanistic/analyze_mechanistic.py`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/mechanistic/analyze_mechanistic.py) to compute **Order-Aware Per-Link LSA/SPF Transition Cycles** (specifically checking whether router $u_a$ updating its FIB *before* router $u_b$ creates a directed cycle **among neighbors whose direct link cost did not simultaneously invalidate the old next hop**, i.e., *remote/indirect* SPF disagreement vs. *local-link* cost update, plus RFC 6976 oFIB rank violation count).
   - **Falsification Criterion G0:** Does this refined pre-deployment symbolic model cleanly separate `V4C-04` from `EX-V4-01..05` AND predict zero cycles for $\sigma_{\text{safe}}$ vs. positive cycles for $\sigma_{\text{anti}}$?
     - If **NO**: Stop immediately. We still do not have a valid pre-deployment mechanistic discriminator. Pivot to **Path B** (publish the V1–V4 synthesis and Batfish specification-completeness benchmark).

2. **Step 2 — Runtime Micro-Pilot Gate G1 (24 Staged Candidates $\times 3$ Replicates = 72 Containerlab Runs, ~2 hours on 1 Laptop):**
   - Execute the 6 incidents $\times 4$ Batfish-PASS repairs ($24$ candidates $\times 3$ replicates = $72$ runs + $6$ no-op controls) in Containerlab with the frozen netlink FIB monitor (`ip -ts monitor link route nexthop`).
   - Crucially, because each incident includes both $\sigma_{\text{safe}}$ and $\sigma_{\text{anti}}$ (plus single-link and paired-link alternatives), this directly tests whether **update order and repair structure** causally control realized $T_1$ within the *same* incident!
   - **Falsification Criteria G1:**
     - **G1a (Within-Incident Contrast):** In at least **4 of the 6 incidents ($\ge 66.7\%$)**, at least one Batfish-PASS repair candidate must have replicate median $T_1 > 6.944 \times 10^{-4}$ AND at least one alternative Batfish-PASS repair candidate for the *same* incident must have replicate median $T_1 \le 6.944 \times 10^{-4}$ (with difference $> 2\delta$).
     - **G1b (Repeatability):** Within-candidate variance share on $\log_{10}(T_1 + \epsilon)$ or raw $T_1$ must be $\le 0.40$ ($\text{ICC}(1) \ge 0.60$).
     - **G1c (Causal Order Verification):** On matched config pairs $(c, \sigma_{\text{anti}})$ vs. $(c, \sigma_{\text{safe}})$, $\text{median } T_1(c, \sigma_{\text{anti}}) > \text{median } T_1(c, \sigma_{\text{safe}}) + \delta$ in at least $4/6$ incidents.
     - If **G1a, G1b, or G1c fails**: Stop Containerlab expansion immediately and execute **Path B**.

### 9.2 Complete Go/No-Go Gate Table (G0–G4)

| Gate | Stage | Exact Metric & Threshold | Decision if PASS | Decision if FAIL |
|---|---|---|---|---|
| **G0: Offline Mechanistic Identifiability** | Pre-Containerlab (Offline Python) | Refined order-aware symbolic model (`oFIB` + remote-SPF mixed-state cycle check) separates `V4C-04` from `EX-V4-01..05` without using runtime telemetry. | Proceed to 24-candidate Micro-Pilot (G1). | **NO-GO on runtime transient prediction.** Pivot to Path B (V1–V4 Negative/Boundary & Spec-Completeness Paper). |
| **G1: Micro-Pilot Within-Incident Contrast & ICC** | 6 incidents $\times 4$ PASS repairs $\times 3$ reps (72 runs, ~2 h) | $\ge 4/6$ incidents have both an above-floor PASS repair ($T_1 > 6.944\times 10^{-4}$) and a sub-floor PASS repair ($T_1 \le 6.944\times 10^{-4}$); $\text{ICC}(1) \ge 0.60$; validity $\ge 90\%$. | Proceed to Main Confirmatory Corpus (G2/G3). | **NO-GO on large Containerlab corpus.** Report G1 findings and pivot to Path B. |
| **G2: Shortcut & Leakage Audit** | Pre-Phase-3 on Frozen Confirmatory Manifest | Recoverability of generator template ID / emission order from allowed features has $\text{AUC} < 0.75$ within mechanism; zero post-deployment or ID columns in $X$. | Proceed to Confirmatory Execution & Ranking Evaluation. | **STOP & FIX generator:** balance mechanisms across risk strata or restrict evaluation to within-mechanism pairs. |
| **G3: Incremental Value Over Batfish Steady-State** | Confirmatory Evaluation (Held-Out Topologies, LOTO / LOFO) | Order-aware Symbolic Model (`B_sym`) OR Tabular ML (`GBT`) achieves Tie-Aware Pairwise Ranking Accuracy $\ge 0.70$ and reduces $\text{Regret}@1$ by $\ge 35\%$ over Batfish Steady-State (`r_exact`) and Device-Count heuristics (95% cluster-bootstrap CI excluding 0). | **GO for Primary Systems + Ranking Paper (Path A).** | Publish as rigorous negative result on pre-deployment transient ranking (Path B). |
| **G4: ML Increment Over Symbolic Staged-SPF** | Confirmatory Evaluation (LOTO / LOFO) | Tabular ML (`GBT`) or `GNN` improves Tie-Aware Pairwise Accuracy or $\text{NDCG}@1$ over `B_sym` (`oFIB` + staged cycle walk) with 95% cluster-bootstrap CI excluding 0. | Claim **Hybrid Symbolic + Learned Risk Ranker** as headline contribution. | Claim **Symbolic Order-Aware Pre-Deployment Analyzer (`B_sym`) + Conformal Triage** as headline contribution, reporting honestly that symbolic transition features capture the learnable signal without needing black-box ML! |

> **Why Gate G4 Is a Win-Win Design:** Notice that if Gate G3 passes, **you have a strong, publishable paper regardless of Gate G4's outcome!**
> - If **G3 PASSES and G4 PASSES**: The paper shows that combining symbolic staged-convergence features with GBT/GNN ranking beats both static Batfish verification and pure symbolic rules on unseen topologies.
> - If **G3 PASSES and G4 FAILS**: The paper shows that static Batfish verification (`r_exact`) fails to rank transient disruption among PASS repairs, while our **pre-deployment Order-Aware Staged-SPF Analyzer (`B_sym`)** accurately ranks repairs and eliminates $\ge 35\%$ of transient disruption regret—and demonstrates through rigorous ML ablations (GBT, RF, GNN) that the symbolic transition abstraction captures $100\%$ of the pre-deployment identifiable signal! In top networking venues (SIGCOMM, NSDI, CoNEXT, NOMS, CNSM), a white-box symbolic analyzer that beats black-box ML on real FRR containers is **more prized, not less**, than a black-box tree model.

---

## 10. Prioritized, Practical Action Roadmap & Safe Commands

### Phase 0: Immediate Preservation & Hygiene (Day 1 — Zero Compute)

1. **Preserve Historical Evidence Untouched:** Do not modify `data/pilot-v1`, `data/pilot-v2`, `data/pilot-v3`, or `v4_transient/results/pilot/`.
2. **Commit or Archive Untracked V4 Postmortem Evidence Safely:** Record an immutable SHA-256 manifest of `v4_transient/results/pilot/` and `analysis/V4-POSTMORTEM.md` so the V4 negative result is permanently anchored.
3. **Verify Environment & Standalone Tests (Safe Read-Only Commands):**
   ```powershell
   # Verify no tracked V2/V3 files were modified
   git status --short
   git diff --quiet HEAD -- data nrl pipeline

   # Run the 8 passing standalone V4 unit test suites
   .\.venv\Scripts\python.exe v4_transient\tests\test_core.py
   .\.venv\Scripts\python.exe v4_transient\tests\test_decisions.py
   .\.venv\Scripts\python.exe v4_transient\tests\test_gates.py
   .\.venv\Scripts\python.exe v4_transient\tests\test_controls_a4.py
   ```

### Phase 1: Execute Gate G0 — Offline Order-Aware Mechanistic Discriminator (Days 2–4 — Zero Containerlab Compute)

1. **Why Model 2 and Model 3 in `v4_transient/analysis/mechanistic/` Over-Predicted Cycles on `EX-V4-01..05`:**
   Inspecting [`analyze_mechanistic.py`](file:///c:/Users/karth/network-research-lab/v4_transient/analysis/mechanistic/analyze_mechanistic.py#L175-L230) (`hybrid_state_features`) reveals a crucial modeling flaw (**VERIFIED-REPO**):
   - In `hybrid_state_features`, when router $u_1$ is pushed (`ip ospf cost 200` on its local interfaces), the script immediately switches $u_1$ to its **final global SPF path map (`final`)** while keeping all other routers on `old`.
   - **Why that is physically inaccurate for `EX-V4-01..05` vs. `V4C-04`:** When a command `ip ospf cost 200` is executed on router $u_1$'s interface $(u_1, u_2)$, **only the directed edge $u_1 \to u_2$ changes cost in $u_1$'s local Router-LSA initially**; the reverse directed edge $u_2 \to u_1$ in the LSDB *still has the old cost* until $u_2$ is pushed!
   - Wait: in `analyze_mechanistic.py`, `stage_features` (Model 1) computed *global* SPF with directed costs (assuming all routers instantly saw the directed cost change), which predicted **0 cycles** for all 6 cases, whereas `hybrid_state_features` (Model 2) jumped straight to the symmetric final cost table on $u_1$, which predicted cycles for **all 6 cases**!
   - **Neither Model 1 nor Model 2 tested the true intermediate physical state:** At stage $s$ (after routers $A_s = \{u_1, \dots, u_s\}$ have executed their `vtysh` commands, resulting in directed cost vector $c^{(s)}$), a transient loop occurs when **Router $x$ has recomputed its SPF tree using directed costs $c^{(s)}$ while Neighbor $y$ is still forwarding using the previous SPF tree $c^{(s-1)}$ (or vice versa) during the LSA flooding / SPF hold-time window!**
2. **Action:** Write a read-only offline script `v4_transient/analysis/mechanistic/test_gate_g0_directed_asymmetric.py` that models:
   - Exact per-router directed link costs $c^{(s)}((u,v))$ after each device push $s$;
   - One-step asynchronous LSA/FIB lag between each pushed router $u_s$ (using $c^{(s)}$) and its upstream/downstream neighbors $v \neq u_s$ (still using $c^{(s-1)}$), plus RFC 6976 oFIB rank ordering;
   - Evaluate whether this physically faithful directed-lag model separates `V4C-04` from `EX-V4-01..05`.

### Phase 2: Execute Gate G1 — 24-Candidate Staged Repair Ranking Micro-Pilot (Days 5–7 — ~2 Hours Compute)

If Gate G0 passes:
1. Create a new, cleanly separated directory `v5_staged_ranking/` (leaving `v4_transient/` 100% untouched).
2. Select **6 incidents across 3 distinct topology families** (`t05_ring6`, `t14_ladder8`, `t15_campus12` or `t20_leafspine12`), where each incident represents a congested/degraded transit link or router requiring traffic engineering repair.
3. For each incident, generate **4 Batfish-SPEC-PASS repair candidates** that all achieve the intended traffic shift (`r_broken_exact == 0`):
   - `R1 (single-link)`: Single-link symmetric cost increase on the target link.
   - `R2 (paired-link)`: Paired-link cost adjustment balancing primary/secondary paths.
   - `R3 (multi-router oFIB-safe)`: Multi-router drain/metric shift pushed in **RFC 6976 oFIB-compliant order** $\sigma_{\text{safe}}$ with controlled $250\text{ ms}$ inter-device pacing.
   - `R4 (multi-router anti-oFIB)`: The **exact same target configuration as `R3`**, pushed in **reverse / anti-oFIB order** $\sigma_{\text{anti}}$ with controlled $250\text{ ms}$ inter-device pacing.
4. Preregister `v5_staged_ranking/docs/MICRO_PILOT_PREREGISTRATION.md` and run $24 \times 3 = 72$ population runs + $6$ no-op controls.
5. Check Gate G1a, G1b, and G1c.

### Phase 3: Confirmatory Study OR Path B Benchmark Paper (Weeks 2–5)

- **Branch 1 (If Gate G1 PASSES):**
  - Expand to **30–36 topologies across 6 families** (6–18 routers each, including 6 subsampled Internet Topology Zoo graphs and 6 Clos/ECMP topologies), **120–180 incidents**, and **4–5 staged repair candidates per incident** ($480\text{–}900$ candidates $\times 3$ replicates).
  - Evaluate **Deterministic Baselines** (`B_rand`, `B_devcount`, `B_bf_r_exact`, `B_pml_rfc5715`, `B_sym_staged_ofib`) vs. **Tabular ML** (`HistGradientBoosting` regressor & pairwise ranker, Random Forest, Ridge) vs. **Edge-Conditioned GNN ablation** under **Leave-One-Topology-Out (LOTO)** and **Leave-One-Family-Out (LOFO)** splits.
  - Apply **Hierarchical Conformal Risk Control** ([Dunn et al., JASA 2023](https://arxiv.org/abs/1809.07441); [Principato et al., 2024](https://arxiv.org/abs/2411.13479)) grouped by topology/incident to bound the maximum transient disruption of the top-1 selected repair.
- **Branch 2 (If Gate G0 or Gate G1 FAILS — Guaranteed Publication Floor):**
  - Do **not** run hundreds of Containerlab hours.
  - Consolidate the complete **V1–V4 Verification-to-Execution Gap & Boundary Study**:
    1. **Empirical False-Pass & Specification-Completeness Analysis (V2 + Batfish Scale-Out):** $P(\text{harm} \mid \text{PASS}) = 26.76\%$, causal $(a)/(b)/(c)$ attribution showing $76.2\%$ is specification incompleteness recoverable by nested specification widening, and proof of how synthetic repair operators create $\text{AUC} = 0.975$ shortcut illusions in ML models.
    2. **Exact Steady-State Equivalence Theorem & Validation (V3):** Proof across $26,738/26,738$ flows on $151/151$ candidates that Batfish's converged RIB computes steady-state blast radius $r$ with $R^2 = 1.000$ in $0.12\text{ s}$, rendering steady-state ML blast-radius prediction redundant.
    3. **Transient Convergence Identifiability Boundary (V4 + G0/G1):** Microsecond netlink FIB replay of 114 Containerlab runs proving that while mixed-state microloops (`V4C-04`) occur in real FRR daemons during Batfish-PASS updates, static pre-deployment configurations only determine *structural loop possibility*, whereas *realized disruption duration $T_1$* is governed by update ordering and asynchronous runtime timing.

---

## 11. Clickable References & Dataset Sources

### Academic Papers (**PUBLISHED-LIT** / **VERIFIED-WEB**)
1. **Batfish (NSDI 2015):** A. Fogel et al., *"A General Approach to Network Configuration Analysis,"* USENIX NSDI 2015. [https://www.usenix.org/conference/nsdi15/technical-sessions/presentation/fogel](https://www.usenix.org/conference/nsdi15/technical-sessions/presentation/fogel)
2. **Batfish Evolution (SIGCOMM 2023):** R. Beckett, R. Mahajan, T. Millstein, J. Padhye, D. Walker, *"Lessons from the Evolution of the Batfish Configuration Analysis Tool,"* ACM SIGCOMM 2023. [https://dl.acm.org/doi/10.1145/3603269.3604872](https://dl.acm.org/doi/10.1145/3603269.3604872)
3. **Rela — Relational Network Verification (SIGCOMM 2024):** X. Xu, Y. Yuan, Z. Kincaid, A. Krishnamurthy, R. Mahajan, D. Walker, E. Zhai, *"Relational Network Verification,"* ACM SIGCOMM 2024 / arXiv:2403.17277. [https://arxiv.org/abs/2403.17277](https://arxiv.org/abs/2403.17277)
4. **Cornetto Benchmark (2026):** I. Protogeros et al. (ETH Zürich NSG), *"Cornetto: Benchmarking LLM-Driven Network Configuration Repair,"* arXiv:2604.22513. [https://arxiv.org/abs/2604.22513](https://arxiv.org/abs/2604.22513)
5. **Config2Spec (NSDI 2020):** R. Birkner, D. Drachsler-Cohen, L. Vanbever, M. Vechev, *"Config2Spec: Mining Network Specifications from Network Configurations,"* USENIX NSDI 2020. [https://www.usenix.org/conference/nsdi20/presentation/birkner](https://www.usenix.org/conference/nsdi20/presentation/birkner)
6. **Control Plane Repair — CPR (SOSR 2017):** A. Gember-Jacobson, A. Akella, R. Mahajan, H. H. Liu, *"Automatically Repairing Network Control Planes Using an Abstract Representation,"* ACM SOSR 2017. [https://dl.acm.org/doi/10.1145/3050220.3050228](https://dl.acm.org/doi/10.1145/3050220.3050228)
7. **AED — Manageable Configuration Repair (CoNEXT 2020):** A. Abhashkumar, A. Gember-Jacobson, A. Akella, *"AED: Incrementally Synthesizing Policy-Compliant and Manageable Configurations,"* ACM CoNEXT 2020. [https://dl.acm.org/doi/10.1145/3386367.3431297](https://dl.acm.org/doi/10.1145/3386367.3431297)
8. **Campion (SIGCOMM 2021):** A. Tang, S. K. R. Kakarla, R. Beckett, E. Zhai, M. Brown, T. Millstein, Y. Tamir, G. Varghese, *"Campion: Debugging Router Configuration Differences,"* ACM SIGCOMM 2021. [https://dl.acm.org/doi/10.1145/3452296.3472925](https://dl.acm.org/doi/10.1145/3452296.3472925)
9. **SelfStarter (NSDI 2020):** S. K. R. Kakarla, A. Tang, R. Beckett, K. Jayaraman, T. Millstein, Y. Tamir, G. Varghese, *"Finding Network Misconfigurations by Automatic Template Inference,"* USENIX NSDI 2020. [https://www.usenix.org/conference/nsdi20/presentation/kakarla](https://www.usenix.org/conference/nsdi20/presentation/kakarla)
10. **Avoiding Transient Loops in IGP Convergence (INFOCOM 2005):** P. François and O. Bonaventure, *"Avoiding Transient Loops During IGP Convergence in IP Networks,"* IEEE INFOCOM 2005. [https://doi.org/10.1109/INFCOM.2005.1498497](https://doi.org/10.1109/INFCOM.2005.1498497)
11. **IETF RFC 5715 (Microloop Prevention Framework, 2010):** M. Shand and S. Bryant, *"A Framework for Loop-Free Convergence,"* RFC 5715. [https://datatracker.ietf.org/doc/rfc5715/](https://datatracker.ietf.org/doc/rfc5715/)
12. **IETF RFC 6976 (Ordered FIB / oFIB, 2013):** M. Shand, S. Bryant, S. Previdi, C. Filsfils, P. François, O. Bonaventure, *"Framework for Loop-Free Convergence Using the Ordered Forwarding Information Base (oFIB) Approach,"* RFC 6976. [https://datatracker.ietf.org/doc/rfc6976/](https://datatracker.ietf.org/doc/rfc6976/)
13. **IETF RFC 8333 (Micro-loop Prevention by Introducing a Local Convergence Delay, 2018):** S. Litkowski, B. Decraene, C. Filsfils, P. François, *"Micro-loop Prevention by Introducing a Local Convergence Delay,"* RFC 8333. [https://datatracker.ietf.org/doc/rfc8333/](https://datatracker.ietf.org/doc/rfc8333/)
14. **Abstractions for Network Update (SIGCOMM 2012):** M. Reitblatt, N. Foster, J. Rexford, C. Schlesinger, D. Walker, *"Abstractions for Network Update,"* ACM SIGCOMM 2012. [https://dl.acm.org/doi/10.1145/2342356.2342427](https://dl.acm.org/doi/10.1145/2342356.2342427)
15. **CrystalNet (SOSP 2017):** H. H. Liu et al., *"CrystalNet: Faithfully Emulating Large Production Networks,"* ACM SOSP 2017. [https://dl.acm.org/doi/10.1145/3132747.3132759](https://dl.acm.org/doi/10.1145/3132747.3132759)
16. **Gandalf (NSDI 2020):** Z. Li et al., *"Gandalf: An Intelligent, End-To-End Analytics System for Safe Deployment in Cloud-Scale Infrastructure,"* USENIX NSDI 2020. [https://www.usenix.org/conference/nsdi20/presentation/li](https://www.usenix.org/conference/nsdi20/presentation/li)
17. **RouteNet-Fermi (IEEE/ACM ToN 2023):** M. Ferriol-Galmés et al., *"RouteNet-Fermi: Network Modeling With Graph Neural Networks,"* IEEE/ACM Transactions on Networking, 2023. [https://doi.org/10.1109/TNET.2022.3230035](https://doi.org/10.1109/TNET.2022.3230035)
18. **Hierarchical Conformal Prediction (JASA 2023):** R. Dunn, L. Wasserman, A. Ramdas, *"Distribution-Free Prediction Sets for Two-Layer Hierarchical Models,"* JASA 118(544), arXiv:1809.07441. [https://arxiv.org/abs/1809.07441](https://arxiv.org/abs/1809.07441)
19. **Conformal Prediction for Hierarchical Data (2024):** G. Principato et al., *"Conformal Prediction for Hierarchical Data,"* arXiv:2411.13479. [https://arxiv.org/abs/2411.13479](https://arxiv.org/abs/2411.13479)
20. **Beta Calibration (AISTATS 2017):** M. Kull, T. Silva Filho, P. Flach, *"Beta Calibration: A Well-Founded and Easily Implemented Improvement on Logistic Calibration for Binary Classifiers,"* AISTATS 2017 (PMLR v54). [https://proceedings.mlr.press/v54/kull17a.html](https://proceedings.mlr.press/v54/kull17a.html)

### Dataset & Tool Repositories (**VERIFIED-WEB**)
- **Cornetto Code Repository (MIT License):** [https://github.com/nsg-ethz/cornetto](https://github.com/nsg-ethz/cornetto)
- **Cornetto Benchmark Dataset on HuggingFace:** [https://huggingface.co/datasets/iprotogeros/cornetto-benchmark](https://huggingface.co/datasets/iprotogeros/cornetto-benchmark)
- **LCORE-D Dataset v2 on Mendeley Data (CC BY 4.0):** [https://data.mendeley.com/datasets/77sztrg5ks/2](https://data.mendeley.com/datasets/77sztrg5ks/2)
- **GNNet Challenge 2021 Dataset (BNN-UPC):** [https://bnn.upc.edu/challenge/gnnet2021/dataset/](https://bnn.upc.edu/challenge/gnnet2021/dataset/)
- **Batfish `test-networks` Repository (Apache-2.0):** [https://github.com/batfish/test-networks](https://github.com/batfish/test-networks)
- **Pybatfish Differential Questions Documentation:** [https://pybatfish.readthedocs.io/en/latest/notebooks/differentialQuestions.html](https://pybatfish.readthedocs.io/en/latest/notebooks/differentialQuestions.html)
- **Containerlab Documentation:** [https://containerlab.dev/](https://containerlab.dev/)
- **FRRouting Documentation:** [https://docs.frrouting.org/](https://docs.frrouting.org/)
