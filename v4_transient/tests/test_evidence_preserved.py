"""Proves the smoke-test evidence and recorded hashes survived the D1-D9 work, and that no pilot ran.
Compares every file against manifests/EVIDENCE-SNAPSHOT-PRE-D1D9.json (taken before any D1-D9 change).
    ./.venv/Scripts/python.exe v4_transient/tests/test_evidence_preserved.py
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


snap = json.loads((V4 / "manifests" / "EVIDENCE-SNAPSHOT-PRE-D1D9.json").read_text(encoding="utf-8"))["files"]
# code/docs deliberately changed by the D1-D9 machinery and freeze; everything else must be byte-identical
INTENTIONALLY_MODIFIED = {"pilot/run_pilot.py", "analysis/analyze_pilot.py", "analysis/validate_smoke.py",
                          "tests/test_runner.py", "README.md", "docs/PILOT-PREREGISTRATION.md",
                          # amendment A3 (2026-09-15): instrument, extraction and ignore rules; see Git history
                          "v4lib/__init__.py", "v4lib/fib.py", "v4lib/targets.py", "v4lib/labops.py",
                          "analysis/extract_runs.py", "tests/test_core.py", ".gitignore",
                          # amendments A4 (positive controls) and A5 (runner), 2026-09-15, docs/V4-LAUNCH-AUDIT-2.md.
                          # What stayed identical inside these files is proven by tests/test_controls_a4.py
                          # (population/no-op entries, run order, pre-existing lock entries and Batfish verdicts).
                          "pilot/build_pilot.py", "pilot/batfish_check.py", "manifests/pilot_manifest.json",
                          "manifests/artifact_lock.json", "manifests/run_plan_pilot.json", "manifests/batfish_check.json"}
missing = sorted(r for r in snap if not (V4 / r).exists())
changed = sorted(r for r in snap if (V4 / r).exists() and sha(V4 / r) != snap[r])
check("no pre-existing file deleted", not missing, missing)
check("only the intentionally modified code/docs differ", set(changed) <= INTENTIONALLY_MODIFIED,
      sorted(set(changed) - INTENTIONALLY_MODIFIED))
print("   intentionally modified since the snapshot:", changed)
for prefix in ("results/", "plots/", "logs/", "manifests/", "pilot/artifacts/", "tools/", "v4lib/"):
    group = [r for r in snap if r.startswith(prefix) and r not in INTENTIONALLY_MODIFIED]
    check(f"every pre-existing file under {prefix} is byte-identical ({len(group)} files)",
          group and not [r for r in group if r in changed or r in missing])

for rj in sorted((V4 / "results" / "smoke" / "raw").glob("*/attempt*/run.json")):
    rec = json.loads(rj.read_text())
    lib = {k: v for k, v in (rec.get("code_sha256") or {}).items() if k.startswith("v4lib/")}
    check(f"{rj.parent.parent.name}/{rj.parent.name}: v4lib hashed at run time equals the snapshotted smoke-era library",
          bool(lib) and all(snap.get(k) == v for k, v in lib.items()),
          [k for k, v in lib.items() if snap.get(k) != v])

draft = json.loads((V4 / "manifests" / "PREREG-DRAFT-RECORD.json").read_text())
check("PREREG-DRAFT-RECORD kept as history (byte-identical, covered above) and differs from the frozen document",
      draft["current_sha256"] != sha(V4 / "docs" / "PILOT-PREREGISTRATION.md"))
appr = json.loads((V4 / "manifests" / "PREREG-APPROVAL.json").read_text())
frozen = json.loads((V4 / "manifests" / "PREREG-FROZEN-RECORD.json").read_text())
check("approval hash equals the frozen pre-registration on disk", appr["prereg_sha256"] == sha(V4 / "docs" / "PILOT-PREREGISTRATION.md"))
check("approval hash equals the frozen decisions on disk", appr["decisions_sha256"] == sha(V4 / "config" / "pilot_decisions.json"))
check("frozen record matches approval and was written with no pilot results present",
      frozen["prereg_sha256"] == appr["prereg_sha256"] and frozen["decisions_sha256"] == appr["decisions_sha256"]
      and frozen["approval_sha256"] == sha(V4 / "manifests" / "PREREG-APPROVAL.json")
      and frozen["pilot_results_exist_at_freeze"] is False)

check("20x5 pilot never executed: results/pilot absent", not (V4 / "results" / "pilot").exists())
check("20x5 pilot never executed: no pilot ledger", not (V4 / "logs" / "pilot_ledger.jsonl").exists())
check("20x5 pilot never executed: no pilot plots", not (V4 / "plots" / "pilot").exists())

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
