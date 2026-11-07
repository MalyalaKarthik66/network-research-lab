"""Kernel FIB parsing and replay.

Primary transient instrument: every router container runs `ip -ts monitor link route nexthop`, which prints each
kernel link, route and nexthop-object change the moment it happens, prefixed with a microsecond timestamp.
Containers share the WSL kernel clock with the runner, so those timestamps and the runner's time.time() are the
same clock (container TZ must be UTC; checked per run).

The FIB at any instant is reconstructed as: the snapshot taken when monitoring started (routes, link states,
nexthop objects), plus every monitored event up to that instant, applied in timestamp order. The reconstructed
per-router FIB is converted to the route format nrl.flowmatrix walks, so transient paths and v3 steady-state paths
are computed by the same frozen walker.

Kernel behaviour the route monitor does NOT report (amendment A3; verified in audit/2026-09-15-instrument-unit-checks):
  * a device going administratively down silently flushes every IPv4 route (and next hop) through it, including the
    connected route; the replay applies that flush at the link event;
  * a device losing carrier silently flushes the nexthop OBJECTS on it, and with them every route installed through
    such an object (FRR installs protocol routes that way, `nhid N`); routes without a nexthop object (e.g. the
    kernel's connected route) stay installed, flagged `linkdown`: the kernel still selects them but the traffic is
    dropped, so such a route whose every next hop is on a carrier-down device discards traffic (BLACKHOLE);
  * a nexthop object replaced in place, or deleted while routes use it, would change routes silently; such events
    are detected (NexthopTable) and invalidate the run instead of being modelled.
ECMP with some unusable members keeps only the usable members (the walker then applies its lowest-address rule); a
flow is broken only when no member can forward. This can miss a partial loss, never invent one.

Scope decisions (documented, not tuned):
  * IPv4 main table only; IPv6, local/broadcast tables are ignored.
  * Routes via the Containerlab management interface eth0 (and the management default route) are dropped: they are
    not part of the modelled network, exactly as flowmatrix skips kernel routes.
  * A router's own loopback /32 lives in the kernel local table, not main; it is added as a connected route from
    the topology spec (config-derived, not measured).
"""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

TS_RE = re.compile(r"^\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)\]\s?(.*)$")
LINK_RE = re.compile(r"^(Deleted\s+)?\d+:\s+([^:@\s]+)(?:@[^:\s]*)?:\s+<([^>]*)>")
NH_RE = re.compile(r"^(Deleted\s+)?id\s+(\d+)\s*(.*)$")
_TYPES = {"blackhole", "unreachable", "prohibit", "throw", "local", "broadcast",
          "multicast", "anycast", "nat"}
_KEYS_WITH_VALUE = {"via", "dev", "proto", "scope", "src", "metric", "table", "weight",
                    "pref", "realm", "expires", "mtu", "advmss", "hoplimit", "nhid"}
_NH_FLAGS = {"dead", "linkdown"}
MGMT_DEVS = ("eth0",)
SNAP_LINKS, SNAP_NEXTHOPS, POLL_ROUTES = "@@LINKS@@", "@@NEXTHOPS@@", "@@ROUTES@@"
UP = (True, True)                                   # (administratively up, carrier)


def parse_ts(s: str) -> float:
    """ISO timestamp printed by `ip -ts` (container TZ is UTC; runner records `date` output to prove it)."""
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


def parse_route_line(body: str) -> Optional[Dict]:
    s = body.strip()
    deleted = False
    if s.startswith("Deleted "):
        deleted, s = True, s[len("Deleted "):].strip()
    toks = s.split()
    if not toks:
        return None
    kind = "unicast"
    if toks[0] in _TYPES:
        kind, toks = toks[0], toks[1:]
    if not toks:
        return None
    dst = toks[0]
    if dst == "default":
        dst = "0.0.0.0/0"
    if ":" in dst:
        return None                                   # IPv6, or a link-object line
    try:
        net = ipaddress.ip_network(dst if "/" in dst else dst + "/32", strict=False)
    except ValueError:
        return None                                   # e.g. a nexthop-object line ("id 34 ...")
    kv: Dict[str, str] = {}
    i = 1
    while i < len(toks):
        k = toks[i]
        if k in _KEYS_WITH_VALUE and i + 1 < len(toks):
            kv.setdefault(k, toks[i + 1])
            i += 2
        else:
            i += 1
    flags = sorted({t for t in toks[1:] if t in _NH_FLAGS})
    metric = kv.get("metric", "0")
    return {"deleted": deleted, "dst": str(net), "kind": kind,
            "metric": int(metric) if metric.isdigit() else 0,
            "proto": kv.get("proto"), "dev": kv.get("dev"), "table": kv.get("table", "main"),
            "nhid": kv.get("nhid"), "flags": flags,
            "nexthops": [(kv["via"], kv.get("dev"))] if "via" in kv else [],
            "nh_flags": [flags] if "via" in kv else []}


def parse_lines(lines: Iterable[str], with_ts: bool) -> List[Dict]:
    """Parse route records from `ip route show` (with_ts=False) or `ip -ts monitor` output (with_ts=True).

    Multipath routes print a header line followed by indented `nexthop via X dev Y [flags]` lines, which carry no
    timestamp; they are folded into the preceding record. Link and nexthop-object lines are skipped here.
    """
    recs: List[Dict] = []
    cur: Optional[Dict] = None
    for raw in lines:
        if not raw.strip():
            continue
        if raw[:1] in (" ", "\t"):
            if cur is not None:
                m = re.search(r"via (\S+)(?: dev (\S+))?", raw)
                if m:
                    cur["nexthops"].append((m.group(1), m.group(2)))
                    cur.setdefault("nh_flags", []).append(sorted(t for t in raw.split() if t in _NH_FLAGS))
            continue
        ts, body = None, raw
        if with_ts:
            m = TS_RE.match(raw.rstrip("\n"))
            if not m:
                cur = None
                continue
            ts, body = parse_ts(m.group(1)), m.group(2)
        r = parse_route_line(body)
        if r is None:
            cur = None
            continue
        r["ts"] = ts
        recs.append(r)
        cur = r
    return recs


def _bodies(lines: Iterable[str], with_ts: bool):
    for raw in lines:
        if not raw.strip() or raw[:1] in (" ", "\t"):
            continue
        body, ts = raw.rstrip("\n"), None
        if with_ts:
            m = TS_RE.match(body)
            if not m:
                continue
            ts, body = parse_ts(m.group(1)), m.group(2)
        yield ts, body


def parse_link_lines(lines: Iterable[str], with_ts: bool) -> List[Dict]:
    """Link records from `ip -o link show` (with_ts=False) or `ip -ts monitor link` output (with_ts=True)."""
    out = []
    for ts, body in _bodies(lines, with_ts):
        m = LINK_RE.match(body)
        if not m:
            continue
        flags = set(m.group(3).split(","))
        out.append({"type": "link", "ts": ts, "deleted": bool(m.group(1)), "dev": m.group(2),
                    "admin_up": "UP" in flags, "carrier": "LOWER_UP" in flags})
    return out


def parse_nexthop_lines(lines: Iterable[str], with_ts: bool) -> List[Dict]:
    """Nexthop-object records from `ip nexthop show` (with_ts=False) or `ip -ts monitor nexthop` (with_ts=True)."""
    out = []
    for ts, body in _bodies(lines, with_ts):
        m = NH_RE.match(body)
        if not m:
            continue
        content = " ".join(m.group(3).split())
        g = re.search(r"\bgroup (\S+)", content)
        members = [x.split(",")[0] for x in g.group(1).split("/")] if g else []
        out.append({"type": "nexthop", "ts": ts, "deleted": bool(m.group(1)), "id": m.group(2),
                    "content": content, "members": members})
    return out


def monitor_error_lines(lines: Iterable[str]) -> List[str]:
    """Lines in a monitor log that are neither timestamped records nor continuation lines (e.g. netlink errors)."""
    return [l for l in lines if l.strip() and l[:1] not in (" ", "\t") and not TS_RE.match(l.rstrip("\n"))]


def split_state(text: str) -> Dict[str, List[str]]:
    """Split a combined snapshot (`routes; @@LINKS@@; links; @@NEXTHOPS@@; nexthops`) into its parts."""
    parts: Dict[str, List[str]] = {"routes": [], "links": [], "nexthops": []}
    cur = "routes"
    for line in (text or "").splitlines():
        s = line.strip()
        if s == SNAP_LINKS:
            cur = "links"
            continue
        if s == SNAP_NEXTHOPS:
            cur = "nexthops"
            continue
        parts[cur].append(line)
    return parts


def links_from(text: str) -> Dict[str, Tuple[bool, bool]]:
    return {l["dev"]: (l["admin_up"], l["carrier"]) for l in parse_link_lines((text or "").splitlines(), False)}


def links_equal(a: Dict[str, Tuple[bool, bool]], b: Dict[str, Tuple[bool, bool]]) -> bool:
    """Link states agree on every device either side knows (unknown = up). Skipped when a side has no link data."""
    if not a or not b:
        return True
    return all(a.get(k, UP) == b.get(k, UP) for k in set(a) | set(b))


def flushes_nexthop_objects(old: Tuple[bool, bool], new: Tuple[bool, bool]) -> bool:
    """True when a link transition makes the kernel silently flush nexthop objects on the device: administrative down,
    or (still administratively up) loss of carrier."""
    return (old[0] and not new[0]) or (new[0] and old[1] and not new[1])


def _nh_core(rec: Dict) -> str:
    return " ".join(t for t in rec["content"].split() if t not in _NH_FLAGS)


class NexthopTable:
    """Kernel nexthop objects of one router. apply() reports a silent route change: a nexthop object replaced in place
    or deleted while routes (directly or through a group) still use it."""

    def __init__(self, recs: Iterable[Dict] = ()):
        self.by_id: Dict[str, Dict] = {r["id"]: r for r in recs}

    def flush_dev(self, dev: str) -> None:
        """Mirror the kernel's silent flush of nexthop objects on a device that went down or lost carrier."""
        for i in [i for i, r in self.by_id.items() if f" dev {dev} " in f" {r['content']} "]:
            del self.by_id[i]

    def apply(self, ev: Dict, referenced: Iterable[str]) -> Optional[str]:
        refs = set(referenced)
        closure = refs | {m for i in refs if i in self.by_id for m in self.by_id[i]["members"]}
        problem = None
        if ev["deleted"]:
            if ev["id"] in closure:
                problem = f"referenced nexthop object {ev['id']} deleted"
            self.by_id.pop(ev["id"], None)
        else:
            old = self.by_id.get(ev["id"])
            if old is not None and _nh_core(old) != _nh_core(ev) and ev["id"] in closure:
                problem = f"referenced nexthop object {ev['id']} replaced in place"
            self.by_id[ev["id"]] = ev
        return problem


class RouterFib:
    """One router's IPv4 main-table FIB keyed by (prefix, metric), as the kernel keys it, plus its link states."""

    def __init__(self, own_prefixes: Iterable[str] = (), links: Optional[Dict[str, Tuple[bool, bool]]] = None):
        self.routes: Dict[Tuple[str, int], Dict] = {}
        self.own = sorted(set(own_prefixes))
        self.links: Dict[str, Tuple[bool, bool]] = dict(links or {})

    def apply(self, rec: Dict) -> bool:
        if rec.get("type") == "link":
            return self.apply_link(rec)
        if rec.get("type") == "nexthop":
            return False
        if rec.get("table", "main") != "main":
            return False
        key = (rec["dst"], rec["metric"])
        if rec["deleted"]:
            return self.routes.pop(key, None) is not None
        self.routes[key] = dict(rec)
        return True

    def apply_link(self, rec: Dict) -> bool:
        if rec.get("deleted"):
            return False
        dev, new = rec["dev"], (bool(rec["admin_up"]), bool(rec["carrier"]))
        old = self.links.get(dev, UP)
        self.links[dev] = new
        if flushes_nexthop_objects(old, new):
            # administrative down flushes everything through the device; carrier loss only nexthop-object routes
            self._flush_dev(dev, nexthop_objects_only=new[0])
        return new != old

    def _flush_dev(self, dev: str, nexthop_objects_only: bool = False) -> None:
        for key in list(self.routes):
            r = self.routes[key]
            if nexthop_objects_only and not r.get("nhid"):
                continue
            if not r.get("nexthops"):
                if r.get("dev") == dev:
                    del self.routes[key]
                continue
            nhf = r.get("nh_flags") or []
            keep = [(nh, nhf[i] if i < len(nhf) else []) for i, nh in enumerate(r["nexthops"])
                    if (nh[1] or r.get("dev")) != dev]
            if not keep:
                del self.routes[key]
            elif len(keep) != len(r["nexthops"]):
                self.routes[key] = dict(r, nexthops=[nh for nh, _ in keep], nh_flags=[f for _, f in keep],
                                        dev=keep[0][0][1] or r.get("dev"))

    def referenced_nhids(self) -> set:
        return {r["nhid"] for r in self.routes.values() if r.get("nhid")}

    def _admin(self, dev) -> bool:
        return self.links.get(dev, UP)[0] if dev else True

    def _usable(self, dev) -> bool:
        return all(self.links.get(dev, UP)) if dev else True

    def to_flowmatrix(self) -> Dict[str, List[Dict]]:
        out: Dict[str, List[Dict]] = {}
        for (dst, metric), r in sorted(self.routes.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            devs = {d for _, d in r["nexthops"] if d} | ({r["dev"]} if r.get("dev") else set())
            if dst == "0.0.0.0/0" or devs & set(MGMT_DEVS):
                continue
            if r["kind"] in ("blackhole", "unreachable", "prohibit"):
                e = {"protocol": "blackhole", "distance": 1, "metric": metric,
                     "nexthops": [{"blackhole": True}]}
            elif r["kind"] != "unicast":
                continue
            else:
                rflags = set(r.get("flags") or ())
                nhf = r.get("nh_flags") or []
                gws = [(gw, dev, dev or r.get("dev"), set(nhf[i] if i < len(nhf) else ()) | rflags)
                       for i, (gw, dev) in enumerate(r["nexthops"]) if gw]
                if gws:
                    present = [g for g in gws if "dead" not in g[3] and self._admin(g[2])]
                    if not present:
                        continue                                  # not selectable by the kernel
                    fwd = [g for g in present if "linkdown" not in g[3] and self._usable(g[2])]
                    if fwd:
                        e = {"protocol": r.get("proto") or "unknown", "distance": 110, "metric": metric,
                             "nexthops": [{"ip": gw, "interfaceName": dev} for gw, dev, _, _ in fwd]}
                    else:                                         # selected, but every next hop drops traffic
                        e = {"protocol": "linkdown", "distance": 110, "metric": metric,
                             "nexthops": [{"blackhole": True}]}
                else:
                    dev = r.get("dev")
                    if "dead" in rflags or not self._admin(dev):
                        continue
                    if "linkdown" in rflags or not self._usable(dev):
                        e = {"protocol": "linkdown", "distance": 0, "metric": metric,
                             "nexthops": [{"blackhole": True}]}
                    else:
                        e = {"protocol": "connected", "distance": 0, "metric": metric,
                             "nexthops": [{"directlyConnected": True, "interfaceName": dev}]}
            out.setdefault(dst, []).append(e)
        for p in self.own:
            out.setdefault(p, []).append({"protocol": "connected", "distance": 0, "metric": 0,
                                          "nexthops": [{"directlyConnected": True, "interfaceName": "lo"}]})
        for entries in out.values():                  # lowest (distance, metric) is the installed one
            entries.sort(key=lambda e: (e["distance"], e["metric"]))
            for j, e in enumerate(entries):
                e["selected"] = (j == 0)
        return out


def own_prefixes(spec) -> Dict[str, List[str]]:
    return {r: [f"{lo}/32"] for r, lo in spec.routers.items()}


def event_order(e: Tuple[float, str, Dict]):
    """Timestamp, router, then link before route before nexthop at an identical timestamp."""
    kind = e[2].get("type")
    return (e[0], e[1], 0 if kind == "link" else (2 if kind == "nexthop" else 1))


def replay(initial: Dict[str, List[Dict]], events: List[Tuple[float, str, Dict]], spec,
           initial_links: Optional[Dict[str, Dict[str, Tuple[bool, bool]]]] = None):
    """Yield (t, ribs) for the initial state (t=None) and after every distinct event timestamp that changes state."""
    own = own_prefixes(spec)
    links = initial_links or {}
    fibs = {r: RouterFib(own.get(r, ()), links.get(r)) for r in spec.routers}
    for r, recs in initial.items():
        for rec in recs:
            if r in fibs and not rec["deleted"]:
                fibs[r].apply(rec)
    yield None, {r: f.to_flowmatrix() for r, f in fibs.items()}
    events = sorted(events, key=event_order)
    i = 0
    while i < len(events):
        t = events[i][0]
        touched = False
        while i < len(events) and events[i][0] == t:
            _, router, rec = events[i]
            if router in fibs:
                touched |= fibs[router].apply(rec)
            i += 1
        if touched:
            yield t, {r: f.to_flowmatrix() for r, f in fibs.items()}
