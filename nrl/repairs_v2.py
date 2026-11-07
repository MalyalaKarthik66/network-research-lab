"""Repair generation: CORRECT / INCOMPLETE / REGRESSIVE, all fault-derived.

Two failures from earlier builds drive this design.

1. An operator that returns GOLDEN recreates the pilot-v1 shortcut, where SAFE
   was synonymous with "is this the revert". No operator here may emit golden.
2. An operator whose output does not depend on the fault produces the SAME
   AFTER network across incidents. Harm depends only on the AFTER network, so
   those are duplicate LABELS a model can memorise. Every operator's content is
   therefore derived from the fault's own link, prefix or peer.

`repair_class` is DESIGN INTENT, not ground truth: a "correct" operator may
still measure HARMFUL. Phase 3 decides. It is provenance and is banned from X.
"""
from __future__ import annotations

from typing import List, Tuple

from .faults_v2 import fault_targets
from .model import Scenario, StaticRoute
from .topologies import TopologySpec

UNUSED = "192.0.2.0/24"
COST_NORM_K = tuple(range(1, 10))     # keeps ordering: primary 10 < secondary 20 < backup 100
Repair = Tuple[str, str, str, Scenario]     # rid, class, description, scenario


def _unrelated(spec: TopologySpec, fault, offset: int = 0):
    t = fault_targets(fault)
    cand = [x for x in spec.transit if (x[0], x[1]) != (t.get("node"), t.get("iface"))]
    return cand[(sum(ord(c) for c in fault.fid) + offset) % len(cand)]


def _target(spec: TopologySpec, fault):
    """(node, iface) the fault touched; families naming only a node resolve to
    that node's first transit interface so no operator becomes a silent no-op."""
    t = fault_targets(fault)
    node, ifc = t.get("node"), t.get("iface")
    if node and (ifc is None or not any(
            i.name == ifc for i in _dev(spec, node))):
        for n, i, *_ in spec.transit:
            if n == node:
                ifc = i
                break
    return node, ifc


def _dev(spec, node):
    from .topologies import build_golden
    return build_golden(spec).devices[node].ifaces


def _same_node_other_iface(spec: TopologySpec, flt):
    """A transit interface on the SAME device the fault touched, but not the
    faulted interface itself. None if that device has only one transit link.

    Exists because of the shortcut audit: every regressive operator used
    _unrelated(), i.e. damaged a DIFFERENT device, so `devices_touched >= 2`
    became a near-perfect tag for repair_class -- 518 of 546 regressive
    candidates carried it, and a one-vs-rest AUC of 0.89 on that single column
    (0.999 in combination) meant a risk model could recover the generator
    instead of the network. Nothing about a regressive repair requires it to
    break a second box; only the generator did.
    """
    node, ifc = _target(spec, flt)
    for n, i, *_ in spec.transit:
        if n == node and i != ifc:
            return n, i
    return None, None


# --------------------------------------------------------------- CORRECT
def correct_repairs(g: Scenario, f: Scenario, flt, spec) -> List[Repair]:
    """Genuinely restores service, never byte-identical to golden.

    Diversity here is mostly PARAMETER diversity (which cost value, which end
    renumbered) rather than strategy diversity, because a small single-area OSPF
    network admits few genuinely distinct correct configurations. That is a real
    limitation of the artifact and is stated in the report rather than hidden.
    """
    out: List[Repair] = []
    node, ifc = _target(spec, flt)
    good = flt.params.get("good_cost", 10)
    peer, pifc = flt.params.get("peer"), flt.params.get("peer_iface")

    for k in COST_NORM_K:
        sc = g.clone()
        try:
            sc.devices[node].iface(ifc).ospf_cost = good + k
        except (KeyError, AttributeError):
            continue
        out.append((f"RC-cost_norm_{k}", "correct",
                    f"restore, normalising {node} {ifc} cost to {good + k}", sc))

    if peer and pifc:
        for k in (1, 2, 3):
            sc = g.clone()
            try:
                sc.devices[peer].iface(pifc).ospf_cost = good + k
            except (KeyError, AttributeError):
                continue
            out.append((f"RC-peer_cost_norm_{k}", "correct",
                        f"restore, normalising peer {peer} {pifc} cost", sc))

    # both ends normalised together -- what an operator tidying a link actually
    # does, and a different config from either single-ended variant
    if peer and pifc:
        for k in (1, 2, 3, 4):
            sc = g.clone()
            try:
                sc.devices[node].iface(ifc).ospf_cost = good + k
                sc.devices[peer].iface(pifc).ospf_cost = good + k
            except (KeyError, AttributeError):
                continue
            out.append((f"RC-both_cost_norm_{k}", "correct",
                        f"restore, normalising both ends of the link to {good + k}", sc))

    # a cost on a passive loopback: visible in config, no effect on any path
    for k in (1, 2, 3):
        sc = g.clone()
        try:
            sc.devices[node].iface("lo").ospf_cost = k
        except (KeyError, AttributeError):
            break
        out.append((f"RC-loopback_cost_{k}", "correct",
                    f"restore, plus an inert cost on {node} lo", sc))

    if flt.family == "iface_wrong_addr":
        sc = f.clone()                       # keep the new address on the faulted end
        sc.devices[flt.params["peer"]].iface(
            flt.params["peer_iface"]).addresses = [flt.params["peer_align"]]
        out.append(("RC-renumber_peer", "correct",
                    "align the peer to the new subnet instead of reverting", sc))
        sc = g.clone()
        base = flt.params["bad"].rsplit(".", 2)[0]
        sc.devices[node].iface(ifc).addresses = [f"{base}.8.2/30"]
        sc.devices[flt.params["peer"]].iface(
            flt.params["peer_iface"]).addresses = [f"{base}.8.1/30"]
        out.append(("RC-renumber_both", "correct",
                    "renumber both ends onto a third consistent /30", sc))

    if flt.family in ("static_blackhole", "static_wrong_nexthop",
                      "static_route_loop"):
        sc = g.clone()
        pfx = flt.params["prefix"]
        nh = _unrelated(spec, flt, 1)[5].split("/")[0]   # peer address
        sc.devices[node].statics.append(StaticRoute(prefix=pfx, nexthop=nh))
        out.append(("RC-equivalent_static", "correct",
                    f"restore, plus an explicit correct static for {pfx}", sc))
    return out


# ------------------------------------------------------------- REGRESSIVE
def regressive_repairs(g: Scenario, f: Scenario, flt, spec) -> List[Repair]:
    """Correctly fixes the fault AND breaks something that was working."""
    out: List[Repair] = []
    n0, i0, a0 = _unrelated(spec, flt, 3)[0:3]   # (node, iface, own addr)
    n1, i1 = _unrelated(spec, flt, 4)[0:2]
    n2, i2 = _unrelated(spec, flt, 5)[0:2]

    sc = g.clone(); sc.devices[n0].statics.append(
        StaticRoute(prefix="10.21.0.0/24", nexthop="blackhole"))
    out.append(("RR-blackhole_other", "regressive",
                f"restore, plus blackhole a working prefix on {n0}", sc))

    sc = g.clone(); sc.devices[n0].iface(i0).up = False
    out.append(("RR-shutdown_other", "regressive",
                f"restore, plus shut {n0} {i0}", sc))

    sc = g.clone(); sc.devices[n1].iface(i1).ospf_area = "0.0.0.9"
    out.append(("RR-area_other", "regressive",
                f"restore, plus move {n1} {i1} to another area", sc))

    sc = g.clone(); sc.devices[n2].iface(i2).ospf_passive = True
    out.append(("RR-passive_other", "regressive",
                f"restore, plus mark {n2} {i2} passive", sc))

    sc = g.clone(); sc.devices[n1].iface(i1).ospf_cost = 1
    for bn, bi in spec.backup:
        sc.devices[bn].iface(bi).ospf_cost = 2
    out.append(("RR-cost_inversion", "regressive",
                f"restore, plus make {n1} {i1} and the backup anomalously cheap", sc))

    edge = spec.hosts["hostc"]
    sc = g.clone()
    sc.devices[edge].statics.append(
        StaticRoute(prefix="10.21.0.10/32", nexthop=a0.split("/")[0]))
    out.append(("RR-loop_other", "regressive",
                "restore, plus a /32 that loops hostc", sc))

    # ---- SAME-DEVICE regressive operators -----------------------------
    # Everything above damages a device OTHER than the one the fault touched,
    # which made `devices_touched >= 2` a near-perfect tag for the regressive
    # class. These break something on the fault's OWN device, so the class is
    # no longer readable off the device count. A real regressive repair is
    # under no obligation to touch a second box.
    tnode, tifc = _target(spec, flt)
    snode, sifc = _same_node_other_iface(spec, flt)

    if tnode:
        sc = g.clone(); sc.devices[tnode].statics.append(
            StaticRoute(prefix="10.21.0.0/24", nexthop="blackhole"))
        out.append(("RR-blackhole_same", "regressive",
                    f"restore, plus blackhole a working prefix on {tnode} "
                    f"(the repaired device itself)", sc))

    if snode and sifc:
        sc = g.clone(); sc.devices[snode].iface(sifc).up = False
        out.append(("RR-shutdown_same", "regressive",
                    f"restore, plus shut {snode} {sifc} on the same device", sc))

        sc = g.clone(); sc.devices[snode].iface(sifc).ospf_area = "0.0.0.9"
        out.append(("RR-area_same", "regressive",
                    f"restore, plus move {snode} {sifc} to another area", sc))

        sc = g.clone(); sc.devices[snode].iface(sifc).ospf_passive = True
        out.append(("RR-passive_same", "regressive",
                    f"restore, plus mark {snode} {sifc} passive", sc))

    if tnode and tifc:
        sc = g.clone(); sc.devices[tnode].iface(tifc).ospf_cost = 1
        out.append(("RR-cost_anomaly_same", "regressive",
                    f"restore, plus make {tnode} {tifc} anomalously cheap", sc))
    return out


# ------------------------------------------------------------- INCOMPLETE
def incomplete_repairs(g: Scenario, f: Scenario, flt, spec) -> List[Repair]:
    """Fixes a symptom, leaves the cause. Starts from the FAULTED network, so
    every one differs per incident automatically."""
    out: List[Repair] = []
    node, ifc = _target(spec, flt)
    nu, iu, au = _unrelated(spec, flt, 6)[0:3]
    edge_a, edge_b = spec.hosts["hosta"], spec.hosts["hostb"]
    core = [n for n in sorted(spec.routers) if n not in (edge_a, edge_b)]
    hub = core[0] if core else edge_a
    bnh = next((l[5].split("/")[0] for l in spec.links if "backup" in l[7]),
               au.split("/")[0])

    sc = f.clone(); sc.devices[node].iface(ifc).alias += " (reviewed NET-1042)"
    out.append(("RI-cosmetic", "incomplete", "change a description only", sc))

    sc = f.clone(); sc.devices[hub].statics.append(
        StaticRoute(prefix="10.20.0.10/32", nexthop=bnh))
    out.append(("RI-static_specific", "incomplete", "a /32 for the tested flow", sc))

    sc = f.clone(); sc.devices[hub].statics.append(
        StaticRoute(prefix="10.20.0.0/15", nexthop=bnh))
    out.append(("RI-static_broad", "incomplete", "a supernet via the backup", sc))

    sc = f.clone()
    for bn, bi in spec.backup:
        sc.devices[bn].iface(bi).ospf_cost = 5
    out.append(("RI-cost_reroute", "incomplete", "lower the backup cost", sc))

    sc = f.clone()
    for n in sc.routers:
        for i in sc.devices[n].ifaces:
            if i.name != "lo":
                i.ospf_area = "0.0.0.0"; i.ospf_passive = False
                if i.ospf_cost is None:
                    i.ospf_cost = 10
    out.append(("RI-overbroad_ospf", "incomplete", "OSPF everywhere, no passive guards", sc))

    sc = f.clone(); sc.devices[nu].iface(iu).ospf_cost = 5
    out.append(("RI-wrong_device", "incomplete", f"right shape, wrong device ({nu})", sc))

    sc = f.clone(); sc.devices[node].iface(ifc).alias = \
        g.devices[node].iface(ifc).alias + " (partially reverted)"
    out.append(("RI-partial_revert", "incomplete", "revert only the cosmetic half", sc))

    sc = f.clone(); base = str(flt.params.get("prefix", "10.20.0.0/24")).split("/")[0]
    sc.devices[node].statics.append(StaticRoute(prefix=f"{base}/25", nexthop=bnh))
    out.append(("RI-static_override", "incomplete", "beat the bad route with a /25", sc))

    sc = f.clone(); sc.devices[nu].statics.append(
        StaticRoute(prefix=UNUSED, nexthop="blackhole"))
    out.append(("RI-noop_route", "incomplete", "a route that changes nothing", sc))
    return out


def generate_repairs(g, f, flt, spec) -> List[Repair]:
    return (correct_repairs(g, f, flt, spec)
            + regressive_repairs(g, f, flt, spec)
            + incomplete_repairs(g, f, flt, spec))
