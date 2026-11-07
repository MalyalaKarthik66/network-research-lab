"""Local verification of the Phase 1 pilot. No Docker, no Batfish, no network.

Everything here is checkable on a laptop with nothing running. It deliberately
does NOT claim anything about whether Batfish parses the snapshot or whether
Containerlab boots the lab -- those need your machine and are listed as
BLOCKERS at the end of the run.

    python pipeline/verify_pilot.py
    python pipeline/verify_pilot.py --skip-repro     (faster; skips check 8)
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl.emit import extract_batfish_sections                     # noqa: E402
from nrl.manifest import RUNTIME_DIRS, in_build_scope              # noqa: E402
from nrl.topologies import TOPOLOGIES                              # noqa: E402
from nrl.topologies import build_golden as build_golden_spec       # noqa: E402
from nrl.topology import LINKS, build_golden                      # noqa: E402
from nrl.render import render_scenario                            # noqa: E402

FAIL = []
PASS = 0


def check(label, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL.append((label, detail))
        print(f"  [FAIL] {label}")
        if detail:
            print(f"         {detail}")
    return ok


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. There is deliberately NO default: a default of data/pilot-v1 once ran every command against the old pilot whose ledger was already complete, and printed success.")
    ap.add_argument("--skip-repro", action="store_true")
    args = ap.parse_args()
    root = (REPO / args.pilot).resolve()

    print(f"verifying {root}\n")
    manifest = json.loads((root / "manifest.json").read_text())
    lock = json.loads((root / "pilot.lock.json").read_text())
    cands = sorted((root / "candidates").iterdir())
    incs = sorted((root / "incidents").iterdir())
    # pilot-v1 has one reference golden; pilot-v2 has one per topology
    refs = sorted(d for d in (root / "reference").iterdir() if d.is_dir())

    # ---------------------------------------------------------------- 1
    manifest = json.loads((root / "manifest.json").read_text())
    print("CHECK 1 -- counts and structure")
    # manifest-driven so the same verifier serves pilot-v1 and pilot-v2
    check(f"{manifest['n_incidents']} incidents",
          len(incs) == manifest["n_incidents"], f"got {len(incs)}")
    check(f"{manifest['n_candidates']} candidates",
          len(cands) == manifest["n_candidates"], f"got {len(cands)}")
    check("manifest agrees with what is on disk",
          manifest["n_candidates"] == len(cands),
          f"manifest says {manifest['n_candidates']}, disk has {len(cands)}")
    missing = [c.name for c in cands
               if not (c / "meta.json").exists()
               or not (c / "artifact" / "topology.clab.yml").exists()
               or not (c / "batfish-snapshot" / "configs").is_dir()
               or not (c / "diffs" / "faulted_to_candidate.diff").exists()]
    check("every candidate has meta + artifact + snapshot + diffs",
          not missing, f"incomplete: {missing[:5]}")

    # ---------------------------------------------------------------- 2
    print("\nCHECK 2 -- SAME-ARTIFACT PROOF (the critical one)")
    print("  For every candidate and every router: the bytes inside the Batfish")
    print("  snapshot must be byte-identical to the files Containerlab mounts.")
    bad, n_pairs = [], 0
    for d in cands + incs + refs:
        for cfg in sorted((d / "batfish-snapshot" / "configs").glob("*.cfg")):
            node = cfg.stem
            sec = extract_batfish_sections(cfg.read_text())
            adir = d / "artifact" / "devices" / node
            src_if = adir.joinpath("interfaces").read_text()
            src_frr = adir.joinpath("frr.conf").read_text()
            n_pairs += 1
            if sec["hostname"] != node:
                bad.append(f"{d.name}/{node}: hostname line")
            if sec["interfaces"].rstrip("\n") != src_if.rstrip("\n"):
                bad.append(f"{d.name}/{node}: interfaces bytes differ")
            if sec["frr.conf"].rstrip("\n") != src_frr.rstrip("\n"):
                bad.append(f"{d.name}/{node}: frr.conf bytes differ")
    check(f"snapshot bytes == artifact bytes for all {n_pairs} device configs",
          not bad, f"{len(bad)} mismatch(es): {bad[:4]}")

    # ---------------------------------------------------------------- 3
    print("\nCHECK 3 -- topology validity (clab references vs artifact)")
    # per-candidate/incident topology, so multi-topology pilots are checked
    # against their OWN link count rather than one hardcoded network
    topo_of = {}
    for c in manifest.get("candidates", []):
        if c.get("topology"): topo_of[c["candidate_id"]] = c["topology"]
    for i in manifest.get("incidents", []):
        if i.get("topology"): topo_of[i["incident_id"]] = i["topology"]
    prob = []
    for d in cands + incs:
        clab = (d / "artifact" / "topology.clab.yml").read_text()
        for m in re.finditer(r"- ([\w./-]+):(/[\w./-]+)", clab):
            src = d / "artifact" / m.group(1)
            if not src.exists():
                prob.append(f"{d.name}: bind source missing {m.group(1)}")
        eps = re.findall(r'endpoints: \["(\w+):(\w+)", "(\w+):(\w+)"\]', clab)
        want = len(TOPOLOGIES[topo_of.get(d.name, "t2")].links) if topo_of \
            else len(LINKS)
        if len(eps) != want:
            prob.append(f"{d.name}: {len(eps)} links, expected {want}")
        for a, ai, b, bi in eps:
            for node, ifn in ((a, ai), (b, bi)):
                dev = d / "artifact" / "devices" / node
                if (dev / "interfaces").exists():
                    if f"iface {ifn}" not in (dev / "interfaces").read_text():
                        prob.append(f"{d.name}: {node} has no iface {ifn}")
                elif (dev / "setup.sh").exists():
                    if f"dev {ifn}" not in (dev / "setup.sh").read_text():
                        prob.append(f"{d.name}: host {node} missing {ifn}")
                else:
                    prob.append(f"{d.name}: no config dir for {node}")
    check("every clab bind source exists and every endpoint is configured",
          not prob, f"{len(prob)} problem(s): {prob[:4]}")

    # ---------------------------------------------------------------- 3b
    print("\nCHECK 3b -- on-disk names match the model EXACTLY (case included)")
    print("  A case-insensitive filesystem will happily serve devices/corea/")
    print("  out of a directory literally named coreA/. Batfish and Windows do")
    print("  not care; a Linux bind-mount does.")
    topo_names = manifest.get("topologies")
    if topo_names:
        expected_nodes = set()
        for tn in topo_names:
            expected_nodes |= set(build_golden_spec(TOPOLOGIES[tn]).devices)
    else:
        expected_nodes = set(build_golden().devices)
    wrong_case = []
    for d in cands + incs + refs:
        for sub in sorted((d / "artifact" / "devices").iterdir()):
            if sub.name not in expected_nodes:
                wrong_case.append(f"{d.name}/artifact/devices/{sub.name}")
        for cfg in sorted((d / "batfish-snapshot" / "configs").glob("*.cfg")):
            if cfg.stem not in expected_nodes:
                wrong_case.append(f"{d.name}/batfish-snapshot/configs/{cfg.name}")
    check("every device directory and config filename matches a model node "
          "name exactly", not wrong_case,
          f"{len(wrong_case)} mismatched: {sorted(set(wrong_case))[:4]}")

    # ---------------------------------------------------------------- 4
    print("\nCHECK 4 -- address plan (per topology)")
    seen, dupes, mism = {}, [], []
    link_sets = ([(tn, TOPOLOGIES[tn].links) for tn in topo_names]
                 if topo_names else [("t2", LINKS)])
    for _tn, _links in link_sets:
      seen = {}
      for (a, ai, aa, b, bi, ba, subnet, label, cost) in _links:
        net = ipaddress.ip_network(subnet)
        for node, addr in ((a, aa), (b, ba)):
            ip = ipaddress.ip_interface(addr).ip
            if ip in seen:
                dupes.append(f"[{_tn}] {ip} on {seen[ip]} and {node}")
            seen[ip] = node
            if ip not in net:
                mism.append(f"[{_tn}] {node} {addr} not in {subnet}")

    check("no duplicate IP addresses anywhere", not dupes, str(dupes[:4]))
    check("both endpoints of every link are inside its subnet", not mism,
          str(mism[:4]))
    check("every /30 link has exactly 2 host addresses",
          all(ipaddress.ip_network(l[6]).prefixlen != 30
              or ipaddress.ip_network(l[6]).num_addresses == 4
              for _tn, _ls in link_sets for l in _ls))

    # ---------------------------------------------------------------- 5
    print("\nCHECK 5 -- no accidental duplicate or conflicting artifacts")
    # Hash the DEVICE CONFIGS only. topology.clab.yml carries a per-candidate
    # lab name, so including it would make every artifact trivially unique and
    # the check would prove nothing. What matters is whether two candidates
    # produce the same network.
    groups = defaultdict(list)
    for c in cands:
        h = hashlib.sha256()
        base = c / "artifact" / "devices"
        for f in sorted(base.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(base)).encode())
                h.update(f.read_bytes())
        groups[h.hexdigest()].append(c.name)
    sizes = Counter(len(v) for v in groups.values())
    revert = [v for v in groups.values() if len(v) > 1]
    expected_revert = sorted(
        m["candidate_id"] for m in manifest["candidates"]
        if m.get("repair_id") == "R-exact_revert")
    if expected_revert:      # pilot-v1: one duplicate group, all equal to golden
        ok = (len(revert) == 1 and sorted(revert[0]) == expected_revert)
        check("the only duplicated artifact is the exact_revert group "
              f"({len(expected_revert)} of them, equal to golden by "
              "construction)", ok,
              f"duplicate groups: {[sorted(v) for v in revert]}")
    else:                    # pilot-v2: the builder dedupes, so expect NONE
        check("no duplicated device-config sets (pilot-v2 drops no-ops and "
              "duplicates at build time)", not revert,
              f"duplicate groups: {[sorted(v) for v in revert][:3]}")
    print(f"         distinct device-config sets: {len(groups)} of {len(cands)}  "
          f"(group sizes: {dict(sizes)})")

    # ---------------------------------------------------------------- 6
    print("\nCHECK 6 -- every candidate actually changes something")
    empty = []
    for c in cands:
        d = (c / "diffs" / "faulted_to_candidate.diff").read_text()
        if len([l for l in d.split("\n")
                if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]) == 0:
            empty.append(c.name)
    check(f"faulted->candidate diff is non-empty for all {len(cands)}", not empty,
          f"empty: {empty}")

    # ---------------------------------------------------------------- 7
    print("\nCHECK 7 -- leakage guard")
    banned = {"fault_id", "fault_family", "fault_description", "repair_id",
              "repair_description", "incident_id", "candidate_id"}
    leaks = []
    for c in cands:
        m = json.loads((c / "meta.json").read_text())
        for block in ("change_stats", "spec_coverage"):
            for k in m[block]:
                if k in banned:
                    leaks.append(f"{c.name}: {block}.{k}")
        if "provenance" not in m:
            leaks.append(f"{c.name}: provenance block missing")
        if m["label"] is not None:
            leaks.append(f"{c.name}: label pre-filled -- outcomes must come "
                         f"from Phase 3 measurement")
    check("no provenance field leaked into change_stats / spec_coverage, "
          "and no label is pre-assigned", not leaks, str(leaks[:4]))

    # ---------------------------------------------------------------- 8
    print("\nCHECK 8 -- reproducibility and stale files (Phase 1 scope only)")
    print(f"  runtime output {list(RUNTIME_DIRS)} is excluded: it is owned by")
    print("  the phase that produced it and is not expected to be reproducible.")
    disk = {str(f.relative_to(root)).replace("\\", "/"): sha(f)
            for f in sorted(root.rglob("*"))
            if f.is_file() and f.name != "pilot.lock.json"
            and in_build_scope(f.relative_to(root))}
    stale = sorted(set(disk) - set(lock["sha256"]))
    check("no stale files left over from an earlier run", not stale,
          f"{len(stale)} stale: {stale[:4]}")
    drift = [k for k in lock["sha256"] if disk.get(k) != lock["sha256"][k]]
    check("every file matches the lock", not drift,
          f"{len(drift)} changed: {drift[:4]}")

    if args.skip_repro:
        print("  [SKIP] byte-identical rebuild (--skip-repro)")
    else:
        with tempfile.TemporaryDirectory() as td:
            builder = lock.get("builder", "build_pilot.py")
            bargs = list(lock.get("build_args", []))
            r = subprocess.run(
                [sys.executable, str(REPO / "pipeline" / builder),
                 "--out", td, "--force", *bargs],
                capture_output=True, text=True, cwd=str(REPO))
            print(f"         rebuilding with {builder} {' '.join(bargs)}")
            if r.returncode != 0:
                check("rebuild succeeded", False, r.stderr[-500:])
            else:
                td_p = Path(td)
                re_hash = {str(f.relative_to(td_p)).replace("\\", "/"): sha(f)
                           for f in sorted(td_p.rglob("*"))
                           if f.is_file() and f.name != "pilot.lock.json"
                           and in_build_scope(f.relative_to(td_p))}
                # Previously meta.json/manifest.json were excluded because they
                # carried timestamps. They no longer do, so every in-scope file
                # is now compared -- strictly stronger than before.
                vol = set()
                a = {k: v for k, v in re_hash.items() if k not in vol}
                b = {k: v for k, v in lock["sha256"].items() if k not in vol}
                diff = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
                check("a fresh rebuild is byte-identical (timestamps excluded)",
                      not diff, f"{len(diff)} differ: {sorted(diff)[:4]}")
                print(f"         compared {len(a)} files; "
                      f"{len(vol)} excluded")

    # ---------------------------------------------------------------- summary
    print(f"\n{'=' * 74}")
    print(f"{PASS} passed, {len(FAIL)} failed")
    if FAIL:
        for l, d in FAIL:
            print(f"  FAILED: {l}\n          {d}")
    print(f"{'=' * 74}")
    if lock.get("artifact_digest"):
        print(f"\n  artifact digest: {lock['artifact_digest'][:16]}...")
        print("  The spike and Phase 2 record this and refuse to run against a")
        print("  pilot that has been rebuilt underneath them.")

    print("""
NOT CHECKED HERE -- these need your machine and are Phase 2 blockers:
  * Does Batfish PARSE the FRR snapshot (fileParseStatus / parseWarning)?
  * Do interface addresses survive the concatenated format?
  * Does `containerlab deploy` boot the lab and do OSPF adjacencies form?
Run pipeline/spike_frr_batfish.py for the first two.""")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
