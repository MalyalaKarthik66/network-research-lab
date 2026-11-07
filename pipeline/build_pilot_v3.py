"""Build the v3 blast-radius corpus, exactly as pre-registered.

    python pipeline/build_pilot_v3.py --out data/pilot-v3

Frozen configuration: docs/ANALYSIS-PLAN-V3.md, tag frozen-v3-plan-20260912.
Nothing here chooses anything -- mechanisms, topologies, selection rule,
quantiles and the SPEC-PASS filter all come from nrl/repairs_v3.py and
nrl/topologies_v3.py at the frozen commit. This module renders what they emit.

TWO STRUCTURAL FACTS ABOUT THE FROZEN DESIGN, RECORDED HERE RATHER THAN FIXED

1.  There are no faults. `repairs_v3.generate()` builds every candidate from the
    GOLDEN scenario plus one intervention, so the "before" state is the golden
    network, not a faulted one. The v3 arm asks what a change that passes the
    SPEC gate does to a healthy network; it does not model repairing an
    incident. Each topology therefore gets ONE baseline entry under incidents/,
    which exists so the Phase 2 and Phase 3 drivers have the before-state
    directory they expect, and which contains the golden scenario unmodified.

2.  Consequently incident identity is topology identity. docs/ANALYSIS-PLAN-V3.md
    section 5 names "nested grouped 5-fold CV grouped by incident" as the
    secondary protocol; with one baseline per topology that split is degenerate
    -- it is the primary leave-one-topology-out split with different fold
    counts. The plan is frozen and is not edited here. The consequence is
    reported so it can be resolved by a dated amendment before any model is
    fitted, which is what the amendment procedure in ANALYSIS-PLAN.md exists for.

Neither fact is a build defect and neither is repairable inside a frozen plan.
Both change what section 5 can mean, so both are surfaced before compute is
spent rather than discovered in analysis.

Writes only to the --out directory. data/pilot-v2 is never opened.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl import GENERATOR_VERSION, __version__                     # noqa: E402
from nrl.emit import FRR_IMAGE, HOST_IMAGE, write_artifact         # noqa: E402
from nrl.graphfeat import graph_features                           # noqa: E402
from nrl.manifest import (BUILD_SCOPE_DIRS, RUNTIME_DIRS,          # noqa: E402
                          artifact_digest, diff_summary, in_build_scope,
                          now_utc, snapshot_digest, unified, write_json)
from nrl.properties import (PROPERTIES, SPEC, SUITE_VERSION,       # noqa: E402
                            as_yaml, spec_coverage_features)
from nrl.render import render_scenario                             # noqa: E402
from nrl.scenario_io import write as write_scenario                # noqa: E402
from nrl.severity import Fabric                                    # noqa: E402
from nrl.topologies import build_golden                            # noqa: E402
from nrl import repairs_v3 as R3                                   # noqa: E402
from nrl import topologies_v3 as T3                                # noqa: E402

PILOT = "pilot-v3"
PLAN = "docs/ANALYSIS-PLAN-V3.md (frozen 2026-09-12, tag frozen-v3-plan-20260912)"


def fp(sc) -> str:
    """Fingerprint of the rendered configuration, for duplicate detection."""
    r = render_scenario(sc)
    return hashlib.sha256(json.dumps(
        {n: dict(sorted(v.items())) for n, v in sorted(r.items())},
        sort_keys=True).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/pilot-v3")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out = (REPO / a.out).resolve()
    if out.exists() and not a.force:
        print(f"BLOCKED: {out} exists. Delete it or pass --force.")
        return 2
    if "pilot-v2" in str(out):
        print("BLOCKED: refusing to write inside pilot-v2.")
        return 2
    out.mkdir(parents=True, exist_ok=True)

    names = list(R3.PRIMARY_TOPOLOGIES)
    print(f"plan       {PLAN}")
    print(f"mechanisms {R3.PRIMARY_MECHANISMS}")
    print(f"topologies {len(names)}")
    print(f"quantiles  {R3.QUANTILES}   cost multiplier {R3.COST_MULTIPLIER}\n")

    hashes, written = {}, set()
    incidents, candidates = [], []
    drop = collections.Counter()
    global_fp = {}
    inum = cnum = 0

    (out / "properties.yml").write_text(
        as_yaml([T3.resolve(n) for n in names]), newline="\n", encoding="utf-8")
    written.add("properties.yml")

    for tname in names:
        spec = T3.resolve(tname)
        golden = build_golden(spec)
        gfp = fp(golden)
        fab = Fabric(spec)
        cat = R3.catalogue(spec, fab)

        gdir = out / "reference" / f"golden-{tname}"
        h = write_artifact(gdir, golden, f"nrlv3-golden-{tname}")
        hashes.update({f"reference/golden-{tname}/{k}": v for k, v in h.items()})
        written |= {f"reference/golden-{tname}/{k}" for k in h}
        write_scenario(gdir / "scenario.json", golden)
        written.add(f"reference/golden-{tname}/scenario.json")

        # ---- baseline "incident": the golden network, unmodified ----------
        inum += 1
        iid = f"I-{inum:05d}"
        idir = out / "incidents" / iid
        h = write_artifact(idir, golden, f"nrlv3-{iid.lower()}")
        hashes.update({f"incidents/{iid}/{k}": v for k, v in h.items()})
        written |= {f"incidents/{iid}/{k}" for k in h}
        written |= {f"incidents/{iid}/fault.json",
                    f"incidents/{iid}/scenario.json",
                    f"incidents/{iid}/golden_to_faulted.diff"}
        write_json(idir / "fault.json", {
            "incident_id": iid, "topology": tname,
            "fault_id": None, "fault_family": None,
            "fault_description":
                "NONE. The v3 arm applies changes to a healthy network; there "
                "is no fault. This entry exists so the Phase 2/3 drivers have "
                "the before-state directory they expect, and it holds the "
                "golden scenario unmodified.",
            "note": "PROVENANCE ONLY -- see docs/LEAKAGE.md"})
        write_scenario(idir / "scenario.json", golden)
        (idir / "golden_to_faulted.diff").write_text(
            "", newline="\n", encoding="utf-8")

        n_here = 0
        for rid, rclass, rdesc, cand in R3.generate(
                golden, spec, fab, cat, mechanisms=R3.PRIMARY_MECHANISMS):
            x = fp(cand)
            if x == gfp:
                drop["equals_golden"] += 1
                continue
            if x in global_fp:
                drop["duplicate_config"] += 1
                continue
            global_fp[x] = f"{tname}/{rid}"
            # recover the frozen prediction for this repair, for provenance
            d = None
            import re as _re
            mm = _re.search(r"predicted r=([0-9.]+)", rdesc)
            pr = float(mm.group(1)) if mm else None
            mech = _re.search(r"\((\w+)\)", rdesc)
            mech = mech.group(1) if mech else None
            if pr is not None and mech:
                d = min((c for c in cat if c["mech"] == mech),
                        key=lambda c: abs(c["r"] - pr), default=None)

            cnum += 1
            cid = f"C-{cnum:05d}"
            cdir = out / "candidates" / cid
            hh = write_artifact(cdir, cand, f"nrlv3-{cid.lower()}")
            hashes.update({f"candidates/{cid}/{k}": v for k, v in hh.items()})
            written |= {f"candidates/{cid}/{k}" for k in hh}
            written |= {f"candidates/{cid}/meta.json",
                        f"candidates/{cid}/scenario.json",
                        f"candidates/{cid}/diffs/faulted_to_candidate.diff"}
            write_scenario(cdir / "scenario.json", cand)
            (cdir / "diffs").mkdir(exist_ok=True)
            (cdir / "diffs" / "faulted_to_candidate.diff").write_text(
                unified(golden, cand, iid, cid), newline="\n", encoding="utf-8")
            ds = diff_summary(golden, cand)
            write_json(cdir / "meta.json", {
                "candidate_id": cid, "incident_id": iid, "topology": tname,
                "generator_version": GENERATOR_VERSION,
                "nrl_version": __version__, "suite_version": SUITE_VERSION,
                "pilot": PILOT, "analysis_plan": PLAN,
                "provenance": {
                    "_warning": "BANNED from X. See docs/LEAKAGE.md and "
                                "ANALYSIS-PLAN-V3.md section 4.",
                    "fault_id": None, "fault_family": None,
                    "repair_id": rid, "repair_class": rclass,
                    "repair_description": rdesc,
                    "mechanism": mech,
                    # the analytic prediction that SELECTED this candidate.
                    # Using it as a feature would be circular; section 4 of the
                    # frozen plan bans it explicitly.
                    "predicted_severity": pr,
                    "predicted_spec_pass": bool(d["spec_pass"]) if d else None,
                    "predicted_r_broken": d["r_broken"] if d else None,
                    "predicted_r_rerouted": d["r_rerouted"] if d else None},
                "artifact": {
                    "root": "artifact",
                    "clab_topology": "artifact/topology.clab.yml",
                    "batfish_snapshot": "batfish-snapshot",
                    "before_state": f"../../incidents/{iid}/artifact",
                    "golden_state": f"../../reference/golden-{tname}/artifact",
                    "frr_image": FRR_IMAGE, "host_image": HOST_IMAGE,
                    "sha256": hh},
                "change_stats": ds,
                "spec_coverage": spec_coverage_features(ds, spec),
                "graph_features": graph_features(
                    spec, golden, cand, ds.get("devices_touched_list", [])),
                "phase2_batfish": None, "phase3_containerlab": None,
                "label": None})
            candidates.append({
                "candidate_id": cid, "incident_id": iid, "topology": tname,
                "fault_family": None, "repair_id": rid, "repair_class": rclass,
                "mechanism": mech, "predicted_severity": pr,
                "path": f"candidates/{cid}"})
            n_here += 1
        incidents.append({"incident_id": iid, "topology": tname,
                          "fault_id": None, "fault_family": None,
                          "n_candidates": n_here,
                          "note": "baseline: golden network, no fault"})
        print(f"[{tname:16s}] {n_here:3d} candidates")

    written.add("manifest.json")
    write_json(out / "manifest.json", {
        "pilot": PILOT, "analysis_plan": PLAN,
        "frozen_tag": "frozen-v3-plan-20260912",
        "topologies": names,
        "primary_mechanisms": list(R3.PRIMARY_MECHANISMS),
        "auxiliary_mechanisms_not_built": list(R3.AUXILIARY_MECHANISMS),
        "held_out_topologies": [t for t in T3.NAMES if t not in names],
        "quantiles": list(R3.QUANTILES),
        "cost_multiplier": R3.COST_MULTIPLIER,
        "ecmp_nudges": T3.report(),
        "generator_version": GENERATOR_VERSION, "suite_version": SUITE_VERSION,
        "n_incidents": len(incidents), "n_candidates": len(candidates),
        "dropped": dict(drop),
        "topology_n_routers": {t: len(T3.resolve(t).routers) for t in names},
        "topology_adjacencies": {t: T3.resolve(t).n_adjacencies for t in names},
        "topology_primary_path": {t: T3.resolve(t).primary_path for t in names},
        "topology_routers": {t: sorted(T3.resolve(t).routers) for t in names},
        "topology_hosts": {t: sorted(T3.resolve(t).hosts) for t in names},
        "spec_properties": [p["pid"] for p in SPEC],
        "oracle_only_properties": [p["pid"] for p in PROPERTIES
                                   if not p["in_spec"]],
        "structural_notes": [
            "No faults: every candidate is golden + one intervention. The "
            "incidents/ entries are baselines holding the golden scenario.",
            "Incident identity equals topology identity, so the secondary "
            "incident-grouped split in ANALYSIS-PLAN-V3.md section 5 is "
            "degenerate with the primary LOTO split. Needs a dated amendment "
            "before any model is fitted.",
        ],
        "incidents": incidents, "candidates": candidates})

    walked = set()
    for f in out.rglob("*"):
        if f.is_file() and f.name != "pilot.lock.json":
            rel = str(f.relative_to(out)).replace("\\", "/")
            if in_build_scope(rel):
                walked.add(rel)
    orphan = sorted(walked - written)
    if orphan:
        print("\n" + "!" * 70)
        print(f"BLOCKED: {len(orphan)} file(s) on disk were NOT written by this run.")
        for o in orphan[:6]:
            print(f"    {o}")
        print("  Delete the output directory and rebuild.")
        print("!" * 70)
        return 4

    full = {}
    for f in sorted(out.rglob("*")):
        if f.is_file() and f.name != "pilot.lock.json":
            rel = str(f.relative_to(out)).replace("\\", "/")
            if in_build_scope(rel):
                full[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    dig, snap = artifact_digest(full), snapshot_digest(full)
    write_json(out / "pilot.lock.json", {
        "pilot": PILOT, "analysis_plan": PLAN,
        "frozen_tag": "frozen-v3-plan-20260912",
        "topologies": names,
        "generator_version": GENERATOR_VERSION, "nrl_version": __version__,
        "suite_version": SUITE_VERSION, "deterministic": True,
        "builder": "build_pilot_v3.py",
        "build_args": ["--out", a.out],
        "built_utc": now_utc(), "build_scope_dirs": list(BUILD_SCOPE_DIRS),
        "runtime_dirs_excluded": list(RUNTIME_DIRS),
        "artifact_digest": dig, "snapshot_digest": snap,
        "n_files": len(full), "sha256": full})

    cls = collections.Counter(c["repair_class"] for c in candidates)
    mech = collections.Counter(c["mechanism"] for c in candidates)
    top = collections.Counter(c["topology"] for c in candidates)
    print(f"\nDONE -> {out}")
    print(f"  incidents {len(incidents)}  candidates {len(candidates)}  "
          f"files {len(full)}")
    print(f"  by class      {dict(cls)}")
    print(f"  by mechanism  {dict(mech)}")
    print(f"  per topology  {sorted(top.values())}")
    print(f"  dropped       {dict(drop) or '{}'}")
    print(f"  artifact_digest {dig}")
    print(f"  snapshot_digest {snap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
