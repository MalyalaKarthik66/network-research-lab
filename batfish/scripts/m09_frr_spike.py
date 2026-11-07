"""
MODULE 9 (annex) -- the FRRouting compatibility spike.

This is a DECISION script, not a teaching script. It runs for about a minute and
its output determines how the rest of the lab is built. Run it once, record the
verdict in notes/lab-notebook.md, and do not defer it.

WHY IT MATTERS
--------------
Everything so far has used Cisco IOS, which is Batfish's best-supported format.
Cisco IOS is a superb thing to learn on and a poor thing to emulate -- there is
no free Cisco container. Emulated routers in practice mean FRRouting, and
Batfish reads FRR through the Cumulus path: the three files

    /etc/network/interfaces
    /etc/cumulus/ports.conf
    /etc/frr/frr.conf

concatenated into a single file per device, with the marker lines Batfish uses
to find the boundaries between them:

    # This file describes the network interfaces      <- start of interfaces
    # ports.conf --                                   <- start of ports.conf
    frr version                                       <- start of frr.conf

THE TRAP THIS SCRIPT EXISTS TO CATCH
------------------------------------
Interface IP addresses live in the INTERFACES file, not in frr.conf. If you feed
Batfish only frr.conf, it builds a network whose devices have no addresses. Every
routing question then returns an empty answer, and every reachability question
returns a confident, wrong answer. The failure is silent. That is the worst kind.

Check 3 below is the one that matters: do the interfaces have their addresses?

VERDICT
-------
  GO   -> all files parse, all addresses present, OSPF adjacencies form, few or
          no parse warnings. Build the emulated lab on FRR (15-20 nodes fit in
          16 GB).
  STOP -> anything above is false after ONE fix attempt. Switch to Arista cEOS,
          which Batfish parses excellently but which costs 1-2 GB of RAM per
          node, capping the lab at four or five devices. That cap changes what
          topology is buildable, so you need to know now, not in month four.

    python m09_frr_spike.py
"""

from __future__ import annotations

import sys

from bf_common import bf_session, load, banner, show

EXPECTED_ADDRESSES = {
    ("r1", "swp1"): "10.1.12.1/30",
    ("r1", "swp2"): "192.168.1.1/24",
    ("r2", "swp1"): "10.1.12.2/30",
    ("r2", "swp2"): "10.1.23.1/30",
    ("r3", "swp1"): "10.1.23.2/30",
    ("r3", "swp2"): "192.168.3.1/24",
}


def main() -> int:
    banner("FRR / BATFISH COMPATIBILITY SPIKE")
    bf = bf_session()
    load(bf, "m10-frr-spike")

    verdict = {"parse": False, "format": False, "addresses": False,
               "ospf": False, "statics": False}

    # ---- 1. did the files parse at all -------------------------------
    banner("CHECK 1 -- parse status", "-")
    fps = show("fileParseStatus", bf.q.fileParseStatus().answer().frame())
    verdict["parse"] = len(fps) == 3 and (fps["Status"] == "PASSED").all()

    init = show("initIssues", bf.q.initIssues().answer().frame())
    pw = show("parseWarning -- READ EVERY ROW", bf.q.parseWarning().answer().frame())
    print()
    print(f"parse warnings: {len(pw)}")
    if len(pw):
        print("Each row is a configuration line Batfish saw and threw away. Decide,")
        print("line by line, whether you need that feature. FRR grammar coverage in")
        print("Batfish is partial; users have hit gaps in things as basic as static")
        print("routes. A warning on a feature you do not use is fine. A warning on")
        print("a feature the lab depends on is a STOP.")

    # ---- 2. was the format detected correctly ------------------------
    banner("CHECK 2 -- vendor format detection", "-")
    nodes = show("nodeProperties",
                 bf.q.nodeProperties(properties="Configuration_Format,Interfaces")
                 .answer().frame())
    fmts = set(str(f) for f in nodes["Configuration_Format"]) if len(nodes) else set()
    print(f"detected formats: {fmts}")
    verdict["format"] = len(nodes) == 3 and all(
        "CUMULUS" in f.upper() or "FRR" in f.upper() for f in fmts)
    if not verdict["format"]:
        print()
        print("If this says UNKNOWN, the marker lines are wrong or missing. Batfish")
        print("finds the file boundaries by looking for those exact comment strings.")

    # ---- 3. THE CRITICAL CHECK: do interfaces have addresses ---------
    banner("CHECK 3 -- interface addresses (the one that silently fails)", "-")
    ifaces = show("interfaceProperties",
                  bf.q.interfaceProperties(properties="Active,All_Prefixes,Description")
                  .answer().frame())
    got = {}
    for _, row in ifaces.iterrows():
        node = str(row["Interface"]).split("[")[0]
        name = str(row["Interface"]).split("[")[1].rstrip("]")
        prefixes = list(row["All_Prefixes"]) if row["All_Prefixes"] is not None else []
        got[(node, name)] = prefixes

    missing, wrong = [], []
    for key, want in EXPECTED_ADDRESSES.items():
        have = got.get(key)
        if not have:
            missing.append(key)
        elif want not in have:
            wrong.append((key, want, have))
    print()
    for key, want in sorted(EXPECTED_ADDRESSES.items()):
        have = got.get(key, [])
        mark = "OK  " if want in have else "BAD "
        print(f"  {mark} {key[0]}:{key[1]:6s} expected {want:18s} got {have}")
    verdict["addresses"] = not missing and not wrong

    if missing or wrong:
        print()
        print("THIS IS THE FAILURE MODE THE GUARDRAILS WARN ABOUT.")
        print("Batfish parsed the file but did not pick up addresses from the")
        print("/etc/network/interfaces section. Almost always one of:")
        print("  * the '# This file describes the network interfaces' marker is")
        print("    missing, misspelled, or not on its own line")
        print("  * the address lines are not indented under an 'iface' stanza")
        print("  * the hostname line at the very top of the file is absent")

    # ---- 4. does the control plane work ------------------------------
    banner("CHECK 4 -- OSPF adjacencies", "-")
    try:
        bf.generate_dataplane()
        ospf = show("ospfSessionCompatibility",
                    bf.q.ospfSessionCompatibility().answer().frame())
        pairs = {frozenset((str(r["Interface"]).split("[")[0],
                            str(r["Remote_Interface"]).split("[")[0]))
                 for _, r in ospf.iterrows()} if len(ospf) else set()
        print(f"adjacent pairs: {sorted(tuple(sorted(p)) for p in pairs)}")
        verdict["ospf"] = pairs == {frozenset(("r1", "r2")), frozenset(("r2", "r3"))}
        show("all routes", bf.q.routes().answer().frame())
    except Exception as exc:  # noqa: BLE001
        print(f"data plane generation failed: {exc}")

    # ---- 5. the specific known-fragile feature -----------------------
    banner("CHECK 5 -- did the static route in frr.conf survive?", "-")
    print("r1's frr.conf contains: ip route 192.168.99.0/24 10.1.12.2")
    st = show("static routes on r1",
              bf.q.routes(nodes="r1", protocols="static").answer().frame())
    verdict["statics"] = len(st) > 0 and "192.168.99.0/24" in set(st["Network"])
    if not verdict["statics"]:
        print()
        print("The static route did not make it into the RIB. This exact gap has")
        print("been reported against Batfish's FRR grammar before. If the lab needs")
        print("static routes -- and it will -- this alone is close to a STOP.")

    # ---- verdict -----------------------------------------------------
    banner("VERDICT")
    for k, v in verdict.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    go = all(verdict.values())
    print()
    if go:
        print("GO. Batfish reads this FRR snapshot correctly.")
        print("Record in notes/lab-notebook.md: 'FRR spike PASSED on <date>,")
        print("pybatfish <version>, batfish/allinone <image digest>.' Pin that image")
        print("digest -- a future 'latest' can regress FRR grammar under you.")
    else:
        print("NOT YET. You get ONE fix attempt. Work through the failing checks")
        print("above in order; they are ordered by how upstream the cause is.")
        print("If it still fails, the answer is Arista cEOS and a smaller topology.")
        print("That is a legitimate outcome of a spike, not a defeat. The point of")
        print("running it in week one is that the answer is cheap now.")
    return 0 if go else 2


if __name__ == "__main__":
    sys.exit(main())
