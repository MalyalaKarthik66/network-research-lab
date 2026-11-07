"""Write manifests/PREREG-APPROVAL.json and manifests/PREREG-FROZEN-RECORD.json for the frozen D1-D9 decisions.

    ./.venv/Scripts/python.exe v4_transient/tools/write_prereg_approval.py

Refuses unless v4lib.decisions.check_approval passes for the pre-registration and decisions file on disk.
It starts nothing: the 20x5 pilot still needs an explicit `run_pilot.py --plan pilot --confirm-pilot ...` command.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from v4lib import decisions as DEC                                   # noqa: E402

APPROVED_BY = ("Project owner: 2026-09-14 instruction delegating D1-D9 to the implementer, and 2026-09-15 instruction "
               "authorizing amendment A3 (instrument and validity fixes), and 2026-09-15 instruction to resolve launch "
               "audit 2 (amendments A4 positive controls and A5 runner, D1-D9 unchanged); written by Claude. Previous "
               "approvals are in Git history.")


def _freeze():
    import importlib.util
    spec = importlib.util.spec_from_file_location("freeze_pilot_decisions", HERE.parent / "freeze_pilot_decisions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    pre, dfile = V4 / DEC.PREREG_REL, V4 / DEC.DECISIONS_REL
    if not dfile.exists():
        print(f"REFUSED: {DEC.DECISIONS_REL} missing")
        return 2
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    appr = {"approved": True, "approved_by": APPROVED_BY, "approved_utc": utc,
            "prereg_file": DEC.PREREG_REL, "prereg_sha256": DEC.sha256_file(pre),
            "decisions_file": DEC.DECISIONS_REL, "decisions_sha256": DEC.sha256_file(dfile)}
    tmp = V4 / "manifests" / ".PREREG-APPROVAL.candidate.json"
    tmp.write_text(json.dumps(appr, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    ok, why = DEC.check_approval(V4, pre, tmp)
    if not ok:
        tmp.unlink()
        print(f"REFUSED: approval would not pass: {why}")
        return 2
    final = V4 / DEC.APPROVAL_REL
    tmp.replace(final)
    draft = json.loads((V4 / "manifests" / "PREREG-DRAFT-RECORD.json").read_text(encoding="utf-8"))
    record = {
        "frozen_utc": utc,
        "prereg_file": DEC.PREREG_REL, "prereg_sha256": appr["prereg_sha256"],
        "decisions_file": DEC.DECISIONS_REL, "decisions_sha256": appr["decisions_sha256"],
        "approval_file": DEC.APPROVAL_REL, "approval_sha256": DEC.sha256_file(final),
        "history": {"draft_sha256_before_validated_smoke": draft.get("original_sha256_before_validated_smoke"),
                    "draft_sha256_after_section_20": draft.get("current_sha256"),
                    "draft_record": "manifests/PREREG-DRAFT-RECORD.json (unchanged)"},
        "derivations": _freeze().derivation(),
        "smoke_evidence_snapshot_sha256": DEC.sha256_file(V4 / "manifests" / "EVIDENCE-SNAPSHOT-PRE-D1D9.json"),
        "pilot_results_exist_at_freeze": (V4 / "results" / "pilot").exists(),
        "note": ("D1-D9 frozen before any pilot run; no smoke-test or pilot outcome consulted. The pilot runner is "
                 "approved but starts only with an explicit --confirm-pilot command."),
    }
    (V4 / "manifests" / "PREREG-FROZEN-RECORD.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8",
                                                               newline="\n")
    print(json.dumps(record, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
