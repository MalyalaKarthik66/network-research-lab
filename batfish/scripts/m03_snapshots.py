"""
MODULE 3 -- snapshots: what Batfish builds when it reads a folder of text files.

A snapshot is a directory. Batfish looks for `configs/` immediately below it and
reads every file in there as one device. It does NOT talk to any router. It does
NOT need the network to exist. The entire input is text.

What Batfish builds after reading a snapshot, in order:

  1. Vendor detection    -- guesses the format of each file from tell-tale lines
  2. Parse tree          -- vendor-specific grammar, per file
  3. Vendor-independent  -- a common model: nodes, VRFs, interfaces, filters,
     configuration          routing processes, expressed the same way regardless
                            of whether the source was Cisco, Arista or FRR
  4. Layer-1 / layer-3   -- which interfaces are physically and logically adjacent
     topology
  5. Control plane       -- simulate OSPF/BGP/static to a fixed point; produces
                            a RIB per VRF per node
  6. Data plane (FIB)    -- the forwarding table actually used to trace packets

Steps 1-4 happen at init_snapshot(). Steps 5-6 happen the first time you ask a
question that needs them, or when you call generate_dataplane().

    python m03_snapshots.py
"""

from __future__ import annotations

import sys

from bf_common import bf_session, load, sanity, banner, show, Checks


def main() -> int:
    c = Checks("MODULE 3 -- snapshots")
    bf = bf_session()

    banner("3.1  Load the snapshot")
    load(bf, "m03-trio-static")

    banner("3.2  The parse-health gate -- run this every single time")
    trustworthy = sanity(bf)
    c.check("snapshot passed the sanity gate", trustworthy)

    banner("3.3  What Batfish thinks the devices are")
    nodes = show("nodeProperties", bf.q.nodeProperties(
        properties="Configuration_Format,Interfaces,Routing_Policies").answer().frame())
    c.check("three nodes: r1, r2, r3",
            sorted(nodes["Node"]) == ["r1", "r2", "r3"],
            f"got {sorted(nodes['Node']) if len(nodes) else 'nothing'}")

    banner("3.4  What Batfish thinks the interfaces are")
    ifaces = show("interfaceProperties", bf.q.interfaceProperties(
        properties="Active,All_Prefixes,Description").answer().frame())
    # 3 devices x (Loopback0 + 2 physical) = 9
    c.check("nine interfaces total", len(ifaces) == 9, f"got {len(ifaces)}")
    c.check("every interface is Active",
            len(ifaces) > 0 and ifaces["Active"].all(),
            "an interface with 'shutdown' in the config would show Active=False")

    banner("3.5  Layer-3 adjacency -- inferred, because there is no layer-1 file here")
    print("This snapshot has no batfish/layer1_topology.json. With no layer-1 file")
    print("Batfish infers adjacency by matching subnets: two interfaces in the same")
    print("subnet are treated as neighbours. That is convenient and it is also a lie")
    print("that will bite you later -- two interfaces can share a subnet and have no")
    print("cable between them. Module 9 supplies an explicit layer-1 file instead.")
    edges = show("layer3Edges", bf.q.layer3Edges().answer().frame())
    # r1<->r2 and r2<->r3, reported in both directions = 4 rows
    c.check("four layer-3 edge rows (two links, both directions)",
            len(edges) == 4, f"got {len(edges)}")

    banner("3.6  IP ownership -- who owns which address")
    owners = show("ipOwners", bf.q.ipOwners().answer().frame())
    c.check("nine owned IPs", len(owners) == 9, f"got {len(owners)}")

    banner("3.7  Switching snapshots")
    print("Snapshots are cheap and independent. Load a second one and switch.")
    load(bf, "m05-trio-ospf")
    n2 = bf.q.nodeProperties().answer().frame()
    c.check("second snapshot also has three nodes", len(n2) == 3, f"got {len(n2)}")

    print()
    print("Both snapshots now live in the network 'phase1':")
    print(f"  {bf.list_snapshots()}")
    bf.set_snapshot("m03-trio-static")
    print("switched back to m03-trio-static")

    banner("3.8  Proof that Batfish is reading text, not a network")
    print("Nothing in this module required a router, a container, or a packet.")
    print("Batfish's entire input was three ~40-line text files. Everything it told")
    print("you was derived by parsing and then by mathematics. Hold on to that fact;")
    print("Module 10 is about exactly what it costs.")

    return c.summary()


if __name__ == "__main__":
    sys.exit(main())
