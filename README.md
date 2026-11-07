# network-research-lab

Measuring how often a network configuration change that PASSES formal
verification still causes operational harm — and learning to predict it.

## Layout

```
docs/
  ARCHITECTURE.md       same-artifact design + every decision, with reasons
  HARM-DEFINITION.md    FROZEN v1, dated before any measurement existed
  LEAKAGE.md            what may never enter the feature matrix, and why
nrl/                    the generator package (model, topology, render, emit,
                        faults, repairs, properties, manifest)
pipeline/
  build_pilot.py        Phase 1: generates the 50-candidate pilot
  verify_pilot.py       Phase 1: 15 local checks; no Docker needed
  spike_frr_batfish.py  THE GATE: does Batfish read our real artifact?
  run_phase2.py         Phase 2: Batfish over all 50, keeps everything
  verify_phase2.py      Phase 2: 30 dataset quality checks
  run_phase3.py         Phase 3: Containerlab BEFORE/AFTER (WSL only)
  verify_phase3.py      Phase 3: 34 dataset quality checks
data/pilot-v1/          generated output (golden, 10 incidents, 50 candidates)
batfish/                PHASE-0 LEARNING MATERIAL — see batfish/README.md
notes/                  lab-notebook.md, surprises.md
```

## Quick start

```powershell
.venv\Scripts\activate
python pipeline\build_pilot.py --out data/pilot-v1 --force
python pipeline\verify_pilot.py

docker run --name batfish -d -v batfish-data:/data -p 8888:8888 -p 9997:9997 -p 9996:9996 batfish/allinone
python pipeline\spike_frr_batfish.py      # <-- the gate; writes spike_result.json
python pipeline\run_phase2.py --limit 3   # smoke test
python pipeline\run_phase2.py             # all 50
python pipeline\verify_phase2.py
```

Phase 2 output lands in `data/pilot-v1/phase2/`; every field is documented in
`docs/PHASE2-DATA-DICTIONARY.md`.

## Phase status

| Phase | Content | State |
|---|---|---|
| 1 | artifact + 10 incidents + 50 candidates + verification | **implemented, locally verified** |
| 1a | FRR/Batfish spike | implemented, **NOT RUN** — gates Phase 2 |
| 1b | Containerlab deploy of one artifact | **NOT RUN** — blocks Phase 3 |
| 2 | Batfish verification of all 50 | **done** — 24 PASS / 26 FAIL, 30/30 checks |
| 3 | Containerlab BEFORE/AFTER ground truth | **implemented, NOT RUN** — needs WSL, see docs/PHASE3-SETUP.md |
| 4 | dataset assembly, risk model, conformal | not started |

No ML. No labels. No outcome is assumed anywhere in Phase 1.
