"""Structured configuration model.

Faults and repairs are STRUCTURED edits to this model, never text substitutions.
That matters for three reasons:

  * a text mutation can silently produce a config that does not parse, and we
    would not find out until Batfish or FRR rejected it;
  * a structured edit is trivially reversible, which is what makes the
    `exact_revert` repair operator honest;
  * the diff between golden / faulted / candidate is computed on RENDERED text,
    so the recorded diff is exactly what the two tools will consume.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Iface:
    name: str                      # lo, eth1, eth2, ...
    addresses: List[str]           # ["10.0.1.1/30"]
    alias: str = ""                # human-readable description
    up: bool = True                # False -> 'shutdown' equivalent
    ospf_area: Optional[str] = None    # None = not in OSPF
    ospf_cost: Optional[int] = None
    ospf_passive: bool = False
    ospf_network: Optional[str] = None  # e.g. "point-to-point"


@dataclass
class StaticRoute:
    prefix: str
    nexthop: str                   # "10.0.1.2" | "blackhole" | "eth2"
    distance: Optional[int] = None


@dataclass
class PrefixListEntry:
    seq: int
    action: str                    # permit | deny
    prefix: str                    # "10.21.0.0/24" | "any"
    le: Optional[int] = None


@dataclass
class RouteMapClause:
    seq: int
    action: str                    # permit | deny
    match_prefix_list: Optional[str] = None
    set_metric: Optional[int] = None


@dataclass
class OspfCfg:
    router_id: str
    redistribute: List[str] = field(default_factory=list)
    distribute_list_in: Optional[str] = None   # access-list name


@dataclass
class Device:
    hostname: str
    kind: str                      # "frr" | "host"
    ifaces: List[Iface] = field(default_factory=list)
    ospf: Optional[OspfCfg] = None
    statics: List[StaticRoute] = field(default_factory=list)
    prefix_lists: Dict[str, List[PrefixListEntry]] = field(default_factory=dict)
    route_maps: Dict[str, List[RouteMapClause]] = field(default_factory=dict)
    access_lists: Dict[str, List[str]] = field(default_factory=dict)
    # host-only
    host_gateway: Optional[str] = None

    def iface(self, name: str) -> Iface:
        for i in self.ifaces:
            if i.name == name:
                return i
        raise KeyError(f"{self.hostname} has no interface {name}")


@dataclass
class Link:
    a_node: str
    a_iface: str
    b_node: str
    b_iface: str
    subnet: str
    label: str


@dataclass
class Scenario:
    name: str
    devices: Dict[str, Device]
    links: List[Link]

    def clone(self) -> "Scenario":
        return copy.deepcopy(self)

    @property
    def routers(self) -> List[str]:
        return [n for n, d in self.devices.items() if d.kind == "frr"]

    @property
    def hosts(self) -> List[str]:
        return [n for n, d in self.devices.items() if d.kind == "host"]
