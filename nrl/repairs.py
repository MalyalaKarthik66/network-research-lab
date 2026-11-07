"""Repair candidate operators.

DESIGN RULE, and the most important line in this file:

    No operator carries a predicted outcome, and nothing here is labelled safe
    or harmful. The operator name is PROVENANCE, recorded so the pilot is
    reproducible and so results can be stratified. It is banned from the feature
    matrix -- see docs/LEAKAGE.md. In a synthetic pilot the generator's operator
    name is a near-perfect predictor of the label by construction; feeding it to
    a model would produce a meaningless AUC.

The library is deliberately mixed. Some operators repair the cause. Some repair
the symptom. Some repair the symptom for one flow and leave another broken. Some
restore reachability while silently moving every packet onto the backup path.
Some do nothing at all. Which of those turns out to be harmful is a question for
Phase 3, not an assumption made here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from .model import PrefixListEntry, Scenario, StaticRoute
from .topology import AREA

BACKUP_NH_FROM_COREA = "10.0.9.2"
BACKUP_NH_FROM_COREB = "10.0.9.1"
HOST_B = "10.20.0.10/32"
BOTH_SITE_B_LANS = "10.20.0.0/15"        # covers 10.20.0.0/24 and 10.21.0.0/24


@dataclass
class Repair:
    rid: str
    description: str
    fn: Callable[[Scenario, Scenario, "Fault"], Scenario]

    def apply(self, golden: Scenario, faulted: Scenario, fault) -> Scenario:
        out = self.fn(golden, faulted, fault)
        out.name = f"{faulted.name}--{self.rid}"
        return out


# --------------------------------------------------------------------------
# operators
# --------------------------------------------------------------------------

def _exact_revert(golden, faulted, fault):
    """Undo exactly the lines the fault changed. Restores the golden config."""
    return golden.clone()


def _target_of(fault):
    """(node, iface) the fault touched. Faults that name only a node -- the
    static-route and route-filter families -- resolve to that node's first
    transit interface, which is what a human would annotate."""
    p = fault.params
    if "pairs" in p:
        return p["pairs"][0]
    node = p["node"]
    return node, p.get("iface", "eth1")


def _cosmetic(golden, faulted, fault):
    """Change a description and nothing else. A real 'fix' that isn't one."""
    sc = faulted.clone()
    node, ifname = _target_of(fault)
    sc.devices[node].iface(ifname).alias += " (reviewed, see ticket NET-1042)"
    return sc


def _static_patch_specific(golden, faulted, fault):
    """A /32 host route for the flow someone actually tested."""
    sc = faulted.clone()
    sc.devices["corea"].statics.append(
        StaticRoute(prefix=HOST_B, nexthop=BACKUP_NH_FROM_COREA))
    return sc


def _static_patch_broad(golden, faulted, fault):
    """A supernet static covering both site-B LANs, via the backup."""
    sc = faulted.clone()
    sc.devices["corea"].statics.append(
        StaticRoute(prefix=BOTH_SITE_B_LANS, nexthop=BACKUP_NH_FROM_COREA))
    return sc


def _cost_reroute(golden, faulted, fault):
    """Make the backup cheap so OSPF routes around the problem."""
    sc = faulted.clone()
    for node, ifname in (("corea", "eth3"), ("coreb", "eth3")):
        sc.devices[node].iface(ifname).ospf_cost = 5
    return sc


def _peer_align(golden, faulted, fault):
    """Change the OTHER end to match the faulted end. Also a valid repair --
    it converges on the wrong value, but it converges."""
    sc = faulted.clone()
    fam = fault.family
    p = fault.params
    if fam == "iface_wrong_addr":
        sc.devices[p["peer"]].iface(p["peer_iface"]).addresses = [p["peer_align"]]
    elif fam == "ospf_area_mismatch":
        sc.devices[p["peer"]].iface(p["peer_iface"]).ospf_area = p["bad_area"]
    else:
        raise ValueError(f"peer_align not applicable to {fam}")
    return sc


def _partial_revert(golden, faulted, fault):
    """Revert one side of a two-sided change. Leaves an asymmetry."""
    sc = faulted.clone()
    node, ifname = fault.params["pairs"][0]
    sc.devices[node].iface(ifname).ospf_cost = fault.params["good_cost"]
    return sc


def _overbroad_ospf(golden, faulted, fault):
    """Turn OSPF on everywhere and drop every passive-interface guard."""
    sc = faulted.clone()
    for n in sc.routers:
        for i in sc.devices[n].ifaces:
            if i.name != "lo":
                i.ospf_area = AREA
                i.ospf_passive = False
                if i.ospf_cost is None:
                    i.ospf_cost = 10
    return sc


def _static_override(golden, faulted, fault):
    """Beat the bad static with a more specific one rather than removing it."""
    sc = faulted.clone()
    p = fault.params
    node = p["node"]
    base = p["prefix"].split("/")[0]
    more_specific = f"{base}/25"
    nh = BACKUP_NH_FROM_COREA if node == "corea" else BACKUP_NH_FROM_COREB
    if node == "corea" and p["prefix"].startswith("10.21."):
        nh = "10.0.2.2"          # toward wan1, the primary path
    sc.devices[node].statics.append(
        StaticRoute(prefix=more_specific, nexthop=nh))
    return sc


# RETIRED with fault family distribute_list_drop -- see nrl/faults.py.
def _prefix_list_widen_RETIRED(golden, faulted, fault):
    """Loosen the filter to permit everything instead of removing it."""
    sc = faulted.clone()
    p = fault.params
    sc.devices[p["node"]].access_lists[p["acl"]] = ["seq 5 permit any"]
    return sc


_WRONG_TARGET: Dict[str, Callable[[Scenario, dict], None]] = {
    "iface_down":
        lambda sc, p: setattr(sc.devices[p["peer"]].iface(p["peer_iface"]),
                              "ospf_cost", 5),
    "iface_wrong_addr":
        lambda sc, p: sc.devices["wan1"].iface("eth1").addresses.__setitem__(
            0, "10.0.7.1/30"),
    "ospf_area_mismatch":
        lambda sc, p: setattr(sc.devices["corea"].iface("eth3"),
                              "ospf_area", p["bad_area"]),
    "ospf_passive_transit":
        lambda sc, p: setattr(sc.devices["edgea"].iface("eth1"),
                              "ospf_passive", False),
    "ospf_iface_removed":
        lambda sc, p: setattr(sc.devices["coreb"].iface("eth3"),
                              "ospf_cost", 5),
    "ospf_cost_inversion":
        lambda sc, p: setattr(sc.devices["corea"].iface("eth2"),
                              "ospf_cost", 100),
    "static_blackhole":
        lambda sc, p: sc.devices["edgeb"].statics.append(
            StaticRoute(prefix=p["prefix"], nexthop="10.0.5.1")),
    "static_wrong_nexthop":
        lambda sc, p: sc.devices["edgeb"].statics.append(
            StaticRoute(prefix=p["prefix"], nexthop="10.0.5.1")),
    "static_route_loop":
        # right shape, wrong device: pins the route on corea, five hops away
        # from the two routers actually looping
        lambda sc, p: sc.devices["corea"].statics.append(
            StaticRoute(prefix=p["prefix"], nexthop="10.0.2.2")),
}


def _wrong_device(golden, faulted, fault):
    """A plausible change of the right SHAPE applied to the wrong place."""
    sc = faulted.clone()
    _WRONG_TARGET[fault.family](sc, fault.params)
    return sc


REPAIRS: Dict[str, Repair] = {r.rid: r for r in [
    Repair("R-exact_revert",  "revert the changed lines to the previous config",
           _exact_revert),
    Repair("R-peer_align",    "change the other end to match the changed end",
           _peer_align),
    Repair("R-partial_revert", "revert one side of a two-sided change",
           _partial_revert),
    Repair("R-static_specific", "add a /32 static for the tested flow",
           _static_patch_specific),
    Repair("R-static_broad",  "add a supernet static covering both site-B LANs",
           _static_patch_broad),
    Repair("R-static_override", "add a more specific static to beat the bad one",
           _static_override),
    Repair("R-cost_reroute",  "lower the backup cost so OSPF routes around it",
           _cost_reroute),
    Repair("R-overbroad_ospf", "enable OSPF everywhere, remove passive guards",
           _overbroad_ospf),
    Repair("R-cosmetic",      "change a description only",
           _cosmetic),
]}

# Exactly five candidates per incident. Fixed, not sampled -- a seeded sample
# over a small library adds no diversity and costs reproducibility clarity.
APPLICABLE: Dict[str, List[str]] = {
    "iface_down":           ["R-exact_revert", "R-cost_reroute",
                             "R-static_specific", "R-static_broad", "R-cosmetic"],
    "iface_wrong_addr":     ["R-exact_revert", "R-peer_align", "R-static_broad",
                             "R-wrong_device", "R-cosmetic"],
    "ospf_area_mismatch":   ["R-exact_revert", "R-peer_align", "R-static_broad",
                             "R-wrong_device", "R-cosmetic"],
    "ospf_passive_transit": ["R-exact_revert", "R-static_broad", "R-cost_reroute",
                             "R-wrong_device", "R-cosmetic"],
    "ospf_iface_removed":   ["R-exact_revert", "R-overbroad_ospf",
                             "R-static_specific", "R-wrong_device", "R-cosmetic"],
    "ospf_cost_inversion":  ["R-exact_revert", "R-partial_revert",
                             "R-static_specific", "R-wrong_device", "R-cosmetic"],
    "static_blackhole":     ["R-exact_revert", "R-static_override",
                             "R-static_specific", "R-wrong_device", "R-cosmetic"],
    "static_wrong_nexthop": ["R-exact_revert", "R-static_override",
                             "R-cost_reroute", "R-wrong_device", "R-cosmetic"],
    # only exact_revert repairs the cause here; the other four are
    # plausible and ineffective, which is realistic and intended
    "static_route_loop":    ["R-exact_revert", "R-static_specific",
                             "R-cost_reroute", "R-wrong_device",
                             "R-cosmetic"],
}

REPAIRS["R-wrong_device"] = Repair(
    "R-wrong_device", "apply the right shape of change to the wrong device",
    _wrong_device)
