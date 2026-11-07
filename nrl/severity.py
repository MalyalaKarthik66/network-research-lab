"""Analytic severity model: predict r(x) from the topology, before any lab runs.

WHY

r(x) -- the fraction of flows a change breaks or reroutes -- is decided by the
forwarding paths, and the forwarding paths of a healthy single-area OSPF network
are Dijkstra over link cost. So r is predictable on paper. That matters for
three reasons:

  * the generator can CHOOSE a severity instead of discovering it after a
    20-hour run;
  * the achievable severity range of a topology can be measured before
    committing to it;
  * a predicted r that disagrees with the measured r is a bug in one of them,
    which is the only cross-check this project has that does not cost labs.

WHAT THE MEASUREMENTS SAID

Two structural facts, computed here and confirmed against Phase 2 / the
zero-inflation run:

  1. Severity granularity is a property of the TOPOLOGY. t01_chain4 has two
     distinct link-betweenness levels (ratio 1.2x) -- no operator can produce a
     spread of risk on a 4-router chain, because damage either lands on the path
     or it does not. t15_campus12 has 13 levels over a 28x range.

  2. Blackholing a prefix has a hard severity ceiling that SHRINKS as topologies
     grow: 0.143 on chain4, 0.053 on dualcore16. A blackhole only breaks flows
     to one endpoint, and each endpoint is 1/N of all destinations. That is the
     whole explanation for the regressive class measuring 0.018-0.089 -- a
     structural ceiling, not an operator choice. High severity requires damaging
     a LINK, which reaches 0.39-0.57.

SCOPE

This models the golden network's steady state: single area, no redistribution,
costs as declared. It is a DESIGN tool, not a replacement for measurement -- the
emulator remains the ground truth, and the gap between predicted and measured r
is itself a quantity worth reporting (it is model-vs-device divergence, the part
of the study Batfish cannot do for us).
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

Link = Tuple[str, str]          # unordered pair, always sorted
Path = Optional[Tuple[str, ...]]


class Fabric:
    """The golden forwarding model of one topology, plus what-if queries."""

    def __init__(self, spec):
        self.spec = spec
        self.routers: List[str] = sorted(spec.routers)
        self.hosts: Dict[str, str] = dict(getattr(spec, "hosts", {}) or {})
        self.adj: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        self.cost: Dict[Link, int] = {}
        #: (from, to) -> the address `to` owns on that link, i.e. the next-hop
        #: IP the RIB shows. Needed to reproduce the walker's tie-break.
        self.nh_addr: Dict[Tuple[str, str], str] = {}
        self.ecmp_pairs = 0
        for (a, ai, aa, b, bi, ba, sub, label, c) in spec.links:
            if a in spec.routers and b in spec.routers:
                self.adj[a].append((b, c))
                self.adj[b].append((a, c))
                self.cost[tuple(sorted((a, b)))] = c
                self.nh_addr[(a, b)] = ba.split("/")[0]
                self.nh_addr[(b, a)] = aa.split("/")[0]
        #: (endpoint name, router that originates its prefix)
        self.endpoints: List[Tuple[str, str]] = (
            [(r, r) for r in self.routers]
            + [(h, r) for h, r in sorted(self.hosts.items())])
        self.golden = self.paths()

    # -- shortest paths ---------------------------------------------------
    def _dist_to(self, root: str, cost: Dict[Link, int],
                 removed: Set[Link]) -> Dict[str, int]:
        """Cost from every router to `root`. Link costs are symmetric here, so
        distance to the root equals distance from it."""
        dist = {root: 0}
        pq = [(0, root)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, 1 << 60):
                continue
            for v, _ in self.adj[u]:
                lk = tuple(sorted((u, v)))
                if lk in removed:
                    continue
                nd = d + cost.get(lk, self.cost[lk])
                if nd < dist.get(v, 1 << 60):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return dist

    def _nexthops(self, dist: Dict[str, int], node: str, cost: Dict[Link, int],
                  removed: Set[Link]) -> List[str]:
        """Every equal-cost next hop from `node` toward the SPF root.

        This is what FRR installs. An earlier version ran SPF from the source
        and broke ties on predecessor NAME, which disagreed with the RIB walker
        (lowest next-hop IP) wherever equal-cost paths exist. The validation run
        showed the consequence exactly: 10/10 predictions correct on
        t14_ladder8 with 0% ECMP, 6/10 on t15_campus12 with 3%, and 2/10 on
        t20_leafspine12 with 10%.
        """
        if node not in dist:
            return []
        out = []
        for v, _ in self.adj[node]:
            lk = tuple(sorted((node, v)))
            if lk in removed or v not in dist:
                continue
            if dist[v] + cost.get(lk, self.cost[lk]) == dist[node]:
                out.append(v)
        return out

    def paths(self, cost_override: Optional[Dict[Link, int]] = None,
              removed: Optional[Iterable[Link]] = None
              ) -> Dict[Tuple[str, str], Path]:
        """Forwarding path for every ordered endpoint pair, as a router tuple.

        Hop by hop through the equal-cost set, choosing the LOWEST NEXT-HOP IP
        at every step -- byte for byte the rule nrl.flowmatrix.forwarding_path
        applies to the real RIB, so predicted and measured are the same
        convention. Under ECMP that convention is a choice, not physical truth:
        the data plane hashes flows across the set. `ecmp_pairs` counts how
        often it was exercised so the ambiguity is reported, not hidden.
        """
        cost = dict(self.cost)
        if cost_override:
            cost.update({tuple(sorted(k)): v for k, v in cost_override.items()})
        rem = {tuple(sorted(x)) for x in (removed or ())}
        dist_by_root = {r: self._dist_to(r, cost, rem) for r in self.routers}
        out: Dict[Tuple[str, str], Path] = {}
        self.ecmp_pairs = 0
        for sn, sr in self.endpoints:
            for dn, dr in self.endpoints:
                if sn == dn:
                    continue
                out[(sn, dn)] = self._walk(dist_by_root[dr], sr, dr, cost, rem)
        return out

    def _walk(self, dist: Dict[str, int], src: str, dst: str,
              cost: Dict[Link, int], removed: Set[Link]) -> Path:
        if src == dst:
            return (src,)
        cur, seq = src, [src]
        while cur != dst:
            nhs = self._nexthops(dist, cur, cost, removed)
            if not nhs:
                return None                 # unreachable
            if len(nhs) > 1:
                self.ecmp_pairs += 1
            nxt = min(nhs, key=lambda v: self._nh_key(cur, v))
            if nxt in seq or len(seq) > 64:
                return None
            seq.append(nxt)
            cur = nxt
        return tuple(seq)

    def _nh_key(self, a: str, b: str) -> str:
        """b's address on the a-b link -- the next-hop IP the RIB would show.

        Compared as a STRING, because flowmatrix.forwarding_path does
        `sorted(n.get("ip") ...)` on the RIB's next-hop list and takes the
        first. String order is not numeric order -- "10.11.10.2" sorts before
        "10.11.9.2" -- so sorting numerically here would reproduce the bug this
        method exists to remove, on exactly the links where it matters.
        """
        return self.nh_addr.get((a, b), "￿")

    # -- centrality -------------------------------------------------------
    def link_betweenness(self) -> Dict[Link, float]:
        """Fraction of endpoint pairs whose golden path crosses each link.

        This is the severity dial. Changing or removing a link moves exactly
        the flows that were using it.
        """
        n = len(self.golden)
        cnt: Dict[Link, int] = defaultdict(int)
        for p in self.golden.values():
            if not p:
                continue
            for i in range(len(p) - 1):
                cnt[tuple(sorted((p[i], p[i + 1])))] += 1
        return {k: v / n for k, v in cnt.items()}

    def prefix_criticality(self) -> Dict[Tuple[str, str], float]:
        """(endpoint, node) -> fraction of pairs that reach `endpoint` through
        `node`. Blackholing that prefix at that node breaks exactly those."""
        n = len(self.golden)
        cnt: Dict[Tuple[str, str], int] = defaultdict(int)
        for (s, d), p in self.golden.items():
            if not p:
                continue
            for node in p:
                cnt[(d, node)] += 1
        return {k: v / n for k, v in cnt.items()}

    # -- what-if ----------------------------------------------------------
    def predict(self, cost_override=None, removed=None,
                blackholes: Optional[Iterable[Tuple[str, str]]] = None) -> Dict:
        """Predicted r for a change, split the same way the lab reports it.

        `blackholes` is (node, endpoint): that node discards traffic destined
        for that endpoint's prefix. A flow is broken if its path reaches such a
        node, which is what the installed static actually does -- and is exactly
        the case the RIB walker missed until it learned to prefer the installed
        route over entries[0].

        A blackhole on the router that ORIGINATES the prefix is dropped as a
        no-op. The connected route has administrative distance 0 and beats a
        static's 1, so the discard never enters the FIB. Measured: C-00175
        blackholes 10.21.0.0/24 on edgeb, which is hostc's own attachment
        router, and scores r=0 in the lab while the naive model predicted 0.091.
        """
        origin = {e: r for e, r in self.endpoints}
        bh = {(n, e) for n, e in (blackholes or ()) if origin.get(e) != n}
        new = self.paths(cost_override, removed)
        base = brk = rer = 0
        for key, gp in self.golden.items():
            if gp is None:
                continue                    # golden cannot carry it
            base += 1
            np_ = new.get(key)
            if np_ is None:
                brk += 1
            elif any((node, key[1]) in bh for node in np_):
                brk += 1
            elif np_ != gp:
                rer += 1
        return {"n_pairs": base, "n_broken": brk, "n_rerouted": rer,
                "r": round((brk + rer) / base, 6) if base else None,
                "r_broken": round(brk / base, 6) if base else None,
                "r_rerouted": round(rer / base, 6) if base else None}


def tiers(values: Dict, k: int = 3) -> Dict[object, str]:
    """Bucket targets into low/mid/high by rank, not by value.

    Rank rather than fixed thresholds because the achievable range differs by
    an order of magnitude between topologies -- 0.476-0.571 on chain4 against
    0.010-0.390 on leafspine12. A fixed cut would put every chain4 target in
    "high" and every leafspine target in "low", which is the topology speaking,
    not the operator.
    """
    if not values:
        return {}
    names = ["low", "mid", "high"][:k]
    order = sorted(values, key=lambda t: (values[t], str(t)))
    out = {}
    for i, t in enumerate(order):
        out[t] = names[min(i * k // len(order), k - 1)]
    return out


def granularity(spec) -> Dict:
    """How much severity spread a topology can express at all."""
    f = Fabric(spec)
    lb = f.link_betweenness()
    pc = f.prefix_criticality()
    lv = sorted(lb.values())
    return {"topology": spec.name, "routers": len(f.routers),
            "endpoints": len(f.endpoints), "pairs": len(f.golden),
            "link_levels": len({round(v, 3) for v in lv}),
            "link_min": round(min(lv), 4) if lv else None,
            "link_max": round(max(lv), 4) if lv else None,
            "link_ratio": round(max(lv) / min(lv), 1) if lv and min(lv) else None,
            "blackhole_max": round(max(pc.values()), 4) if pc else None}
