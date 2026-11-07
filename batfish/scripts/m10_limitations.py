"""
MODULE 10 -- what Batfish cannot do, demonstrated rather than asserted.

Everything up to here made Batfish look powerful, because it is. This module
exists to make the boundary of that power precise, because a verifier you trust
past its boundary is more dangerous than no verifier at all.

The one sentence to remember:

    Batfish is SOUND with respect to the question you asked and the model it
    builds. It is not, and does not claim to be, a model of your network.

That sentence has three load-bearing parts, and each one is a demonstration
below:

  10.1  "the question you asked"  -- specification incompleteness
  10.2  "the model it builds"     -- model scope: converged steady state only
  10.3  "the model it builds"     -- model versus device

Run it, then read section 10.5 and write your own version of it in your Phase 1
report. If you can write that section in your own words, Phase 1 is complete.

    python m10_limitations.py
"""

from __future__ import annotations

import sys

from pybatfish.datamodel import HeaderConstraints, PathConstraints

from bf_common import bf_session, load, banner, show, Checks, dispositions

PC_IF = "@enter(r1[GigabitEthernet0/1])"


def main() -> int:
    c = Checks("MODULE 10 -- limitations")
    bf = bf_session()

    # =================================================================
    banner("10.1  BATFISH ANSWERS THE QUESTION YOU ASKED, AND ONLY THAT ONE")
    load(bf, "m09-corp-link-down")
    bf.generate_dataplane()

    print("Suppose the operator's acceptance test is the obvious one:")
    print("   'can the PC LAN reach the server LAN?'")
    print("and, as is extremely common, 'reach' is tested with ICMP.")
    icmp = bf.q.reachability(
        pathConstraints=PathConstraints(startLocation=PC_IF),
        headers=HeaderConstraints(srcIps="192.168.10.0/24",
                                  dstIps="192.168.20.0/24",
                                  applications="ICMP_ECHO_REQUEST"),
        actions="SUCCESS",
    ).answer().frame()
    show("reachability, ICMP only", icmp)
    c.check("the ICMP-only acceptance test PASSES on the broken network",
            len(icmp) > 0,
            "if this fails, the demonstration below does not hold")

    https = bf.q.reachability(
        pathConstraints=PathConstraints(startLocation=PC_IF),
        headers=HeaderConstraints(srcIps="192.168.10.0/24",
                                  dstIps="192.168.20.0/24",
                                  applications="HTTPS"),
        actions="SUCCESS",
    ).answer().frame()
    c.check("meanwhile HTTPS is completely broken", len(https) == 0,
            f"{len(https)} HTTPS flow(s) succeed")

    print()
    print("Batfish was not wrong. It was never asked. The verifier proved exactly")
    print("what it was told to prove, soundly, and the network is still down for")
    print("every user of the application that actually matters.")
    print()
    print("Say this out loud, because it is the thing most people get backwards:")
    print("  the failure is in the SPECIFICATION, not in the verifier.")
    print()
    print("No amount of improving Batfish fixes this. The missing piece is a")
    print("property nobody wrote down. Real outages are routinely caused this way.")

    # =================================================================
    banner("10.2  BATFISH MODELS THE CONVERGED STEADY STATE, AND NOTHING ELSE")
    print("m09-corp-base and m09-corp-link-down are two static pictures: 'before'")
    print("and 'after, once everything has settled'. Batfish can compare them.")
    print()
    print("What lives between them, and what Batfish has no representation of:")
    print("  * OSPF dead-interval expiry, typically 40 seconds on a real link")
    print("  * LSA flooding across the area")
    print("  * every router re-running Dijkstra, at slightly different moments")
    print("  * FIB reprogramming, which lags the RIB")
    print("  * micro-loops while some routers have the new topology and some the old")
    print("  * BGP session teardown, hold timers, and route withdrawal propagation")
    print()
    print("For those 5 to 60 seconds packets are dropped and looped. A change can")
    print("be provably correct in both the before state and the after state and")
    print("still cause a real, user-visible, ticket-generating outage in between.")
    print()
    print("This is not a bug. It is a deliberate scope decision -- modelling time")
    print("is what makes verification tractable to skip. But it means 'Batfish says")
    print("the change is safe' and 'the change is safe' are different sentences.")
    print()
    print("There is no query that demonstrates this, and that absence IS the")
    print("demonstration. Try to think of one before moving on.")
    c.check("you have accepted that no query here can show a transient", True)

    # =================================================================
    banner("10.3  THE MODEL IS NOT THE DEVICE -- a demonstration you can check")
    print("m10-acl-blocks-ospf is m05-trio-ospf with SERVER_PROTECT applied INBOUND")
    print("on r3's transit interface Gi0/0 instead of outbound on the LAN side:")
    print()
    print("   interface GigabitEthernet0/0        <- faces r2")
    print("    ip access-group SERVER_PROTECT in")
    print("   ...")
    print("    permit tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq www")
    print("    permit tcp ... eq 443")
    print("    permit icmp ...")
    print("    deny   ip any any                  <- denies IP protocol 89")
    print()
    print("On a real Cisco router this breaks OSPF. Hellos are IP protocol 89 to")
    print("224.0.0.5, they arrive inbound on Gi0/0, and 'deny ip any any' eats them.")
    print("The adjacency drops within the dead interval and r3 loses every route.")
    print()
    print("Ask Batfish what it thinks.")

    load(bf, "m05-trio-ospf")
    bf.generate_dataplane()
    base = bf.q.ospfSessionCompatibility().answer().frame()
    base_pairs = {(frozenset((str(r["Interface"]).split("[")[0],
                              str(r["Remote_Interface"]).split("[")[0])),
                   str(r["Session_Status"])) for _, r in base.iterrows()}

    load(bf, "m10-acl-blocks-ospf")
    bf.generate_dataplane()
    acl = show("ospfSessionCompatibility WITH the deny-all inbound ACL",
               bf.q.ospfSessionCompatibility().answer().frame())
    acl_pairs = {(frozenset((str(r["Interface"]).split("[")[0],
                             str(r["Remote_Interface"]).split("[")[0])),
                  str(r["Session_Status"])) for _, r in acl.iterrows()}

    print()
    print(f"without the ACL: {sorted((tuple(sorted(p)), s) for p, s in base_pairs)}")
    print(f"with    the ACL: {sorted((tuple(sorted(p)), s) for p, s in acl_pairs)}")
    c.check("Batfish's OSPF verdict is IDENTICAL with and without the ACL",
            base_pairs == acl_pairs,
            "if these differ, Batfish has started modelling control-plane "
            "filtering and this demonstration needs rewriting -- which would be "
            "an excellent surprises.md entry")

    r3_routes = bf.q.routes(nodes="r3", protocols="ospf").answer().frame()
    show("r3's OSPF routes, according to Batfish", r3_routes)
    c.check("Batfish still believes r3 has learned routes via OSPF",
            len(r3_routes) > 0,
            "on real hardware this table would be empty")

    print()
    print("Batfish's control-plane simulation checks configuration compatibility --")
    print("area, network type, MTU, timers, subnet. It does not run the packets that")
    print("build an adjacency through the data-plane filters. So it reports a")
    print("healthy network that would be entirely down in reality.")
    print()
    print("Note the direction of the error. Batfish is OPTIMISTIC here. It says")
    print("'fine' about something that is broken. That direction is the dangerous")
    print("one, and it is a property of the model boundary, not of a defect.")
    print()
    print("You will be able to check this claim yourself in the emulated lab later.")
    print("Do check it. Do not take this script's word for it.")

    # =================================================================
    banner("10.4  THE COMPLETE INVENTORY")
    print("""
WHAT BATFISH CAN DO -- and does soundly

  * Parse many vendors into one common model, and tell you what it could not
    parse (fileParseStatus, parseWarning)
  * Find dangling and orphaned names             (undefinedReferences,
                                                  unusedStructures)
  * Simulate OSPF/BGP/static to convergence and give you every RIB
  * Prove a filter line can never match          (filterLineReachability)
  * Search the whole header space for a counterexample, not sample it
                                                  (reachability, searchFilters)
  * Enumerate EVERY ECMP path, including ones a real traceroute would never show
  * Diff two snapshots and report exactly which flows changed fate
                                                  (differentialReachability)
  * Do all of the above in seconds, with no hardware, from text files

WHAT BATFISH CANNOT DO -- three distinct categories, do not blur them

  A. OUT OF SCOPE BY DESIGN -- the model deliberately excludes these
     * time: convergence, micro-loops, timer expiry, flap
     * traffic: it never sends a packet; every result is derived symbolically
     * telemetry: CPU, memory, latency, jitter, loss, queue depth, optic power
       are not inputs and cannot be outputs
     * anything that is not expressible as a configuration diff. "High CPU on
       the core switch" has no representation in a text file

  B. MODEL VERSUS DEVICE -- the model is an abstraction of the device
     * ECMP hashing: it enumerates paths, it does not predict which one a flow
       takes
     * hardware limits: TCAM exhaustion, ACL compilation failure, line-card
       differences
     * platform quirks, bugs, and version-specific behaviour
     * control-plane policing and protocol packets crossing data-plane filters
       (section 10.3)
     * partial grammar coverage: any line in parseWarning is a piece of your
       intent that the model does not contain

  C. SPECIFICATION INCOMPLETENESS -- the model is fine, the question was not
     * it proves the properties you wrote. Properties you did not write are not
       violated, they are unexamined (section 10.1)
     * "no rows returned" means "no counterexample in the space you specified".
       Narrow the space and you narrow the proof
     * an empty DataFrame is ambiguous: it can mean "the property holds" or
       "nothing parsed". Only the sanity questions tell them apart
""")

    # =================================================================
    banner("10.5  WHY BATFISH DOES IT THIS WAY -- the trade that was made")
    print("""
Batfish does not send packets because sending packets does not scale and does
not prove anything general. To test a firewall by sending traffic you would
need to enumerate the header space: 2^32 source addresses x 2^32 destinations
x 2^16 ports x protocols. That is not a large number, it is an impossible one.

So Batfish encodes the network as logic instead. Configuration becomes a set of
constraints; a question becomes a formula; a solver looks for a satisfying
assignment. "Is there a packet that gets through?" becomes "is this formula
satisfiable?" -- and the answer covers the entire header space at once, in
seconds, on a laptop.

That is an enormous win and it has an exact price. The formula only contains
what the model contains. Time is not in it. Hardware is not in it. Traffic is
not in it. Anything the parser dropped is not in it.

So the correct mental model is not "Batfish tells me whether my network works."
It is:

    Batfish tells me, with certainty, whether the properties I wrote down hold
    over an abstraction of my configuration that excludes time, hardware and
    traffic.

Every word of that sentence is doing work. When someone says "the verifier was
wrong", almost always one of these three happened instead:
    (a) they did not write the property that would have caught it,
    (b) the failure lived in time or hardware, outside the model, or
    (c) they never read parseWarning.
""")

    banner("10.6  WHERE THIS LEAVES YOU")
    print("""
You now have a verifier you understand well enough to distrust correctly, which
is the only useful kind. Concretely you can:

  * build a snapshot and gate it on parse health before believing any answer
  * read a RIB and explain why each route won
  * follow a packet and name the exact disposition that killed it
  * prove a filter has a dead line
  * diff two snapshots and enumerate what a change broke
  * state, without hedging, the three categories of thing Batfish cannot see

The natural next question -- and you should feel it as a question, not be told
it -- is: how big is the gap between what Batfish says and what a network
actually running these configurations does? Section 10.3 asserted one instance.
You have no way to check it yet.

That is what the emulated lab is for. Phase 2 begins there.

Before you start it: run the FRR compatibility spike if you have not.

    python m09_frr_spike.py
""")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
