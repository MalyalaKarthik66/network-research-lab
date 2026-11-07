"""Build the 50-candidate Phase 1 pilot.

    python pipeline/build_pilot.py --out data/pilot-v1

Fully deterministic: 10 incidents x 5 repair candidates, no sampling anywhere.
The --seed flag is recorded in the lock file for forward compatibility with
stochastic operators, but pilot-v1 does not consume it. Determinism is a
stronger reproducibility property than a fixed seed, so it is preferred while
the library is small enough to enumerate.

Writes NOTHING about expected outcomes. Whether a candidate is safe is decided
in Phase 3 by measurement, not here by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl import GENERATOR_VERSION, __version__                    # noqa: E402
from nrl.emit import write_artifact, FRR_IMAGE, HOST_IMAGE        # noqa: E402
from nrl.faults import FAULTS                                     # noqa: E402
from nrl.manifest import (BUILD_SCOPE_DIRS, RUNTIME_DIRS,          # noqa: E402
                          artifact_digest, diff_summary, in_build_scope,
                          snapshot_digest,
                          now_utc, unified, write_json)
from nrl.properties import (PROPERTIES, SPEC, SUITE_VERSION,      # noqa: E402
                            as_yaml, spec_coverage_features)
from nrl.repairs import APPLICABLE, REPAIRS                       # noqa: E402
from nrl.topology import build_golden                             # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/pilot-v1")
    ap.add_argument("--seed", type=int, default=20260825)
    ap.add_argument("--force", action="store_true",
                    help="delete the output directory first")
    args = ap.parse_args()

    out = (REPO / args.out).resolve()
    if out.exists() and not args.force:
        print(f"refusing to overwrite {out} -- pass --force")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    prev_lock = {}
    if (out / "pilot.lock.json").exists():
        try:
            prev_lock = json.loads((out / "pilot.lock.json").read_text())
        except Exception:                                          # noqa: BLE001
            prev_lock = {}

    # Windows and macOS filesystems are case-INSENSITIVE. Writing
    # devices/corea/frr.conf into a tree that already has devices/coreA/ lands
    # in the old directory and leaves the old NAME in place. The content is
    # right, the path casing is wrong, and it only breaks later -- inside a
    # Linux container mount, where names are case-sensitive. Catch it here.
    expected_nodes = set(build_golden().devices)
    stale = []
    for d in out.rglob("artifact/devices/*"):
        if d.is_dir() and d.name not in expected_nodes \
                and d.name.lower() in {n.lower() for n in expected_nodes}:
            stale.append(str(d.relative_to(out)))
    if stale:
        print("BLOCKED: leftover directories whose names differ only by case.")
        print(f"  e.g. {stale[:3]}")
        print("  Your filesystem is case-insensitive, so --force cannot fix "
              "this.")
        print(f"  Delete the output directory and rebuild:")
        print(f"     Remove-Item -Recurse -Force {out}")
        print(f"     python pipeline\\build_pilot.py --out {args.out}")
        return 3
    # Overwrite in place rather than rmtree: some mounts refuse unlink. Stale
    # files from an older run are caught by verify_pilot, which compares the
    # files on disk against the complete file set recorded in the lock.

    all_hashes = {}
    golden = build_golden()

    print("[1/4] reference (golden) network")
    h = write_artifact(out / "reference" / "golden", golden, "nrl-golden")
    all_hashes.update({f"reference/golden/{k}": v for k, v in h.items()})

    (out / "properties.yml").write_text(as_yaml(), newline="\n", encoding="utf-8")

    print("[2/4] incidents (the BROKEN networks -- Phase 3 BEFORE state)")
    faulted_by_id = {}
    incidents = []
    for idx, fault in enumerate(FAULTS, start=1):
        iid = f"I-{idx:02d}"
        faulted = fault.apply(golden)
        faulted_by_id[fault.fid] = faulted
        idir = out / "incidents" / iid
        h = write_artifact(idir, faulted, f"nrl-{iid.lower()}")
        all_hashes.update({f"incidents/{iid}/{k}": v for k, v in h.items()})
        write_json(idir / "fault.json", {
            "incident_id": iid,
            "fault_id": fault.fid,
            "fault_family": fault.family,
            "fault_description": fault.description,
            "fault_params": json.loads(json.dumps(fault.params, default=str)),
            "note": "PROVENANCE ONLY -- see docs/LEAKAGE.md",
        })
        (idir / "golden_to_faulted.diff").write_text(
            unified(golden, faulted, "golden", iid), newline="\n",
            encoding="utf-8")
        incidents.append((iid, fault, faulted))
        print(f"      {iid}  {fault.fid}  {fault.family}")

    print("[3/4] candidates (the REPAIRED networks -- Phase 3 AFTER state)")
    candidates = []
    cnum = 0
    for iid, fault, faulted in incidents:
        for rid in APPLICABLE[fault.family]:
            cnum += 1
            cid = f"C-{cnum:04d}"
            repair = REPAIRS[rid]
            cand = repair.apply(golden, faulted, fault)
            cdir = out / "candidates" / cid
            h = write_artifact(cdir, cand, f"nrl-{cid.lower()}")
            all_hashes.update({f"candidates/{cid}/{k}": v for k, v in h.items()})

            (cdir / "diffs").mkdir(exist_ok=True)
            (cdir / "diffs" / "faulted_to_candidate.diff").write_text(
                unified(faulted, cand, iid, cid), newline="\n", encoding="utf-8")
            (cdir / "diffs" / "golden_to_candidate.diff").write_text(
                unified(golden, cand, "golden", cid), newline="\n",
                encoding="utf-8")

            ds = diff_summary(faulted, cand)
            meta = {
                "candidate_id": cid,
                "incident_id": iid,
                "generator_version": GENERATOR_VERSION,
                "nrl_version": __version__,
                "suite_version": SUITE_VERSION,
                "seed": args.seed,
                # No timestamp here on purpose. A per-candidate created_utc made
                # every meta.json differ between two otherwise identical builds,
                # which made artifact_digest a build clock rather than a content
                # hash -- so a harmless rebuild would invalidate a finished
                # Phase 3 dataset. The build time lives in pilot.lock.json,
                # which is excluded from its own hash.

                "provenance": {
                    "_warning": "BANNED from the feature matrix. In a synthetic "
                                "pilot these fields predict the label by "
                                "construction. See docs/LEAKAGE.md.",
                    "fault_id": fault.fid,
                    "fault_family": fault.family,
                    "fault_description": fault.description,
                    "repair_id": rid,
                    "repair_description": repair.description,
                },

                "artifact": {
                    "root": "artifact",
                    "clab_topology": "artifact/topology.clab.yml",
                    "batfish_snapshot": "batfish-snapshot",
                    "before_state": f"../../incidents/{iid}/artifact",
                    "routers": sorted(cand.routers),
                    "hosts": sorted(cand.hosts),
                    "frr_image": FRR_IMAGE,
                    "host_image": HOST_IMAGE,
                    "sha256": h,
                },

                "change_stats": ds,
                "spec_coverage": spec_coverage_features(ds),

                "phase2_batfish": None,
                "phase3_containerlab": None,
                "label": None,
            }
            write_json(cdir / "meta.json", meta)
            candidates.append(meta)

    print(f"      wrote {len(candidates)} candidates")

    print("[4/4] manifest + lock")
    write_json(out / "manifest.json", {
        "pilot": "pilot-v1",
        "generator_version": GENERATOR_VERSION,
        "n_incidents": len(incidents),
        "n_candidates": len(candidates),
        "suite_version": SUITE_VERSION,
        "spec_properties": [p["pid"] for p in SPEC],
        "oracle_only_properties": [p["pid"] for p in PROPERTIES
                                   if not p["in_spec"]],
        "candidates": [{"candidate_id": c["candidate_id"],
                        "incident_id": c["incident_id"],
                        "fault_family": c["provenance"]["fault_family"],
                        "repair_id": c["provenance"]["repair_id"],
                        "path": f"candidates/{c['candidate_id']}"}
                       for c in candidates],
    })
    # Hash every IN-SCOPE file. This doubles as the stale-file detector for
    # Phase 1 output. Runtime directories (phase2/, phase3/ ...) belong to the
    # phase that wrote them and are deliberately excluded -- locking them would
    # make a Phase-1 reproducibility check fail simply because a later tool ran.

    # A lock computed from a directory WALK adopts whatever it finds, including
    # leftovers from an earlier run with different ids -- which is exactly how
    # ten stale I-0001..I-0010 directories became "expected" and made the stale
    # check pass while the incident count was wrong. Compare the walk against
    # what this run actually produced and refuse to lock anything else.
    expected_dirs = ({f"reference/{d.name}" for d in (out / "reference").iterdir()
                      if d.is_dir()} if (out / "reference").exists() else set())
    def _id(x, key):
        # v1 tracks incidents as tuples, v2 as dicts
        return x[key] if isinstance(x, dict) else x[0]
    expected_dirs |= {f"incidents/{_id(i, 'incident_id')}" for i in incidents}
    expected_dirs |= {f"candidates/{_id(c, 'candidate_id')}" for c in candidates}
    expected_files = {"properties.yml", "manifest.json", "pilot.lock.json"}
    orphan = set()
    for sub in ("incidents", "candidates", "reference"):
        d = out / sub
        if not d.exists():
            continue
        for child in d.iterdir():
            if child.is_dir() and f"{sub}/{child.name}" not in expected_dirs:
                orphan.add(f"{sub}/{child.name}")
    if orphan:
        print()
        print("!" * 70)
        print(f"BLOCKED: {len(orphan)} directory(ies) on disk were NOT produced "
              f"by this run.")
        print(f"  e.g. {sorted(orphan)[:6]}")
        print("  They are almost certainly leftovers from an earlier build with")
        print("  different ids. Locking them would make them 'expected' forever.")
        print(f"  Delete the output directory and rebuild:")
        print(f"     Remove-Item -Recurse -Force {out}")
        print("!" * 70)
        return 4

    full = {}
    for f in sorted(out.rglob("*")):
        if not f.is_file() or f.name == "pilot.lock.json":
            continue
        rel = str(f.relative_to(out)).replace("\\", "/")
        if in_build_scope(rel):
            full[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    digest = artifact_digest(full)
    snap_digest = snapshot_digest(full)
    write_json(out / "pilot.lock.json", {
        "generator_version": GENERATOR_VERSION,
        "nrl_version": __version__,
        "suite_version": SUITE_VERSION,
        "seed": args.seed,
        "deterministic": True,
        "builder": "build_pilot.py",
        "build_args": ["--seed", str(args.seed)],

        "built_utc": now_utc(),
        "build_scope_dirs": list(BUILD_SCOPE_DIRS),
        "runtime_dirs_excluded": list(RUNTIME_DIRS),
        "artifact_digest": digest,
        "snapshot_digest": snap_digest,
        "n_files": len(full),
        "sha256": full,
    })

    # Loud warning, because this one is silent and dangerous: rebuilding the
    # artifacts invalidates any downstream result computed from the old ones.
    stale_runtime = [d for d in RUNTIME_DIRS if (out / d).exists()]
    if stale_runtime:
        snap_changed = prev_lock.get("snapshot_digest") not in (None, snap_digest)
        art_changed = prev_lock.get("artifact_digest") not in (None, digest)
        print()
        print("!" * 70)
        print(f"downstream output exists: {stale_runtime}")
        if snap_changed:
            print("  SNAPSHOT DIGEST CHANGED -- the Batfish snapshots differ.")
            print("  Re-run: spike_frr_batfish.py, then run_phase2.py, then")
            print("          run_phase3.py. All downstream results are void.")
        elif art_changed:
            print("  snapshot digest UNCHANGED -- Batfish reads the same bytes,")
            print("  so the Phase 2 dataset is STILL VALID and need not be")
            print("  re-run. Only the artifact changed (clab topology, host")
            print("  scripts, images or metadata).")
            print("  Re-run: spike_frr_batfish.py (it stamps both digests),")
            print("          then Phase 3.")
        else:
            print("  both digests unchanged -- downstream results remain valid.")
        print(f"  artifact digest: {digest[:16]}...")
        print(f"  snapshot digest: {snap_digest[:16]}...")
        print("!" * 70)
    print(f"\nDONE -> {out}")
    print(f"  artifact digest: {digest[:16]}...  "
          f"snapshot digest: {snap_digest[:16]}...")
    print(f"  incidents : {len(incidents)}")
    print(f"  candidates: {len(candidates)}")
    print(f"  files     : {len(all_hashes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
