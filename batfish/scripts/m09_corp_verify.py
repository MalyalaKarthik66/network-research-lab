"""
MODULE 9 -- our own network, verified end to end, then broken on purpose.

This is not an example shipped with Batfish. Every line of it was written for
this lab, and every property below was decided before the tool was run.

TOPOLOGY (snapshot m09-corp-base)

                        PC LAN 192.168.10.0/24
                               |
                          Gi0/1 |
                             [ r1 ]  edge, lo0 10.255.0.1
                    Gi0/0 /          \\ Gi0/2
              cost 10   /              \\  cost 100
        10.0.12.0/30  /                  \\  10.0.13.0/30
                   [ r2 ]              [ r3 ]
             core, lo0 .2          core, lo0 .3
             Gi0/1 |  cost 10        Gi0/1 |  cost 10
          10.0.24.0/30                10.0.34.0/30
                   \\                    /
              Gi0/0  \\                 / Gi0/1
                          [ r4 ]  edge, lo0 10.255.0.4
                          Gi0/2 |
                        SERVER LAN 192.168.20.0/24

  PRIMARY path : r1 -> r2 -> r4   total OSPF cost 20
  BACKUP  path : r1 -> r3 -> r4   total OSPF cost 110

  FILTERS
    r4 Gi0/2 out : SERVER_POLICY       -- only the PC LAN, only HTTP/HTTPS/ICMP
    r3 Gi0/1 out : BACKUP_PATH_FILTER  -- the backup link is meant to be
                                          low-capacity, so only ICMP and HTTP

  This snapshot also carries an explicit batfish/layer1_topology.json. Adjacency
  is declared, not guessed from subnet overlap.

THE INTENT CHECKLIST

  P1  every configuration file parses with no warnings
  P2  no undefined or unused named structures
  P3  all four OSPF adjacencies are established
  P4  the PC LAN can reach the server LAN over HTTP
  P5  the PC LAN can reach the server LAN over HTTPS
  P6  the PC LAN CANNOT reach the server LAN over SSH
  P7  traffic to the server LAN takes the PRIMARY path through r2
  P8  no ACL contains an unreachable line
  P9  there are no forwarding loops

Nine properties. Write them down BEFORE running anything. This ordering is not
a stylistic preference -- a property invented after seeing the output is not a
specification, it is a description.

    python m09_corp_verify.py
"""

from __future__ import annotations

import sys

from pybatfish.datamodel import HeaderConstraints, PathConstraints

from bf_common import bf_session, load, banner, show, Checks, dispositions

PC_IF = "@enter(r1[GigabitEthernet0/1])"
PC_LAN = "192.168.10.0/24"
SRV_LAN = "192.168.20.0/24"
PC = "192.168.10.10"
SRV = "192.168.20.10"

EXPECTED_OSPF_PAIRS = {
    frozenset(("r1", "r2")), frozenset(("r1", "r3")),
    frozenset(("r2", "r4")), frozenset(("r3", "r4")),
}


def trace(bf, app, src=PC, dst=SRV):
    return bf.q.traceroute(
        startLocation=PC_IF,
        headers=HeaderConstraints(srcIps=src, dstIps=dst, applications=app),
    ).answer().frame()


def paths(frame):
    out = []
    if frame is None or len(frame) == 0:
        return out
    for _, row in frame.iterrows():
        for tr in row["Traces"]:
            out.append((str(tr.disposition), [h.node for h in tr.hops]))
    return out


def reach_ok(bf, app):
    return bf.q.reachability(
        pathConstraints=PathConstraints(startLocation=PC_IF),
        headers=HeaderConstraints(srcIps=PC_LAN, dstIps=SRV_LAN, applications=app),
        actions="SUCCESS",
    ).answer().frame()


PROPERTY_TEXT = {
    "P1": "every configuration file parses with no warnings",
    "P2": "no undefined or unused named structures",
    "P3": "all four OSPF adjacencies are established",
    "P4": "the PC LAN can reach the server LAN over HTTP",
    "P5": "the PC LAN can reach the server LAN over HTTPS",
    "P6": "the PC LAN CANNOT reach the server LAN over SSH",
    "P7": "traffic to the server LAN takes the PRIMARY path through r2",
    "P8": "no ACL contains an unreachable line",
    "P9": "there are no forwarding loops",
}


def run_checklist(bf, tag):
    """Evaluate all nine properties against the loaded snapshot.

    Returns {property_id: (holds: bool, evidence: str)}. It deliberately does NOT
    assert anything -- the caller decides which outcome is expected, because for
    a deliberately broken snapshot the expected outcome is failure.
    """
    banner(f"INTENT CHECKLIST -- {tag}", "-")
    res = {}

    fps = bf.q.fileParseStatus().answer().frame()
    pw = bf.q.parseWarning().answer().frame()
    res["P1"] = (len(fps) == 4 and (fps["Status"] == "PASSED").all() and len(pw) == 0,
                 f"{len(fps)} files parsed, {len(pw)} parse warnings")

    ur = bf.q.undefinedReferences().answer().frame()
    us = bf.q.unusedStructures().answer().frame()
    res["P2"] = (len(ur) == 0 and len(us) == 0,
                 f"{len(ur)} undefined, {len(us)} unused")

    bf.generate_dataplane()

    ospf = bf.q.ospfSessionCompatibility().answer().frame()
    pairs = {frozenset((str(r["Interface"]).split("[")[0],
                        str(r["Remote_Interface"]).split("[")[0]))
             for _, r in ospf.iterrows()} if len(ospf) else set()
    res["P3"] = (pairs == EXPECTED_OSPF_PAIRS and len(ospf) > 0 and
                 all(str(s) == "ESTABLISHED" for s in ospf["Session_Status"]),
                 f"adjacent pairs: {sorted(tuple(sorted(p)) for p in pairs)}")

    http = reach_ok(bf, "HTTP")
    res["P4"] = (len(http) > 0, f"{len(http)} succeeding HTTP flow example(s)")
    https = reach_ok(bf, "HTTPS")
    res["P5"] = (len(https) > 0, f"{len(https)} succeeding HTTPS flow example(s)")
    ssh = reach_ok(bf, "SSH")
    res["P6"] = (len(ssh) == 0, f"{len(ssh)} SSH flow(s) got through")

    p = paths(trace(bf, "HTTPS"))
    res["P7"] = (len(p) > 0 and all("r2" in hops for _, hops in p),
                 f"paths: {[(d, '->'.join(h)) for d, h in p]}")

    flr = bf.q.filterLineReachability().answer().frame()
    res["P8"] = (len(flr) == 0, f"{len(flr)} unreachable ACL line(s)")

    loops = bf.q.detectLoops().answer().frame()
    res["P9"] = (len(loops) == 0, f"{len(loops)} loop(s)")

    print()
    for pid in sorted(res):
        holds, ev = res[pid]
        print(f"  {pid} {'HOLDS   ' if holds else 'VIOLATED'}  "
              f"{PROPERTY_TEXT[pid]}")
        print(f"       evidence: {ev}")
    return res


def expect(c, res, tag, expected: dict):
    """Assert that each property's outcome matches what the manual predicts."""
    for pid in sorted(PROPERTY_TEXT):
        want = expected[pid]
        holds, ev = res[pid]
        c.check(f"[{tag}] {pid} is expected to "
                f"{'HOLD' if want else 'be VIOLATED'}",
                holds == want, f"actual: {'holds' if holds else 'violated'}; {ev}")


def main() -> int:
    c = Checks("MODULE 9 -- our own network")
    bf = bf_session()

    # =================================================================
    banner("9.1  THE HEALTHY NETWORK")
    load(bf, "m09-corp-base")
    show("nodeProperties", bf.q.nodeProperties(
        properties="Configuration_Format,Interfaces").answer().frame())
    show("layer3Edges (declared, from layer1_topology.json)",
         bf.q.layer3Edges().answer().frame())

    res = run_checklist(bf, "base")
    expect(c, res, "base", {p: True for p in PROPERTY_TEXT})
    print()
    print("Observed path(s) for HTTPS:")
    for disp, hops in paths(trace(bf, "HTTPS")):
        print(f"  [{disp}] {' -> '.join(hops)}")
    print()
    print("Why the primary: OSPF cost r1->r2 is 10 and r1->r3 is 100. Both paths")
    print("then cost 10 to r4. 20 versus 110, so r2 wins outright and the backup")
    print("carries nothing. This is exactly how a real dual-homed site is built.")

    # =================================================================
    banner("9.2  FAULT A -- the primary link goes down (m09-corp-link-down)")
    print("One line changed: 'shutdown' added to r1's Gi0/0.")
    print("Predict the outcome BEFORE reading the output. Write your prediction in")
    print("notes/lab-notebook.md. Then run it.")
    load(bf, "m09-corp-link-down")
    res = run_checklist(bf, "link-down")
    expect(c, res, "link-down", {
        "P1": True,    # still valid IOS
        "P2": True,    # no names broken
        "P3": False,   # r1-r2 adjacency is gone
        "P4": True,    # HTTP survives on the backup path
        "P5": False,   # HTTPS is dropped by BACKUP_PATH_FILTER
        "P6": True,    # SSH was blocked before and is still blocked
        "P7": False,   # traffic now goes via r3
        "P8": True,    # the ACLs themselves are unchanged
        "P9": True,
    })

    print()
    p = paths(trace(bf, "HTTPS"))
    print("HTTPS paths after the failure:")
    for disp, hops in p:
        print(f"  [{disp}] {' -> '.join(hops)}")
    p_http = paths(trace(bf, "HTTP"))
    print("HTTP paths after the failure:")
    for disp, hops in p_http:
        print(f"  [{disp}] {' -> '.join(hops)}")

    c.check("HTTP survives the failover",
            any(d in ("DELIVERED_TO_SUBNET", "EXITS_NETWORK", "ACCEPTED")
                for d, _ in p_http), f"{p_http}")
    c.check("HTTPS does NOT survive the failover -- it is dropped on the backup path",
            all(d == "DENIED_OUT" for d, _ in p) and len(p) > 0, f"{p}")

    print()
    print("THIS IS THE MOST IMPORTANT RESULT IN PHASE 1. Read it slowly.")
    print()
    print("  * The network still converges. OSPF did its job.")
    print("  * Every device is up. Every remaining adjacency is established.")
    print("  * Ping works. HTTP works.")
    print("  * HTTPS is silently dropped on the last hop of the backup path,")
    print("    because BACKUP_PATH_FILTER never contemplated it.")
    print()
    print("If your monitoring pings the server, it is green. If your verification")
    print("checked 'can the PC LAN reach the server LAN', and 'reach' meant ICMP,")
    print("it passes. The property that would have caught this -- P5, HTTPS")
    print("specifically, under the failure of the primary link -- had to be written")
    print("down by a human who thought of it in advance.")

    print()
    print("differentialReachability makes the damage explicit without needing that")
    print("human to have guessed correctly:")
    diff = bf.q.differentialReachability(
        headers=HeaderConstraints(srcIps=PC_LAN, dstIps=SRV_LAN),
        pathConstraints=PathConstraints(startLocation=PC_IF),
    ).answer(snapshot="m09-corp-link-down",
             reference_snapshot="m09-corp-base").frame()
    show("differentialReachability: link-down vs base", diff)
    c.check("the differential finds flows that regressed", len(diff) > 0,
            "zero rows would mean the failure changed nothing, which is false")

    # =================================================================
    banner("9.3  FAULT B -- a one-character ACL typo (m09-corp-acl-typo)")
    print("SERVER_POLICY line 1 on r4 was:")
    print("   permit tcp 192.168.10.0 0.0.0.255 192.168.20.0 0.0.0.255 eq www")
    print("and is now:")
    print("   permit tcp 192.168.10.0 0.0.0.0   192.168.20.0 0.0.0.255 eq www")
    print()
    print("Wildcard 0.0.0.0 means 'exactly this one address'. HTTP is now permitted")
    print("only from the host 192.168.10.0 -- which is the network address and")
    print("belongs to no host at all. HTTPS is untouched.")
    load(bf, "m09-corp-acl-typo")
    res = run_checklist(bf, "acl-typo")
    expect(c, res, "acl-typo", {
        "P1": True,
        "P2": True,
        "P3": True,
        "P4": False,   # HTTP from any real host is now denied
        "P5": True,    # HTTPS untouched
        "P6": True,
        "P7": True,    # routing is unaffected
        "P8": True,    # the line is still reachable, so structural analysis is blind
        "P9": True,
    })

    print()
    print("Note which properties failed and which did not:")
    print("  P8 (unreachable ACL lines) PASSES. The line is still reachable -- one")
    print("     address matches it. Structural ACL analysis cannot see this bug.")
    print("  P4 (HTTP reachability) FAILS. Only a reachability property catches it.")
    print()
    tf = bf.q.testFilters(
        nodes="r4", filters="SERVER_POLICY",
        headers=HeaderConstraints(srcIps=PC, dstIps=SRV, applications="HTTP"),
        startLocation="r4",
    ).answer().frame()
    show("testFilters: HTTP from a real host under the typo", tf)
    c.check("HTTP from a real PC-LAN host is now denied",
            len(tf) and str(tf.iloc[0]["Action"]) == "DENY",
            f"got {tf.iloc[0]['Action'] if len(tf) else 'nothing'}")

    diff = bf.q.differentialReachability(
        headers=HeaderConstraints(srcIps=PC_LAN, dstIps=SRV_LAN),
        pathConstraints=PathConstraints(startLocation=PC_IF),
    ).answer(snapshot="m09-corp-acl-typo",
             reference_snapshot="m09-corp-base").frame()
    show("differentialReachability: acl-typo vs base", diff)
    c.check("the differential finds the regression", len(diff) > 0)

    # =================================================================
    banner("9.4  WHAT TO WRITE DOWN")
    print("In notes/lab-notebook.md, for each fault:")
    print("  * your prediction, written before you ran it")
    print("  * which of P1-P9 actually failed")
    print("  * which Batfish question found it FIRST")
    print("  * whether a plausible operator would have written that property")
    print()
    print("In notes/surprises.md, anything where the answer differed from your")
    print("prediction. Those entries are worth more than the ones that matched.")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
