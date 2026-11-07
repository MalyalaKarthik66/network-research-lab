"""Create manifests/PILOT-FREEZE.json, the execution freeze that run_pilot.py verifies before the 20x5 pilot.

    ./.venv/Scripts/python.exe v4_transient/tools/write_pilot_freeze.py

Writes nothing unless ALL hold:
  1. the launch-audit register manifests/AUDIT-BLOCKING-ISSUES.json has no open issue;
  2. decisions.check_approval passes (pre-registration + D1-D9 decisions approved by hash);
  3. every frozen file (V4 code, config, pre-registration, manifests, and the nrl modules the pilot code imports) is
     tracked by Git and identical to HEAD, so the freeze is anchored in an independently timestamped commit.
After writing, commit manifests/PILOT-FREEZE.json itself. Starting the pilot still needs the explicit command.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
REPO = V4.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(V4))

from v4lib import decisions as DEC                                   # noqa: E402
from v4lib import freeze as FREEZE                                   # noqa: E402


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def nrl_dependencies():
    """nrl modules imported by the code that executes and analyses the pilot (import only; no main is run)."""
    for rel in ("pilot/run_pilot.py", "analysis/extract_runs.py", "analysis/analyze_pilot.py"):
        spec = importlib.util.spec_from_file_location(f"_freeze_{Path(rel).stem}", V4 / rel)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    return sorted(Path(m.__file__).resolve().relative_to(REPO).as_posix() for n, m in list(sys.modules.items())
                  if (n == "nrl" or n.startswith("nrl.")) and getattr(m, "__file__", None))


def main() -> int:
    issues = FREEZE.open_blocking_issues(V4)
    if issues is None or issues:
        print(f"REFUSED: launch-audit register {FREEZE.BLOCKING_REL} is missing or has open issues: {issues}")
        return 2
    ok, why = DEC.check_approval(V4)
    if not ok:
        print(f"REFUSED: approval check failed: {why}")
        return 2
    nrl = nrl_dependencies()
    rels = [f"{FREEZE.V4_DIR}/{r}" for r in FREEZE.v4_frozen_files(V4)] + nrl
    untracked = [r for r in rels if git("ls-files", "--error-unmatch", r).returncode != 0]
    if untracked:
        print(f"REFUSED: {len(untracked)} frozen file(s) not tracked by Git, e.g. {untracked[:5]}")
        return 2
    dirty = git("status", "--porcelain", "--", *rels).stdout.strip()
    if dirty:
        print(f"REFUSED: frozen files differ from HEAD:\n{dirty}")
        return 2
    head = git("rev-parse", "HEAD").stdout.strip()
    doc = FREEZE.build(REPO, nrl, head, created_by="tools/write_pilot_freeze.py",
                       created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    tmp = V4 / "manifests" / ".PILOT-FREEZE.candidate.json"
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    ok, why = FREEZE.verify(REPO, tmp)
    if not ok:
        tmp.unlink()
        print(f"REFUSED: freeze would not verify: {why}")
        return 2
    tmp.replace(V4 / FREEZE.FREEZE_REL)
    print(f"wrote {FREEZE.FREEZE_REL}: commit {head}, {len(doc['files'])} files, {doc['n_artifact_files']} artifact files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
