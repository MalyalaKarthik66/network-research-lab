"""T2 -- the pilot topology, as data.

                 10.10.0.0/24                                        10.20.0.0/24
   hosta ---------- edgea ---- corea ---- wan1 ==== wan2 ---- coreb ---- edgeb ---- hostb
                              (ABR-ish)         PRIMARY WAN                   \
                                  \                                            \--- hostc
                                   \------ BACKUP  cost 100 ------ coreb          10.21.0.0/24

Design decisions, and why (full rationale in docs/ARCHITECTURE.md):

  * OSPF area 0 only, no BGP in pilot-v1. Batfish's FRR grammar coverage is
    partial and unverified on this machine; every protocol added is parse risk.
    BGP is deferred to pilot-v2, gated on the FRR spike passing.
  * No packet ACLs anywhere. FRR access-lists are ROUTE filters. Packet
    filtering on Cumulus lives in /etc/cumulus/acl/policy.conf -> iptables,
    which is not in the concatenated format Batfish reads. Putting iptables
    rules in the container would break the same-artifact property outright.
  * Two site-B LANs (10.20.0.0/24, 10.21.0.0/24) with a host on each. This is
    what lets a repair fix the tested flow and break an untested one -- the
    exact mechanism the project is built to measure. It costs one extra 5 MB
    alpine container.
  * Backup path exists and is expensive (cost 100 vs 30) so that a repair can
    silently move traffic onto it without breaking reachability.
"""

from __future__ import annotations

from .model import (Device, Iface, Link, OspfCfg, Scenario, StaticRoute)

AREA = "0.0.0.0"
COST_NORMAL = 10
COST_BACKUP = 100

# (a_node, a_iface, a_addr, b_node, b_iface, b_addr, subnet, label, cost)
LINKS = [
    ("hosta", "eth1", "10.10.0.10/24", "edgea", "eth1", "10.10.0.1/24",
     "10.10.0.0/24", "siteA-lan", COST_NORMAL),
    ("edgea", "eth2", "10.0.1.1/30", "corea", "eth1", "10.0.1.2/30",
     "10.0.1.0/30", "siteA-core", COST_NORMAL),
    ("corea", "eth2", "10.0.2.1/30", "wan1", "eth1", "10.0.2.2/30",
     "10.0.2.0/30", "siteA-wan", COST_NORMAL),
    ("wan1", "eth2", "10.0.3.1/30", "wan2", "eth1", "10.0.3.2/30",
     "10.0.3.0/30", "wan-primary", COST_NORMAL),
    ("wan2", "eth2", "10.0.4.1/30", "coreb", "eth1", "10.0.4.2/30",
     "10.0.4.0/30", "wan-siteB", COST_NORMAL),
    ("coreb", "eth2", "10.0.5.1/30", "edgeb", "eth1", "10.0.5.2/30",
     "10.0.5.0/30", "siteB-core", COST_NORMAL),
    ("edgeb", "eth2", "10.20.0.1/24", "hostb", "eth1", "10.20.0.10/24",
     "10.20.0.0/24", "siteB-lan1", COST_NORMAL),
    ("edgeb", "eth3", "10.21.0.1/24", "hostc", "eth1", "10.21.0.10/24",
     "10.21.0.0/24", "siteB-lan2", COST_NORMAL),
    ("corea", "eth3", "10.0.9.1/30", "coreb", "eth3", "10.0.9.2/30",
     "10.0.9.0/30", "wan-backup", COST_BACKUP),
]

ROUTERS = {
    "edgea": "10.255.0.1",
    "corea": "10.255.0.2",
    "wan1":  "10.255.0.3",
    "wan2":  "10.255.0.4",
    "coreb": "10.255.0.5",
    "edgeb": "10.255.0.6",
}
HOSTS = {"hosta": "edgea", "hostb": "edgeb", "hostc": "edgeb"}

# interfaces that face a host LAN -- advertised into OSPF but no adjacency there
PASSIVE = {("edgea", "eth1"), ("edgeb", "eth2"), ("edgeb", "eth3")}


def build_golden() -> Scenario:
    """The known-good reference network. Every fault is a delta from this."""
    devices = {}

    for name, rid in ROUTERS.items():
        devices[name] = Device(
            hostname=name, kind="frr",
            ifaces=[Iface(name="lo", addresses=[f"{rid}/32"],
                          alias="router-id and management",
                          ospf_area=AREA, ospf_passive=True)],
            ospf=OspfCfg(router_id=rid),
        )

    for name in HOSTS:
        devices[name] = Device(hostname=name, kind="host", ifaces=[])

    links = []
    for (a, ai, aa, b, bi, ba, subnet, label, cost) in LINKS:
        links.append(Link(a, ai, b, bi, subnet, label))
        for node, ifname, addr, peer in ((a, ai, aa, b), (b, bi, ba, a)):
            d = devices[node]
            if d.kind == "host":
                d.ifaces.append(Iface(name=ifname, addresses=[addr],
                                      alias=f"link to {peer}"))
                gw_addr = ba if node == a else aa
                d.host_gateway = gw_addr.split("/")[0]
            else:
                d.ifaces.append(Iface(
                    name=ifname, addresses=[addr], alias=f"link to {peer} {label}",
                    ospf_area=AREA, ospf_cost=cost,
                    ospf_passive=(node, ifname) in PASSIVE,
                    ospf_network=None if (node, ifname) in PASSIVE else "point-to-point",
                ))

    return Scenario(name="t2-golden", devices=devices, links=links)


def link_by_label(label: str) -> Link:
    for (a, ai, b_, bi, subnet, lbl, *_rest) in [
            (l[0], l[1], l[3], l[4], l[6], l[7]) for l in LINKS]:
        if lbl == label:
            return Link(a, ai, b_, bi, subnet, lbl)
    raise KeyError(label)
