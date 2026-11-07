"""Controls for the Tier A+ graph features. Pure Python, no Batfish.

Each check makes a structural fact TRUE and then FALSE and asserts the feature
follows. A feature that never changes is a constant, and phase4.matrix() will
silently drop it -- so a feature that is never seen to move has not been tested.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl.topologies import (DESIGN_NAMES, TOPOLOGIES,             # noqa: E402
                            build_golden)
from nrl.graphfeat import (ospf_graph, bridges, betweenness,       # noqa: E402
                           dijkstra, graph_features, connected,
                           weighted_diameter, edges_of)

FAIL = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAIL.append(label)
        if detail:
            print(f"         {detail}")


def main() -> int:
    chain = TOPOLOGIES["t01_chain4"]
    ring = TOPOLOGIES["t05_ring6"]

    print("CHECK 1 -- the OSPF graph agrees with the spec, on every topology")
    # The strongest available check: edge count is derived from the RENDERED
    # config model (interfaces up, same area, not passive), n_adjacencies is
    # declared in the topology spec. Two independent sources of the same fact.
    for name, sp in TOPOLOGIES.items():
        gg = ospf_graph(build_golden(sp))
        check(f"{name}: |edges| == spec.n_adjacencies ({sp.n_adjacencies})",
              len(edges_of(gg)) == sp.n_adjacencies,
              f"graph has {len(edges_of(gg))}: {sorted(edges_of(gg))}")
        check(f"{name}: golden OSPF graph is connected", connected(gg))
    g = ospf_graph(build_golden(chain))
    gr = ospf_graph(build_golden(ring))

    print("\nCHECK 1b -- P06 is well defined: ONE shortest ingress->egress path")
    # A topology with two equal-cost paths between the hosts has no single
    # "primary path". P06 asserts the primary path is USED, and under ECMP that
    # is false for half the traces -- so the property fails on a network that is
    # healthy by construction. t16_pop14 (rr chain tied with the P-core at 30)
    # and t17_metro13 (a uniform-cost ring, both halves 40) both did exactly
    # that, and the golden gate caught it. This makes it a build-time check.
    from nrl.graphfeat import dijkstra as _dj
    for name in DESIGN_NAMES:
        sp = TOPOLOGIES[name]
        gg = ospf_graph(build_golden(sp))
        ends = sorted(set(sp.hosts.values()))
        _, npaths = _dj(gg, ends[0])
        k = npaths[ends[-1]]
        check(f"{name}: exactly one shortest {ends[0]}->{ends[-1]} path",
              k == 1,
              f"{k} equal-cost paths -- primary_path is one of {k} and P06 "
              f"cannot hold on the golden. Break the tie in the link costs.")

    print("\nCHECK 2 -- bridges reflect real redundancy")
    # t01_chain4 is a 4-CYCLE in the OSPF graph (edgea-corea-coreb-edgeb-edgea),
    # not a path, so it has no bridges. t05_ring6 is a 4-ring of core/wan nodes
    # with edgea and edgeb hanging off it, so it has exactly two bridges: the
    # two spur links. Asserting the actual shape rather than the name.
    check("t01_chain4 (a 4-cycle) has no bridges", len(bridges(g)) == 0,
          str(sorted(bridges(g))))
    check("t05_ring6 has exactly the two edge-router spurs as bridges",
          bridges(gr) == {("corea", "edgea"), ("coreb", "edgeb")},
          str(sorted(bridges(gr))))

    print("\nCHECK 3 -- NEGATIVE CONTROL: shutting a link removes the edge")
    scn = build_golden(chain)
    ln = [l for l in scn.links
          if l.a_node in scn.routers and l.b_node in scn.routers][0]
    scn.devices[ln.a_node].iface(ln.a_iface).up = False
    g2 = ospf_graph(scn)
    check("a down interface removes its adjacency",
          len(edges_of(g2)) == len(edges_of(g)) - 1,
          f"{len(edges_of(g2))} vs {len(edges_of(g))}")
    check("a 4-cycle survives one cut (still connected)", connected(g2))
    # cut a SPUR instead and the graph must partition
    rg = build_golden(ring)
    spur = [l for l in rg.links
            if {l.a_node, l.b_node} == {"corea", "edgea"}][0]
    rg.devices[spur.a_node].iface(spur.a_iface).up = False
    g3 = ospf_graph(rg)
    check("cutting a bridge DOES disconnect the graph", not connected(g3),
          "if this passes the connectivity feature has no power")
    check("weighted diameter of a disconnected graph is inf",
          weighted_diameter(g3) == float("inf"))

    print("\nCHECK 4 -- NEGATIVE CONTROL: an area mismatch removes the edge")
    scn = build_golden(chain)
    scn.devices[ln.a_node].iface(ln.a_iface).ospf_area = "9"
    check("mismatched areas do not form an adjacency",
          len(edges_of(ospf_graph(scn))) == len(edges_of(g)) - 1)

    print("\nCHECK 5 -- NEGATIVE CONTROL: a passive interface removes the edge")
    scn = build_golden(chain)
    scn.devices[ln.a_node].iface(ln.a_iface).ospf_passive = True
    check("a passive transit interface does not form an adjacency",
          len(edges_of(ospf_graph(scn))) == len(edges_of(g)) - 1)

    print("\nCHECK 6 -- cost changes move the weighted path, not the topology")
    scn = build_golden(ring)
    before = ospf_graph(scn)
    src, dst = sorted(before)[0], sorted(before)[-1]
    d0, _ = dijkstra(before, src)
    for i in scn.devices[sorted(before)[0]].ifaces:
        if i.ospf_cost is not None:
            i.ospf_cost = 500
    after = ospf_graph(scn)
    d1, _ = dijkstra(after, src)
    check("edge count is unchanged by a cost edit",
          len(edges_of(after)) == len(edges_of(before)))
    check("some shortest-path distance changed",
          any(d0[n] != d1[n] for n in d0), f"{d0} vs {d1}")

    print("\nCHECK 7 -- feature block on a real before/after pair")
    b = build_golden(ring)
    a = b.clone()
    # cut one of the two ring links (corea-wan1), which the ring tolerates
    ln2 = [l for l in a.links if {l.a_node, l.b_node} == {"corea", "wan1"}][0]
    a.devices[ln2.a_node].iface(ln2.a_iface).up = False
    f = graph_features(ring, b, a, [ln2.a_node])
    print(f"         touched={ln2.a_node}  "
          f"d_edges={f['g_d_edges']} d_bridges={f['g_d_bridges']} "
          f"d_paths={f['g_d_n_shortest_paths']} "
          f"lost_alt={f['g_lost_last_alternate_path']}")
    check("removing one ring edge is recorded as -1 edges",
          f["g_d_edges"] == -1, str(f["g_d_edges"]))
    check("removing a ring edge creates NEW bridges", f["g_d_bridges"] > 0,
          f"d_bridges={f['g_d_bridges']} -- cutting a ring turns the "
          f"remaining ring edges into cut edges")
    check("the graph is still connected (a ring tolerates one cut)",
          f["g_connected_after"], "cut the wrong edge?")
    check("the change is recorded as touching a bridge or raising bridge count",
          f["g_change_touches_bridge"] or f["g_d_bridges"] > 0)
    check("the touched device is reported on or near the spec path",
          f["g_touched_hops_to_spec_path"] >= 0)
    check("every feature is JSON-safe (no inf/nan)",
          all(not (isinstance(v, float) and (v != v or v in
              (float("inf"), float("-inf")))) for v in f.values()),
          str({k: v for k, v in f.items()
               if isinstance(v, float) and (v != v or abs(v) == float("inf"))}))

    print("\nCHECK 8 -- features are permutation invariant")
    # renaming routers must not change any numeric feature
    import copy as _c
    b2, a2 = _c.deepcopy(b), _c.deepcopy(a)
    for scn2 in (b2, a2):
        scn2.devices = {k: v for k, v in reversed(list(scn2.devices.items()))}
    f2 = graph_features(ring, b2, a2, [ln2.a_node])
    diff = {k: (f[k], f2[k]) for k in f if f[k] != f2[k]}
    check("reordering the device dict changes nothing", not diff, str(diff))

    print("\nCHECK 9 -- features actually vary across topologies")
    seen = {}
    for name, sp in TOPOLOGIES.items():
        gg = build_golden(sp)
        seen[name] = graph_features(sp, gg, gg, [])
    for key in ("g_n_routers", "g_n_edges_after", "g_n_bridges_after",
                "g_weighted_diameter_after"):
        vals = {seen[n][key] for n in seen}
        check(f"{key} is not constant across topologies", len(vals) > 1,
              f"all equal to {vals}")

    print("\n" + "=" * 62)
    print("ALL GRAPH-FEATURE CHECKS PASSED" if not FAIL else "FAILED")
    for f_ in FAIL:
        print(f"   {f_}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
