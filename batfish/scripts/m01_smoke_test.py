"""
MODULE 1 -- environment smoke test.

Run this the moment the Batfish container is up and pybatfish is installed.
It proves four things, in order, and stops at the first one that fails:

  1. Python can import pybatfish at all.
  2. The Batfish service answers on the network.
  3. A network can be created and a snapshot initialised end to end.
  4. A question can be asked and returns a pandas DataFrame with real rows.

If this script prints ALL CHECKS PASSED, Module 1 is finished and nothing in
Modules 3-10 will fail for environment reasons.

    python m01_smoke_test.py
"""

from __future__ import annotations

import sys

from bf_common import bf_session, load, banner, show, Checks, SNAPSHOT_DIR


def main() -> int:
    c = Checks("MODULE 1 -- environment smoke test")

    banner("STEP 1: import pybatfish and report its version")
    import pybatfish  # noqa: PLC0415

    version = getattr(pybatfish, "__version__", "unknown")
    print(f"pybatfish version: {version}")
    print(f"python version   : {sys.version.split()[0]}")
    c.check("pybatfish imports", True)

    banner("STEP 2: connect to the Batfish service")
    bf = bf_session()
    networks = bf.list_networks()
    print(f"networks currently on the service: {networks}")
    c.check("Batfish service reachable and network 'phase1' selected", True)

    banner("STEP 3: initialise the Module 3 snapshot")
    print(f"snapshot root on disk: {SNAPSHOT_DIR}")
    load(bf, "m03-trio-static")
    snaps = bf.list_snapshots()
    print(f"snapshots in this network: {snaps}")
    c.check("snapshot m03-trio-static initialised",
            "m03-trio-static" in [str(s) for s in snaps],
            f"got {snaps}")

    banner("STEP 4: ask a question and get a DataFrame back")
    fps = show("fileParseStatus", bf.q.fileParseStatus().answer().frame())
    c.check("three configuration files were read", len(fps) == 3,
            f"got {len(fps)} rows; expected one row per file in configs/")
    c.check("every file parsed with status PASSED",
            len(fps) > 0 and (fps["Status"] == "PASSED").all(),
            f"statuses: {list(fps['Status']) if len(fps) else 'none'}")

    nodes = show("nodeProperties (a few columns)",
                 bf.q.nodeProperties(properties="Configuration_Format,Interfaces")
                 .answer().frame())
    c.check("Batfish identified three devices", len(nodes) == 3, f"got {len(nodes)}")
    if len(nodes):
        fmts = set(nodes["Configuration_Format"])
        c.check("all three detected as a Cisco IOS format",
                all("CISCO" in str(f).upper() for f in fmts),
                f"formats detected: {fmts}")

    banner("STEP 5: the data plane")
    print("Asking Batfish to compute the data plane. This is the expensive step:")
    print("Batfish simulates the routing protocols to convergence, then derives a")
    print("forwarding table for every device. On this three-node snapshot it takes")
    print("a couple of seconds. It is what makes traceroute and reachability work.")
    bf.generate_dataplane()
    print("data plane computed")
    c.check("data plane generated without error", True)

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
