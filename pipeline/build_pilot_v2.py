"""Build pilot-v2: 3 topologies x parameterised incidents x 3 repair classes.

    python3 pipeline/build_pilot_v2.py --profile small    # validation
    python3 pipeline/build_pilot_v2.py --profile full     # ~1850 candidates

Writes data/pilot-v2/. data/pilot-v1 is never touched.

Two invariants enforced at build time, both learned the hard way:
  * no candidate may equal GOLDEN            (the pilot-v1 SAFE shortcut)
  * no two candidates may share an AFTER config, even across incidents or
    topologies (harm depends only on the AFTER network, so that is a duplicate
    LABEL a model can memorise)
"""
from __future__ import annotations

import argparse, collections, hashlib, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl import GENERATOR_VERSION, __version__                     # noqa: E402
from nrl.emit import FRR_IMAGE, HOST_IMAGE, write_artifact         # noqa: E402
from nrl.faults_v2 import build_incidents                          # noqa: E402
from nrl.manifest import (BUILD_SCOPE_DIRS, RUNTIME_DIRS,          # noqa: E402
                          artifact_digest, diff_summary, in_build_scope,
                          now_utc, snapshot_digest, unified, write_json)
from nrl.properties import (PROPERTIES, SPEC, SUITE_VERSION,       # noqa: E402
                            as_yaml, spec_coverage_features)
from nrl.graphfeat import graph_features
from nrl.render import render_scenario                             # noqa: E402
from nrl.repairs_v2 import generate_repairs                        # noqa: E402
from nrl.scenario_io import write as write_scenario                # noqa: E402
from nrl.topologies import (DESIGN_NAMES, REFERENCE_DERIVED,
                            TEN_NAMES, TOPOLOGIES,                 # noqa: E402
                            build_golden)

# per_family -> incidents per topology = 10 families x per_family
PROFILES = {"c": 1, "medium": 2, "large": 3}


def fp(sc) -> str:
    r = render_scenario(sc)
    return hashlib.sha256(json.dumps(
        {n: dict(sorted(v.items())) for n, v in sorted(r.items())},
        sort_keys=True).encode()).hexdigest()


def select_per_class(pool, incident_id: str, per_class: int):
    """Up to `per_class` repairs from each class, chosen deterministically.

    Ordering is by a stable hash of (incident_id, repair_id), so the choice is
    reproducible across machines and Python versions -- unlike hash() or set
    iteration -- and differs between incidents, so the same operators are not
    picked every time.
    """
    if per_class <= 0:
        return pool
    by_class = {}
    for item in pool:
        by_class.setdefault(item[1], []).append(item)
    out = []
    for rclass in sorted(by_class):
        ranked = sorted(by_class[rclass], key=lambda it: hashlib.sha256(
            f"{incident_id}/{it[0]}".encode()).hexdigest())
        out.extend(ranked[:per_class])
    # restore generation order so the manifest reads naturally
    order = {id(it): i for i, it in enumerate(pool)}
    return sorted(out, key=lambda it: order[id(it)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/pilot-v2")
    ap.add_argument("--profile", choices=list(PROFILES), default="c")
    ap.add_argument("--topologies", default="all",
                    help="'all' = the twenty design networks, or a comma list. "
                         "'ten' = the original ten, for reproducing the first "
                         "pilot-v2 build.")
    ap.add_argument("--per-class", type=int, default=3, metavar="N",
                    help="candidates kept per repair class per incident "
                         "(default 3, so ~9 per incident). 0 = keep every "
                         "repair, which is the pre-20-topology behaviour.")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    per_family = PROFILES[args.profile]
    names = (list(DESIGN_NAMES) if args.topologies == "all"
             else list(TEN_NAMES) if args.topologies == "ten"
             else [x.strip() for x in args.topologies.split(",") if x.strip()])
    out = (REPO / args.out).resolve()
    if out.exists() and not args.force:
        print(f"refusing to overwrite {out} -- pass --force"); return 2
    out.mkdir(parents=True, exist_ok=True)

    hashes, incidents, candidates = {}, [], []
    written = set()          # every in-scope path THIS run produced
    drop = collections.Counter()
    global_fp = {}
    inum = cnum = 0

    (out / "properties.yml").write_text(
        as_yaml([TOPOLOGIES[n] for n in names]), newline="\n", encoding="utf-8")
    written.add("properties.yml")

    for tname in names:
        spec = TOPOLOGIES[tname]
        golden = build_golden(spec)
        gfp = fp(golden)
        gdir = out / "reference" / f"golden-{tname}"
        h = write_artifact(gdir, golden, f"nrlv2-golden-{tname}")
        hashes.update({f"reference/golden-{tname}/{k}": v for k, v in h.items()})
        written |= {f"reference/golden-{tname}/{k}" for k in h}
        write_scenario(gdir / "scenario.json", golden)
        written.add(f"reference/golden-{tname}/scenario.json")
        print(f"[{tname}] golden written ({len(spec.routers)} routers, "
              f"{spec.n_adjacencies} adjacencies)")

        for fault in build_incidents(spec, per_family):
            inum += 1
            iid = f"I-{inum:05d}"
            faulted = fault.apply(golden)
            ffp = fp(faulted)
            idir = out / "incidents" / iid
            h = write_artifact(idir, faulted, f"nrlv2-{iid.lower()}")
            hashes.update({f"incidents/{iid}/{k}": v for k, v in h.items()})
            written |= {f"incidents/{iid}/{k}" for k in h}
            written |= {f"incidents/{iid}/fault.json",
                        f"incidents/{iid}/scenario.json",
                        f"incidents/{iid}/golden_to_faulted.diff"}
            write_json(idir / "fault.json", {
                "incident_id": iid, "topology": tname, "fault_id": fault.fid,
                "fault_family": fault.family,
                "fault_description": fault.description,
                "fault_params": json.loads(json.dumps(fault.params, default=str)),
                "note": "PROVENANCE ONLY -- see docs/LEAKAGE.md"})
            write_scenario(idir / "scenario.json", faulted)
            (idir / "golden_to_faulted.diff").write_text(
                unified(golden, faulted, f"golden-{tname}", iid),
                newline="\n", encoding="utf-8")

            # ---- select ~N per repair class, deterministically -----------
            # The 20-topology design holds the CANDIDATE budget fixed while
            # doubling the number of networks (docs/FINAL-PLAN.md 3.4), so each
            # incident contributes about nine candidates rather than eighteen.
            #
            # The selection must be stratified by repair class, not a slice:
            # generate_repairs emits correct/regressive/incomplete in blocks,
            # so taking the first nine would take nine of one class. And it
            # must be a pure function of the incident id and the repair ids --
            # no wall clock, no set iteration order -- or rebuilds stop being
            # byte-identical and the lock's whole point is lost.
            pool = []
            for rid, rclass, rdesc, cand in generate_repairs(
                    golden, faulted, fault, spec):
                x = fp(cand)
                if x == gfp:  drop["equals_golden"] += 1; continue
                if x == ffp:  drop["noop"] += 1;          continue
                pool.append((rid, rclass, rdesc, cand, x))
            selected = select_per_class(pool, iid, args.per_class)
            drop["not_selected"] += len(pool) - len(selected)

            n_here = 0
            for rid, rclass, rdesc, cand, x in selected:
                if x in global_fp: drop["duplicate_after_config"] += 1; continue
                global_fp[x] = f"{iid}/{rid}"
                cnum += 1
                cid = f"C-{cnum:05d}"
                cdir = out / "candidates" / cid
                hh = write_artifact(cdir, cand, f"nrlv2-{cid.lower()}")
                hashes.update({f"candidates/{cid}/{k}": v for k, v in hh.items()})
                written |= {f"candidates/{cid}/{k}" for k in hh}
                written |= {f"candidates/{cid}/meta.json",
                            f"candidates/{cid}/scenario.json",
                            f"candidates/{cid}/diffs/faulted_to_candidate.diff"}
                write_scenario(cdir / "scenario.json", cand)
                (cdir / "diffs").mkdir(exist_ok=True)
                (cdir / "diffs" / "faulted_to_candidate.diff").write_text(
                    unified(faulted, cand, iid, cid), newline="\n", encoding="utf-8")
                ds = diff_summary(faulted, cand)
                write_json(cdir / "meta.json", {
                    "candidate_id": cid, "incident_id": iid, "topology": tname,
                    "generator_version": GENERATOR_VERSION,
                    "nrl_version": __version__, "suite_version": SUITE_VERSION,
                    "pilot": "pilot-v2",
                    "provenance": {
                        "_warning": "BANNED from X. See docs/LEAKAGE.md.",
                        "fault_id": fault.fid, "fault_family": fault.family,
                        "fault_description": fault.description,
                        "repair_id": rid, "repair_class": rclass,
                        "repair_description": rdesc},
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
                    # Tier A+. Structural features of the change, computed from
                    # the BEFORE (faulted) and AFTER (candidate) OSPF graphs.
                    # They must be built here: they cannot be harvested from
                    # Batfish output afterwards, and a feature that is not
                    # written at build time is simply absent from the dataset.
                    "graph_features": graph_features(
                        spec, faulted, cand,
                        ds.get("devices_touched_list", [])),
                    "phase2_batfish": None, "phase3_containerlab": None,
                    "label": None})
                candidates.append({"candidate_id": cid, "incident_id": iid,
                                   "topology": tname, "fault_family": fault.family,
                                   "repair_id": rid, "repair_class": rclass,
                                   "path": f"candidates/{cid}"})
                n_here += 1
            incidents.append({"incident_id": iid, "topology": tname,
                              "fault_id": fault.fid, "fault_family": fault.family,
                              "n_candidates": n_here})
        print(f"[{tname}] {inum} incidents, {cnum} candidates so far")

    written.add("manifest.json")
    write_json(out / "manifest.json", {
        "pilot": "pilot-v2", "profile": args.profile,
        "topologies": names, "per_family": per_family,
        "per_class": args.per_class,
        "reference_derived": sorted(set(names) & REFERENCE_DERIVED),
        "topology_n_routers": {t: len(TOPOLOGIES[t].routers) for t in names},
        "generator_version": GENERATOR_VERSION, "suite_version": SUITE_VERSION,
        "n_incidents": len(incidents), "n_candidates": len(candidates),
        "dropped": dict(drop),
        "topology_adjacencies": {t: TOPOLOGIES[t].n_adjacencies for t in names},
        "topology_primary_path": {t: TOPOLOGIES[t].primary_path for t in names},
        "topology_routers": {t: sorted(TOPOLOGIES[t].routers) for t in names},
        "topology_hosts": {t: sorted(TOPOLOGIES[t].hosts) for t in names},
        "spec_properties": [p["pid"] for p in SPEC],
        "oracle_only_properties": [p["pid"] for p in PROPERTIES if not p["in_spec"]],
        "incidents": incidents, "candidates": candidates})


    # A lock computed from a directory WALK adopts whatever it finds. The
    # directory-level version of this guard was not enough: --force overwrites
    # FILES but never removes directories that no longer belong, so a candidate
    # id that moved to a smaller topology kept the previous build's extra
    # routers (C-00161 held wan1/wan2 from a 6-router topology while being a
    # 4-router candidate), and those files were hashed into the lock. Compare at
    # FILE granularity against what this run actually produced.
    walked = set()
    for f in out.rglob("*"):
        if f.is_file() and f.name != "pilot.lock.json":
            rel = str(f.relative_to(out)).replace("\\", "/")
            if in_build_scope(rel):
                walked.add(rel)
    orphan = sorted(walked - written)
    if orphan:
        print()
        print("!" * 70)
        print(f"BLOCKED: {len(orphan)} file(s) on disk were NOT written by this run.")
        for o in orphan[:6]:
            print(f"    {o}")
        print("  Leftovers from an earlier build. Locking them would make the")
        print("  artifact digest describe files that are not in the artifact.")
        print(f"  Delete the output directory and rebuild:")
        print(f"     Remove-Item -Recurse -Force {out}")
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
        "pilot": "pilot-v2", "profile": args.profile, "topologies": names,
        "generator_version": GENERATOR_VERSION, "nrl_version": __version__,
        "suite_version": SUITE_VERSION, "deterministic": True,
        "builder": "build_pilot_v2.py",
        "build_args": ["--profile", args.profile,
                       "--per-class", str(args.per_class),
                       "--topologies", ",".join(names)],
        "built_utc": now_utc(), "build_scope_dirs": list(BUILD_SCOPE_DIRS),
        "runtime_dirs_excluded": list(RUNTIME_DIRS),
        "artifact_digest": dig, "snapshot_digest": snap,
        "n_files": len(full), "sha256": full})

    cls = collections.Counter(c["repair_class"] for c in candidates)
    top = collections.Counter(c["topology"] for c in candidates)
    print(f"\nDONE -> {out}")
    print(f"  topologies : {names}")
    print(f"  incidents  : {len(incidents)}")
    print(f"  candidates : {len(candidates)}  class={dict(cls)}  topo={dict(top)}")
    print(f"  dropped    : {dict(drop)}")
    print(f"  artifact digest {dig[:16]}...  snapshot digest {snap[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
