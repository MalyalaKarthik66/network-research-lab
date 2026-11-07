"""
MODULE 7 -- ACL and firewall verification.

Two snapshots, identical except for four lines of ACL on r3:

  m07-acl-good   the policy the operator intended
  m07-acl-bad    the policy the operator wrote

Both are applied outbound on r3's server-LAN interface:

    interface GigabitEthernet0/1
     description SERVER LAN
     ip address 192.168.3.1 255.255.255.0
     ip access-group SERVER_PROTECT out

Three different Batfish questions attack an ACL from three directions:

  testFilters           "what does this filter do to THIS packet?"      (a test)
  searchFilters         "find me a packet this filter treats like X"    (a search)
  filterLineReachability "is any line here dead?"                       (a proof)

Only the third one finds bugs you did not already suspect. That distinction is
the single most important idea in this module.

    python m07_acl_verification.py
"""

from __future__ import annotations

import sys

from pybatfish.datamodel import HeaderConstraints, PathConstraints

from bf_common import bf_session, load, sanity, banner, show, Checks, dispositions

ACL = "SERVER_PROTECT"
PC_IF = "@enter(r1[GigabitEthernet0/1])"
PC = "192.168.1.10"
SRV = "192.168.3.10"
OUTSIDER = "172.16.5.5"


def reach(bf, src, dst, app, action):
    return bf.q.reachability(
        pathConstraints=PathConstraints(startLocation=PC_IF),
        headers=HeaderConstraints(srcIps=src, dstIps=dst, applications=app),
        actions=action,
    ).answer().frame()


def main() -> int:
    c = Checks("MODULE 7 -- ACL and firewall verification")
    bf = bf_session()

    # =================================================================
    banner("7.1  THE INTENDED POLICY (m07-acl-good)")
    load(bf, "m07-acl-good")
    sanity(bf, strict=False)
    bf.generate_dataplane()

    print("SERVER_PROTECT, as written:")
    print("   permit tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq www")
    print("   permit tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq 443")
    print("   permit icmp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255")
    print("   deny   ip any any")
    print()
    print("Reminder on wildcard masks: Cisco ACLs use INVERTED masks. 0.0.0.255")
    print("means 'the last octet is a wildcard', i.e. a /24. It is not a subnet")
    print("mask. Getting this backwards is the most common ACL bug in existence.")

    # --- testFilters: one packet at a time -------------------------------
    print()
    print("QUESTION 1 -- testFilters: what does the filter do to one specific packet?")
    for app, expect in (("HTTP", "PERMIT"), ("HTTPS", "PERMIT"), ("SSH", "DENY")):
        tf = bf.q.testFilters(
            nodes="r3", filters=ACL,
            headers=HeaderConstraints(srcIps=PC, dstIps=SRV, applications=app),
            startLocation="r3",
        ).answer().frame()
        show(f"testFilters: {app} from the PC LAN", tf)
        got = str(tf.iloc[0]["Action"]) if len(tf) else "NO_ANSWER"
        c.check(f"{app} from the PC LAN -> {expect}", got == expect,
                f"got {got}; matched line: "
                f"{tf.iloc[0]['Line_Content'] if len(tf) else 'n/a'}")

    tf = bf.q.testFilters(
        nodes="r3", filters=ACL,
        headers=HeaderConstraints(srcIps=OUTSIDER, dstIps=SRV, applications="HTTP"),
        startLocation="r3",
    ).answer().frame()
    show("testFilters: HTTP from an address outside the PC LAN", tf)
    c.check("an outsider is denied even on HTTP",
            len(tf) and str(tf.iloc[0]["Action"]) == "DENY",
            f"got {tf.iloc[0]['Action'] if len(tf) else 'nothing'}")

    print()
    print("Read the Line_Content column, not just Action. It names the exact ACL")
    print("line that decided the packet's fate. That is the difference between")
    print("'the firewall blocked it' and 'line 4 blocked it'.")

    # --- end-to-end effect ------------------------------------------------
    print()
    print("QUESTION 2 -- does the filter change end-to-end reachability?")
    ok = reach(bf, "192.168.1.0/24", "192.168.3.0/24", "HTTPS", "SUCCESS")
    c.check("HTTPS from the PC LAN still reaches the server LAN", len(ok) > 0)
    bad = reach(bf, "192.168.1.0/24", "192.168.3.0/24", "SSH", "SUCCESS")
    c.check("SSH from the PC LAN does NOT reach the server LAN", len(bad) == 0,
            f"{len(bad)} SSH flow(s) got through")

    tr = bf.q.traceroute(
        startLocation=PC_IF,
        headers=HeaderConstraints(srcIps=PC, dstIps=SRV, applications="SSH"),
    ).answer().frame()
    show("traceroute of the SSH flow -- watch where it dies", tr)
    d = dispositions(tr)
    c.check("SSH is dropped with DENIED_OUT at r3", d == ["DENIED_OUT"], f"got {d}")
    print()
    print("DENIED_OUT, not DENIED_IN, because the ACL is applied 'out' on the")
    print("interface facing the server LAN. The packet crossed r1 and r2 perfectly")
    print("happily and died on the last hop, on egress. If you were debugging this")
    print("from the PC you would have blamed the network. It is a policy.")

    # --- filterLineReachability on the good ACL ---------------------------
    print()
    print("QUESTION 3 -- filterLineReachability: is any line of this ACL dead?")
    flr = show("filterLineReachability (good ACL)",
               bf.q.filterLineReachability(nodes="r3", filters=ACL).answer().frame())
    c.check("no unreachable lines in the intended policy", len(flr) == 0,
            f"{len(flr)} dead line(s)")

    # =================================================================
    banner("7.2  THE POLICY THAT WAS ACTUALLY WRITTEN (m07-acl-bad)")
    load(bf, "m07-acl-bad")
    sanity(bf, strict=False)
    bf.generate_dataplane()

    print("SERVER_PROTECT, as written this time:")
    print("   remark INTENT: allow the host LAN to the server LAN, but never SSH")
    print("   permit ip  192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255")
    print("   deny   tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq 22")
    print("   permit icmp any any")
    print("   deny   ip any any")
    print()
    print("Read it as a human. The intent is stated in a remark. Line 2 implements")
    print("it. Line 1 was added first, by someone else, six months earlier. Nothing")
    print("looks wrong. Two people signed off on the change.")

    print()
    print("Now ask the machine.")
    tf = bf.q.testFilters(
        nodes="r3", filters=ACL,
        headers=HeaderConstraints(srcIps=PC, dstIps=SRV, applications="SSH"),
        startLocation="r3",
    ).answer().frame()
    show("testFilters: SSH from the PC LAN under the broken ACL", tf)
    c.check("SSH is PERMITTED, contradicting the stated intent",
            len(tf) and str(tf.iloc[0]["Action"]) == "PERMIT",
            f"got {tf.iloc[0]['Action'] if len(tf) else 'nothing'}")
    if len(tf):
        print(f"Deciding line: {tf.iloc[0]['Line_Content']}")

    flr = show("filterLineReachability (broken ACL)",
               bf.q.filterLineReachability(nodes="r3", filters=ACL).answer().frame())
    c.check("Batfish reports exactly one unreachable line", len(flr) == 1,
            f"got {len(flr)}")
    if len(flr):
        print()
        print(f"Unreachable line   : {flr.iloc[0]['Unreachable_Line']}")
        print(f"Blocking line(s)   : {flr.iloc[0]['Blocking_Lines']}")
        c.check("the dead line is the SSH deny",
                "eq 22" in str(flr.iloc[0]["Unreachable_Line"]),
                f"got {flr.iloc[0]['Unreachable_Line']}")

    print()
    print("THIS is the class of bug worth having a verifier for. testFilters only")
    print("told you the truth because you already suspected SSH and asked about it.")
    print("filterLineReachability needed no hypothesis at all -- it proved a line")
    print("can never match any packet, which is a property of the ACL alone.")

    # --- differential ------------------------------------------------------
    banner("7.3  DIFFERENTIAL REACHABILITY -- 'what did my change break?'")
    print("The single most useful question in Batfish for reviewing a change.")
    print("It compares two snapshots and returns only the flows whose fate differs.")
    diff = bf.q.differentialReachability(
        headers=HeaderConstraints(srcIps="192.168.1.0/24", dstIps="192.168.3.0/24"),
        pathConstraints=PathConstraints(startLocation=PC_IF),
    ).answer(snapshot="m07-acl-bad", reference_snapshot="m07-acl-good").frame()
    show("differentialReachability: bad ACL vs good ACL", diff)
    c.check("the two policies differ for at least one flow", len(diff) > 0,
            "zero rows would mean the two ACLs are behaviourally identical")
    print()
    print("Every row is a flow that succeeds in one snapshot and fails in the other.")
    print("Notice what this question does NOT need: a list of flows to test. You do")
    print("not have to have thought of SSH. That property -- finding differences you")
    print("did not predict -- is what separates verification from testing.")
    print()
    print("Notice also what it still needs: a header space to search. Here we gave")
    print("it srcIps=192.168.1.0/24 and dstIps=192.168.3.0/24. Anything outside")
    print("those two ranges was never examined. Remember that in Module 10.")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
