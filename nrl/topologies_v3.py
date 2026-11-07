"""Tie-broken topologies for the v3 corpus. The v2 definitions are not touched.

WHY

Under equal-cost multipath a flow's forwarding path is a tie-break CONVENTION,
not a physical fact: the control plane installs several next hops and the data
plane hashes across them. r(x) -- the fraction of flows a change breaks or
reroutes -- is therefore not uniquely defined on those flows, however carefully
it is measured. Measured ambiguity in the v2 designs:

    zero ECMP        t01 t02 t03 t04 t07 t08 t10 t11 t12 t14 t19
    under 5% of hops t05 t06 t09 t13 t15 t16
    above 5%         t17_metro13 (24/240), t18_grid12 (16/210),
                     t20_leafspine12 (37/210)

Only t14_ladder8 and t19_dualcore16 combine zero ECMP with eight or more
distinct severity levels, so simply dropping the ambiguous designs would cost
most of the corpus and most of its structural variety.

WHAT THIS DOES

Adds 1 to one link cost at a time until no equal-cost set remains. Round-number
costs are an artifact of a synthetic generator, not a property of real networks
worth preserving, and the project has already done exactly this twice for
exactly this reason -- see the comments in topologies.py on t16/t17, where
uniform ring and rr-chain costs produced two equal-cost paths and made P06
false for half the traces on a network that is healthy by construction.

WHY A SEPARATE MODULE

data/pilot-v2 was built from the v2 definitions and pilot.lock.json hashes every
file. Editing topologies.py in place would leave the frozen corpus describing
artifacts that can no longer be regenerated from the source, and would silently
change the spec that run_phase3 checks v2 runs against. The v2 designs are read
here and never modified; v3 is a derived set with its own names.

The nudges are reported, not hidden: `report()` returns every changed edge so
the paper can state exactly how the topologies differ from their v2 ancestors.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .severity import Fabric
from .topologies import _DESIGNS, _DESIGNS_B, make_topology

MAX_NUDGES = 200
SITE_A, SITE_B = "edgea", "edgeb"

#: name -> [(a, b, label, old_cost, new_cost)]
_NUDGES: Dict[str, List[Tuple[str, str, str, int, int]]] = {}


def _first_tie(spec) -> Tuple[str, str] | None:
    """The lexicographically largest (node, next-hop) in any equal-cost set.

    Deterministic so the derived topology is reproducible, and largest-first so
    the choice does not depend on iteration order of the design table.
    """
    fab = Fabric(spec)
    worst = None
    for root in fab.routers:
        dist = fab._dist_to(root, fab.cost, set())
        for node in fab.routers:
            if node == root:
                continue
            nhs = fab._nexthops(dist, node, fab.cost, set())
            if len(nhs) > 1:
                cand = max((node, v) for v in nhs)
                worst = cand if worst is None else max(worst, cand)
    return worst


def _tiebreak(name: str, octet: int, edges) -> Tuple[list, list]:
    """Raise costs by 1 until the design has no equal-cost paths."""
    edges = [list(e) for e in edges]
    changes: List[Tuple[str, str, str, int, int]] = []
    for _ in range(MAX_NUDGES):
        spec = make_topology(name, octet, [tuple(e) for e in edges],
                             SITE_A, SITE_B)
        fab = Fabric(spec)
        fab.paths()
        if fab.ecmp_pairs == 0:
            return edges, changes
        tie = _first_tie(spec)
        if tie is None:
            return edges, changes
        a, b = tie
        for e in edges:
            if {e[0], e[1]} == {a, b}:
                changes.append((e[0], e[1], e[2], e[3], e[3] + 1))
                e[3] += 1
                break
        else:
            # the tie is on a link that is not an inter-router edge, which
            # should be impossible; stop rather than loop forever
            return edges, changes
    raise RuntimeError(f"{name}: still has equal-cost paths after "
                       f"{MAX_NUDGES} nudges")


def _build() -> Dict[str, object]:
    out = {}
    for name, octet, edges in list(_DESIGNS) + list(_DESIGNS_B):
        new_edges, changes = _tiebreak(name, octet, edges)
        if changes:
            _NUDGES[name] = changes
        out[name] = make_topology(name, octet, [tuple(e) for e in new_edges],
                                  SITE_A, SITE_B)
    return out


TOPOLOGIES_V3 = _build()
NAMES = sorted(TOPOLOGIES_V3)


def resolve(name: str):
    """v3 spec by name. Unknown names raise, never fall back -- see the note in
    topologies.resolve about a silent fallback resolving the whole property
    suite to the wrong network with every check still green."""
    try:
        return TOPOLOGIES_V3[name]
    except KeyError:
        raise KeyError(f"unknown v3 topology {name!r}; known: {NAMES}") from None


def report() -> Dict[str, List[Tuple[str, str, str, int, int]]]:
    """Every cost nudged, so the corpus can state how v3 differs from v2."""
    return {k: list(v) for k, v in sorted(_NUDGES.items())}
