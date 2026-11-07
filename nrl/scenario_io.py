"""Serialise the Scenario model beside each artifact.

run_phase3 used to REGENERATE scenarios in memory from a hardcoded v1 fault
list, which is why it could not run pilot-v2 at all (`C-00001` was simply not in
the dict). Writing the model next to the artifact removes the regeneration step:
Phase 3 loads exactly the scenario the artifact was rendered from, whatever
pilot, topology or generator produced it.

scenario.json lives at the CANDIDATE level, not inside artifact/, so it is
covered by the build lock but never mounted into a container and never seen by
verify_pilot's byte-identity check.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import (Device, Iface, OspfCfg, PrefixListEntry, RouteMapClause,
                    Scenario, StaticRoute)


def to_dict(sc: Scenario) -> dict:
    return {
        "name": sc.name,
        "links": [{"a_node": l.a_node, "a_iface": l.a_iface,
                   "b_node": l.b_node, "b_iface": l.b_iface,
                   "subnet": l.subnet, "label": l.label} for l in sc.links],
        "devices": {n: {
            "hostname": d.hostname, "kind": d.kind,
            "host_gateway": d.host_gateway,
            "ospf": (None if d.ospf is None else
                     {"router_id": d.ospf.router_id,
                      "redistribute": list(d.ospf.redistribute),
                      "distribute_list_in": d.ospf.distribute_list_in}),
            "ifaces": [{"name": i.name, "addresses": list(i.addresses),
                        "alias": i.alias, "up": i.up,
                        "ospf_area": i.ospf_area, "ospf_cost": i.ospf_cost,
                        "ospf_passive": i.ospf_passive,
                        "ospf_network": i.ospf_network} for i in d.ifaces],
            "statics": [{"prefix": s.prefix, "nexthop": s.nexthop,
                         "distance": s.distance} for s in d.statics],
            "access_lists": {k: list(v) for k, v in d.access_lists.items()},
            "prefix_lists": {k: [{"seq": e.seq, "action": e.action,
                                  "prefix": e.prefix, "le": e.le}
                                 for e in v] for k, v in d.prefix_lists.items()},
            "route_maps": {k: [{"seq": c.seq, "action": c.action,
                                "match_prefix_list": c.match_prefix_list,
                                "set_metric": c.set_metric}
                               for c in v] for k, v in d.route_maps.items()},
        } for n, d in sc.devices.items()},
    }


def from_dict(d: dict) -> Scenario:
    devices = {}
    for n, dd in d["devices"].items():
        devices[n] = Device(
            hostname=dd["hostname"], kind=dd["kind"],
            host_gateway=dd.get("host_gateway"),
            ospf=(None if dd.get("ospf") is None else
                  OspfCfg(router_id=dd["ospf"]["router_id"],
                          redistribute=list(dd["ospf"].get("redistribute", [])),
                          distribute_list_in=dd["ospf"].get("distribute_list_in"))),
            ifaces=[Iface(name=i["name"], addresses=list(i["addresses"]),
                          alias=i.get("alias", ""), up=i.get("up", True),
                          ospf_area=i.get("ospf_area"),
                          ospf_cost=i.get("ospf_cost"),
                          ospf_passive=i.get("ospf_passive", False),
                          ospf_network=i.get("ospf_network"))
                    for i in dd["ifaces"]],
            statics=[StaticRoute(prefix=s["prefix"], nexthop=s["nexthop"],
                                 distance=s.get("distance"))
                     for s in dd.get("statics", [])],
            access_lists={k: list(v) for k, v in dd.get("access_lists", {}).items()},
            prefix_lists={k: [PrefixListEntry(**e) for e in v]
                          for k, v in dd.get("prefix_lists", {}).items()},
            route_maps={k: [RouteMapClause(**c) for c in v]
                        for k, v in dd.get("route_maps", {}).items()})
    from .model import Link
    links = [Link(**l) for l in d.get("links", [])]
    return Scenario(name=d.get("name", ""), devices=devices, links=links)


def write(path: Path, sc: Scenario) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(sc), indent=1) + "\n",
                    newline="\n", encoding="utf-8")


def read(path: Path) -> Scenario:
    return from_dict(json.loads(Path(path).read_text()))
