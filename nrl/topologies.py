"""Multiple topologies for pilot-v2.

pilot-v1 used one 9-node topology. The validation build showed why that caps the
dataset: the CORRECT repair class saturates at ~40 distinct networks no matter
how many incidents you add, because benign modifications of a single small
network run out. Topology variation is the only way to scale that class, and it
is also what lets the paper claim generalisation rather than one lucky network.

All three topologies share an addressing CONVENTION so the frozen property suite
applies unchanged:

    hosta 10.10.0.10   (site A)      hostb 10.20.0.10, hostc 10.21.0.10 (site B)
    loopbacks 10.255.0.x             transit subnets 10.<topo>.x.y/30

Each has a primary and a more expensive backup path between the sites, which is
the structure the whole harm story depends on. Only two property parameters vary
per topology: how many OSPF adjacencies exist (P08) and which nodes the primary
path traverses (P06).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from .model import Device, Iface, Link, OspfCfg, Scenario

AREA = "0.0.0.0"


@dataclass
class TopologySpec:
    name: str
    links: List[tuple]                 # (a,ai,aa,b,bi,ba,subnet,label,cost)
    routers: Dict[str, str]            # node -> loopback ip
    hosts: Dict[str, str]              # host -> attached router
    passive: Set[Tuple[str, str]]
    primary_path: List[str]            # P06 must_traverse
    n_adjacencies: int                 # P08 expected

    @property
    def transit(self) -> List[tuple]:
        """(node, iface, own_addr, peer, peer_iface, PEER_ADDR, label, cost)

        peer_addr used to be dropped. Faults that need a neighbour's address as
        a next hop then used the node's OWN address, which is unresolvable --
        producing NEIGHBOR_UNREACHABLE instead of the intended routing loop or
        misdirection, in 20 of 100 incidents.
        """
        out = []
        for (a, ai, aa, b, bi, ba, subnet, label, cost) in self.links:
            if a in self.routers and b in self.routers:
                out.append((a, ai, aa, b, bi, ba, label, cost))
                out.append((b, bi, ba, a, ai, aa, label, cost))
        return out

    @property
    def backup(self) -> List[Tuple[str, str]]:
        return [(l[0], l[1]) for l in self.links if "backup" in l[7]] + \
               [(l[3], l[4]) for l in self.links if "backup" in l[7]]


def _spec(name, links, routers, hosts, passive, primary, n_adj):
    return TopologySpec(name, links, routers, hosts, passive, primary, n_adj)


# --------------------------------------------------------------- T1: 4 routers
T1 = _spec(
    "t1",
    [("hosta", "eth1", "10.10.0.10/24", "edgea", "eth1", "10.10.0.1/24",
      "10.10.0.0/24", "siteA-lan", 10),
     ("edgea", "eth2", "10.1.1.1/30", "corea", "eth1", "10.1.1.2/30",
      "10.1.1.0/30", "siteA-core", 10),
     ("corea", "eth2", "10.1.2.1/30", "coreb", "eth1", "10.1.2.2/30",
      "10.1.2.0/30", "wan-primary", 10),
     ("coreb", "eth2", "10.1.3.1/30", "edgeb", "eth1", "10.1.3.2/30",
      "10.1.3.0/30", "siteB-core", 10),
     ("edgeb", "eth2", "10.20.0.1/24", "hostb", "eth1", "10.20.0.10/24",
      "10.20.0.0/24", "siteB-lan1", 10),
     ("edgeb", "eth3", "10.21.0.1/24", "hostc", "eth1", "10.21.0.10/24",
      "10.21.0.0/24", "siteB-lan2", 10),
     ("edgea", "eth3", "10.1.9.1/30", "edgeb", "eth4", "10.1.9.2/30",
      "10.1.9.0/30", "wan-backup", 100)],
    {"edgea": "10.255.0.1", "corea": "10.255.0.2",
     "coreb": "10.255.0.5", "edgeb": "10.255.0.6"},
    {"hosta": "edgea", "hostb": "edgeb", "hostc": "edgeb"},
    {("edgea", "eth1"), ("edgeb", "eth2"), ("edgeb", "eth3")},
    ["corea", "coreb"], 4)

# --------------------------------------------------------------- T2: 6 routers
T2 = _spec(
    "t2",
    [("hosta", "eth1", "10.10.0.10/24", "edgea", "eth1", "10.10.0.1/24",
      "10.10.0.0/24", "siteA-lan", 10),
     ("edgea", "eth2", "10.2.1.1/30", "corea", "eth1", "10.2.1.2/30",
      "10.2.1.0/30", "siteA-core", 10),
     ("corea", "eth2", "10.2.2.1/30", "wan1", "eth1", "10.2.2.2/30",
      "10.2.2.0/30", "siteA-wan", 10),
     ("wan1", "eth2", "10.2.3.1/30", "wan2", "eth1", "10.2.3.2/30",
      "10.2.3.0/30", "wan-primary", 10),
     ("wan2", "eth2", "10.2.4.1/30", "coreb", "eth1", "10.2.4.2/30",
      "10.2.4.0/30", "wan-siteB", 10),
     ("coreb", "eth2", "10.2.5.1/30", "edgeb", "eth1", "10.2.5.2/30",
      "10.2.5.0/30", "siteB-core", 10),
     ("edgeb", "eth2", "10.20.0.1/24", "hostb", "eth1", "10.20.0.10/24",
      "10.20.0.0/24", "siteB-lan1", 10),
     ("edgeb", "eth3", "10.21.0.1/24", "hostc", "eth1", "10.21.0.10/24",
      "10.21.0.0/24", "siteB-lan2", 10),
     ("corea", "eth3", "10.2.9.1/30", "coreb", "eth3", "10.2.9.2/30",
      "10.2.9.0/30", "wan-backup", 100)],
    {"edgea": "10.255.0.1", "corea": "10.255.0.2", "wan1": "10.255.0.3",
     "wan2": "10.255.0.4", "coreb": "10.255.0.5", "edgeb": "10.255.0.6"},
    {"hosta": "edgea", "hostb": "edgeb", "hostc": "edgeb"},
    {("edgea", "eth1"), ("edgeb", "eth2"), ("edgeb", "eth3")},
    ["wan1", "wan2"], 6)

# --------------------------------------------------------------- T3: 8 routers
T3 = _spec(
    "t3",
    [("hosta", "eth1", "10.10.0.10/24", "edgea", "eth1", "10.10.0.1/24",
      "10.10.0.0/24", "siteA-lan", 10),
     ("edgea", "eth2", "10.3.1.1/30", "corea", "eth1", "10.3.1.2/30",
      "10.3.1.0/30", "siteA-core", 10),
     ("corea", "eth2", "10.3.2.1/30", "wan1", "eth1", "10.3.2.2/30",
      "10.3.2.0/30", "siteA-wan-a", 10),
     ("wan1", "eth2", "10.3.3.1/30", "wan2", "eth1", "10.3.3.2/30",
      "10.3.3.0/30", "wan-primary", 10),
     ("wan2", "eth2", "10.3.4.1/30", "coreb", "eth1", "10.3.4.2/30",
      "10.3.4.0/30", "wan-siteB-a", 10),
     ("corea", "eth4", "10.3.6.1/30", "wan3", "eth1", "10.3.6.2/30",
      "10.3.6.0/30", "siteA-wan-b", 20),
     ("wan3", "eth2", "10.3.7.1/30", "wan4", "eth1", "10.3.7.2/30",
      "10.3.7.0/30", "wan-secondary", 20),
     ("wan4", "eth2", "10.3.8.1/30", "coreb", "eth4", "10.3.8.2/30",
      "10.3.8.0/30", "wan-siteB-b", 20),
     ("coreb", "eth2", "10.3.5.1/30", "edgeb", "eth1", "10.3.5.2/30",
      "10.3.5.0/30", "siteB-core", 10),
     ("edgeb", "eth2", "10.20.0.1/24", "hostb", "eth1", "10.20.0.10/24",
      "10.20.0.0/24", "siteB-lan1", 10),
     ("edgeb", "eth3", "10.21.0.1/24", "hostc", "eth1", "10.21.0.10/24",
      "10.21.0.0/24", "siteB-lan2", 10),
     ("corea", "eth3", "10.3.9.1/30", "coreb", "eth3", "10.3.9.2/30",
      "10.3.9.0/30", "wan-backup", 100)],
    {"edgea": "10.255.0.1", "corea": "10.255.0.2", "wan1": "10.255.0.3",
     "wan2": "10.255.0.4", "coreb": "10.255.0.5", "edgeb": "10.255.0.6",
     "wan3": "10.255.0.7", "wan4": "10.255.0.8"},
    {"hosta": "edgea", "hostb": "edgeb", "hostc": "edgeb"},
    {("edgea", "eth1"), ("edgeb", "eth2"), ("edgeb", "eth3")},
    ["wan1", "wan2"], 9)

# ---------------------------------------------------- pilot-v1's network
# Mirrors nrl/topology.py byte-for-byte in structure and addressing. pilot-v1
# was built and measured against it, so it must keep its own subnets (10.0.x.x)
# rather than being folded into t2 (10.2.x.x). Having it here means v1 and v2
# both resolve expectations through ONE mechanism instead of two.
def _t2v1() -> TopologySpec:
    from .topology import HOSTS, LINKS, PASSIVE, ROUTERS
    return _spec("t2v1", list(LINKS), dict(ROUTERS), dict(HOSTS),
                 set(PASSIVE), ["wan1", "wan2"], 6)


T2V1 = _t2v1()



# ---------------------------------------------------------------------------
# Topology builder
# ---------------------------------------------------------------------------
# Hand-writing link tuples is how P06/P08 get mis-specified. This assigns
# interface names and /30 subnets mechanically and computes the primary path by
# Dijkstra over OSPF cost, so the two topology-dependent property parameters are
# DERIVED from the network rather than asserted about it.

def make_topology(name: str, octet: int, edges, site_a: str, site_b: str,
                  backup_label: str = "wan-backup") -> TopologySpec:
    """edges: [(a, b, label, cost)] between routers. Hosts are attached
    automatically: hosta -> site_a, hostb/hostc -> site_b."""
    routers, order = [], {}
    for a, b, _l, _c in edges:
        for n in (a, b):
            if n not in order:
                order[n] = len(order); routers.append(n)

    nxt = {n: 1 for n in routers}
    links, sub = [], 1

    def take(n):
        i = nxt[n]; nxt[n] += 1; return f"eth{i}"

    # host links first so hosta is always on the site-A edge's eth1
    links.append(("hosta", "eth1", "10.10.0.10/24", site_a, take(site_a),
                  "10.10.0.1/24", "10.10.0.0/24", "siteA-lan", 10))
    links.append((site_b, take(site_b), "10.20.0.1/24", "hostb", "eth1",
                  "10.20.0.10/24", "10.20.0.0/24", "siteB-lan1", 10))
    links.append((site_b, take(site_b), "10.21.0.1/24", "hostc", "eth1",
                  "10.21.0.10/24", "10.21.0.0/24", "siteB-lan2", 10))

    for a, b, label, cost in edges:
        net = f"10.{octet}.{sub}.0/30"
        links.append((a, take(a), f"10.{octet}.{sub}.1/30",
                      b, take(b), f"10.{octet}.{sub}.2/30", net, label, cost))
        sub += 1

    rmap = {n: f"10.255.0.{order[n] + 1}" for n in routers}
    passive = {(site_a, "eth1")}
    for l in links:
        if l[3] in ("hostb", "hostc"):
            passive.add((l[0], l[1]))

    # Dijkstra over OSPF cost -> which routers the primary path traverses
    adj = {n: [] for n in routers}
    for a, b, label, cost in edges:
        adj[a].append((b, cost)); adj[b].append((a, cost))
    import heapq
    dist = {site_a: 0}; prev = {}; pq = [(0, site_a)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1 << 30):
            continue
        for v, c in adj[u]:
            if d + c < dist.get(v, 1 << 30):
                dist[v] = d + c; prev[v] = u; heapq.heappush(pq, (dist[v], v))
    path, cur = [], site_b
    while cur in prev:
        path.append(cur); cur = prev[cur]
    path.append(site_a)
    primary = [n for n in reversed(path) if n not in (site_a, site_b)]

    return TopologySpec(name, links, rmap,
                        {"hosta": site_a, "hostb": site_b, "hostc": site_b},
                        passive, primary or [site_a], len(edges))


# ten genuinely different shapes, all sharing the host-addressing convention
_DESIGNS = [
    ("t01_chain4", 11, [("edgea", "corea", "siteA", 10), ("corea", "coreb", "wan-primary", 10),
                        ("coreb", "edgeb", "siteB", 10), ("edgea", "edgeb", "wan-backup", 100)]),
    ("t02_wan6", 12, [("edgea", "corea", "siteA", 10), ("corea", "wan1", "wanA", 10),
                      ("wan1", "wan2", "wan-primary", 10), ("wan2", "coreb", "wanB", 10),
                      ("coreb", "edgeb", "siteB", 10), ("corea", "coreb", "wan-backup", 100)]),
    ("t03_dual8", 13, [("edgea", "corea", "siteA", 10), ("corea", "wan1", "wanA1", 10),
                       ("wan1", "wan2", "wan-primary", 10), ("wan2", "coreb", "wanB1", 10),
                       ("corea", "wan3", "wanA2", 20), ("wan3", "wan4", "wan-secondary", 20),
                       ("wan4", "coreb", "wanB2", 20), ("coreb", "edgeb", "siteB", 10),
                       ("corea", "coreb", "wan-backup", 100)]),
    ("t04_star5", 14, [("edgea", "corea", "siteA", 10), ("corea", "hub", "hubA", 10),
                       ("hub", "coreb", "hubB", 10), ("coreb", "edgeb", "siteB", 10),
                       ("corea", "coreb", "wan-backup", 100)]),
    ("t05_ring6", 15, [("edgea", "corea", "siteA", 10), ("corea", "wan1", "ringA", 10),
                       ("wan1", "coreb", "wan-primary", 10), ("coreb", "edgeb", "siteB", 10),
                       ("corea", "wan2", "ringB", 40), ("wan2", "coreb", "wan-backup", 40)]),
    ("t06_mesh6", 16, [("edgea", "corea", "siteA", 10), ("corea", "wan1", "meshA1", 10),
                       ("corea", "wan2", "meshA2", 30), ("wan1", "coreb", "wan-primary", 10),
                       ("wan2", "coreb", "wan-backup", 30), ("coreb", "edgeb", "siteB", 10)]),
    ("t07_tier7", 17, [("edgea", "agga", "siteA", 10), ("agga", "corea", "aggA", 10),
                       ("corea", "coreb", "wan-primary", 10), ("coreb", "aggb", "aggB", 10),
                       ("aggb", "edgeb", "siteB", 10), ("agga", "aggb", "wan-backup", 100)]),
    ("t08_chain8", 18, [("edgea", "corea", "siteA", 10), ("corea", "wan1", "w1", 10),
                        ("wan1", "wan2", "w2", 10), ("wan2", "wan3", "wan-primary", 10),
                        ("wan3", "wan4", "w4", 10), ("wan4", "coreb", "w5", 10),
                        ("coreb", "edgeb", "siteB", 10), ("corea", "coreb", "wan-backup", 100)]),
    ("t09_twin6", 19, [("edgea", "corea", "siteA", 10), ("corea", "wan1", "twinA1", 10),
                       ("wan1", "coreb", "wan-primary", 10), ("corea", "wan2", "twinA2", 15),
                       ("wan2", "coreb", "wan-secondary", 15), ("coreb", "edgeb", "siteB", 10),
                       ("edgea", "edgeb", "wan-backup", 200)]),
    ("t10_deep9", 20, [("edgea", "agga", "siteA", 10), ("agga", "corea", "aggA", 10),
                       ("corea", "wan1", "wA", 10), ("wan1", "wan2", "wan-primary", 10),
                       ("wan2", "coreb", "wB", 10), ("coreb", "aggb", "aggB", 10),
                       ("aggb", "edgeb", "siteB", 10), ("corea", "coreb", "wan-backup", 100)]),
]

TEN = [make_topology(n, o, e, "edgea", "edgeb") for n, o, e in _DESIGNS]

# ---------------------------------------------------------------------------
# The other ten. Added 2026-09-02 to take the design from 10 topologies to 20
# at an unchanged candidate budget (docs/FINAL-PLAN.md section 3.4).
#
# Two reasons, both from the external reviews:
#
#  * Ten topologies gives ten leave-one-topology-out folds, so any statement
#    about between-topology variance rests on ten points -- and Phase 3 cost is
#    per CANDIDATE, not per topology, so more networks are nearly free.
#  * "All topologies come from one generator" was raised independently as a
#    threat to external validity. Four of these (marked REFERENCE) are shaped
#    from published enterprise/ISP architectures rather than from a generator's
#    idea of a graph, and results are reported split by source so the
#    generator's contribution to the rate is visible instead of assumed away.
#
# Six are 10-16 routers, which is also what makes "does residual risk grow with
# network size?" answerable. Every design keeps edgea/edgeb as the hosts'
# attachment points and at least one alternate path, or the property suite has
# nothing to discriminate.
_DESIGNS_B = [
    # REFERENCE -- collapsed-core branch with a firewall pair in the path
    ("t11_branch6", 21, [("edgea", "corea", "siteA", 10),
                         ("corea", "fw1", "fwA", 10),
                         ("fw1", "fw2", "fw-pair", 10),
                         ("fw2", "coreb", "fwB", 10),
                         ("coreb", "edgeb", "siteB", 10),
                         ("corea", "coreb", "wan-backup", 120)]),
    # REFERENCE -- classic three-tier campus, access/distribution/core
    ("t12_campus8", 22, [("edgea", "dista", "accA", 10),
                         ("dista", "agga", "aggA", 10),
                         ("agga", "corea", "coreA", 10),
                         ("corea", "coreb", "core-link", 10),
                         ("coreb", "aggb", "coreB", 10),
                         ("aggb", "distb", "aggB", 10),
                         ("distb", "edgeb", "accB", 10),
                         ("dista", "distb", "dist-xlink", 150)]),
    # two triangles joined at a waist: every path crosses one node
    ("t13_bowtie7", 23, [("edgea", "a1", "A1", 10), ("edgea", "a2", "A2", 20),
                         ("a1", "mid", "M1", 10), ("a2", "mid", "M2", 20),
                         ("mid", "b1", "M3", 10), ("mid", "b2", "M4", 20),
                         ("b1", "edgeb", "B1", 10), ("b2", "edgeb", "B2", 20)]),
    # two parallel chains with rungs: many equal-ish alternatives
    ("t14_ladder8", 24, [("edgea", "l1", "A1", 10), ("l1", "l2", "L1", 10),
                         ("l2", "l3", "L2", 10), ("l3", "edgeb", "B1", 10),
                         ("edgea", "r1", "A2", 30), ("r1", "r2", "R1", 30),
                         ("r2", "r3", "R2", 30), ("r3", "edgeb", "B2", 30),
                         ("l1", "r1", "rung1", 50), ("l2", "r2", "rung2", 50)]),
    # REFERENCE -- three-tier campus at scale, dual distribution per site
    ("t15_campus12", 25, [("edgea", "acca1", "accA1", 10),
                          ("acca1", "dista1", "dA1", 10),
                          ("acca1", "dista2", "dA1b", 30),
                          ("edgea", "acca2", "accA2", 40),
                          ("acca2", "dista2", "dA2", 10),
                          ("dista1", "corea", "cA1", 10),
                          ("dista2", "corea", "cA2", 20),
                          ("corea", "coreb", "core-link", 10),
                          ("coreb", "distb1", "cB1", 10),
                          ("coreb", "distb2", "cB2", 20),
                          ("distb1", "accb1", "dB1", 10),
                          ("accb1", "edgeb", "accB1", 10),
                          ("distb2", "accb2", "dB2", 10),
                          ("accb2", "edgeb", "accB2", 40)]),
    # REFERENCE -- small ISP PoP: PE/P core, route reflectors, dual planes
    ("t16_pop14", 26, [("edgea", "pe1", "peA1", 10), ("pe1", "p1", "pA1", 10),
                       ("p1", "p2", "core1", 10), ("p2", "pe3", "peB1", 10),
                       ("pe3", "edgeb", "peB", 10),
                       ("edgea", "pe2", "peA2", 30), ("pe2", "p3", "pA2", 30),
                       ("p3", "p4", "core2", 30), ("p4", "pe4", "peB2", 30),
                       ("pe4", "edgeb", "peB2b", 30),
                       ("p1", "p3", "xlink1", 50), ("p2", "p4", "xlink2", 50),
                       # 20, not 10. At 10 the rr chain cost pe1->pe3 exactly
                       # 30, the same as pe1->p1->p2->pe3, so there were TWO
                       # equal-cost paths and `primary_path` picked one by
                       # Dijkstra tie-breaking. P06 asserts the primary path is
                       # USED, which is false for half the traces under ECMP --
                       # the golden gate caught it on a network that is healthy
                       # by construction. A route-reflector path costing more
                       # than the P-core is also what the reference design does.
                       ("pe1", "rr1", "rrA", 20), ("rr1", "rr2", "rr-link", 20),
                       ("rr2", "pe3", "rrB", 20),
                       ("edgea", "agga", "aggA", 60), ("agga", "p1", "aggA2", 60),
                       ("edgeb", "aggb", "aggB", 60), ("aggb", "p2", "aggB2", 60)]),
    # metro ring with access spurs
    ("t17_metro13", 27, [("edgea", "agga", "accA", 10),
                         ("agga", "m1", "ringIn", 10),
                         ("m1", "m2", "ring1", 10), ("m2", "m3", "ring2", 10),
                         ("m3", "m4", "ring3", 10), ("m4", "m5", "ring4", 10),
                         # 20 on the far half. A ring with uniform costs has
                         # TWO equal-cost paths between any two nodes opposite
                         # each other -- m1->m2->m3->m4->m5 and
                         # m1->m8->m7->m6->m5 were both 40 -- so `primary_path`
                         # was one of two and P06 failed on the healthy golden.
                         # Asymmetric metro-ring costs are realistic anyway.
                         ("m5", "m6", "ring5", 20), ("m6", "m7", "ring6", 20),
                         ("m7", "m8", "ring7", 20), ("m8", "m1", "ring-close", 20),
                         ("m5", "aggb", "ringOut", 10),
                         ("aggb", "edgeb", "accB", 10),
                         ("agga", "mgmt", "mgmtA", 80),
                         ("mgmt", "aggb", "mgmtB", 80)]),
    # 2x5 grid: many equal-cost paths, which is where ECMP-shaped risk lives
    ("t18_grid12", 28, [("edgea", "g1", "accA", 10),
                        ("g1", "g2", "r1a", 10), ("g2", "g3", "r1b", 10),
                        ("g3", "g4", "r1c", 10), ("g4", "g5", "r1d", 10),
                        ("g6", "g7", "r2a", 20), ("g7", "g8", "r2b", 20),
                        ("g8", "g9", "r2c", 20), ("g9", "g10", "r2d", 20),
                        ("g1", "g6", "rung1", 30), ("g3", "g8", "rung2", 30),
                        ("g5", "g10", "rung3", 30),
                        ("g5", "edgeb", "accB", 10),
                        ("g10", "edgeb", "accB2", 40)]),
    # two long independent cores plus a slow third path
    ("t19_dualcore16", 29, [("edgea", "agga", "accA", 10),
                            ("agga", "a1", "A1", 10), ("a1", "a2", "A2", 10),
                            ("a2", "a3", "A3", 10), ("a3", "corea", "A4", 10),
                            ("corea", "coreb", "core-link", 10),
                            ("coreb", "b3", "B4", 10), ("b3", "b2", "B3", 10),
                            ("b2", "b1", "B2", 10), ("b1", "aggb", "B1", 10),
                            ("aggb", "edgeb", "accB", 10),
                            ("agga", "x1", "X1", 40), ("x1", "x2", "X2", 40),
                            ("x2", "x3", "X3", 40), ("x3", "x4", "X4", 40),
                            ("x4", "aggb", "X5", 40)]),
    # leaf/spine, the shape where a single spine loss halves the fabric
    ("t20_leafspine12", 30, [("edgea", "l1", "accA", 10),
                             ("l1", "s1", "ls1", 10), ("l1", "s2", "ls2", 20),
                             ("l2", "s1", "ls3", 10), ("l2", "s2", "ls4", 20),
                             ("l3", "s1", "ls5", 10), ("l3", "l6", "ll", 60),
                             ("l6", "s2", "ls6", 20),
                             ("s1", "l4", "sl1", 10), ("s2", "l5", "sl2", 20),
                             ("l4", "edgeb", "accB", 10),
                             ("l5", "edgeb", "accB2", 30),
                             ("edgea", "agga", "aggA", 50),
                             ("agga", "l2", "aggA2", 50),
                             ("edgeb", "aggb", "aggB", 50),
                             ("aggb", "l5", "aggB2", 50)]),
]

#: topologies whose shape came from a published reference architecture rather
#: than from the generator. Reported as a split so the generator's contribution
#: to the measured rate is visible.
REFERENCE_DERIVED = {"t11_branch6", "t12_campus8", "t15_campus12", "t16_pop14"}

TWENTY = TEN + [make_topology(n, o, e, "edgea", "edgeb") for n, o, e in _DESIGNS_B]



TOPOLOGIES: Dict[str, TopologySpec] = {
    t.name: t for t in (T1, T2, T3, T2V1, *TWENTY)}
TEN_NAMES = [t.name for t in TEN]              # kept: pilot-v2's first build
DESIGN_NAMES = [t.name for t in TWENTY]        # the 20-topology design
DEFAULT_TOPOLOGY = "t2v1"          # what a pilot without a topology field means


def resolve(name) -> TopologySpec:
    """Single entry point.

    None/empty means pilot-v1's network -- that is a real contract, because
    pilot-v1 artifacts carry no topology field.

    An UNKNOWN name is an error. It used to fall back to t2v1 silently, which
    meant one typo or one manifest entry with a stale topology name would
    resolve the entire twelve-property suite to pilot-v1 values -- P06 path,
    P08 adjacency count and P11 loopback all pointing at the wrong network at
    once, with every check still green. That is the P11 defect with the blast
    radius multiplied by twelve, and nothing downstream could detect it.
    """
    if name is None or name == "":
        return TOPOLOGIES[DEFAULT_TOPOLOGY]
    try:
        return TOPOLOGIES[name]
    except KeyError:
        raise KeyError(
            f"unknown topology {name!r}. Known: {sorted(TOPOLOGIES)}. "
            f"This used to fall back to {DEFAULT_TOPOLOGY!r} silently; it no "
            f"longer does, because the fallback resolved P06/P08/P11 to "
            f"another network's values without failing.") from None


def expected_ospf_pairs(spec: TopologySpec):
    return {frozenset((l[0], l[3])) for l in spec.links
            if l[0] in spec.routers and l[3] in spec.routers}


def host_attach(spec: TopologySpec) -> Dict[str, tuple]:
    """source IP -> (router, ingress iface). Loopback sources originate ON the
    device, so they carry iface None and are entered at node level."""
    out = {}
    for (a, ai, aa, b, bi, ba, subnet, label, cost) in spec.links:
        if a in spec.hosts and b in spec.routers:
            out[aa.split("/")[0]] = (b, bi)
        if b in spec.hosts and a in spec.routers:
            out[ba.split("/")[0]] = (a, ai)
    for edge in {spec.hosts[h] for h in spec.hosts}:
        out[spec.routers[edge]] = (edge, None)
    return out


def ip_to_node(spec: TopologySpec) -> Dict[str, str]:
    out = {}
    for (a, ai, aa, b, bi, ba, subnet, label, cost) in spec.links:
        if a in spec.routers:
            out[aa.split("/")[0]] = a
        if b in spec.routers:
            out[ba.split("/")[0]] = b
    for n, rid in spec.routers.items():
        out[rid] = n
    return out


def src_node(spec: TopologySpec) -> Dict[str, tuple]:
    """source IP -> (container, -I source or None) for emulator probes."""
    out = {}
    for (a, ai, aa, b, bi, ba, subnet, label, cost) in spec.links:
        if a in spec.hosts:
            out[aa.split("/")[0]] = (a, None)
        if b in spec.hosts:
            out[ba.split("/")[0]] = (b, None)
    for edge in {spec.hosts[h] for h in spec.hosts}:
        out[spec.routers[edge]] = (edge, spec.routers[edge])
    return out


def build_golden(spec: TopologySpec) -> Scenario:
    """The healthy reference network for one topology."""
    devices = {}
    for name, rid in spec.routers.items():
        devices[name] = Device(
            hostname=name, kind="frr",
            ifaces=[Iface(name="lo", addresses=[f"{rid}/32"],
                          alias="router-id and management",
                          ospf_area=AREA, ospf_passive=True)],
            ospf=OspfCfg(router_id=rid))
    for name in spec.hosts:
        devices[name] = Device(hostname=name, kind="host", ifaces=[])

    links = []
    for (a, ai, aa, b, bi, ba, subnet, label, cost) in spec.links:
        links.append(Link(a, ai, b, bi, subnet, label))
        for node, ifname, addr, peer in ((a, ai, aa, b), (b, bi, ba, a)):
            d = devices[node]
            if d.kind == "host":
                d.ifaces.append(Iface(name=ifname, addresses=[addr],
                                      alias=f"link to {peer}"))
                d.host_gateway = (ba if node == a else aa).split("/")[0]
            else:
                d.ifaces.append(Iface(
                    name=ifname, addresses=[addr],
                    alias=f"link to {peer} {label}",
                    ospf_area=AREA, ospf_cost=cost,
                    ospf_passive=(node, ifname) in spec.passive,
                    ospf_network=None if (node, ifname) in spec.passive
                    else "point-to-point"))
    return Scenario(name=f"{spec.name}-golden", devices=devices, links=links)
