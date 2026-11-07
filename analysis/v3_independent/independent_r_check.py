"""Independent raw-RIB cross-check for v3 measured blast radius.

This intentionally does not import nrl.flowmatrix or any prior v3 audit script.
"""
from __future__ import annotations

import csv
import ipaddress
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from nrl.topologies_v3 import resolve

PILOT = ROOT / "data" / "pilot-v3"
P3 = PILOT / "phase3"
OUT = ROOT / "analysis" / "v3_independent"


def route_state(run_id, spec):
    state = {}
    for node in spec.routers:
        path = P3 / "runs" / run_id / "state" / f"{node}.route.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        state[node] = raw["json"]
    return state


def owner_map(spec):
    owner = dict(spec.routers)
    for a, _, aa, b, _, ba, *_ in spec.links:
        owner[aa.split("/")[0]] = a
        owner[ba.split("/")[0]] = b
    return owner


def selected(entries):
    if not isinstance(entries, list):
        entries = [entries]
    entries = [e for e in entries if e.get("protocol") != "kernel"]
    for entry in entries:
        if entry.get("selected") or entry.get("installed"):
            return entry
    return min(entries, key=lambda e: (e.get("distance", 255), e.get("metric", 10**9))) if entries else None


def lpm(rib, dst):
    ip = ipaddress.ip_address(dst)
    best = None
    best_len = -1
    for prefix, entries in rib.items():
        try:
            network = ipaddress.ip_network(prefix)
        except ValueError:
            continue
        if ip in network and network.prefixlen > best_len:
            entry = selected(entries)
            if entry is not None:
                best, best_len = entry, network.prefixlen
    return best


def walk(ribs, source_router, dst, owner):
    path = [source_router]
    current = source_router
    for _ in range(16):
        entry = lpm(ribs.get(current, {}), dst)
        if entry is None:
            return tuple(path), "NO_ROUTE"
        next_hops = entry.get("nexthops") or []
        if any(n.get("blackhole") or n.get("unreachable") or n.get("reject") for n in next_hops):
            return tuple(path), "BLACKHOLE"
        ips = sorted(n.get("ip") for n in next_hops if n.get("ip"))
        if not ips:
            return tuple(path), "OK"
        nxt = owner.get(ips[0])
        if nxt is None:
            return tuple(path), "UNKNOWN_NH"
        if nxt in path:
            return tuple(path + [nxt]), "LOOP"
        path.append(nxt)
        current = nxt
    return tuple(path), "MAX_HOPS"


def endpoints(spec):
    result = [{"name": n, "addr": addr} for n, addr in sorted(spec.routers.items())]
    seen = set()
    for a, _, aa, b, _, ba, *_ in spec.links:
        for node, addr in ((a, aa), (b, ba)):
            if node in spec.hosts and node not in seen:
                result.append({"name": node, "addr": addr.split("/")[0]})
                seen.add(node)
    return result


def paths(run_id, spec):
    ribs = route_state(run_id, spec)
    owner = owner_map(spec)
    if ribs is None:
        return None
    attach = dict(spec.hosts)
    result = {}
    eps = endpoints(spec)
    for source in eps:
        for dest in eps:
            if source["addr"] == dest["addr"]:
                continue
            source_router = attach.get(source["name"], source["name"])
            path, term = walk(ribs, source_router, dest["addr"], owner)
            result[f'{source["name"]}->{dest["name"]}'] = {"path": path, "term": term}
    return result


def score(golden, candidate):
    broken_terms = {"NO_ROUTE", "LOOP", "BLACKHOLE"}
    unknown_terms = {"UNKNOWN_NH", "MAX_HOPS"}
    carried = [fid for fid, row in golden.items() if row["term"] == "OK"]
    broken, rerouted, unknown = [], [], []
    for fid in carried:
        row = candidate.get(fid)
        if row is None or row["term"] in unknown_terms:
            unknown.append(fid)
        elif row["term"] in broken_terms:
            broken.append(fid)
        elif (row["path"], row["term"]) != (golden[fid]["path"], golden[fid]["term"]):
            rerouted.append(fid)
    denominator = len(carried) - len(unknown)
    return {"golden_flows": len(carried), "broken": len(broken),
            "rerouted": len(rerouted), "undetermined": len(unknown),
            "r": (len(broken) + len(rerouted)) / denominator if denominator else None}


def main():
    manifest = json.loads((PILOT / "manifest.json").read_text(encoding="utf-8"))
    candidates = manifest["candidates"]
    output = []
    golden_by_topology = {}
    for topology in sorted({c["topology"] for c in candidates}):
        spec = resolve(topology)
        golden_by_topology[topology] = paths(f"golden-{topology}", spec)
    for c in candidates:
        spec = resolve(c["topology"])
        golden = golden_by_topology[c["topology"]]
        candidate = paths(c["candidate_id"], spec)
        result = score(golden, candidate)
        output.append({"candidate_id": c["candidate_id"], **result})
    with (OUT / "independent_r.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    prior = {r["candidate_id"]: r for r in csv.DictReader(
        (ROOT / "analysis" / "v3_audit" / "measured_blast_radius.csv").open(newline="", encoding="utf-8"))}
    mismatches = []
    for row in output:
        p = prior[row["candidate_id"]]
        if round(float(row["r"]), 6) != round(float(p["r"]), 6) or any(
            int(row[k]) != int(float(p[key])) for k, key in
            (("golden_flows", "golden_carried_flows"), ("broken", "broken_flows"),
             ("rerouted", "rerouted_flows"), ("undetermined", "undetermined_flows"))):
            mismatches.append({"candidate_id": row["candidate_id"], "independent": row, "prior": p})
    print(json.dumps({"n": len(output), "mismatches": len(mismatches),
                      "sample": output[:5], "mismatch_examples": mismatches[:5]}, indent=2))


if __name__ == "__main__":
    main()
