"""
MODULE 5 -- routing analysis: static, OSPF, BGP, best-route selection, LPM.

Three snapshots, one topology:

  m03-trio-static  every route typed by hand
  m05-trio-ospf    one area, link-state, cost-based
  m05-trio-bgp     three autonomous systems, path-vector

The point is not that Batfish can list routes. The point is that you can see
exactly WHY each route won, and that the reason differs per protocol.

    python m05_routing_analysis.py
"""

from __future__ import annotations

import sys

from bf_common import bf_session, load, sanity, banner, show, Checks

SRV_NET = "192.168.3.0/24"


def main() -> int:
    c = Checks("MODULE 5 -- routing analysis")
    bf = bf_session()

    # =================================================================
    banner("5.1  STATIC ROUTING")
    load(bf, "m03-trio-static")
    sanity(bf, strict=False)
    st = show("r1 routes, static only",
              bf.q.routes(nodes="r1", protocols="static").answer().frame())
    c.check("r1 has four static routes", len(st) == 4, f"got {len(st)}")
    c.check("static admin distance is 1",
            len(st) > 0 and set(st["Admin_Distance"]) == {1},
            f"got {set(st['Admin_Distance']) if len(st) else 'none'}")
    print()
    print("Why: 'ip route A B C' is an instruction, not a negotiation. Admin distance")
    print("1 is the IOS default and it beats every dynamic protocol. A static route")
    print("survives the failure of the thing it points at -- which is exactly how a")
    print("blackhole is born. Module 6 builds one.")

    # =================================================================
    banner("5.2  OSPF -- link-state, cost-based")
    load(bf, "m05-trio-ospf")
    sanity(bf, strict=False)

    print("First: are the OSPF adjacencies even compatible? This needs the control")
    print("plane, so Batfish computes it now.")
    bf.generate_dataplane()
    ospf_sess = show("ospfSessionCompatibility",
                     bf.q.ospfSessionCompatibility().answer().frame())
    # Batfish reports one row per directed interface pair, so a two-link network
    # yields more rows than links. Assert on the node pairs, not on the row count.
    pairs = {frozenset((str(r["Interface"]).split("[")[0],
                        str(r["Remote_Interface"]).split("[")[0]))
             for _, r in ospf_sess.iterrows()} if len(ospf_sess) else set()
    print(f"OSPF adjacent node pairs: {[sorted(p) for p in pairs]}")
    c.check("OSPF adjacencies are exactly r1-r2 and r2-r3",
            pairs == {frozenset(("r1", "r2")), frozenset(("r2", "r3"))},
            f"got {[sorted(p) for p in pairs]}")
    if len(ospf_sess):
        c.check("every OSPF session is ESTABLISHED",
                all(str(s) == "ESTABLISHED" for s in ospf_sess["Session_Status"]),
                f"statuses: {list(ospf_sess['Session_Status'])}")

    ospf_routes = show("r1 routes, OSPF only",
                       bf.q.routes(nodes="r1", protocols="ospf").answer().frame())
    c.check("r1 learned the server LAN via OSPF",
            SRV_NET in set(ospf_routes["Network"]),
            f"OSPF networks on r1: {set(ospf_routes['Network'])}")
    srv = ospf_routes[ospf_routes["Network"] == SRV_NET]
    if len(srv):
        c.check("OSPF admin distance is 110",
                int(srv.iloc[0]["Admin_Distance"]) == 110,
                f"got {srv.iloc[0]['Admin_Distance']}")
        print()
        print(f"Metric on r1 for {SRV_NET}: {srv.iloc[0]['Metric']}")
        print("Why: OSPF cost on a Cisco IOS GigabitEthernet defaults to 1 (reference")
        print("bandwidth 100 Mbps / 1000 Mbps, floored at 1). Two transit links plus")
        print("the cost of the destination link gives the metric you see. Nobody typed")
        print("this route anywhere -- r3 flooded a link-state advertisement, r1 ran")
        print("Dijkstra over the resulting graph, and this fell out.")

    # =================================================================
    banner("5.3  BGP -- path vector across three autonomous systems")
    load(bf, "m05-trio-bgp")
    sanity(bf, strict=False)
    bf.generate_dataplane()

    compat = show("bgpSessionCompatibility",
                  bf.q.bgpSessionCompatibility().answer().frame())
    c.check("four BGP session rows (two sessions, both directions)",
            len(compat) == 4, f"got {len(compat)}")
    if len(compat):
        c.check("every BGP session is compatible (UNIQUE_MATCH)",
                all("UNIQUE_MATCH" in str(s) for s in compat["Configured_Status"]),
                f"statuses: {list(compat['Configured_Status'])}")

    status = show("bgpSessionStatus", bf.q.bgpSessionStatus().answer().frame())
    if len(status):
        c.check("every BGP session actually establishes",
                all(str(s) == "ESTABLISHED" for s in status["Established_Status"]),
                f"statuses: {list(status['Established_Status'])}")

    bgp_routes = show("r1 routes, BGP only",
                      bf.q.routes(nodes="r1", protocols="bgp").answer().frame())
    c.check("r1 learned the server LAN via BGP",
            SRV_NET in set(bgp_routes["Network"]),
            f"BGP networks on r1: {set(bgp_routes['Network'])}")
    print()
    print("The BGP RIB, with attributes -- this is where 'why did this route win?'")
    print("actually gets answered:")
    bgp_rib = show("bgpRib on r1", bf.q.bgpRib(nodes="r1").answer().frame())
    if len(bgp_rib):
        srv_rib = bgp_rib[bgp_rib["Network"] == SRV_NET]
        if len(srv_rib):
            print()
            print(f"AS path to {SRV_NET} as seen by r1: "
                  f"{srv_rib.iloc[0]['AS_Path']}")
            print("Why: r3 originated it in AS 65003, r2 prepended 65002 crossing the")
            print("eBGP boundary, so r1 sees 65002 65003. eBGP admin distance is 20,")
            print("which beats OSPF's 110 -- if both protocols carried this prefix,")
            print("BGP would win on r1 before metrics were even compared.")

    # =================================================================
    banner("5.4  BEST-ROUTE SELECTION -- the order of the tie-breakers")
    print("A router picks a route in this order, and stops at the first difference:")
    print("  1. longest prefix match     <- decided FIRST, before anything else")
    print("  2. lowest administrative distance   (connected 0, static 1, eBGP 20,")
    print("                                       OSPF 110, RIP 120, iBGP 200)")
    print("  3. lowest protocol metric   (OSPF cost, or the BGP decision process)")
    print()
    print("The most common misconception is that admin distance is compared first.")
    print("It is not. A /32 static route and a /8 OSPF route are never compared at")
    print("all -- they match different packets.")

    # =================================================================
    banner("5.5  LONGEST PREFIX MATCH, demonstrated")
    load(bf, "m03-trio-static")
    for ip in ("192.168.3.10", "10.0.0.3", "8.8.8.8"):
        lpm = bf.q.lpmRoutes(ip=ip, nodes="r1").answer().frame()
        show(f"lpmRoutes on r1 for {ip}", lpm)
        if ip == "8.8.8.8":
            c.check("r1 has no route to 8.8.8.8", len(lpm) == 0,
                    "there is no default route anywhere in this snapshot")
        else:
            c.check(f"r1 has exactly one best route for {ip}", len(lpm) == 1,
                    f"got {len(lpm)}")
    print()
    print("Why: lpmRoutes answers 'which RIB entry would this exact destination")
    print("address select?' -- the same computation the forwarding chip does. Zero")
    print("rows for 8.8.8.8 is not an error. It is the fact that a packet to 8.8.8.8")
    print("is dropped at r1 with disposition NO_ROUTE.")

    # =================================================================
    banner("5.6  ROUTE CHANGES -- diffing two snapshots")
    print("This is the most useful question in Batfish for change review: given two")
    print("snapshots, which routes appeared, disappeared, or changed?")
    diff = bf.q.routes().answer(snapshot="m05-trio-ospf",
                                reference_snapshot="m03-trio-static").frame()
    show("routes: OSPF snapshot vs static snapshot", diff, max_rows=30)
    c.check("switching from static to OSPF changes the RIB", len(diff) > 0,
            "if this is zero the two snapshots are identical, which they are not")
    print()
    print("Read the KeyPresence / diff columns: '+' rows exist only in the OSPF")
    print("snapshot, '-' rows only in the static one. The prefixes are largely the")
    print("same; the Protocol, Metric and Admin_Distance columns are what moved.")
    print("Same reachability, completely different failure behaviour.")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
