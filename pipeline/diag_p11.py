"""
Is the OSPF loopback /32 actually in Batfish's model, or does P11 fail for a
modelling reason rather than a network reason?

P11 ("edgea loopback can reach edgeb loopback") returned NO_ROUTE on candidates
that are CORRECT repairs of a fault unrelated to loopbacks. Either:
  (a) the loopback /32 is genuinely unreachable  -> P11 is right, investigate, or
  (b) Batfish never installed it                 -> P11 is measuring the model's
      FRR loopback handling, not the network, and every P11 row in the dataset
      is noise.

Distinguishing them needs three facts from the golden snapshot, where the
answer is not in doubt: the address is on lo, lo is in the OSPF process, and
the /32 appears in a REMOTE router's RIB.

    python pipeline/diag_p11.py --pilot data/pilot-v2
"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--topology", default="t01_chain4")
    a = ap.parse_args()

    root = (REPO / a.pilot).resolve()
    snap = root / "reference" / f"golden-{a.topology}" / "batfish-snapshot"
    if not snap.exists():
        print(f"no snapshot at {snap}")
        return 2

    logging.getLogger("pybatfish").setLevel(logging.ERROR)
    from pybatfish.client.session import Session
    bf = Session(host="localhost")
    bf.set_network(f"nrl-diag-{root.name}")
    bf.init_snapshot(str(snap), name=f"diag-{a.topology}", overwrite=True)
    bf.generate_dataplane()

    print("=" * 66)
    print("FACT 1 -- does Batfish see an address on lo?")
    ifs = bf.q.interfaceProperties(interfaces="/lo/",
                                   properties="All_Prefixes,Active").answer().frame()
    print(ifs.to_string() if len(ifs) else "  NO lo INTERFACES AT ALL")

    print("=" * 66)
    print("FACT 2 -- is lo inside the OSPF process?")
    try:
        oi = bf.q.ospfInterfaceConfiguration(
            properties="Interface,OSPF_Area_Name,OSPF_Passive,OSPF_Enabled"
        ).answer().frame()
        lo = oi[oi["Interface"].astype(str).str.contains(r"\[lo\]")]
        print(lo.to_string() if len(lo) else "  lo IS NOT IN THE OSPF PROCESS")
    except Exception as e:
        print(f"  query failed: {e}")

    print("=" * 66)
    print("FACT 3 -- does a REMOTE router have the /32 in its RIB?")
    print("  (edgea's loopback, seen from edgeb -- these are not neighbours)")
    for proto in ("ospf", None):
        rt = (bf.q.routes(nodes="edgeb", network="10.255.0.1/32",
                          protocols=proto) if proto else
              bf.q.routes(nodes="edgeb", network="10.255.0.1/32")).answer().frame()
        print(f"  protocols={proto or 'any'}: {len(rt)} row(s)")
        if len(rt):
            print(rt.to_string())

    print("=" * 66)
    print("FACT 4 -- all /32s any router learned via OSPF")
    rt = bf.q.routes(protocols="ospf").answer().frame()
    if len(rt):
        stub = rt[rt["Network"].astype(str).str.endswith("/32")]
        print(f"  {len(stub)} OSPF-learned /32 route(s) across the topology")
        if len(stub):
            print(stub.to_string())
    else:
        print("  NO OSPF ROUTES AT ALL -- something much more basic is wrong")

    print("=" * 66)
    print("READING THIS:")
    print("  lo has an address + lo is in OSPF + FACT 3 empty")
    print("      -> Batfish does not originate FRR loopback stubs. P11 is")
    print("         unusable as written; rewrite it against a transit address")
    print("         or drop it from the suite BEFORE the full run.")
    print("  lo has NO address")
    print("      -> the interfaces-file loopback stanza is not being parsed;")
    print("         this also means router-id provenance is model-only.")
    print("  FACT 3 non-empty")
    print("      -> the model is fine and P11's failure is real; the fault or")
    print("         repair genuinely partitions the loopbacks. Investigate P11")
    print("         on the GOLDEN, which must pass by construction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
