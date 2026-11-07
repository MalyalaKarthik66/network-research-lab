"""
MODULE 4 -- basic verification: asking questions and reading the answers.

Topology (snapshot m03-trio-static, static routing only):

  192.168.1.0/24        10.1.12.0/30          10.1.23.0/30        192.168.3.0/24
   PC LAN --- Gi0/1 [r1] Gi0/0 ---- Gi0/0 [r2] Gi0/1 ---- Gi0/0 [r3] Gi0/1 --- SERVER LAN
                lo0 10.0.0.1        lo0 10.0.0.2        lo0 10.0.0.3

Five verification families, each with: the question, the answer, and why.

    python m04_basic_verification.py
"""

from __future__ import annotations

import sys

from pybatfish.datamodel import HeaderConstraints, PathConstraints

from bf_common import bf_session, load, sanity, banner, show, Checks, dispositions

PC = "192.168.1.10"
SRV = "192.168.3.10"


def main() -> int:
    c = Checks("MODULE 4 -- basic verification")
    bf = bf_session()
    load(bf, "m03-trio-static")
    if not sanity(bf):
        print("Refusing to continue: the snapshot did not parse cleanly.")
        return 1

    # ------------------------------------------------------------------
    banner("4.1  INTERFACE STATUS -- 'is anything administratively down?'")
    print("Question asked : for every interface, is it active, and what address does")
    print("                 it carry?")
    print("Why it matters : a shut interface is the cheapest possible cause of an")
    print("                 outage and the easiest to miss in a 4000-line config.")
    ifaces = show("interfaceProperties", bf.q.interfaceProperties(
        properties="Active,All_Prefixes,Description").answer().frame())
    down = ifaces[~ifaces["Active"]]
    c.check("no interface is administratively down", len(down) == 0,
            f"down: {list(down['Interface']) if len(down) else []}")
    print()
    print("Why this answer: Batfish marks an interface inactive when the config")
    print("contains 'shutdown', or when the interface is referenced but never")
    print("defined. It has NO idea whether a cable is plugged in -- there is no")
    print("cable in a text file.")

    # ------------------------------------------------------------------
    banner("4.2  ROUTING TABLES -- 'what does each router believe?'")
    print("Question asked : show the RIB of each device.")
    print("Why it matters : the RIB is the output of the control plane. Everything")
    print("                 downstream -- forwarding, reachability -- is derived")
    print("                 from it. If the RIB is wrong, nothing else can be right.")
    r1_routes = show("routes on r1", bf.q.routes(nodes="r1").answer().frame())

    to_srv = r1_routes[r1_routes["Network"] == "192.168.3.0/24"]
    c.check("r1 has a route to the server LAN", len(to_srv) == 1,
            f"got {len(to_srv)} rows")
    if len(to_srv) == 1:
        row = to_srv.iloc[0]
        c.check("that route is a static route", str(row["Protocol"]) == "static",
                f"protocol was {row['Protocol']}")
        c.check("its next hop is r2 at 10.1.12.2",
                str(row["Next_Hop_IP"]) == "10.1.12.2",
                f"next hop was {row['Next_Hop_IP']}")
    print()
    print("Why this answer: nothing in this snapshot runs a routing protocol. Every")
    print("non-connected route came from an explicit 'ip route' line. Batfish read")
    print("those lines, installed them, and resolved each next hop against the")
    print("connected routes. Admin distance 1 is the IOS default for a static route.")

    print()
    print("Protocol mix across the whole network:")
    all_routes = bf.q.routes().answer().frame()
    print(all_routes["Protocol"].value_counts().to_string())
    c.check("no OSPF or BGP routes exist in this snapshot",
            not any(p in set(all_routes["Protocol"]) for p in ("ospf", "bgp")),
            f"found protocols: {set(all_routes['Protocol'])}")

    # ------------------------------------------------------------------
    banner("4.3  NEIGHBOUR DISCOVERY -- 'who is adjacent to whom?'")
    print("Question asked : which layer-3 interfaces can see each other?")
    edges = show("layer3Edges", bf.q.layer3Edges().answer().frame())
    pairs = {(str(r["Interface"]).split("[")[0], str(r["Remote_Interface"]).split("[")[0])
             for _, r in edges.iterrows()}
    c.check("r1 and r2 are adjacent", ("r1", "r2") in pairs, f"pairs: {pairs}")
    c.check("r2 and r3 are adjacent", ("r2", "r3") in pairs, f"pairs: {pairs}")
    c.check("r1 and r3 are NOT adjacent", ("r1", "r3") not in pairs,
            "they are two hops apart; a direct edge would mean the model is wrong")
    print()
    print("Why this answer: no layer-1 file is present, so adjacency was inferred")
    print("from subnet overlap. 10.1.12.1/30 and 10.1.12.2/30 share a subnet, so")
    print("Batfish assumes a wire. The PC LAN and SERVER LAN interfaces have no")
    print("partner and therefore no edge -- which is correct here, and is also why")
    print("packets to those subnets get the disposition DELIVERED_TO_SUBNET below.")

    # ------------------------------------------------------------------
    banner("4.4  FORWARDING -- 'trace one specific packet'")
    print("Question asked : a TCP packet from 192.168.1.10 to 192.168.3.10 port 443")
    print("                 enters r1 on Gi0/1. Where does it end up?")
    print("Why it matters : the RIB says what a router believes; a trace says what")
    print("                 actually happens to a packet, hop by hop, including")
    print("                 every filter it passes through.")
    tr = bf.q.traceroute(
        startLocation="@enter(r1[GigabitEthernet0/1])",
        headers=HeaderConstraints(srcIps=PC, dstIps=SRV,
                                  applications="HTTPS"),
    ).answer().frame()
    show("traceroute r1 -> server LAN", tr)

    print()
    print("Full hop-by-hop detail of the first trace:")
    for i, trace in enumerate(tr.iloc[0]["Traces"]):
        print(f"  trace {i}: disposition = {trace.disposition}")
        for hop in trace.hops:
            print(f"    hop: {hop.node}")
            for step in hop.steps:
                print(f"      {type(step).__name__:22s} {step.action}")

    d = dispositions(tr)
    c.check("the packet is delivered", len(d) > 0 and all(
        x in ("DELIVERED_TO_SUBNET", "EXITS_NETWORK", "ACCEPTED") for x in d),
            f"dispositions were {d}")
    c.check("the path is exactly three hops (r1, r2, r3)",
            len(tr.iloc[0]["Traces"][0].hops) == 3,
            f"hops: {[h.node for h in tr.iloc[0]['Traces'][0].hops]}")
    print()
    print("Why this answer: r1 matched 192.168.3.0/24 -> 10.1.12.2, resolved that to")
    print("Gi0/0, and forwarded. r2 and r3 did the same. At r3 the destination is in")
    print("a directly connected subnet with no device owning .10, so Batfish stops")
    print("with DELIVERED_TO_SUBNET: 'I handed it to the wire, what happens next is")
    print("outside my model.' It did not ping anything. There is no server.")

    # ------------------------------------------------------------------
    banner("4.5  REACHABILITY -- 'search over ALL packets, not one'")
    print("Question asked : does there EXIST any packet from the PC LAN that fails")
    print("                 to reach the server LAN?")
    print("Why it matters : traceroute checks one flow. reachability is a symbolic")
    print("                 search over the whole header space at once. This is the")
    print("                 difference between testing and verification.")
    fail = bf.q.reachability(
        pathConstraints=PathConstraints(startLocation="@enter(r1[GigabitEthernet0/1])"),
        headers=HeaderConstraints(srcIps="192.168.1.0/24", dstIps="192.168.3.0/24"),
        actions="FAILURE",
    ).answer().frame()
    show("reachability: counterexamples where delivery FAILS", fail)
    c.check("no failing flow exists from the PC LAN to the server LAN",
            len(fail) == 0, f"{len(fail)} counterexample(s) found")

    ok = bf.q.reachability(
        pathConstraints=PathConstraints(startLocation="@enter(r1[GigabitEthernet0/1])"),
        headers=HeaderConstraints(srcIps="192.168.1.0/24", dstIps="192.168.3.0/24"),
        actions="SUCCESS",
    ).answer().frame()
    show("reachability: an example of a SUCCEEDING flow", ok)
    c.check("at least one succeeding flow exists", len(ok) > 0)

    print()
    print("Why this answer: 'FAILURE returned zero rows' is the strong result. It is")
    print("not a sample -- Batfish encoded the forwarding behaviour of the whole")
    print("network as a formula and proved no satisfying assignment exists in that")
    print("header space. That is a proof, for that question, over that model.")
    print()
    print("Read the previous sentence twice. 'For that question' and 'over that")
    print("model' are where Modules 8 and 10 live.")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
