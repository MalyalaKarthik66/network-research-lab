"""
MODULE 6 -- forwarding analysis: what actually happens to a packet.

Routing (Module 5) is what each router BELIEVES. Forwarding is what a packet
EXPERIENCES. They come apart more often than you would expect, and every way
they come apart has a name in Batfish's vocabulary of dispositions:

  ACCEPTED             the destination address is owned by a device in the model
  DELIVERED_TO_SUBNET  handed to a connected subnet with no modelled device on it
  EXITS_NETWORK        forwarded out of an interface that leads outside the model
  NO_ROUTE             no RIB entry matched -- dropped
  NULL_ROUTED          matched a route pointing at Null0 -- deliberately dropped
  DENIED_IN            an inbound ACL dropped it
  DENIED_OUT           an outbound ACL dropped it
  LOOP                 the packet revisited a hop
  INSUFFICIENT_INFO    Batfish cannot decide (usually a modelling gap)
  NEIGHBOR_UNREACHABLE next hop did not resolve to a reachable neighbour

The first three are successes. Everything else is a failure, and you need to be
able to tell them apart on sight, because they have completely different causes.

    python m06_forwarding_analysis.py
"""

from __future__ import annotations

import sys
from collections import Counter

from pybatfish.datamodel import HeaderConstraints, PathConstraints

from bf_common import bf_session, load, sanity, banner, show, Checks, dispositions

PC_IF = "@enter(r1[GigabitEthernet0/1])"
PC = "192.168.1.10"
SRV = "192.168.3.10"


def trace(bf, dst, src=PC, app=None, start=PC_IF):
    hdr = HeaderConstraints(srcIps=src, dstIps=dst)
    if app:
        hdr = HeaderConstraints(srcIps=src, dstIps=dst, applications=app)
    return bf.q.traceroute(startLocation=start, headers=hdr).answer().frame()


def print_traces(frame) -> None:
    if frame is None or len(frame) == 0:
        print("(no traces)")
        return
    for _, row in frame.iterrows():
        for i, tr in enumerate(row["Traces"]):
            path = " -> ".join(h.node for h in tr.hops)
            print(f"  [{tr.disposition:20s}] {path}")


def main() -> int:
    c = Checks("MODULE 6 -- forwarding analysis")
    bf = bf_session()

    # =================================================================
    banner("6.1  THE NORMAL CASE -- next-hop resolution, hop by hop")
    load(bf, "m05-trio-ospf")
    sanity(bf, strict=False)
    bf.generate_dataplane()
    tr = trace(bf, SRV, app="HTTPS")
    show("traceroute PC -> server, OSPF snapshot", tr)
    print_traces(tr)
    d = dispositions(tr)
    c.check("delivered", all(x in ("DELIVERED_TO_SUBNET", "EXITS_NETWORK",
                                   "ACCEPTED") for x in d) and len(d) > 0,
            f"dispositions {d}")
    c.check("single path", len(d) == 1, f"{len(d)} paths")
    print()
    print("Next-hop resolution is recursive. r1's RIB says 'via 10.1.12.2'. That is")
    print("an IP, not an exit port. r1 must look 10.1.12.2 up again, find it in the")
    print("connected route 10.1.12.0/30 on Gi0/0, and only then does it have an")
    print("egress interface. Batfish performs that recursion. A next hop that does")
    print("not resolve produces a route that exists in the RIB but forwards nothing.")

    # =================================================================
    banner("6.2  ECMP -- one destination, two equally good paths")
    load(bf, "m06-trio-ecmp")
    sanity(bf, strict=False)
    bf.generate_dataplane()

    ecmp_routes = show("r1 routes to the server LAN (ECMP snapshot)",
                       bf.q.routes(nodes="r1", network="192.168.3.0/24")
                       .answer().frame())
    c.check("two equal-cost RIB entries for the same prefix",
            len(ecmp_routes) == 2, f"got {len(ecmp_routes)}")
    if len(ecmp_routes) == 2:
        c.check("both entries have the same OSPF metric",
                len(set(ecmp_routes["Metric"])) == 1,
                f"metrics {list(ecmp_routes['Metric'])}")
        c.check("they leave by different interfaces",
                len(set(ecmp_routes["Next_Hop_Interface"])) == 2,
                f"interfaces {list(ecmp_routes['Next_Hop_Interface'])}")

    tr = trace(bf, SRV, app="HTTPS")
    show("traceroute across ECMP", tr)
    print_traces(tr)
    c.check("Batfish enumerates BOTH paths, not one",
            len(dispositions(tr)) == 2, f"{len(dispositions(tr))} traces")
    print()
    print("This is a genuine strength and a genuine limitation at the same time.")
    print()
    print("Strength : a real traceroute picks one path, determined by a hash of the")
    print("           five-tuple. You could run it a hundred times and never see the")
    print("           broken path. Batfish shows you every path, always.")
    print("Limitation: Batfish does not model the hash. It cannot tell you WHICH")
    print("           path YOUR flow takes on real hardware, only that both are")
    print("           possible. If one path is broken and the other is not, Batfish")
    print("           reports 'multipath inconsistency' -- it will not tell you the")
    print("           probability that a given customer is affected.")

    print()
    incons = show("multipathConsistency -- flows treated differently by different paths",
                  bf.q.multipathConsistency().answer().frame())
    c.check("no multipath inconsistency in the healthy ECMP snapshot",
            len(incons) == 0, f"{len(incons)} inconsistent flow(s)")

    loops = show("detectLoops", bf.q.detectLoops().answer().frame())
    c.check("no forwarding loops", len(loops) == 0, f"{len(loops)} loop(s)")

    # =================================================================
    banner("6.3  BLACKHOLE -- the route exists, the packet dies")
    load(bf, "m06-trio-blackhole")
    sanity(bf, strict=False)
    bf.generate_dataplane()

    print("r2 carries one extra line compared with m05-trio-ospf:")
    print("    ip route 192.168.3.0 255.255.255.0 Null0")
    print()
    print("Static admin distance 1 beats OSPF's 110, so this route WINS on r2 even")
    print("though OSPF is working perfectly and offers a correct alternative.")
    r2_srv = show("r2's best route to the server LAN",
                  bf.q.routes(nodes="r2", network="192.168.3.0/24").answer().frame())
    c.check("only the static Null0 route is installed on r2",
            len(r2_srv) == 1 and str(r2_srv.iloc[0]["Protocol"]) == "static",
            f"got {list(r2_srv['Protocol']) if len(r2_srv) else 'nothing'}")

    print()
    print("Note carefully: r1's RIB is unchanged and still looks perfectly healthy.")
    r1_srv = show("r1's route to the server LAN -- still an ordinary OSPF route",
                  bf.q.routes(nodes="r1", network="192.168.3.0/24").answer().frame())
    c.check("r1 still believes it has a working OSPF route",
            len(r1_srv) == 1 and str(r1_srv.iloc[0]["Protocol"]) == "ospf",
            f"got {list(r1_srv['Protocol']) if len(r1_srv) else 'nothing'}")

    tr = trace(bf, SRV, app="HTTPS")
    show("traceroute into the blackhole", tr)
    print_traces(tr)
    d = dispositions(tr)
    c.check("the packet is NULL_ROUTED", d == ["NULL_ROUTED"], f"got {d}")
    print()
    print("This is the whole reason forwarding analysis exists as a separate step.")
    print("Checking every RIB device-by-device would have found nothing wrong on r1.")
    print("Only following the packet across devices exposes it.")

    # =================================================================
    banner("6.4  NO ROUTE -- the plain drop")
    load(bf, "m03-trio-static")
    bf.generate_dataplane()
    tr = trace(bf, "8.8.8.8")
    show("traceroute to an address nobody has a route for", tr)
    print_traces(tr)
    d = dispositions(tr)
    c.check("disposition is NO_ROUTE", d == ["NO_ROUTE"], f"got {d}")
    print()
    print("NO_ROUTE and NULL_ROUTED look identical from a user's chair -- the packet")
    print("vanished. They are completely different bugs. NO_ROUTE means someone")
    print("forgot to configure something. NULL_ROUTED means someone configured a")
    print("drop on purpose, or made a typo that created one.")

    # =================================================================
    banner("6.5  SUMMARY -- disposition census across every snapshot so far")
    census = Counter()
    for snap in ("m03-trio-static", "m05-trio-ospf",
                 "m06-trio-ecmp", "m06-trio-blackhole"):
        load(bf, snap)
        bf.generate_dataplane()
        for x in dispositions(trace(bf, SRV, app="HTTPS")):
            census[(snap, x)] += 1
    for (snap, disp), n in sorted(census.items()):
        print(f"  {snap:22s} {disp:22s} x{n}")
    c.check("four snapshots produced at least three distinct dispositions",
            len({k[1] for k in census}) >= 3,
            f"saw {sorted({k[1] for k in census})}")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
