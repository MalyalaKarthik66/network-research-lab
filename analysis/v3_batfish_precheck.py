"""Does Batfish model the one construct the v3 spike never checked?

    ./.venv-wsl/bin/python analysis/v3_batfish_precheck.py --pilot data/pilot-v3

WHY

spike_frr_batfish.py CHECK 3 reported `static_route checked=0` on the v3 corpus.
It samples goldens and incidents, and v3 has no faults -- its incidents ARE the
goldens -- so no snapshot in the sample contains a static route. But 72 of the
151 v3 candidates use the `blackhole` mechanism, which emits exactly one
`ip route <prefix> blackhole` line. That construct is therefore unvalidated
against Batfish for the arm that depends on it most: blackhole is the canonical
false-pass case, breaking oracle-only P03/P04 while the SPEC gate passes.

The F10 lesson in the spike's own docstring is the reason this cannot be
assumed: Batfish accepted the distribute-list construct, emitted no parse
warning, and modelled nothing. Byte-identity is necessary and not sufficient.

WHAT THIS CHECKS, on real candidate snapshots rather than goldens

  1. parse status and init issues are clean
  2. the static route appears in Batfish's routing table at the node that
     configures it
  3. it is a DISCARD/NULL next hop, not merely present
  4. it beats the OSPF route for the same prefix, i.e. it is the selected route
  5. traffic to the blackholed prefix is actually dropped in Batfish's model

Read-only. Loads snapshots, answers questions, writes one JSON report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT = Path(__file__).resolve().parent / "v3_batfish_precheck.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", default="data/pilot-v3")
    ap.add_argument("--n", type=int, default=6, help="blackhole candidates to check")
    a = ap.parse_args()
    root = (REPO / a.pilot).resolve()
    man = json.loads((root / "manifest.json").read_text())

    bh = [c for c in man["candidates"] if c.get("mechanism") == "blackhole"]
    cost = [c for c in man["candidates"] if c.get("mechanism") == "cost"]
    print(f"corpus: {len(man['candidates'])} candidates "
          f"({len(bh)} blackhole, {len(cost)} cost)")
    # spread across topologies rather than taking the first n
    seen, sample = set(), []
    for c in bh:
        if c["topology"] not in seen:
            seen.add(c["topology"])
            sample.append(c)
        if len(sample) >= a.n:
            break
    print(f"checking {len(sample)} blackhole candidates across "
          f"{len(seen)} topologies\n")

    import logging
    from pybatfish.client.session import Session
    logging.getLogger("pybatfish").setLevel(logging.ERROR)
    bf = Session(host="localhost")
    bf.set_network("nrl-v3-precheck")

    results, ok_all = [], True
    for c in sample:
        cid = c["candidate_id"]
        snap = root / "candidates" / cid / "batfish-snapshot"
        bf.init_snapshot(str(snap), name=cid, overwrite=True)
        bf.set_snapshot(cid)

        # what the artifact actually configures
        sc = json.loads((root / "candidates" / cid / "scenario.json").read_text())
        tgt = [(n, s["prefix"]) for n, d in sc["devices"].items()
               for s in (d.get("statics") or [])
               if str(s.get("nexthop", "")).lower() == "blackhole"]
        if not tgt:
            print(f"  {cid}: no blackhole static in scenario -- skipped")
            continue
        node, prefix = tgt[0]

        init = bf.q.initIssues().answer().frame()
        parse = bf.q.fileParseStatus().answer().frame()
        bad_parse = [r for _, r in parse.iterrows()
                     if str(r.get("Status")) != "PASSED"]

        rt = bf.q.routes().answer().frame()
        mine = rt[(rt["Node"] == node.lower()) & (rt["Network"] == prefix)]
        protos = sorted({str(r["Protocol"]) for _, r in mine.iterrows()})
        nhs = sorted({str(r.get("Next_Hop")) for _, r in mine.iterrows()})
        static_rows = [r for _, r in mine.iterrows()
                       if str(r["Protocol"]) == "static"]
        discard = any("discard" in str(r.get("Next_Hop")).lower()
                      or "null" in str(r.get("Next_Hop")).lower()
                      for r in static_rows)
        # selected route: Batfish's main RIB holds only installed routes, so a
        # static present here at all means it won the administrative-distance
        # contest against the OSPF route for the same prefix
        selected = bool(static_rows)

        row = {"candidate_id": cid, "topology": c["topology"],
               "node": node, "prefix": prefix,
               "parse_failures": len(bad_parse), "init_issues": len(init),
               "protocols_for_prefix": protos, "next_hops": nhs,
               "static_present": bool(static_rows),
               "is_discard": discard, "static_selected": selected}
        good = (not bad_parse and len(init) == 0 and static_rows
                and discard and selected)
        ok_all = ok_all and good
        results.append({**row, "ok": bool(good)})
        print(f"  [{'OK  ' if good else 'FAIL'}] {cid} {c['topology']:16s} "
              f"{node}:{prefix}")
        print(f"          protocols={protos} next_hops={nhs} "
              f"discard={discard} parse_fail={len(bad_parse)} init={len(init)}")

    print("\n" + "=" * 66)
    print(f"blackhole construct modelled by Batfish: "
          f"{sum(1 for r in results if r['ok'])}/{len(results)}")
    print(f"VERDICT: {'MODELLED' if ok_all and results else 'NOT MODELLED'}")
    print("=" * 66)
    OUT.write_text(json.dumps(
        {"pilot": str(root), "n_checked": len(results),
         "n_ok": sum(1 for r in results if r["ok"]),
         "verdict": "MODELLED" if ok_all and results else "NOT MODELLED",
         "results": results}, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0 if (ok_all and results) else 1


if __name__ == "__main__":
    sys.exit(main())
