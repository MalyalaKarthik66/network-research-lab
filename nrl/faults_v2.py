"""Incident generation across topologies: 10 families x N parameterisations x 3 topologies."""
from __future__ import annotations

from typing import Dict, List

from .faults import (Fault, _add_static, _area_mismatch, _cost_inversion,
                     _iface_down, _ospf_removed, _passive_transit, _wrong_addr)
from .topologies import TopologySpec

HOST_PREFIXES = ["10.20.0.0/24", "10.21.0.0/24", "10.10.0.0/24"]
HOST32 = ["10.20.0.10/32", "10.21.0.10/32", "10.10.0.10/32"]


def _take(seq, n):
    return [seq[i % len(seq)] for i in range(n)]


def build_incidents(spec: TopologySpec, per_family: int = 5,
                    start: int = 0) -> List[Fault]:
    """Every fault is anchored to a real element of THIS topology, so the same
    family lands on different devices, links and prefixes in each network."""
    T = spec.transit
    R = sorted(spec.routers)
    F: List[Fault] = []
    n = start

    def add(family, desc, params, fn):
        nonlocal n
        n += 1
        params = dict(params, topology=spec.name)
        F.append(Fault(f"F{n:04d}", family, f"[{spec.name}] {desc}", params, fn))

    for node, ifc, addr, peer, pifc, paddr, label, cost in _take(T, per_family):
        add("iface_down", f"{node} {ifc} shut ({label})",
            {"node": node, "iface": ifc, "peer": peer, "peer_iface": pifc,
             "link": label, "good_cost": cost}, _iface_down(node, ifc))

    for i, (node, ifc, addr, peer, pifc, paddr, label, cost) in enumerate(_take(T, per_family)):
        bad = f"10.{200 + i}.{i}.2/30"
        add("iface_wrong_addr", f"{node} {ifc} renumbered off the shared /30",
            {"node": node, "iface": ifc, "bad": bad, "good": addr,
             "peer": peer, "peer_iface": pifc, "link": label,
             "peer_align": f"10.{200 + i}.{i}.1/30", "good_cost": cost},
            _wrong_addr(node, ifc, bad))

    for i, (node, ifc, addr, peer, pifc, paddr, label, cost) in enumerate(_take(T, per_family)):
        ba = f"0.0.0.{i + 1}"
        add("ospf_area_mismatch", f"{node} {ifc} moved to area {ba}",
            {"node": node, "iface": ifc, "bad_area": ba, "good_area": "0.0.0.0",
             "peer": peer, "peer_iface": pifc, "link": label, "good_cost": cost},
            _area_mismatch(node, ifc, ba))

    for node, ifc, addr, peer, pifc, paddr, label, cost in _take(T, per_family):
        add("ospf_passive_transit", f"{node} {ifc} marked passive ({label})",
            {"node": node, "iface": ifc, "peer": peer, "peer_iface": pifc,
             "link": label, "good_cost": cost}, _passive_transit(node, ifc))

    for node, ifc, addr, peer, pifc, paddr, label, cost in _take(T, per_family):
        add("ospf_iface_removed", f"{node} {ifc} dropped out of OSPF",
            {"node": node, "iface": ifc, "peer": peer, "peer_iface": pifc,
             "link": label, "good_cost": cost, "good_area": "0.0.0.0"},
            _ospf_removed(node, ifc))

    for node, ifc, addr, peer, pifc, paddr, label, cost in _take(T, per_family):
        bad = 1 if cost >= 100 else 500
        add("ospf_cost_inversion", f"{node} {ifc} cost {cost} -> {bad}",
            {"pairs": [(node, ifc)], "node": node, "iface": ifc,
             "bad_cost": bad, "good_cost": cost, "link": label},
            _cost_inversion([(node, ifc)], bad))

    for node, ifc, addr, peer, pifc, paddr, label, cost in _take(T, per_family):
        add("ospf_cost_excessive", f"{node} {ifc} cost {cost} -> 65535",
            {"pairs": [(node, ifc)], "node": node, "iface": ifc,
             "bad_cost": 65535, "good_cost": cost, "link": label},
            _cost_inversion([(node, ifc)], 65535))

    for i in range(per_family):
        node = R[i % len(R)]
        pfx = HOST_PREFIXES[i % len(HOST_PREFIXES)]
        add("static_blackhole", f"{node} blackholes {pfx}",
            {"node": node, "prefix": pfx, "nexthop": "blackhole"},
            _add_static(node, pfx, "blackhole"))

    for i in range(per_family):
        pfx = HOST_PREFIXES[i % len(HOST_PREFIXES)]
        owner, _u = _owner_and_upstream(spec, pfx)
        node, nh = _misdirection(spec, owner, i)
        if node is None:            # no router with an alternative neighbour
            continue
        add("static_wrong_nexthop",
            f"{node} sends {pfx} to {nh}, off the shortest path",
            {"node": node, "prefix": pfx, "nexthop": nh},
            _add_static(node, pfx, nh))

    for i in range(per_family):
        pfx = HOST32[i % len(HOST32)]
        owner, nh = _owner_and_upstream(spec, pfx)
        if owner is None:
            continue
        peer = next((x[3] for x in spec.transit if x[0] == owner), "?")
        add("static_route_loop",
            f"{owner} installs {pfx} pointing back upstream at {peer}",
            {"node": owner, "prefix": pfx, "nexthop": nh,
             "loop_with": peer}, _add_static(owner, pfx, nh))
    return F


def _first_hop(spec, src, dst):
    """Neighbour of `src` on the shortest OSPF path to `dst`."""
    import heapq
    adj = {}
    for (a, ai, aa, b, bi, ba, net, label, cost) in spec.links:
        if a in spec.routers and b in spec.routers:
            adj.setdefault(a, []).append((b, cost))
            adj.setdefault(b, []).append((a, cost))
    dist, prev, pq = {src: 0}, {}, [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1 << 30):
            continue
        for v, c in adj.get(u, []):
            if d + c < dist.get(v, 1 << 30):
                dist[v] = d + c; prev[v] = u; heapq.heappush(pq, (dist[v], v))
    cur, path = dst, []
    while cur in prev:
        path.append(cur); cur = prev[cur]
    return path[-1] if path else None


def _owner_and_upstream(spec, prefix):
    """(edge router owning this LAN, address of its upstream neighbour).

    A loop needs the /32 on the router that OWNS the destination LAN, pointing
    upstream -- the upstream router's own route for that LAN points back here.
    Installing it anywhere else just duplicates what OSPF already does, which
    is why the first attempt produced DELIVERED_TO_SUBNET and no loop.
    """
    host = {"10.20.0.10/32": "hostb", "10.21.0.10/32": "hostc",
            "10.10.0.10/32": "hosta", "10.20.0.0/24": "hostb",
            "10.21.0.0/24": "hostc", "10.10.0.0/24": "hosta"}.get(prefix)
    owner = spec.hosts.get(host)
    up = next((x for x in spec.transit if x[0] == owner), None)
    return (owner, up[5].split("/")[0]) if up else (None, None)


def _misdirection(spec, dest_router, i):
    """(node, address) where the address is provably NOT the shortest-path
    next hop from that node toward dest_router."""
    out = []
    for n in sorted(spec.routers):
        if n == dest_router:
            continue
        nbrs = [(x[3], x[5]) for x in spec.transit if x[0] == n]
        if len(nbrs) < 2:
            continue
        fh = _first_hop(spec, n, dest_router)
        wrong = [(p, a) for p, a in nbrs if p != fh]
        if wrong:
            out.append((n, wrong[0][1].split("/")[0]))
    return out[i % len(out)] if out else (None, None)


def fault_targets(fault: Fault) -> Dict:
    p = fault.params
    if "pairs" in p:
        return {"node": p["pairs"][0][0], "iface": p["pairs"][0][1]}
    return {"node": p.get("node"), "iface": p.get("iface")}
