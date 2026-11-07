"""Flow-level risk measurement: what FRACTION of the network does a repair break?

WHY THIS EXISTS

The frozen suite probes four endpoints -- hosta<->hostb, hosta->hostc and one
loopback pair -- and calls a property satisfied when loss is under 100%
(`p3_eval.py:74`). In 3,186 recorded probes the loss distribution is 0.0 (2,499)
and 100.0 (686), with exactly one value in between. So a continuous quantity is
being read by an instrument with two settings.

The damage is not binary. Across 79 harmful candidates there are six distinct
violation signatures: 37 break only P06 (traffic still flows, it just takes the
backup WAN), 23 break only P03/P04 (one site unreachable), 11 break everything.
"slightly suboptimal" and "the network is down" both come out as HARMFUL.

That is why there is no probability to calibrate. P(harm | X) can only be 0 or
1 when harm is "did any of four probes reach zero packets".

WHAT THIS MEASURES INSTEAD

    r(x) = (flows broken  +  flows whose forwarding path changed)
           -----------------------------------------------------
                    (flows the golden network carries)

Endpoints are the router loopbacks and the LAN hosts -- addresses that already
exist in every topology; P11 has always probed loopback to loopback, so this is
the same instrument pointed at more of the network. A six-router topology has
~72 ordered pairs, a sixteen-router one ~380.

The golden baseline is not optional. A flow that is broken on the golden network
is not the repair's fault, which is exactly the rule the property suite already
uses ("in G iff it holds on the golden").

WHY THE FLOW SET IS FIXED PER TOPOLOGY

Seeded by topology name, so every candidate in a topology is scored on the same
flows and r(x) is comparable across candidates. Resampling per run would add
binomial noise to r, which is measurement error, not risk. The genuinely
stochastic component comes from the environment (nrl/env_randomize.py) and is
measured across replicates, where it belongs.

COST

One `docker exec` per source container, not per flow: a shell loop inside the
container amortises the ~0.4 s exec overhead across that source's destinations.
48 flows over ~9 sources costs roughly 60 s, against ~130 s for the lab itself.
Forwarding paths add nothing: they are read from the RIBs the run already
captured, so the blast-radius half of r(x) is free.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Dict, List, Optional, Sequence, Tuple

from . import clab

DEFAULT_N_FLOWS = 48
PING_COUNT = 1          # one packet per flow; the fraction comes from FLOWS
PING_WAIT_S = 1
#: "<dst> <0|1> <ttl or ->"
_LINE = re.compile(r"^(\S+)\s+([01])\s+(\S+)$")


def endpoints(spec) -> List[Dict]:
    """Every probeable address in the topology, with how to source from it.

    Router loopbacks need `ping -I <loopback>` so the packet carries a routable
    source address; a host has one interface and needs no -I.
    """
    out = []
    for node, lo in sorted(spec.routers.items()):
        out.append({"name": node, "kind": "router", "container": node,
                    "addr": lo, "src_flag": lo})
    seen = set()
    for (a, ai, aa, b, bi, ba, subnet, label, cost) in spec.links:
        for who, addr in ((a, aa), (b, ba)):
            if who in spec.hosts and who not in seen:
                seen.add(who)
                out.append({"name": who, "kind": "host", "container": who,
                            "addr": addr.split("/")[0], "src_flag": None})
    return out


def sample_flows(spec, n: int = DEFAULT_N_FLOWS,
                 seed_extra: str = "") -> List[Dict]:
    """Deterministic ordered (src, dst) pairs, seeded by topology name.

    Same flows for every candidate in a topology, so r(x) is comparable. Pairs
    are drawn by sorting on a hash rather than shuffling, so the selection does
    not depend on Python's RNG version.
    """
    eps = endpoints(spec)
    pairs = [(s, d) for s in eps for d in eps if s["addr"] != d["addr"]]
    key = f"{spec.name}|{seed_extra}"
    def rank(p):
        h = hashlib.sha256(f"{key}|{p[0]['addr']}|{p[1]['addr']}".encode())
        return h.hexdigest()
    pairs.sort(key=rank)
    chosen = pairs[:min(n, len(pairs))]
    return [{"flow_id": f"{s['name']}->{d['name']}",
             "src_name": s["name"], "src_container": s["container"],
             "src_addr": s["addr"], "src_flag": s["src_flag"],
             "dst_name": d["name"], "dst_addr": d["addr"]}
            for s, d in chosen]


def measure_flows(lab: str, flows: List[Dict]) -> Dict:
    """Probe every flow. One exec per source container.

    A flow whose probe errors is recorded `reachable=None`, never False: an
    exec that failed to run is not evidence that the network is broken, and
    folding it into the numerator would inflate r(x) with harness noise.
    """
    by_src: Dict[Tuple[str, Optional[str]], List[Dict]] = {}
    for f in flows:
        by_src.setdefault((f["src_container"], f["src_flag"]), []).append(f)

    results: Dict[str, Dict] = {}
    for (container, src_flag), fs in sorted(by_src.items()):
        src = f"-I {src_flag} " if src_flag else ""
        dsts = " ".join(f["dst_addr"] for f in fs)
        # The TTL of the reply is a free hop count: it is already in the output
        # we were discarding. `grep -o` rather than a sed capture because both
        # busybox (alpine hosts) and GNU (frr routers) support it identically.
        script = (
            f'for d in {dsts}; do '
            f'o=$(ping -c {PING_COUNT} -W {PING_WAIT_S} {src}$d 2>/dev/null); '
            f't=$(printf "%s" "$o" | grep -o "ttl=[0-9]*" | head -1 | cut -d= -f2); '
            f'if [ -n "$t" ]; then echo "$d 1 $t"; else echo "$d 0 -"; fi; done')
        r = clab.dexec(lab, container, ["sh", "-c", script],
                       timeout=len(fs) * (PING_WAIT_S * PING_COUNT + 2) + 15)
        seen = {}
        if r.get("status") == "OK":
            for line in (r.get("stdout") or "").splitlines():
                m = _LINE.match(line.strip())
                if m:
                    ttl = m.group(3)
                    seen[m.group(1)] = (m.group(2) == "1",
                                        int(ttl) if ttl.isdigit() else None)
        for f in fs:
            reach, ttl = seen.get(f["dst_addr"], (None, None))
            results[f["flow_id"]] = {
                **{k: f[k] for k in ("flow_id", "src_name", "dst_name",
                                     "src_addr", "dst_addr")},
                "reachable": reach,
                "ttl": ttl,
                "probe_status": r.get("status"),
                "error": r.get("error") if r.get("status") != "OK" else None,
            }
    ok = sum(1 for v in results.values() if v["reachable"] is True)
    bad = sum(1 for v in results.values() if v["reachable"] is False)
    err = sum(1 for v in results.values() if v["reachable"] is None)
    ttls = sum(1 for v in results.values() if v["ttl"] is not None)
    return {"flows": results, "n_flows": len(flows), "n_reachable": ok,
            "n_unreachable": bad, "n_error": err, "n_with_ttl": ttls}


# ---------------------------------------------------------------------------
# forwarding paths, reconstructed from the RIBs already captured per run
# ---------------------------------------------------------------------------

def owner_map(spec) -> Dict[str, str]:
    """Every interface and loopback address -> the router that owns it."""
    own = {lo: n for n, lo in spec.routers.items()}
    for (a, ai, aa, b, bi, ba, sub, label, cost) in spec.links:
        own[aa.split("/")[0]] = a
        own[ba.split("/")[0]] = b
    return own


def _selected(entries) -> Optional[Dict]:
    """The one route FRR actually installed for a prefix.

    `show ip route json` returns a LIST per prefix -- every candidate route,
    only one of which is in the FIB. Taking entries[0] silently follows a route
    the router is not using. That is not hypothetical: RR-blackhole_other adds
    `ip route 10.21.0.0/24 blackhole`, and corea then reports

        [0] ospf   distance=110  selected=None  installed=None
        [1] static distance=1    selected=True  installed=True  blackhole=true

    so entries[0] reported a healthy OSPF path while the box was discarding the
    traffic. All six regressive candidates scored r=0 because of this, while
    their data-plane probes showed flows dying.
    """
    if entries is None:
        return None
    if not isinstance(entries, list):
        entries = [entries]
    live = [e for e in entries if e.get("protocol") != "kernel"]
    if not live:
        return None
    for e in live:
        if e.get("selected") or e.get("installed"):
            return e
    # no explicit flag: fall back to the FIB's own preference order
    return min(live, key=lambda e: (e.get("distance", 255),
                                    e.get("metric", 10 ** 9)))


def _lpm(rib: Dict, dst: str) -> Optional[Dict]:
    """Longest-prefix match on the INSTALLED route, skipping the kernel default."""
    try:
        ip = ipaddress.ip_address(dst)
    except ValueError:
        return None
    best, blen = None, -1
    for pref, entries in (rib or {}).items():
        try:
            net = ipaddress.ip_network(pref)
        except ValueError:
            continue
        if ip in net and net.prefixlen > blen:
            e = _selected(entries)
            if e is None:
                continue
            best, blen = e, net.prefixlen
    return best


def forwarding_path(ribs: Dict[str, Dict], src: str, dst: str,
                    owner: Dict[str, str], max_hops: int = 16):
    """Walk next-hops from `src` to `dst`. Returns (router sequence, status).

    WHY A PATH AND NOT A COST OR A HOP COUNT

    Two earlier metrics were wrong in opposite directions and both passed the
    gate, which is why this one is computed from the forwarding decision itself.

      * HOP COUNT is sign-inverted here. The backup WAN is one hop and cost 100
        while the primary is three hops and cost 30, so a repair that dumps
        traffic onto the expensive backup -- exactly the P06 violation -- looks
        like a SHORTER path. Six of nine changed flows on C-00039 scored as
        "improved" when they were the harm.
      * OSPF COST is false-positive here. `correct` repairs work by renumbering
        link costs, so the metric to a destination changes while the traffic
        takes the identical route. C-00001 and C-00002 scored 0.083 and 0.292
        when nothing had moved.

    The path is neither. It answers "does traffic still go the same way", which
    needs no judgement about better or worse and cannot be fooled by renumbering.

    ECMP picks the lowest next-hop address so the walk is deterministic. That
    under-reports a candidate that only reshuffles equal-cost members, which is
    the conservative direction: it can miss a change, never invent one.
    """
    cur, seq = src, [src]
    for _ in range(max_hops):
        rib = ribs.get(cur)
        if rib is None:
            return tuple(seq), "NO_RIB"
        e = _lpm(rib, dst)
        if e is None:
            return tuple(seq), "NO_ROUTE"
        nh = e.get("nexthops") or []
        # A discard route has no next-hop IP, exactly like a connected route.
        # Checking "no IP means directly connected" first therefore read every
        # blackhole as successful delivery. Order matters here.
        if any(n.get("blackhole") or n.get("unreachable") or n.get("reject")
               for n in nh):
            return tuple(seq), "BLACKHOLE"
        nhs = sorted(n.get("ip") for n in nh if n.get("ip"))
        if not nhs:
            return tuple(seq), "OK"          # directly connected
        nxt = owner.get(nhs[0])
        if nxt is None:
            return tuple(seq), "UNKNOWN_NH"
        if nxt in seq:
            return tuple(seq + [nxt]), "LOOP"
        seq.append(nxt)
        cur = nxt
    return tuple(seq), "MAX_HOPS"


def ribs_from_state(state: Dict) -> Dict[str, Dict]:
    """`show ip route json` per router, as vtysh already parsed it."""
    out = {}
    for node, s in (state or {}).items():
        r = (s or {}).get("route") or {}
        j = r.get("json")
        if j is None and r.get("stdout"):
            try:
                import json as _j
                j = _j.loads(r["stdout"])
            except Exception:                                      # noqa: BLE001
                j = None
        if j is not None:
            out[node] = j
    return out


def measure_paths(state: Dict, spec, flows: Sequence[Dict]) -> Dict[str, Dict]:
    """Forwarding path for every flow. A host's path starts at its edge router,
    which is the first device that makes a routing decision for it."""
    ribs = ribs_from_state(state)
    owner = owner_map(spec)
    attach = dict(getattr(spec, "hosts", {}) or {})
    out = {}
    for f in flows:
        src = attach.get(f["src_name"], f["src_name"])
        path, term = forwarding_path(ribs, src, f["dst_addr"], owner)
        out[f["flow_id"]] = {"path": list(path), "term": term,
                             "src_router": src}
    return out


def risk(candidate: Dict, golden: Dict) -> Dict:
    """r(x) against the golden baseline: what fraction of flows got worse?

    Denominator is the flows that WORKED on the golden, never the flow count:
    a flow the healthy network cannot carry says nothing about the repair. This
    is the rule the property suite already applies -- a property is in G iff it
    holds on the golden.

    THREE quantities, because Phase 2 showed one is not enough. Measuring only
    connectivity scored 5 of 12 candidates at exactly 0.0 -- identical to a
    perfectly safe repair -- because their damage was P06/P08: traffic still
    arrives, it just takes the backup path. That is 42 of the 79 harmful
    candidates in the corpus. A ruler that reads "no harm" on 53% of the harm
    is the wrong ruler.

        broken   -- the flow stopped working, or its route vanished/looped
        rerouted -- the flow still works but takes a DIFFERENT forwarding path

    Path comparison, not hop count and not OSPF cost. Both of those were tried
    and both were wrong in opposite directions -- see forwarding_path(). TTL is
    still recorded per flow as diagnostic evidence, but no longer decides
    anything.

    `undeterminable` counts flows where either side errored or whose path could
    not be reconstructed.
    They are reported, never silently treated as healthy, and they bound r the
    way Manski bounds the harm rate.
    """
    g, c = golden.get("flows", {}), candidate.get("flows", {})
    gp, cp = golden.get("paths", {}) or {}, candidate.get("paths", {}) or {}
    UNDET_TERMS = ("NO_RIB", "UNKNOWN_NH", "MAX_HOPS")
    BROKEN_TERMS = ("NO_ROUTE", "LOOP", "BLACKHOLE")
    base, broken, rerouted, undet = [], [], [], []
    for fid, gv in g.items():
        if gv.get("reachable") is not True:
            continue                      # not carried by the healthy network
        base.append(fid)
        cv = c.get(fid)
        gpath, cpath = gp.get(fid), cp.get(fid)
        if (cv is None or cv.get("reachable") is None or cpath is None
                or gpath is None or cpath["term"] in UNDET_TERMS
                or gpath["term"] in UNDET_TERMS):
            undet.append(fid)
        elif cv.get("reachable") is False or cpath["term"] in BROKEN_TERMS:
            broken.append(fid)
        elif (cpath["path"], cpath["term"]) != (gpath["path"], gpath["term"]):
            rerouted.append(fid)
    n = len(base)
    dec = n - len(undet)
    hurt = len(broken) + len(rerouted)

    def frac(k):
        return round(k / dec, 6) if dec else None

    return {
        "n_golden_flows": n,
        "n_broken": len(broken),
        "n_rerouted": len(rerouted),
        "n_undeterminable": len(undet),
        "n_decidable": dec,
        # PRIMARY: the blast radius -- flows whose forwarding changed at all
        "risk_r": frac(hurt),
        # the severity split. broken is model-vs-device divergence; rerouted is
        # a policy change a wider specification could have caught. Reporting
        # one number would let a reviewer conflate the two contributions.
        "risk_r_broken": frac(len(broken)),
        "risk_r_rerouted": frac(len(rerouted)),
        "risk_r_min": round(hurt / n, 6) if n else None,
        "risk_r_max": round((hurt + len(undet)) / n, 6) if n else None,
        "broken_flows": sorted(broken),
        "rerouted_flows": sorted(rerouted),
    }


def install(get_plan, sink: Dict, rp3) -> None:
    """Measure flows immediately after the frozen property measurement.

    Patches the module attribute run_phase3 resolves at call time, so run_one
    is untouched and v1.1.0 is still produced by the code that produced the
    frozen corpus. The flow matrix is recorded alongside it, never instead.
    """
    if getattr(rp3.measure_all, "_flow_wrapped", False):
        return
    original = rp3.measure_all

    def wrapped(lab, state, scenario=None, spec=None):
        res = original(lab, state, scenario, spec)
        plan = get_plan()
        if plan:
            try:
                fmx = measure_flows(lab, plan)
                # paths come from `state`, which vtysh already parsed -- no
                # extra probe, no disk read, and the same RIB the property
                # measurement just used
                fmx["paths"] = measure_paths(state, spec, plan)
                sink["flowmatrix"] = fmx
            except Exception as exc:                               # noqa: BLE001
                sink["flowmatrix"] = {"error": f"{type(exc).__name__}: {exc}",
                                      "flows": {}, "paths": {},
                                      "n_flows": len(plan)}
        return res

    wrapped._flow_wrapped = True                                   # noqa: SLF001
    wrapped._original = original                                   # noqa: SLF001
    rp3.measure_all = wrapped


def uninstall(rp3) -> None:
    fn = rp3.measure_all
    if getattr(fn, "_flow_wrapped", False):
        rp3.measure_all = fn._original                             # noqa: SLF001
