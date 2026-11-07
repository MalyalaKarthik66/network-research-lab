# v4_transient — transient-disruption feasibility pilot

**Question:** among configuration changes that pass Batfish, can pre-deployment evidence predict transient
traffic disruption while the network converges?

**Scope:** this directory holds a small **feasibility pilot** (20 changes × 5 replicates + controls). It is
not the large V4 corpus, and it does not start one.

**Isolation from v2/v3:**
- Everything V4 lives here.
- The frozen `nrl/` package (topologies_v3, repairs_v3, severity, flowmatrix, clab, bf_eval, emit) is imported
  read-only.
- No v2/v3 data, results or code is modified.

## Layout

| path | contents |
|---|---|
| `docs/PILOT-PREREGISTRATION.md` | frozen protocol, including the D1-D9 decisions frozen before the pilot (§19) |
| `docs/D1-D9-DECISION-SCHEMA.md` | how D1-D9 are recorded, validated and approved; machinery rules R1-R13 to review |
| `config/pilot_decisions.json` | the FROZEN D1-D9 decisions (written by `tools/freeze_pilot_decisions.py`, approved in `manifests/PREREG-APPROVAL.json`) |
| `config/pilot_decisions.TEMPLATE.json`, `config/pilot_decisions.schema.json` | blank D1-D9 template and its JSON Schema |
| `v4lib/` | FIB parsing/replay (`fib.py`), targets (`targets.py`), pre-deployment features (`analytic.py`), lab operations (`labops.py`), D1-D9 schema/validation/approval (`decisions.py`), gate machinery (`gates.py`) |
| `pilot/build_pilot.py` | fixed selection rule → artifacts, lock, features, run plans |
| `pilot/batfish_check.py` | Batfish SPEC verdicts + Batfish-computed steady-state r for every change |
| `pilot/run_pilot.py` | the transient protocol (smoke or pilot), resumable, keeps every attempt |
| `pilot/artifacts/` | golden and candidate artifacts + Batfish snapshots |
| `manifests/` | pilot manifest, artifact lock, run plans, Batfish check, approval file |
| `analysis/extract_runs.py` | raw logs → time series, T1/T2/T3, validity checks |
| `analysis/analyze_pilot.py` | replicate statistics, variance components, baselines, ML feasibility, host checks, gates, plots |
| `results/<plan>/` | `raw/` (per-run attempts, gitignored), `timeseries/`, `run_metrics.csv`, `analysis.json` |
| `plots/<plan>/` | the seven pre-registered plots |
| `logs/` | Batfish check, run ledgers, runner stdout |
| `tests/test_core.py` | offline tests of parser, replay (incl. kernel link semantics), targets and features |
| `tests/test_*.py` | decisions, gates, runner locks, freeze, analysis statistics, smoke regression, evidence preservation |
| `docs/V4-LAUNCH-AUDIT.md`, `docs/V4-PAPER-READINESS.md` | launch audit + A3 resolution; what a paper can and cannot claim |
| `manifests/AUDIT-BLOCKING-ISSUES.json`, `manifests/PILOT-FREEZE.json` | launch-audit register (must be empty) and the Git-anchored execution freeze the runner verifies |
| `audit/` | throwaway-container instrument checks (kernel and FRR link-down semantics) |
| `pilot/build_smoke2.py`, `analysis/validate_smoke2.py`, `results/smoke2/` | amendment A3 engineering smoke (engineering only) |
| `tools/` | capability probe and environment check |

## Order of operations

```bash
./.venv/Scripts/python.exe v4_transient/tests/test_core.py
./.venv/Scripts/python.exe v4_transient/pilot/build_pilot.py
# inside WSL (distro clab), no sudo needed (user in clab_admins):
./.venv-wsl/bin/python v4_transient/pilot/batfish_check.py
./.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan smoke
./.venv/Scripts/python.exe v4_transient/analysis/extract_runs.py --plan smoke
./.venv/Scripts/python.exe v4_transient/analysis/analyze_pilot.py --plan smoke
# amendment A3 engineering smoke (done 2026-09-15; docs/V4-LAUNCH-AUDIT.md §6):
./.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan smoke2
./.venv/Scripts/python.exe v4_transient/analysis/extract_runs.py --plan smoke2
./.venv/Scripts/python.exe v4_transient/analysis/validate_smoke2.py
# amendments A4 (positive controls) + A5 (runner) engineering smoke 3 (docs/V4-LAUNCH-AUDIT-2.md):
./.venv/Scripts/python.exe v4_transient/tests/test_controls_a4.py
./.venv/Scripts/python.exe v4_transient/tests/test_runner_parallel.py
./.venv/Scripts/python.exe v4_transient/pilot/build_smoke3.py
./.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan smoke3
./.venv/Scripts/python.exe v4_transient/analysis/extract_runs.py --plan smoke3
./.venv/Scripts/python.exe v4_transient/analysis/validate_smoke3.py
# Git-anchored execution freeze (refuses unless the audit register is empty, approval passes and the tree is committed):
./.venv/Scripts/python.exe v4_transient/tools/write_pilot_freeze.py
# the 20x5 pilot starts ONLY with the explicit token, and only if approval + freeze + clean host verify
# (optional hygiene: stop unrelated containers such as Batfish first; the pilot does not need it):
./.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan pilot --resume --confirm-pilot START-20x5-PILOT
./.venv/Scripts/python.exe v4_transient/analysis/extract_runs.py --plan pilot
./.venv/Scripts/python.exe v4_transient/analysis/analyze_pilot.py --plan pilot
```

The final decision is recorded in `PILOT-DECISION.md`.
