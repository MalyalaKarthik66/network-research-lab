# Research assessment: Batfish + ML network repair risk ranking



Research documents reviewed

Path A requires validation



I've reviewed the research proposal, the V1–V4 experimental history, and Gemini's feasibility assessment. I've also examined the continuation instructions and cross-referenced the major disagreements between the original proposal and the redesigned approach.

My initial conclusion is:

Your original research objective is still valuable, but the original formulation needs a fundamental change. Path A is worth investigating, but it is not yet scientifically established.

I would not start building an ML model or generating hundreds of experiments now.

The most important lesson from your previous research is that a sophisticated ML pipeline cannot compensate for a target that is already deterministically computable or a dataset that does not contain the phenomenon you want to predict.

## A. The revised research idea in simple terms

Imagine a network engineer needs to repair a network problem.

There are three possible repairs:

- Repair A changes the cost of one link.
- Repair B changes the costs of two links.
- Repair C changes several routers to gradually move traffic.

All three repairs satisfy the required Batfish specifications.

However, there is another problem: how you deploy a repair can matter just as much as what configuration you deploy.

Consider two deployment strategies for exactly the same final configuration:

Strategy 1 — Safe update order

Intended to prevent transient loops

1. Update router B.
2. Allow its forwarding state to converge.
3. Update router A.
4. Verify forwarding stability.

Strategy 2 — Potentially unsafe update order

Potential transient-loop exposure

1. Update router A first.
2. Router A starts forwarding through B.
3. Router B still has its old forwarding entry pointing to A.
4. A temporary forwarding loop may occur.

Illustrative mechanism, not a new experimental result.

The important observation is that both strategies can end with exactly the same configuration.

Batfish can establish that the final configuration satisfies the specified properties. It does not, by that final-state result alone, establish that every intermediate forwarding state is safe.

Your revised research should investigate three separate questions:

1. Final-state correctness: Does the repair satisfy the required specifications?
2. Structural transition safety: Can the chosen deployment sequence produce dangerous intermediate forwarding states?
3. Runtime realization: Does that potential actually become packet loss, a forwarding loop, or measurable service disruption?

The proposed system should first perform deterministic analysis of the deployment sequence. Only if that analysis leaves a meaningful prediction problem should ML be introduced.

This is a much stronger research direction than simply training a neural network to predict network risk.

## B. Is your original research pipeline still correct?

Core architecture retained

Yes, but I recommend changing the ordering and adding several essential stages.

Your original pipeline was:

```
Dataset
   |
   v
Incident generation
   |
   v
Repair generation
   |
   v
Batfish verification
   |
   v
PASS candidates
   |
   v
Feature extraction
   |
   v
Containerlab + FRR
   |
   v
Runtime labels
   |
   v
ML training
   |
   v
Evaluation
```

The architecture is fundamentally sound. However, the revised experiment must recognize that a repair and its deployment procedure are two separate things.

### The revised complete pipeline

1\. Public topology and configuration sources

Topology Zoo · Batfish examples · compatible Cornetto scenarios · procedural topologies

2\. Experimental corpus construction

Topology conversion · FRR configuration · addressing · traffic · specifications

3\. Incident generation

Create reproducible network problems with known intended outcomes

4\. Alternative repair generation

Multiple genuinely different repairs for each incident

5\. Batfish verification

Final-state specifications · differential analysis · eligibility filtering

6\. Eligible Batfish-PASS repairs

Preserve FAIL and UNKNOWN records separately

7\. Deployment-plan generation

\\(p=(c,\sigma,\Delta t)\\)Target configuration · router update order · update pacing

8\. Pre-deployment feature extraction

Topology · configuration differences · routing · symbolic transition analysis

9\. Freeze experimental protocol and candidate manifest

Features, sequences, versions, hashes, execution rules

10\. Containerlab + FRR execution

Repeated, controlled runtime experiments

11\. Runtime measurement and ground-truth construction

Packet loss · FIB changes · forwarding loops · transient disruption · convergence

12\. Statistical analysis and leakage audit

Replicate aggregation · uncertainty · grouped data splits

13\. Deterministic and ML comparison

RFC baselines · symbolic analysis · GBT · optional GNN

14\. Generalization and final scientific conclusions

Unseen topologies · unseen incidents · ranking utility · regret · ablations

### Why each stage exists

| Stage                       | Scientific purpose                                             | Output                        |
| --------------------------- | -------------------------------------------------------------- | ----------------------------- |
| Dataset collection          | Obtain realistic graph structures and available configurations | Source inventory              |
| Corpus construction         | Convert sources into reproducible experimental networks        | Topology/configuration corpus |
| Incident generation         | Define the exact problem to solve                              | Incident specification        |
| Repair generation           | Create comparable alternatives                                 | Candidate configurations      |
| Batfish verification        | Establish final-state eligibility                              | PASS/FAIL/UNKNOWN             |
| Deployment-order generation | Define how each repair is applied                              | Ordered deployment plan       |
| Feature extraction          | Describe information available before deployment               | Feature records               |
| Runtime execution           | Observe actual transition behaviour                            | Raw traces                    |
| Label construction          | Quantify operational outcomes                                  | Runtime labels                |
| Model training              | Learn relationships, if any exist                              | Predictive models             |
| Evaluation                  | Establish generalization and incremental utility               | Statistical results           |

One important addition: freeze the experiment before runtime execution. This includes the candidate population, deployment sequences, feature definitions, runtime settings and evaluation splits.

You should not generate candidates, inspect their runtime labels, and then selectively keep the interesting ones.

### Three things that must be separated

This distinction is particularly important.

1\. Dataset collection

Finding existing resources such as Topology Zoo, Cornetto and Batfish examples.

2\. Experimental corpus construction

Building your own usable network environments from those resources. This includes:

- Router configurations.
- IP addressing.
- Routing protocols.
- Link costs.
- Traffic flows.
- Golden/reference configurations.
- Network specifications.

3\. Incident and repair generation

Creating network problems and multiple alternative solutions for each problem.

A public topology is not automatically an experimental dataset. It becomes part of your experimental corpus only after you have constructed and validated the missing elements.

## C. What exactly changes from your original proposal?

There are six major changes.

| Original approach                          | Revised approach                                          |
| ------------------------------------------ | --------------------------------------------------------- |
| Candidate = configuration                  | Candidate experiment = configuration plus deployment plan |
| Cornetto as primary source                 | Independently constructed, compatible corpus              |
| Predict composite operational risk         | Separate steady-state and transient outcomes              |
| CNN/GNN/GBT comparison                     | Symbolic baseline first, GBT second                       |
| Simple deterministic heuristics            | RFC-based and staged-transition analysis                  |
| Runtime data used after feature extraction | Deployment sequence explicitly included before runtime    |

The mathematical change is important.

Originally:

\\[ c\_{i,j}=\text{candidate repair} \\]

Now:

\\[ p\_{i,j,k}=(c\_{i,j},\sigma\_{i,j,k},\Delta t) \\]

Where:

- \\(c\\): final target configuration.
- \\(\sigma\\): ordered list of routers receiving changes.
- \\(\Delta t\\): controlled inter-device deployment pacing.

One repair can have multiple deployment plans.

For example:

```
Incident I-001
     |
     +--- Repair C1
     |       |
     |       +--- Plan P1: A -> B -> C
     |       +--- Plan P2: C -> B -> A
     |
     +--- Repair C2
             |
             +--- Plan P3: A -> C -> B
```

This allows two different experiments:

- Same final configuration, different deployment sequences: isolates update-order effects.
- Different final configurations, comparable deployment procedures: investigates repair-structure effects.

This is a substantially better experimental design.

However, one technical qualification is essential: router configuration push order is not necessarily the same as actual FIB installation order. OSPF LSA propagation, LSDB updates, SPF scheduling and kernel installation can occur asynchronously. You must record both the management-plane push events and actual forwarding-state transitions.



RESEARCH_FEASIBILITY_AND_ACTION_PLAN(1).md

PROJECT_HISTORY_AND_RESEARCH_EVOLUTION(1).md



## D. Public dataset decision

Decision: build your own primary experimental corpus

I disagree with the original proposal's decision to make Cornetto the primary dataset.

Cornetto is useful, but its actual contents do not match your experimental requirements.

### Dataset comparison

| Resource              | What it provides                                                                          | What it lacks                                                                  | Recommended role        |
| --------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ----------------------- |
| Cornetto              | Faulty configurations, topology graphs, formal specifications, repair benchmark scenarios | Most reference configurations, multiple repair alternatives and runtime labels | Secondary source        |
| Internet Topology Zoo | Real-world-inspired network graph structures in GML/GraphML                               | Configurations, incidents, routing behaviour and runtime labels                | Primary topology source |
| Batfish test-networks | Configuration snapshots and network examples                                              | Matched incidents, competing repairs and runtime labels                        | Engineering fixtures    |
| LCORE-D               | 407 hours of monitoring and fault-related observations                                    | Matching configurations, repair candidates and Batfish verification            | Exclude from main study |
| GNNet Challenge 2021  | Simulated topologies, traffic matrices, delay, jitter and packet-loss measurements        | Batfish verification, staged repairs and routing convergence experiments       | Exclude from main study |

### 1. Cornetto — secondary, not primary

[Reproducing ‘Routenet: Leveraging Graph Neural Networks for network modeling and optimization in SDN’ | by Janani Vijayarajan | Medium](https://images.openai.com/static-rsc-4/rmQZ75Uib-uuEVP-AepS0nW21WtSiEzbhi-YQdcMmlUW892py6c3bFPffLzH0SGf8ApL5BK-3-rW0vp5zikBrw90-AKdGgg-CmSekLA_CYLVe4rBu8UBtTmXURWgOXuv56WvYmgTckNohZjzb_z7XSasPEqHyOn4OP4duITwfNI?purpose=inline)

[Cornetto GitHub repository](https://github.com/nsg-ethz/cornetto?utm_source=chatgpt.com)

Paper: arXiv:2604.22513

MIT license, according to the audited release

Verified findings from the audit:

- 231 scenarios, not 231 unique topologies.
- Router counts range from 20 to 754.
- Median router count: 69.
- Only four scenarios have 20 or fewer routers.
- 230 of 231 scenarios omit the original working configurations and `fault_metrics.csv`.
- No scenario supplies the multiple Batfish-PASS repair alternatives and independent runtime measurements your study needs.

The Cisco IOS configuration constructs and custom Batfish image also create compatibility problems with your existing FRR environment.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



My decision: use Cornetto for repair-scenario ideas, specification research, graph structures and a possible separate Batfish-only evaluation. Do not build the main Containerlab experiment around it.

### 2. Internet Topology Zoo — primary topology source

[PPT - IPv6 in Internet2 PowerPoint Presentation, free download - ID:20327](https://images.openai.com/static-rsc-4/svQHb1pgU0ksGXSBZFTaf3JF0BxUbRUq_kij9lfc76S8MQLvjSzAy5rHp8zDFrwH32ZKvCMbP9IUl7PSL5v_GQ-H3E2FU9xb8W4eQUNHEW8i-BLVymP00SQBxouuR2iorCNZG0v_-BpoEBmPwLRQWdkTzG7yiDiibcc_uqAs7X8?purpose=inline)

[Topology Zoo dataset](https://topology-zoo.org/dataset.html?utm_source=chatgpt.com)

GML and GraphML topology structures

This is a much better starting point for your topology corpus.

It contains more than 250 network topologies, including real-world network maps.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://topology-zoo.org\&sz=32)

topology-zoo.org+1



However, these graphs do not give you complete router configurations, routing protocol state, traffic matrices or transient runtime labels.

You must generate those elements.

Also, verify licensing and provenance for each topology before redistribution; do not assume that every file has identical reuse terms.

### 3. Batfish test networks — engineering fixtures

[Batfish. Введение / Хабр](https://images.openai.com/static-rsc-4/RCP1uqe1K5FmmHgj6ddtF18IrH_kL09bUKK6vaw11S2hdn1n1CKhZ_f7kjy6yQa2XF661sUUejLvdLKzyr-mrpb12ATcR7CPaMHvDR3x5K9XZXeUObSDfJon2WcvF7tTWso0Kbnh69UHG2N2xhUPJ_wS1i4ycIzqCxYYsP88Nq8?purpose=inline)

[Batfish test-networks](https://github.com/batfish/test-networks?utm_source=chatgpt.com)

Parser and verification examples

The feasibility audit identified seven network directories, including Internet2 examples and several large synthetic networks.

The smaller Internet2 examples are useful for checking whether your configuration conversion and Batfish analysis work.

They are not a labelled repair-risk dataset.

### 4. LCORE-D — exclude from primary experiments

[LCORE-D Dataset v2](https://data.mendeley.com/datasets/77sztrg5ks/2?utm_source=chatgpt.com)

The official record describes 407 hours of monitoring data and multiple induced and naturally occurring fault events. It is licensed CC BY 4.0.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://data.mendeley.com\&sz=32)

Mendeley Data



It is valuable for studying monitoring and fault detection, but there is no matching candidate-repair experiment.

Do not attach its labels to your own topology candidates.

### 5. GNNet 2021 — exclude from primary experiments

[GNNet Challenge 2021](https://bnn.upc.edu/challenge/gnnet2021/dataset/?utm_source=chatgpt.com)

This dataset provides simulated networks, routing configurations, traffic matrices and performance measurements from OMNeT++.

Its main objective is network performance prediction, particularly delay prediction, rather than configuration-change convergence safety.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://bnn.upc.edu\&sz=32)

bnn.upc.edu



It is useful for a separate GNN/digital-twin research direction, not this experiment.

### My recommended dataset architecture

Main experimental corpus

Your own corpus

- Topology Zoo graph structures.
- Selected Batfish example configurations.
- Small procedural topologies.
- Generated FRR configurations.
- Generated incidents and repair alternatives.
- Your own Batfish verification results.
- Your own Containerlab/FRR runtime measurements.

Supporting resources

- Cornetto: repair and specification reference.
- LCORE-D: telemetry methodology reference.
- GNNet: optional graph-learning reference.
- Batfish test networks: parser and verification tests.

These resources can inform the same project, but their records must not be merged into a false matched training dataset.

Important hardware decision: start with approximately 6–12 routers per experimental topology. Your previous repository demonstrated operation with roughly 16–19 FRR containers under its tested environment. Do not assume that every larger topology will run reliably on your laptop.

## E. The strongest version of the new hypothesis

I would rewrite Gemini's hypothesis.

The current version is still too broad because it combines structural susceptibility and actual runtime disruption.

### Recommended research hypothesis

> Among multiple alternative network repairs satisfying the same Batfish final-state specifications, the deployment sequence and the topology-dependent interaction between old and new forwarding states determine measurable differences in transient forwarding disruption. A pre-deployment staged-transition analyzer can identify structural exposure, and its features may improve within-incident ranking of deployment plans over steady-state verification and simpler deterministic baselines.

There are two hypotheses inside this statement.

H1 — Structural hypothesis

Deployment order and mixed forwarding states can create different structural transient hazards even when the final configuration is identical.

H2 — Predictive hypothesis

The structural features available before deployment contain enough information to rank runtime disruption meaningfully on unseen topologies.

These must be tested separately.

H1 can be true while H2 is false.

For example, a symbolic algorithm may correctly identify that a forwarding cycle is possible, but the actual loop may last 2 milliseconds in one execution and 300 milliseconds in another.

That difference matters enormously.

### F. What Batfish, RFC 5715 and RFC 6976 establish

[Batfish を使ってネットワーク構成を可視化してみよう (1) #Network - Qiita](https://images.openai.com/static-rsc-4/3l8b4kx3wZxBSLO9KUoaohkgxkFEr38SvJI84fe1fBeiSznfCu5yGD2YzFLHTVz-9TaUH3TgjIhElxIEtEudpbVp_WSLFcqaPF0aETpMVee1Anm4oQXY-GzJQNK0UXEj3C4NjATHcsP2Vi0bn3IQeDTplf-oaN9W6HwKCdZJjg0?purpose=inline)

Batfish

Analyzes network configurations and verifies specified network properties under its modeled network semantics. It supports differential configuration analysis.

It does not automatically prove the safety of every asynchronous intermediate deployment state.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



[How to Configure Microloop Avoidance in OSPFv2 Segment Routing Networks | Junos OS | Juniper Networks](https://images.openai.com/static-rsc-4/_TsLG-fcVrLUIpqs4tvQ0EJ2f1arEh3GmkiJNtKXd1uT75_WV6BTl4jLU7ZtxyuSEp1xP042i-UNkW6Wf0KOxz10B2mywj6i3O4L6m_Dss2r4C-0MpD5Qqq3BTpSJRn9oYPFYf5to7XNUVXVUIQDLr1cUh6-nh2AEmmbjiC6n3o?purpose=inline)

RFC 5715

Explains how inconsistent forwarding information during convergence can create microloops, and describes prevention and mitigation approaches.

It provides the conceptual and analytical foundation for studying transient loop susceptibility.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.rfc-editor.org\&sz=32)

RFC Editor+1



[Cisco Nonstop Forwarding with Stateful Switchover Deployment Guide  \[High Availability\] - Cisco Systems](https://images.openai.com/static-rsc-4/bqGuljjB71r414YDjzjQ2ddMrfEKGjfrQniiIA4tMMQ6bOpZ7eHw8uWBpbutvwn91xthpwkIt5uauVF_BAVAHSheZlJ53MPYPGj6wdvfv8XhVtz2XphJqROOA5yxR6l8soxSw5pc6zlQ683OOP2ZmJvGPNlxFO6aP2lTJtcVqnQ?purpose=inline)

RFC 6976

Describes how FIB updates can be ordered to prevent transient loops under its specified conditions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.rfc-editor.org\&sz=32)

RFC Editor+1



There is an important qualification to Gemini's interpretation.

RFC 6976 is an informational framework, not a guarantee that any manually chosen router-push sequence will be loop-free.

Its assumptions include:

- A supported oFIB convergence mechanism.
- Participating routers being oFIB-capable.
- An applicable, classified network event.
- Appropriate ordering and convergence coordination.
- Its stated failure-model restrictions, including the single-failure limitation.

The document itself describes the mechanisms as illustrative and notes that additional protocol specification work is needed.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.rfc-editor.org\&sz=32)

RFC Editor



I would therefore use RFC 6976 as a theoretical deterministic baseline, not assume that your existing FRR 8.4.1 containers implement oFIB.

### A critical problem with Gemini's G0 proposal

Gemini proposes improving the old mixed-state model by introducing directed asymmetric link costs and a one-step asynchronous LSA/FIB lag.

This is a reasonable hypothesis to investigate, but it is not yet a physically faithful model of OSPF convergence.

Actual convergence involves several distinct processes:

1. Configuration commands are applied to a device.
2. The device originates or updates routing advertisements.
3. LSAs propagate to other routers.
4. Each router updates its link-state database.
5. SPF computations are triggered and scheduled.
6. FIB changes are installed.
7. The kernel begins forwarding using the updated entries.

These processes do not necessarily happen in the same order or at the same speed.

A one-step old/new forwarding abstraction may identify possible cycles, but it cannot automatically establish the actual asynchronous state space.

My recommendation: call the proposed model a staged mixed-state abstraction initially. Validate its predictions against actual captured LSA, SPF and FIB events before describing it as a faithful OSPF convergence model.

### Possible versus observed loops

Keep these concepts separate:

| Concept              | Meaning                                                  |
| -------------------- | -------------------------------------------------------- |
| Potential loop       | A modeled intermediate forwarding graph contains a cycle |
| Observed FIB loop    | Captured forwarding-table states reconstruct a cycle     |
| Observed packet loop | Actual packets exhibit repeated forwarding               |
| Measured disruption  | Traffic is lost or service becomes unavailable           |
| Disruption duration  | How long the measured problem persists                   |

A structural cycle does not establish packet loss or outage duration.

This distinction should be central to the paper.

## G. Revised experimental data model

This is one of the most important architectural changes.

I recommend maintaining separate records for repairs and deployment plans.

### 1. Entity relationships

```
TOPOLOGY
   |
   v
INCIDENT
   |
   v
REPAIR CANDIDATE
   |
   +-----------------------+
   |                       |
   v                       v
TARGET CONFIGURATION   BATFISH RESULT
   |
   v
DEPLOYMENT PLAN
   |
   +------ Deployment order
   |
   +------ Inter-device pacing
   |
   +------ Execution policy
   |
   v
PRE-DEPLOYMENT FEATURES
   |
   v
RUNTIME EXECUTIONS
   |
   +------ Replicate 1
   +------ Replicate 2
   +------ Replicate 3
   +------ Replicate N
   |
   v
GROUND-TRUTH AGGREGATES
   |
   v
RANKING EVALUATION
```

### 2. Recommended database tables

| Table                    | One row represents                | Important fields                              |
| ------------------------ | --------------------------------- | --------------------------------------------- |
| `topologies`             | One network graph                 | topology_id, family, graph_hash, router_count |
| `incidents`              | One network problem               | incident_id, topology_id, baseline_hash       |
| `candidate_repairs`      | One alternative repair            | repair_id, incident_id, target_config_hash    |
| `target_configurations`  | One immutable final configuration | config_hash, device_configs                   |
| `deployment_plans`       | One way to deploy a repair        | plan_id, repair_id, sequence, pacing          |
| `batfish_verification`   | One verification result           | repair_id, spec_id, status                    |
| `predeployment_features` | One plan's available features     | plan_id, feature_version, values              |
| `runtime_executions`     | One actual execution              | run_id, plan_id, replicate                    |
| `runtime_metrics`        | Measurements from one execution   | run_id, packet_loss, loops, T1                |
| `ground_truth_labels`    | Aggregated outcome                | plan_id, mean_T1, median_T1, uncertainty      |
| `dataset_splits`         | Group assignment                  | entity_id, split                              |
| `environment_manifest`   | Environment configuration         | image_digest, FRR_version, kernel             |

Use immutable hashes to connect the exact configuration tested by Batfish with the configuration executed by FRR.

### 3. Preventing generator leakage

Your V2 and V3 experiences make this mandatory.

Suppose:

```
Repair family A -> Always safe
Repair family B -> Always harmful
```

A model can simply memorize the repair family.

It has learned nothing about operational risk.

I recommend:

- Generate alternatives within the same incident.
- Include same-configuration/different-order comparisons.
- Include different-configurations with comparable device counts.
- Randomize execution order.
- Avoid alphabetical router deployment as the default.
- Deduplicate identical configurations.
- Detect near-duplicate repairs.
- Keep generator provenance outside the feature matrix.
- Hold out entire repair families when feasible.

### Forbidden model columns

```
topology_id
incident_id
repair_id
plan_id
candidate_id
run_id
replicate_id
generation_order
generator_template
repair_family
file_path
configuration_filename
runtime_timestamp
execution_duration
retry_count
run_validity
observed_T1
packet_loss_after_deployment
observed_FIB_events
observed_loop_duration
```

IDs are allowed for grouping, joining, auditing and splitting. They are not prediction features.

## H. Define the correct research target

I disagree with retaining the original composite target:

\\[ L_r=w_pP_r+w_dD_r+w_fF_r \\]

The problem is that steady-state impact and transient disruption are different phenomena.

V3 already demonstrated that the steady-state component can be computed exactly from Batfish's routing information in the tested environment.

### My recommendation: separate two layers

Layer 1 — Final-state eligibility and impact

Use Batfish to establish:

- Required reachability.
- Required specifications.
- Intended traffic movement.
- Final broken-flow count.
- Final rerouted-flow count.

This is not the ML prediction target.

Layer 2 — Transient operational disruption

Use independent runtime measurements.

The strongest initial continuous target is the V4-style excess transient disruption area:

\\[ T_1=\int_0^{T\_{\mathrm{obs}}}b\_{\mathrm{excess}}(t)\\,dt \\]

This represents the accumulated fraction of temporarily disrupted traffic over time.

It is important to preserve the precise V4 implementation and normalization if reusing its formula.

However, the old V4 noise floor must not automatically become the new study's threshold. It was established for a particular measurement protocol.

### Comparison of possible targets

| Target                           | Advantages                                    | Limitations                                      | Decision                       |
| -------------------------------- | --------------------------------------------- | ------------------------------------------------ | ------------------------------ |
| Continuous \\(T_1\\)             | Measures magnitude and duration together      | Runtime variability and timing sensitivity       | Primary candidate              |
| Binary loop occurrence           | Easy to interpret                             | A tiny loop and a long loop are treated equally  | Secondary                      |
| Above-noise-floor disruption     | Helps distinguish measurable events           | Sensitive to threshold choice                    | Secondary                      |
| Ordinal risk categories          | Easy for engineers to interpret               | Requires defensible category boundaries          | Later                          |
| Within-incident pairwise ranking | Directly matches the repair-selection problem | Requires reliable differences between candidates | Primary evaluation formulation |
| Weighted composite loss          | Combines multiple operational concerns        | Arbitrary weights and double-counting            | Remove initially               |

### What should be measured?

I would collect the following.

| Measurement                     | Purpose                              |
| ------------------------------- | ------------------------------------ |
| Packets transmitted             | Traffic denominator                  |
| Packets received                | Packet-loss calculation              |
| Per-flow reachability over time | Affected-flow measurement            |
| Transient disruption area       | Primary continuous outcome           |
| Actual packet-loop observations | Evidence of forwarding loops         |
| FIB event timestamps            | Forwarding-state transition timeline |
| LSA/SPF event information       | Control-plane convergence timeline   |
| Time to stable forwarding       | Convergence measurement              |
| Final reachability              | Final-state validation               |
| Invalid-run reason              | Measurement integrity                |

Do not equate FIB event count with operational risk.

A router may install many FIB entries without causing disruption.

Similarly, a captured FIB cycle is not automatically proof that every affected packet was lost.

### Ranking formulation

For candidates \\(a\\) and \\(b\\) belonging to the same incident:

\\[ a\prec b \quad \text{if} \quad T_1(a)\<T_1(b) \\]

But only if the difference is sufficiently large to be meaningful.

Define a practical tie margin \\(\delta\\) based on independently measured instrument resolution and no-op variability.

\\[ |T_1(a)-T_1(b)|\leq\delta \\]

means an operational tie.

This prevents the model from being rewarded for predicting meaningless numerical differences.

### Risk score versus probability

Keep these separate:

- Ranking score: used to sort candidates.
- Event probability: estimated probability of a defined event.
- Expected loss: estimated probability multiplied by conditional severity.

Initially, produce a ranking score, not a claim such as 90% probability of safety.

## I. Which model architecture should you use?

My recommendation is substantially different from your original CNN/GNN/GBT plan.

1\. Deterministic symbolic analysis

Mandatory first

This is the strongest baseline and potentially the main research contribution.

- RFC 5715 potential microloop analysis.
- RFC 6976 ordering analysis.
- Mixed-state forwarding graphs.
- Staged-cycle exposure.

2\. Gradient-boosted trees

Primary ML candidate

Start with scikit-learn HistGradientBoosting and interpretable regression/ranking baselines.

Learn interactions between topology, configuration and symbolic features.

3\. Graph Neural Network

Optional experiment

Use a small edge-conditioned GNN only if independent topology diversity and sample size justify it.

4\. CNN

Remove from primary plan

Adjacency matrices depend on router ordering. A CNN may learn arbitrary matrix arrangements rather than graph structure.

### Required comparison

| Baseline/model                    | What it establishes              |
| --------------------------------- | -------------------------------- |
| Random ranking                    | Minimum performance              |
| Changed-device count              | Simple deployment complexity     |
| Batfish exact steady-state impact | Existing verification capability |
| RFC 5715                          | Potential microloop exposure     |
| RFC 6976                          | Update-order safety baseline     |
| Symbolic staged-transition model  | Intermediate forwarding exposure |
| Ridge regression                  | Simple learned baseline          |
| Random Forest                     | Nonlinear tabular baseline       |
| Gradient boosting                 | Strong tabular learner           |
| Pairwise ranker                   | Direct ranking optimization      |
| GNN                               | Optional graph-native comparison |

The scientific rule should be:

\\[ \text{ML is useful only if it adds value beyond }B\_{\mathrm{sym}} \\]

Here \\(B\_{\mathrm{sym}}\\) is your strongest deterministic symbolic baseline.

If the symbolic model performs better, that is a valid finding. Do not manufacture a reason to use ML.

## J. Evaluation protocol

The main problem in previous versions was not simply model accuracy. It was whether the model learned something transferable.

### 1. Data splitting

Use:

- Leave-One-Topology-Out (LOTO).
- Leave-One-Topology-Family-Out (LOFO).
- Incident-grouped evaluation.
- Repair-family holdouts.

The strictest evaluation should hold out entire topology families, where the dataset allows it.

Do not put different deployment plans for the same underlying repair into separate train and test sets.

Likewise, never split runtime replicates of the same plan across training and testing.

### 2. Ranking metrics

I recommend these priorities:

| Metric                      | Priority  |
| --------------------------- | --------- |
| Tie-aware pairwise accuracy | Primary   |
| Regret\@1                   | Primary   |
| Safe-Top-1 rate             | Primary   |
| NDCG\@k                     | Secondary |
| Kendall's tau-b             | Secondary |
| MAE/RMSE for \\(T_1\\)      | Secondary |

Regret\@1 is particularly meaningful:

\\[ Regret\@1=T_1(\text{selected})-\min_c T_1(c) \\]

It measures how much additional transient disruption the engineer experiences by choosing the model's top-ranked repair instead of the empirically safest alternative.

### 3. Statistical reliability

Use hierarchical or cluster bootstrap:

1. Sample topology groups.
2. Sample incidents within selected topologies.
3. Preserve candidate and replicate relationships.

Do not bootstrap individual candidate rows as if they were independent observations.

### 4. Ablation experiments

Test these separately:

- Topology-only.
- Configuration-difference-only.
- Batfish-only.
- RFC 5715-only.
- RFC 6976-only.
- Staged-transition-only.
- All symbolic features.
- Symbolic plus GBT.

This will reveal whether the model learns something beyond the deterministic algorithm.

### 5. The actual success criterion

Do not define success as achieving a particular AUC.

The important question is:

Does your system consistently select safer repairs on previously unseen topologies, and does it reduce decision regret compared with the strongest deterministic baseline?

That is the result worth investigating.

## K. Critical review of Gemini's G0–G4 gates

I agree with Gemini's decision to introduce early falsification gates. I do not agree with retaining all its proposed thresholds.

| Gate             | Gemini's proposal                                 | My assessment                                                       |
| ---------------- | ------------------------------------------------- | ------------------------------------------------------------------- |
| G0               | Separate V4C-04 from five exploratory cases       | Useful mechanistic sanity check, not generalization                 |
| G1               | Six incidents, three topologies, three replicates | Too small for a generalization claim                                |
| G1 pacing        | 250 ms                                            | Unjustified until measured                                          |
| G1 repeatability | ICC ≥ 0.60                                        | Threshold needs a scientific justification                          |
| G2               | Metadata recoverability AUC below 0.75            | Useful audit idea, arbitrary universal threshold                    |
| G3               | 0.70 pairwise accuracy and 35% regret reduction   | Thresholds not justified by prior evidence                          |
| G4               | ML significantly beats symbolic baseline          | Correct scientific question, but also require practical effect size |

### Problem 1: G0 is too dependent on V4

V4C-04 is a known positive example. EX-V4-01 through EX-V4-05 are exploratory comparisons.

If you develop the symbolic model specifically to separate those six examples, you risk overfitting the mechanistic explanation.

G0 should be divided into:

- Known-case reconstruction: can the model explain V4C-04?
- Independent-case evaluation: does it work on cases not used to design the model?

G0 cannot establish generalization by itself.

### Problem 2: Six incidents are not enough

Six incidents across three topologies may establish that the experiment is operationally possible.

They cannot establish robust unseen-topology generalization.

The same applies to three runtime replicates.

Three repetitions can expose gross inconsistencies, but they provide weak evidence about rare events and the shape of runtime variability.

Use the pilot to estimate variance and determine the necessary replication count. Five is a reasonable initial planning value, not a universal minimum.

### Problem 3: The 250 ms pacing assumption

A fixed 250 ms interval is not a scientifically established safe deployment interval.

It could be longer or shorter than the actual convergence process.

Measure actual command-completion times and FIB update events first. Then test explicitly controlled pacing conditions.

Do not assume that a management-plane delay translates into the same FIB installation delay.

### Problem 4: G3 and G4 need redesign

Gemini's G3 allows either the symbolic model or ML to pass. That is acceptable as a broad research continuation gate, but its numerical criteria are arbitrary.

G4 correctly asks whether ML improves on symbolic analysis, but statistical significance alone is not enough. A tiny improvement may be practically useless.

I recommend predeclaring:

- Minimum meaningful improvement.
- Cluster-aware confidence intervals.
- Ranking performance on unseen topology families.
- Regret reduction.
- A rule for operational ties.

### My revised gate structure

G0

Mechanistic validity

Can a formally defined staged-transition abstraction reconstruct known mechanisms without being designed solely around V4C-04?

Failure: redesign or stop Path A.

G1

Independent structural validation

Test on independently selected topology/incident cases. Compare symbolic predictions against independently generated state-transition traces.

Failure: no runtime expansion.

G2

Controlled runtime falsification

Same target configuration, different deployment sequences; randomized, paired, repeated experiments.

Failure: stop claims that deployment-order features predict meaningful runtime differences.

G3

Corpus and leakage validity

Confirm genuine alternative repairs, matched specifications, no generator shortcuts, adequate measurement quality and independent cases.

Failure: redesign the corpus, not the labels.

G4

Incremental predictive value

Compare symbolic analysis against GBT on untouched topology groups.

Failure of ML improvement: retain the deterministic contribution if independently validated; otherwise Path B.

One further distinction: a failed G2 does not automatically prove that deployment order is irrelevant. It could show that your particular repair population or runtime environment did not produce measurable differences. Report exactly what was falsified.

## L. Final research roadmap — 13 phases

This is the roadmap I recommend adopting. It retains your requested Phase 0–12 structure but incorporates the scientific corrections above.

Mandatory before experiments

### Phase 0 — Repository and historical evidence preservation

Objective: Preserve V1–V4 permanently.

Tasks:

1. Inspect Git status, branch and commit.
2. Inventory tracked and untracked historical evidence.
3. Calculate SHA-256 hashes of frozen experiment data.
4. Verify V1–V4 manifests and reports.
5. Document the V1 summary discrepancy and V4 ledger omission.
6. Establish a separate directory for new research.

Inputs: Existing repository and historical reports.

Outputs:

- `HISTORICAL_EVIDENCE_MANIFEST.json`
- `REPOSITORY_STATE.md`
- `PRESERVATION_POLICY.md`

Tools: Git, Python, SHA-256.

Risks: Accidentally overwriting historical records.

Exit: All historical artifacts have documented identities and preservation rules.

### Phase 1 — Literature review and novelty assessment

Objective: Establish whether Path A offers a defensible contribution.

Tasks:

1. Study Batfish and relational verification.
2. Study RFC 5715, RFC 6976 and RFC 8333.
3. Examine CPR, AED and automated configuration repair.
4. Study consistent network updates.
5. Study microloop prevention and staged convergence.
6. Examine existing runtime network emulation systems.
7. Build a novelty comparison matrix.

Outputs:

- `LITERATURE_REVIEW.md`
- `RELATED_WORK_MATRIX.csv`
- `NOVELTY_ASSESSMENT.md`

Tools: IEEE Xplore, ACM DL, USENIX, arXiv, RFC Editor.

Risk: Rediscovering an existing deterministic algorithm.

Exit: A narrow, defensible research gap is identified.

### Phase 2 — Public dataset and topology compatibility audit

Objective: Determine which source graphs can actually run through your toolchain.

Tasks:

1. Audit Topology Zoo.
2. Select small candidate graphs.
3. Audit Cornetto topology structures.
4. Inspect Batfish test networks.
5. Identify supported FRR constructs.
6. Test Batfish and FRR compatibility.
7. Document source licenses.
8. Record topology complexity and resource requirements.

Outputs:

- `DATASET_AUDIT.md`
- `TOPOLOGY_MANIFEST.csv`
- `COMPATIBILITY_REPORT.md`

Tools: NetworkX, Batfish, FRR, Containerlab.

Risk: Topology conversion silently changing network semantics.

Exit: At least a small, diverse set of reproducible topologies passes compatibility tests.

### Phase 3 — Experimental corpus and incident design

Objective: Create a controlled collection of network problems.

Tasks:

1. Define topology families.
2. Establish baseline configurations.
3. Define traffic flows.
4. Define golden/reference configurations.
5. Define common specifications.
6. Generate reproducible incident scenarios.
7. Document intended repair outcomes.

Outputs:

- `topologies/`
- `incidents/`
- `specifications/`
- `CORPUS_CARD.md`

Tools: Python, NetworkX, FRR, Batfish.

Risk: Synthetic incidents becoming too simplistic.

Exit: Every incident has an independently reproducible baseline and intended outcome.

### Phase 4 — Alternative repair and deployment-order generation

Objective: Produce genuinely comparable repair alternatives.

Tasks:

1. Implement supported repair transformations.
2. Generate multiple alternatives per incident.
3. Deduplicate configurations.
4. Calculate configuration differences.
5. Generate multiple deployment sequences.
6. Include matched same-configuration/different-order pairs.
7. Record every generation decision.

Outputs:

- `candidate_generation/`
- `candidate_manifest.json`
- `deployment_plans.json`
- `GENERATOR_AUDIT.md`

Tools: Python, NetworkX, FRR configuration generation.

Risk: Generator fingerprints and candidate-class leakage.

Exit: Multiple semantically comparable alternatives exist without inspecting runtime outcomes.

### Phase 5 — Batfish verification and eligibility filtering

Objective: Verify all final target configurations.

Tasks:

1. Build Batfish snapshots.
2. Parse configurations.
3. Apply identical specifications to alternatives within each incident.
4. Run differential reachability.
5. Calculate final steady-state impact.
6. Store PASS, FAIL and UNKNOWN separately.
7. Check unsupported configuration constructs.

Outputs:

- `batfish_results/`
- `verification_manifest.csv`
- `ELIGIBILITY_REPORT.md`

Tools: Pybatfish, Batfish Docker.

Risk: False confidence caused by unsupported constructs.

Exit: Every eligible repair has reproducible verification evidence.

### Phase 6 — Pre-deployment feature extraction and symbolic analysis

Objective: Determine what can be known before deployment.

Tasks:

1. Extract topology features.
2. Extract configuration differences.
3. Calculate baseline and final routing features.
4. Implement RFC 5715 analysis.
5. Implement RFC 6976 ordering analysis.
6. Develop a staged mixed-state forwarding abstraction.
7. Compare symbolic predictions against hand-constructed test cases.
8. Freeze feature definitions.

Outputs:

- `features/`
- `symbolic_analysis/`
- `FEATURE_DICTIONARY.md`
- `SYMBOLIC_MODEL_VALIDATION.md`

Tools: Python, NetworkX, Batfish RIB information.

Risk: The symbolic model may oversimplify asynchronous OSPF behaviour.

Exit: The model has explicit assumptions, independently testable outputs and no runtime-derived features.

### Phase 7 — Containerlab/FRR runtime measurement pipeline

Objective: Independently observe real forwarding transitions.

Tasks:

1. Generate Containerlab topologies.
2. Establish clean baseline connectivity.
3. Configure controlled traffic.
4. Apply deployment plans.
5. Capture device push timestamps.
6. Capture LSA/SPF information where available.
7. Capture netlink FIB events.
8. Measure packet loss and reachability.
9. Calculate transient disruption.
10. Separate infrastructure failures from actual network outcomes.

Outputs:

- `runtime_runner/`
- `measurement_schema.json`
- `RUNTIME_VALIDATION_REPORT.md`

Tools: Containerlab, FRR, Python, Linux networking, netlink monitoring.

Risk: Host scheduling and monitoring overhead affecting measured timing.

Exit: No-op and positive controls demonstrate that the instrument can distinguish expected behaviours.

### Phase 8 — Small pilot and falsification gates

Objective: Determine whether Path A is worth scaling.

Tasks:

1. Run G0 offline mechanistic validation.
2. Assemble independent cases.
3. Run controlled same-configuration/different-order experiments.
4. Repeat executions.
5. Estimate within-plan variability.
6. Measure event prevalence.
7. Audit measurement resolution.
8. Compare symbolic predictions with runtime outcomes.
9. Decide whether further experiments are justified.

Outputs:

- `PILOT_PREREGISTRATION.md`
- `PILOT_REPORT.md`
- `GATE_DECISION.md`

Exit: Sufficient structural and runtime evidence exists to justify a confirmatory study.

### Phase 9 — Confirmatory data collection

Objective: Build the final immutable experimental corpus.

Tasks:

1. Freeze the topology and incident population.
2. Freeze candidates and deployment plans.
3. Freeze features and measurement protocol.
4. Freeze train/validation/test groups.
5. Execute repeated runtime experiments.
6. Preserve raw traces.
7. Audit invalid runs.
8. Construct ground-truth labels without changing thresholds.

Outputs:

- `CONFIRMATORY_DATASET/`
- `DATASET_CARD.md`
- `DEVIATION_LOG.md`
- `LABEL_VALIDATION_REPORT.md`

Exit: Predeclared completeness and measurement-validity criteria pass.

### Phase 10 — ML training and deterministic comparison

Objective: Test whether ML adds predictive value.

Tasks:

1. Implement random ranking.
2. Implement simple deterministic heuristics.
3. Implement RFC-based baselines.
4. Implement symbolic staged-transition baseline.
5. Train Ridge and Random Forest.
6. Train HistGradientBoosting.
7. Test pairwise ranking.
8. Compare all models on grouped development data.

Outputs:

- `models/`
- `MODEL_COMPARISON.md`
- `TRAINING_CONFIGS/`

Exit: Model and hyperparameters are frozen before final test evaluation.

### Phase 11 — Generalization, statistics and ablation

Objective: Establish whether the findings transfer.

Tasks:

1. Evaluate LOTO.
2. Evaluate LOFO.
3. Evaluate incident-grouped splits.
4. Calculate pairwise ranking metrics.
5. Calculate regret\@1.
6. Calculate group-aware confidence intervals.
7. Perform leakage audits.
8. Run feature-group ablations.
9. Evaluate uncertainty and calibration if probabilities are claimed.
10. Document failures and limitations.

Outputs:

- `FINAL_EVALUATION.md`
- `STATISTICAL_ANALYSIS.md`
- `ABLATION_REPORT.md`
- `THREATS_TO_VALIDITY.md`

Exit: Incremental value over the strongest deterministic baseline is established, or the negative result is documented.

### Phase 12 — Paper preparation and reproducibility release

Objective: Present the actual scientific contribution.

Tasks:

1. Write the research methodology.
2. Document the V1–V4 history.
3. Explain the new experimental design.
4. Report positive and negative findings.
5. Compare against existing literature.
6. Release reproducible code and permitted data.
7. Publish environment and artifact manifests.
8. Provide reproduction instructions.

Outputs:

- Research paper.
- Public repository.
- Dataset documentation.
- Reproducibility package.

Exit: All reported results can be traced to preserved experimental evidence.

## M. Practical implementation architecture for your laptop

Your Windows 11 + WSL2 environment is sufficient for the initial research stages, provided you control container concurrency.

I recommend this division:

Windows 11

VS Code, Git, documentation and experiment management

WSL2 / Ubuntu

Containerlab and FRRouting

Batfish and network verification

Netlink, traffic and runtime measurements

Python research environment

NetworkX, pandas, NumPy, scikit-learn

Statistical analysis and visualization

### Hardware recommendations

| Component | Recommendation                                 |
| --------- | ---------------------------------------------- |
| CPU       | Use limited concurrent Containerlab runs       |
| RAM       | Reserve enough memory for WSL, Batfish and FRR |
| GPU       | Not required for initial experiments           |
| Storage   | Keep immutable raw traces and manifests        |
| ML        | CPU-based HistGradientBoosting initially       |
| GNN       | Optional, later                                |
| CNN       | Remove from main study                         |

A key operational decision: do not run Batfish, many FRR containers and ML workloads at maximum concurrency simultaneously.

Use separate experimental stages, with resource limits and clean runtime environments.

## N. Path A versus Path B — my final decision

Path A — Staged-update risk analysis

Recommended investigation

Investigate first, but do not commit to a large experiment yet.

Advantages:

- A meaningful extension of your previous V4 work.
- Controlled deployment-order experiments.
- A strong deterministic research component.
- Potential for a useful ML contribution if it adds measurable value.
- Direct relevance to network engineers.

  Path B — Verification-to-execution gap

  Fallback and parallel evidence base

  Preserve this direction throughout the investigation.

  Advantages:
- Uses the existing V1–V4 evidence.
- Does not require an expensive new runtime campaign.
- Provides a coherent analysis of specification completeness, deterministic redundancy and transient identifiability.
- Can produce a valuable reproducibility and negative-results contribution.

### Why I choose Path A first

Your V4 research already demonstrated an interesting phenomenon: transient forwarding loops can occur even when the final configuration passes Batfish verification.

The V4C-04 reconstruction is particularly valuable.

However, the population-level result was negative:

- 20 changes investigated.
- 99/100 valid population executions.
- Only 1/20 change-level medians above the frozen threshold.
- D2/G1 failed.
- Confirmatory ML was never executed.

These results must remain unchanged.&#x20;

PROJECT_HISTORY_AND_RESEARCH_EVOLUTION(1).md



The next study should therefore ask a different question:

Can we deliberately study the relationship between repair structure, deployment sequence, mixed forwarding states and observed transient disruption?

This is sufficiently different to justify a new investigation, but it does not yet establish novelty.

### My decision

1. Preserve Path B's evidence.
2. Investigate Path A using offline deterministic analysis.
3. Validate the mechanism on independent cases.
4. Run a small controlled runtime experiment only after the offline stage passes.
5. Expand only if the runtime evidence justifies it.
6. Introduce ML only if the symbolic model leaves a meaningful prediction problem.

I would not accept Gemini's claim that Path B has a guaranteed publication outcome. Publication depends on the strength of the contribution, related work, evaluation and venue.

Also, Gemini's numerical feasibility percentages are subjective assessments, not experimentally established probabilities. They should not determine your decision.

## O. Biggest unresolved scientific risks

These are the questions I would want answered before approving the new research.

| Priority | Unresolved question                                                                      | Why it matters                                                                 |
| -------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Critical | Does the staged symbolic model represent actual OSPF transitions adequately?             | Otherwise the strongest baseline is physically inaccurate.                     |
| Critical | Does deployment order cause repeatable differences in runtime disruption?                | This is the foundation of Path A.                                              |
| Critical | Can the symbolic features distinguish genuinely different outcomes on independent cases? | Prevents repeating V4.                                                         |
| High     | Does FRR implement any relevant oFIB mechanism?                                          | Determines whether RFC 6976 is a deployed mechanism or an analytical baseline. |
| High     | Can you produce multiple meaningful repairs for the same incident?                       | Prevents artificial candidate populations.                                     |
| High     | Can the laptop provide sufficiently accurate runtime measurements?                       | Host timing can influence results.                                             |
| High     | Does GBT improve over symbolic analysis?                                                 | Determines whether ML is actually needed.                                      |
| Medium   | Can the results generalize across topology families?                                     | Determines external validity.                                                  |

There is also an important limitation concerning the target itself.

Your proposed \\(T_1\\) may be measurable, but that does not automatically make it identifiable from pre-deployment information.

You must demonstrate that distinction experimentally.

RESEARCH_FEASIBILITY_AND_ACTION_PLAN(1).md

## P. The first concrete action in your repository

Recommended first action: Phase 0

I do not recommend immediately creating `v5_staged_ranking/`.

First, establish the exact current repository state.

Your feasibility report inspected:

```
C:\Users\karth\network-research-lab

Branch: master
Inspected HEAD: 2030a7c
```

Those are the previously inspected values, not a guarantee of the current state.

Run these read-only commands in PowerShell:

```
cd C:\Users\karth\network-research-lab

# 1. Current branch
git branch --show-current

# 2. Current commit
git rev-parse HEAD

# 3. Working tree status
git status --short

# 4. Tracked changes
git diff --stat

# 5. Check historical experiment directories
Get-ChildItem data\pilot-v1
Get-ChildItem data\pilot-v2
Get-ChildItem data\pilot-v3
Get-ChildItem v4_transient\results\pilot

# 6. Inspect the V4 evidence without changing it
Get-ChildItem v4_transient\analysis\mechanistic
Get-ChildItem v4_transient\logs
```

Do not commit, clean, reset, overwrite or move anything yet.

After inspecting the output, the next task will be to establish a complete immutable SHA-256 inventory of historical evidence and identify the precise files needed for the new offline investigation.

### What I would investigate immediately afterward

The first technical research task should be:

Validate the staged-transition mathematical model before implementing a new runtime experiment.

Specifically:

1. Understand the existing V4 `analyze_mechanistic.py`.
2. Inspect its `stage_features` and `hybrid_state_features` functions.
3. Understand why the existing models over-predicted cycles.
4. Study the exact relationship between directional link-cost changes, LSA propagation and FIB installation.
5. Formally specify the new model.
6. Test it against independently selected synthetic cases.
7. Compare its predictions with captured V4 FIB evidence.

Do not change the existing V4 script or overwrite its reports. Any new implementation should be separately versioned.

## Q. Final recommendation

I want you to take away one central principle from this entire investigation:

# Verification → Structural analysis → Runtime evidence → Learning

This should become the foundation of your research.

- Batfish establishes final-state correctness under specified properties.
- Symbolic analysis investigates potential intermediate hazards.
- Containerlab and FRR establish what actually happens in the tested runtime.
- Statistical analysis establishes whether those observations are repeatable.
- ML is justified only if it improves decisions beyond the deterministic methods.

Your V1–V4 work was not wasted.

V1 established the experimental plumbing. V2 exposed generator shortcuts and specification incompleteness. V3 established that the steady-state target was analytically redundant. V4 exposed a real transient mechanism but failed its population-level feasibility gate.

Those are meaningful research findings, including the negative ones.

I recommend continuing with a carefully redesigned Path A, while preserving Path B as the fallback.

I have not modified your repository or launched experiments.

One final decision: I suggest we proceed with Phase 0 first. Once the repository state and historical evidence are secure, we can investigate the new staged-transition model without risking your previous research.

I'll wait for your approval before making repository changes or starting experiments.
