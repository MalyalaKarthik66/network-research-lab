"""Phase 3: evaluate the twelve frozen properties against the RUNNING network.

The same twelve properties Phase 2 asked Batfish, asked again of the emulator.
Deliberately the same identifiers and the same SPEC/ORACLE split, because the
whole measurement is the disagreement between the two.

A property returns HOLDS or VIOLATED only when status == OK. Anything the
harness could not carry out is ERROR with the reason preserved, and it is not
counted as a violation. See RULE 1 in nrl/clab.py.
"""

from __future__ import annotations

import time
from typing import Dict, List

from . import clab
from .properties import PROPERTIES, properties_for
from .topologies import ip_to_node, src_node

# SRC_NODE and IP_TO_NODE used to live here as module constants holding
# pilot-v1's addresses -- "10.255.0.6": ("edgeb", ...) among them. Deleted for
# the same reason as their bf_eval counterparts: everything topology-dependent
# is derived from the spec via src_node(spec) / ip_to_node(spec).

APP_PORT = {"HTTPS": 443, "HTTP": 80}


def _res(p, status, holds=None, error=None, evidence=None, extra=None, t0=None):
    return {
        "property_id": p["pid"], "kind": p["kind"], "in_spec": p["in_spec"],
        "text": p["text"],
        "status": status,                      # OK | ERROR
        "holds": holds,                        # True | False | None (None iff ERROR)
        "error": error,
        "evidence": evidence or {},
        "extra": extra or {},
        "seconds": round(time.time() - t0, 2) if t0 else 0.0,
    }


def hop_path(tr: Dict, spec) -> List[str]:
    out = []
    table = ip_to_node(spec)
    for h in tr.get("hops", []):
        n = table.get(h["ip"])
        if n and (not out or out[-1] != n):
            out.append(n)
    return out


def measure_property(lab: str, prop: Dict, state: Dict, cache: Dict,
                     scenario=None, spec=None) -> Dict:
    if spec is None:
        raise ValueError("measure_property requires a topology spec; it used "
                         "to default to pilot-v1's network")
    t0 = time.time()
    pid, kind = prop["pid"], prop["kind"]
    try:
        if kind == "reachability":
            node, src_if = src_node(spec)[prop["src"]]
            ping = clab.probe_ping(lab, node, prop["dst"], src=src_if)
            ev = {"ping": ping}
            if ping["status"] == "ERROR":
                return _res(prop, "ERROR", error=ping["error"], evidence=ev, t0=t0)
            if prop["app"] in APP_PORT:
                tcp = clab.probe_tcp(lab, node, prop["dst"], APP_PORT[prop["app"]])
                ev["tcp"] = tcp
                if tcp["status"] == "ERROR":
                    return _res(prop, "ERROR", error=tcp["error"],
                                evidence=ev, t0=t0)
                holds = bool(tcp["connected"])
            else:
                holds = ping["loss_pct"] is not None and ping["loss_pct"] < 100.0
            return _res(prop, "OK", holds, evidence=ev, t0=t0,
                        extra={"loss_pct": ping["loss_pct"],
                               "rtt_avg_ms": ping["rtt_avg_ms"],
                               "app": prop["app"]})

        if kind == "path_contains":
            node, _ = src_node(spec)[prop["src"]]
            tr = cache.get(f"tr:{node}:{prop['dst']}") or \
                clab.probe_traceroute(lab, node, prop["dst"])
            cache[f"tr:{node}:{prop['dst']}"] = tr
            if tr["status"] == "ERROR":
                return _res(prop, "ERROR", error=tr["error"],
                            evidence={"traceroute": tr}, t0=t0)
            path = hop_path(tr, spec)
            holds = set(prop["must_traverse"]).issubset(set(path))
            return _res(prop, "OK", holds, evidence={"traceroute": tr}, t0=t0,
                        extra={"observed_path": path,
                               "must_traverse": prop["must_traverse"]})

        if kind == "no_loops":
            trs, suspected, unreached = {}, False, []
            for dst in ("10.20.0.10", "10.21.0.10"):
                key = f"tr:hosta:{dst}"
                tr = cache.get(key) or clab.probe_traceroute(lab, "hosta", dst)
                cache[key] = tr
                trs[dst] = tr
                if tr["status"] == "ERROR":
                    return _res(prop, "ERROR", error=tr["error"],
                                evidence={"traceroutes": trs}, t0=t0)
                # A LOOP is a hop that repeats. Running out of hops is
                # UNREACHABILITY -- a blackholed destination returns twelve
                # rows of '*', which the previous criterion scored as a loop
                # via max_hops_reached. That made three candidates look like
                # Batfish/emulator divergence on P07 when Batfish's
                # detectLoops was simply right. Unreachability is P03/P04's
                # job; it is recorded here as evidence, not counted as a loop.
                suspected = suspected or bool(tr["loop_suspected"])
                if tr["max_hops_reached"] and not tr["loop_suspected"]:
                    unreached.append(dst)
            return _res(prop, "OK", not suspected,
                        evidence={"traceroutes": trs}, t0=t0,
                        extra={"loop_suspected": suspected,
                               "destinations_unreached_not_looping": unreached})

        if kind == "ospf_adjacencies":
            adj = clab.ospf_full_adjacencies(state)
            errs = [n for n, v in adj["per_router"].items()
                    if v["status"] == "ERROR"]
            if errs:
                return _res(prop, "ERROR",
                            error=f"ospf neighbor unavailable on {errs}",
                            evidence={"adjacencies": adj}, t0=t0)
            holds = adj["full_adjacency_pairs"] == prop["expected"]
            return _res(prop, "OK", holds, evidence={"adjacencies": adj}, t0=t0,
                        extra={"full_adjacency_pairs":
                               adj["full_adjacency_pairs"],
                               "expected": prop["expected"]})

        if kind == "route_present":
            present = clab.routes_for_prefix(state, prop["prefix"])
            unavailable = [n for n in spec.routers
                           if state.get(n, {}).get("route", {}).get("status")
                           != "OK"]
            if unavailable:
                return _res(prop, "ERROR",
                            error=f"RIB unavailable on {unavailable}",
                            evidence={"present": present}, t0=t0)
            missing = sorted(n for n, ok in present.items() if not ok)
            return _res(prop, "OK", not missing, evidence={"present": present},
                        t0=t0, extra={"nodes_missing_route": missing,
                                      "prefix": prop["prefix"]})

        if kind == "no_iface_down":
            unavailable = [n for n in spec.routers
                           if state.get(n, {}).get("interface", {}).get("status")
                           != "OK"]
            if unavailable:
                return _res(prop, "ERROR",
                            error=f"interface state unavailable on {unavailable}",
                            t0=t0)
            down = clab.interfaces_down(state, scenario)
            return _res(prop, "OK", not down, t0=t0,
                        extra={"down_interfaces": down,
                               "ignored_non_artifact_interfaces":
                                   getattr(clab.interfaces_down,
                                           "last_ignored", [])})

        return _res(prop, "ERROR", error=f"no measurer for kind={kind}", t0=t0)

    except Exception as exc:                                       # noqa: BLE001
        return _res(prop, "ERROR", error=f"{type(exc).__name__}: {exc}", t0=t0)


def measure_all(lab: str, state: Dict, scenario=None, spec=None) -> List[Dict]:
    if spec is None:
        raise ValueError("measure_all requires a topology spec")
    cache: Dict = {}
    return [measure_property(lab, p, state, cache, scenario, spec)
            for p in properties_for(spec)]
