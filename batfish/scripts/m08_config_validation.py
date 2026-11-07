"""
MODULE 8 -- configuration validation: breaking things on purpose.

Three broken snapshots, one bug each. For every one, three questions:

  1. Does Batfish notice at PARSE time?      (initIssues / parseWarning /
                                              undefinedReferences)
  2. Does Batfish notice at CONTROL PLANE time?  (session compatibility)
  3. Does Batfish notice at DATA PLANE time?     (reachability)

The answers are not the same, and the pattern is the lesson: bugs are caught at
different layers, and a bug that is invisible at every layer you happen to check
is indistinguishable from a working network.

    python m08_config_validation.py
"""

from __future__ import annotations

import sys

from pybatfish.datamodel import HeaderConstraints, PathConstraints

from bf_common import bf_session, load, sanity, banner, show, Checks, dispositions

PC_IF = "@enter(r1[GigabitEthernet0/1])"
PC = "192.168.1.10"
SRV = "192.168.3.10"


def main() -> int:
    c = Checks("MODULE 8 -- configuration validation")
    bf = bf_session()

    # =================================================================
    banner("8.1  BUG: WRONG IP ADDRESS / SUBNET MISMATCH (m08-broken-subnet)")
    print("r2's link to r3 was renumbered from 10.1.23.1/30 to 10.1.24.1/30.")
    print("r3 was not updated. The OSPF network statement on r2 was updated to")
    print("match, so the config is internally self-consistent and reads fine.")
    load(bf, "m08-broken-subnet")

    print()
    print("LAYER 1 -- does it parse?")
    init = show("initIssues", bf.q.initIssues().answer().frame())
    pw = show("parseWarning", bf.q.parseWarning().answer().frame())
    c.check("the broken config parses without complaint",
            len(init) == 0 and len(pw) == 0,
            "Batfish has no opinion about which IP address is correct")
    print("Every line is valid IOS. Batfish has no idea what you MEANT the address")
    print("to be. Syntactic validity buys you nothing here.")

    print()
    print("LAYER 2 -- does the control plane notice?")
    bf.generate_dataplane()
    edges = show("layer3Edges", bf.q.layer3Edges().answer().frame())
    pairs = {(str(r["Interface"]).split("[")[0],
              str(r["Remote_Interface"]).split("[")[0]) for _, r in edges.iterrows()}
    c.check("r2 and r3 are no longer adjacent", ("r2", "r3") not in pairs,
            f"pairs found: {pairs}")
    ospf = show("ospfSessionCompatibility",
                bf.q.ospfSessionCompatibility().answer().frame())
    ospf_pairs = {frozenset((str(r["Interface"]).split("[")[0],
                             str(r["Remote_Interface"]).split("[")[0]))
                  for _, r in ospf.iterrows()} if len(ospf) else set()
    c.check("only the r1-r2 OSPF adjacency survives",
            ospf_pairs == {frozenset(("r1", "r2"))},
            f"got {[sorted(p) for p in ospf_pairs]}")
    print("Now it is loud. Two interfaces in different subnets cannot form an")
    print("adjacency, so the r2-r3 session simply does not exist.")

    print()
    print("LAYER 3 -- what does a packet experience?")
    tr = bf.q.traceroute(startLocation=PC_IF,
                         headers=HeaderConstraints(srcIps=PC, dstIps=SRV,
                                                   applications="HTTPS")
                         ).answer().frame()
    show("traceroute PC -> server", tr)
    d = dispositions(tr)
    c.check("the packet no longer reaches the server LAN",
            all(x not in ("DELIVERED_TO_SUBNET", "EXITS_NETWORK", "ACCEPTED")
                for x in d) or len(d) == 0,
            f"dispositions {d}")
    print(f"Dispositions: {d}")
    print("Caught at layers 2 and 3, invisible at layer 1.")

    # =================================================================
    banner("8.2  BUG: DANGLING AND ORPHANED NAMES (m08-broken-refs)")
    print("Two separate mistakes on r1:")
    print("  * Gi0/1 applies an ACL called HOST_FILTER that was never defined.")
    print("  * An ACL called LEFTOVER_MGMT_ACL is defined and never applied.")
    print("Both are things a human reviewer skims past. Both are one query away.")
    load(bf, "m08-broken-refs")

    ur = show("undefinedReferences", bf.q.undefinedReferences().answer().frame())
    c.check("Batfish flags the undefined ACL", len(ur) >= 1, f"got {len(ur)} rows")
    if len(ur):
        c.check("the flagged name is HOST_FILTER",
                any("HOST_FILTER" in str(v) for v in ur["Struct_Name"]),
                f"names: {list(ur['Struct_Name'])}")

    us = show("unusedStructures", bf.q.unusedStructures().answer().frame())
    c.check("Batfish flags the orphaned ACL",
            any("LEFTOVER_MGMT_ACL" in str(v) for v in us["Struct_Name"]) if len(us)
            else False,
            f"names: {list(us['Struct_Name']) if len(us) else []}")

    print()
    print("These two questions are the cheapest audit in the whole tool. On a real")
    print("enterprise snapshot they routinely return dozens of rows, and each row is")
    print("either dead configuration or a live bug. Run them on every snapshot.")
    print()
    print("Note the asymmetry, though: Batfish tells you HOST_FILTER does not exist.")
    print("It cannot tell you what HOST_FILTER was supposed to do. Detecting a")
    print("missing specification is not the same as recovering it.")

    # =================================================================
    banner("8.3  BUG: WRONG BGP NEIGHBOUR AS (m08-broken-bgp-as)")
    print("r3 says 'neighbor 10.1.23.1 remote-as 65099'. r2 is actually AS 65002.")
    print("A single wrong digit. The kind of thing that survives code review.")
    load(bf, "m08-broken-bgp-as")

    print()
    print("LAYER 1 -- parse:")
    pw = show("parseWarning", bf.q.parseWarning().answer().frame())
    c.check("parses cleanly", len(pw) == 0, "65099 is a perfectly legal AS number")

    print()
    print("LAYER 2 -- control plane:")
    bf.generate_dataplane()
    compat = show("bgpSessionCompatibility",
                  bf.q.bgpSessionCompatibility().answer().frame())
    broken = compat[~compat["Configured_Status"].astype(str).str.contains("UNIQUE_MATCH")]
    c.check("Batfish reports at least one incompatible BGP session",
            len(broken) > 0,
            f"statuses: {list(compat['Configured_Status']) if len(compat) else []}")
    if len(broken):
        print()
        print("The incompatible session(s):")
        print(broken.to_string())

    status = show("bgpSessionStatus", bf.q.bgpSessionStatus().answer().frame())
    not_est = status[status["Established_Status"].astype(str) != "ESTABLISHED"] \
        if len(status) else status
    c.check("at least one session fails to establish", len(not_est) > 0,
            f"statuses: {list(status['Established_Status']) if len(status) else []}")

    print()
    print("LAYER 3 -- data plane:")
    bgp_r1 = bf.q.routes(nodes="r1", protocols="bgp").answer().frame()
    show("BGP routes still known to r1", bgp_r1)
    c.check("r1 has lost the BGP route to the server LAN",
            "192.168.3.0/24" not in set(bgp_r1["Network"]) if len(bgp_r1)
            else True,
            f"r1 BGP networks: {set(bgp_r1['Network']) if len(bgp_r1) else 'none'}")

    # =================================================================
    banner("8.4  THE PATTERN")
    print("                          parse?   control plane?   data plane?")
    print("  wrong IP / subnet         no          YES             YES")
    print("  undefined ACL name        YES          no              no*")
    print("  wrong BGP remote-as       no          YES             YES")
    print()
    print("* the undefined ACL does not change forwarding in Batfish's model. On a")
    print("  real Cisco device, applying a nonexistent ACL permits everything, which")
    print("  means the ACL you thought you had is simply absent. Batfish told you")
    print("  the name is undefined; it did not tell you the security consequence.")
    print("  You have to know to care.")
    print()
    print("Three bugs, three different detection layers, and one detected only by a")
    print("question you had to know to ask. Write this table into your lab notebook.")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
