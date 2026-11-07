"""Execution freeze for the V4 20x5 pilot.

decisions.check_approval authenticates only the pre-registration and the D1-D9 decisions file. This module
authenticates the exact implementation that executes and analyses the pilot:
  * every V4 file that runs or analyses the pilot (v4lib/*.py, pilot/, analysis/),
  * every frozen nrl module those files import (read-only v2/v3 code the protocol depends on),
  * the decisions, schema, pre-registration, approval, manifests, run plan and Batfish verdicts,
  * every file under pilot/artifacts (a digest over all files, not only the per-artifact lock),
  * the launch-audit blocking-issue register, which must be empty;
and it records the Git commit holding that tree, the independent chronology anchor.

manifests/PILOT-FREEZE.json is written only by tools/write_pilot_freeze.py. run_pilot.py refuses the pilot unless
verify() passes, at start and again before every attempt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = "v4-pilot-freeze-1"
V4_DIR = "v4_transient"
FREEZE_REL = "manifests/PILOT-FREEZE.json"
BLOCKING_REL = "manifests/AUDIT-BLOCKING-ISSUES.json"
V4_FIXED_FILES = ("pilot/run_pilot.py", "pilot/build_pilot.py", "pilot/batfish_check.py",
                  "analysis/extract_runs.py", "analysis/analyze_pilot.py",
                  "config/pilot_decisions.json", "config/pilot_decisions.schema.json",
                  "docs/PILOT-PREREGISTRATION.md", "manifests/PREREG-APPROVAL.json",
                  "manifests/pilot_manifest.json", "manifests/artifact_lock.json",
                  "manifests/run_plan_pilot.json", "manifests/batfish_check.json", BLOCKING_REL)
#: nrl modules the runner and extraction cannot work without; a freeze that omits any of them is refused
REQUIRED_NRL = ("nrl/clab.py", "nrl/flowmatrix.py", "nrl/topologies_v3.py", "nrl/scenario_io.py")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def v4_frozen_files(v4_root: Path) -> List[str]:
    """V4-relative paths that must be covered. The v4lib glob is taken at verify time, so a file added later is refused."""
    return sorted(f"v4lib/{p.name}" for p in Path(v4_root, "v4lib").glob("*.py")) + list(V4_FIXED_FILES)


def artifact_digest(v4_root: Path) -> Tuple[str, int]:
    base = Path(v4_root) / "pilot" / "artifacts"
    # order by the relative POSIX path STRING: sorting Path objects is case-insensitive on Windows and case-sensitive
    # on POSIX, which made the digest platform-dependent (freeze written on Windows, verified in WSL)
    files = sorted(((p.relative_to(base).as_posix(), p) for p in base.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts), key=lambda x: x[0])
    h = hashlib.sha256()
    for rel, p in files:
        h.update(f"{rel}\t{sha256_file(p)}\n".encode())
    return h.hexdigest(), len(files)


def open_blocking_issues(v4_root: Path) -> Optional[list]:
    """The open issues of the launch-audit register, or None if the register is missing or malformed."""
    p = Path(v4_root) / BLOCKING_REL
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    op = doc.get("open") if isinstance(doc, dict) else None
    return op if isinstance(op, list) else None


def build(repo_root: Path, nrl_files: List[str], git_commit: str, created_by: str, created_utc: str) -> Dict:
    repo_root = Path(repo_root)
    v4 = repo_root / V4_DIR
    files = {f"{V4_DIR}/{r}": sha256_file(v4 / r) for r in v4_frozen_files(v4)}
    files.update({r: sha256_file(repo_root / r) for r in sorted(set(nrl_files))})
    digest, n = artifact_digest(v4)
    return {"schema_version": SCHEMA_VERSION, "status": "FROZEN", "created_by": created_by,
            "created_utc": created_utc, "git_commit": git_commit, "files": files,
            "artifacts_digest": digest, "n_artifact_files": n}


def verify(repo_root: Path, freeze_path: Optional[Path] = None, check_artifacts: bool = True) -> Tuple[bool, str]:
    """(ok, reason). Pure check with no side effects."""
    repo_root = Path(repo_root)
    v4 = repo_root / V4_DIR
    issues = open_blocking_issues(v4)
    if issues is None:
        return False, f"{BLOCKING_REL} missing or unreadable"
    if issues:
        ids = [str(x.get("id")) if isinstance(x, dict) else str(x) for x in issues]
        return False, f"{len(issues)} open blocking launch-audit issue(s): {', '.join(ids)} ({BLOCKING_REL})"
    fp = Path(freeze_path) if freeze_path else v4 / FREEZE_REL
    if not fp.exists():
        return False, f"{FREEZE_REL} missing (the execution freeze has not been created)"
    try:
        doc = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"freeze unreadable: {exc}"
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or doc.get("status") != "FROZEN":
        return False, "freeze schema_version/status invalid"
    if not isinstance(doc.get("git_commit"), str) or len(doc["git_commit"]) < 7:
        return False, "freeze records no Git commit"
    files = doc.get("files")
    if not isinstance(files, dict) or not files:
        return False, "freeze lists no files"
    missing = sorted(({f"{V4_DIR}/{r}" for r in v4_frozen_files(v4)} | set(REQUIRED_NRL)) - set(files))
    if missing:
        return False, f"files not covered by the freeze: {missing[:5]}"
    for rel, want in sorted(files.items()):
        p = repo_root / rel
        if not p.is_file():
            return False, f"frozen file missing: {rel}"
        if sha256_file(p) != want:
            return False, f"frozen file changed after the freeze: {rel}"
    if check_artifacts:
        digest, n = artifact_digest(v4)
        if digest != doc.get("artifacts_digest") or n != doc.get("n_artifact_files"):
            return False, "pilot/artifacts differ from the freeze"
    return True, "ok"
