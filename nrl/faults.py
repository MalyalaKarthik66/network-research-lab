"""Fault injection -- ten incidents, all configuration-only.

Every fault here is a routing-layer configuration change, for two hard reasons:

  * Batfish never consumes telemetry. "High CPU" has no representation in a
    config file and cannot be fixed by a config diff.
  * On FRR the shared fault surface is routing only. FRR access-lists are ROUTE
    filters; packet filtering lives in /etc/cumulus/acl/policy.conf -> iptables,
    which is not in the format Batfish reads. Injecting an iptables rule would
    make the container and the snapshot describe different networks, which is
    exactly the confound this pilot is built to avoid.

The families are chosen to span the detection layers deliberately: some are
visible at parse time, some only in the control plane, some only in the data
plane, and one (F07) leaves full reachability intact while silently moving all
traffic onto the backup path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from .model import Scenario, StaticRoute
from .topology import AREA


@dataclass
class Fault:
    fid: str
    family: str
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    apply_fn: Callable[[Scenario], None] = None

    def apply(self, sc: Scenario) -> Scenario:
        out = sc.clone()
        self.apply_fn(out)
        out.name = f"{sc.name}--{self.fid}"
        return out


def _iface_down(node, ifname):
    def fn(sc):
        sc.devices[node].iface(ifname).up = False
    return fn


def _wrong_addr(node, ifname, new_addr):
    def fn(sc):
        sc.devices[node].iface(ifname).addresses = [new_addr]
    return fn


def _area_mismatch(node, ifname, area):
    def fn(sc):
        sc.devices[node].iface(ifname).ospf_area = area
    return fn


def _passive_transit(node, ifname):
    def fn(sc):
        sc.devices[node].iface(ifname).ospf_passive = True
    return fn


def _ospf_removed(node, ifname):
    def fn(sc):
        i = sc.devices[node].iface(ifname)
        i.ospf_area = None
        i.ospf_cost = None
        i.ospf_network = None
    return fn


def _cost_inversion(pairs, cost):
    def fn(sc):
        for node, ifname in pairs:
            sc.devices[node].iface(ifname).ospf_cost = cost
    return fn


def _add_static(node, prefix, nexthop, distance=None):
    def fn(sc):
        sc.devices[node].statics.append(
            StaticRoute(prefix=prefix, nexthop=nexthop, distance=distance))
    return fn


# RETIRED (second attempt at F10) -- kept for the record.
#
# An OSPF network-type mismatch cannot be expressed in this artifact. Batfish's
# FRR grammar accepts only `ip ospf network point-to-point`; the spike showed
# `ip ospf network broadcast` raising "This syntax is unrecognized" (parser
# context siipo_network_p2p) and being dropped, leaving wan1<->wan2 ESTABLISHED.
# A fault only one tool can see is not a fault, it is a confound.
def _network_type_mismatch_RETIRED(node, ifname, net_type):
    def fn(sc):
        sc.devices[node].iface(ifname).ospf_network = net_type
    return fn


# RETIRED -- kept for the record, not referenced by FAULTS.
#
# F10 was originally an OSPF distribute-list dropping a prefix, implemented with
# an FRR access-list. The compatibility spike proved Batfish's
# CUMULUS_CONCATENATED model does not represent either construct: coreA's
# definedStructures showed only interfaces, with ZERO parse warnings. Batfish
# accepted the lines and modelled nothing.
#
# That is a silent model gap, not a parse error, and it is exactly the kind of
# divergence that must not sit inside a fault family -- Containerlab would
# enforce the filter while Batfish could not see it, so the artifact would be
# byte-identical and semantically different. Replaced by an OSPF network-type
# mismatch, which ospfSessionCompatibility does model.
def _distribute_list_drop_RETIRED(node, aclname, denied):
    def fn(sc):
        d = sc.devices[node]
        d.access_lists[aclname] = [f"seq 5 deny {denied}", "seq 10 permit any"]
        d.ospf.distribute_list_in = aclname
    return fn


FAULTS: List[Fault] = [
    Fault("F01", "iface_down",
          "primary WAN interface administratively shut on wan1",
          {"node": "wan1", "iface": "eth2", "peer": "wan2", "peer_iface": "eth1"},
          _iface_down("wan1", "eth2")),

    Fault("F02", "iface_down",
          "site-B core-to-edge interface shut on coreb (no alternate path)",
          {"node": "coreb", "iface": "eth2", "peer": "edgeb", "peer_iface": "eth1"},
          _iface_down("coreb", "eth2")),

    Fault("F03", "iface_wrong_addr",
          "wan2 eth1 renumbered off the shared /30; peer not updated",
          {"node": "wan2", "iface": "eth1", "bad": "10.0.7.2/30",
           "good": "10.0.3.2/30", "peer": "wan1", "peer_iface": "eth2",
           "peer_good": "10.0.3.1/30", "peer_align": "10.0.7.1/30"},
          _wrong_addr("wan2", "eth1", "10.0.7.2/30")),

    Fault("F04", "ospf_area_mismatch",
          "corea eth2 moved to area 0.0.0.1; wan1 still in area 0.0.0.0",
          {"node": "corea", "iface": "eth2", "bad_area": "0.0.0.1",
           "good_area": AREA, "peer": "wan1", "peer_iface": "eth1"},
          _area_mismatch("corea", "eth2", "0.0.0.1")),

    Fault("F05", "ospf_passive_transit",
          "wan2 eth2 marked passive; adjacency to coreb dies silently",
          {"node": "wan2", "iface": "eth2", "peer": "coreb", "peer_iface": "eth1"},
          _passive_transit("wan2", "eth2")),

    Fault("F06", "ospf_iface_removed",
          "coreb eth1 dropped out of OSPF entirely",
          {"node": "coreb", "iface": "eth1", "peer": "wan2", "peer_iface": "eth2"},
          _ospf_removed("coreb", "eth1")),

    Fault("F07", "ospf_cost_inversion",
          "backup link cost lowered to 1; all traffic silently uses the backup",
          {"pairs": [("corea", "eth3"), ("coreb", "eth3")], "bad_cost": 1,
           "good_cost": 100},
          _cost_inversion([("corea", "eth3"), ("coreb", "eth3")], 1)),

    Fault("F08", "static_blackhole",
          "corea blackholes 10.21.0.0/24; admin distance 1 beats OSPF's 110",
          {"node": "corea", "prefix": "10.21.0.0/24", "nexthop": "blackhole"},
          _add_static("corea", "10.21.0.0/24", "blackhole")),

    Fault("F09", "static_wrong_nexthop",
          "coreb static for 10.20.0.0/24 points back over the backup link",
          {"node": "coreb", "prefix": "10.20.0.0/24", "nexthop": "10.0.9.1"},
          _add_static("coreb", "10.20.0.0/24", "10.0.9.1")),

    # Third choice for F10, and this one is built only from constructs the
    # spike has PROVEN both tools represent: a static route. I-08 showed
    # Batfish modelling a static blackhole as discard/null_interface at admin
    # distance 1, so the construct is safe.
    #
    # edgeb installs a /32 for hostb pointing back at coreb. The /32 beats the
    # connected /24 on edgeb; coreb's OSPF route for 10.20.0.0/24 points at
    # edgeb. Traffic to hostb ping-pongs between them. Batfish detectLoops sees
    # it and FRR genuinely loops, and it is the only family that violates P07,
    # which is in the SPEC.
    Fault("F10", "static_route_loop",
          "edgeb installs a /32 for hostb pointing back at coreb, looping",
          {"node": "edgeb", "prefix": "10.20.0.10/32", "nexthop": "10.0.5.1",
           "loop_with": "coreb", "victim": "10.20.0.10"},
          _add_static("edgeb", "10.20.0.10/32", "10.0.5.1")),
]

FAULT_BY_ID = {f.fid: f for f in FAULTS}
