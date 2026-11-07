"""Per-candidate record schema and diffing.

Every field is tagged as PROVENANCE or FEATURE_ELIGIBLE. Provenance fields
describe how the pilot generated the candidate and would not exist for a repair
arriving from a real operator or an LLM. They are recorded for reproducibility
and stratified analysis, and they must never enter X. See docs/LEAKAGE.md.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from .model import Scenario
from .render import render_scenario

# --------------------------------------------------------------------------
# Build scope
# --------------------------------------------------------------------------
# The pilot directory holds two kinds of content and they must not be confused:
#
#   BUILD OUTPUT     -- deterministic, reproducible, owned and locked by Phase 1
#   RUNTIME OUTPUT   -- phase2/, phase3/ ... measurements, timestamps, tool
#                       versions. Non-deterministic by nature and owned by the
#                       phase that produced it.
#
# Phase 1's lock covers the first only. Hashing phase2/spike_result.json into
# pilot.lock.json made a Phase-1 reproducibility check fail because a Phase-2
# tool had run -- the check was right to complain, the scope was wrong.
BUILD_SCOPE_DIRS = ("reference", "incidents", "candidates")
BUILD_SCOPE_FILES = ("properties.yml", "manifest.json")
RUNTIME_DIRS = ("phase2", "phase3", "phase4")


def in_build_scope(relpath: str) -> bool:
    """Is this path Phase 1 build output?"""
    rel = str(relpath).replace("\\", "/").lstrip("./")
    if rel in BUILD_SCOPE_FILES:
        return True
    return rel.split("/", 1)[0] in BUILD_SCOPE_DIRS


def snapshot_digest(hashes: dict) -> str:
    """Digest over the Batfish snapshots ONLY.

    The spike and Phase 2 read `batfish-snapshot/`; they are entirely unaffected
    by `topology.clab.yml`, host setup scripts or container image tags. Gating
    them on the full artifact digest meant that correcting a container image --
    which Batfish never sees -- invalidated a Phase 2 dataset that was still
    perfectly valid. Two digests, each covering what its consumer depends on.
    """
    body = "\n".join(f"{k}:{v}" for k, v in sorted(hashes.items())
                      if in_build_scope(k) and "/batfish-snapshot/" in k)
    return hashlib.sha256(body.encode()).hexdigest()


def artifact_digest(hashes: dict) -> str:
    """One digest identifying the whole in-scope artifact set.

    Downstream phases record this so they can tell whether the pilot has been
    rebuilt underneath them.
    """
    body = "\n".join(f"{k}:{v}" for k, v in sorted(hashes.items())
                      if in_build_scope(k))
    return hashlib.sha256(body.encode()).hexdigest()


PROVENANCE_FIELDS = [
    "provenance.fault_id", "provenance.fault_family",
    "provenance.fault_description", "provenance.fault_params",
    "provenance.repair_id", "provenance.repair_description",
    "incident_id", "candidate_id",
]


def _flatten(sc: Scenario) -> str:
    out = []
    for node, files in sorted(render_scenario(sc).items()):
        for fname, text in sorted(files.items()):
            out.append(f"===== {node}/{fname} =====")
            out.extend(text.split("\n"))
    return "\n".join(out)


def unified(a: Scenario, b: Scenario, a_name: str, b_name: str) -> str:
    return "\n".join(difflib.unified_diff(
        _flatten(a).split("\n"), _flatten(b).split("\n"),
        fromfile=a_name, tofile=b_name, lineterm="")) + "\n"


def diff_summary(faulted: Scenario, candidate: Scenario) -> Dict:
    """FEATURE_ELIGIBLE. Derived from the config diff alone -- exactly the
    information that would be available for a repair proposed in production."""
    added = removed = 0
    devices = set()
    cur_dev = None
    touches = {"ospf": False, "static": False, "interface": False,
               "access_list": False, "prefix_list": False, "route_map": False,
               "shutdown": False, "address": False, "cost": False,
               "area": False, "passive": False, "description_only": True}
    for line in unified(faulted, candidate, "faulted", "candidate").split("\n"):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            body = line[1:].strip()
            if line.startswith("+"):
                added += 1
            else:
                removed += 1
            low = body.lower()
            if not low.startswith("description") and not low.startswith("alias"):
                touches["description_only"] = False
            for key, needle in (("ospf", "ospf"), ("static", "ip route"),
                                ("interface", "interface "),
                                ("access_list", "access-list"),
                                ("prefix_list", "prefix-list"),
                                ("route_map", "route-map"),
                                ("shutdown", "shutdown"),
                                ("address", "address "),
                                ("cost", "ospf cost"),
                                ("area", "ospf area"),
                                ("passive", "passive-interface")):
                if needle in low:
                    touches[key] = True
        if line.startswith("+===== ") or line.startswith("-===== "):
            cur_dev = line.split("=====")[1].strip().split("/")[0]
        if (line.startswith("+") or line.startswith("-")) and cur_dev:
            devices.add(cur_dev)

    # recompute device attribution reliably by comparing per-device renders
    fa, ca = render_scenario(faulted), render_scenario(candidate)
    devices = {n for n in ca if fa.get(n) != ca.get(n)}

    return {
        "lines_added": added, "lines_removed": removed,
        "lines_changed_total": added + removed,
        "devices_touched": len(devices),
        "devices_touched_list": sorted(devices),
        **{f"touches_{k}": v for k, v in touches.items()},
    }


def write_json(path: Path, obj) -> str:
    text = json.dumps(obj, indent=2, sort_keys=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, newline="\n", encoding="utf-8")
    return text


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
