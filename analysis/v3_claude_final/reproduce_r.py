"""Three-way check of measured r, independent of both Copilot scripts.

(1) nrl.flowmatrix RIB walk over EVERY ordered endpoint pair, on the Phase 3
    emulator RIBs (golden run vs candidate run);
(2) nrl.severity analytic Dijkstra on the topology spec -- no emulator at all;
(3) analysis/v3_independent/independent_r.csv, Copilot's own reimplementation.
If all three agree, measured r is established by two genuinely different
mechanisms (emulator state vs pure graph computation).
"""
import csv, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(REPO))
from nrl import flowmatrix as fm, topologies_v3 as T3, repairs_v3 as R3
from nrl.severity import Fabric
from nrl.scenario_io import read as read_sc

root = REPO / "data/pilot-v3"; runs = root / "phase3/runs"
man = json.loads((root / "manifest.json").read_text())

def state(rd):
    return {f.name[:-11]: {"route": json.loads(f.read_text())}
            for f in (rd / "state").glob("*.route.json")}

def pairs(spec):
    e = fm.endpoints(spec)
    return [{"flow_id": f"{s['name']}->{d['name']}", "src_name": s["name"],
             "dst_name": d["name"], "src_addr": s["addr"], "dst_addr": d["addr"]}
            for s in e for d in e if s["addr"] != d["addr"]]

UND = ("NO_RIB", "UNKNOWN_NH", "MAX_HOPS"); BRK = ("NO_ROUTE", "LOOP", "BLACKHOLE")
def rib_r(cp, gp):
    n = b = rr = u = 0
    for k, g in gp.items():
        if g["term"] in UND or g["term"] in BRK: continue
        n += 1; c = cp.get(k)
        if c is None or c["term"] in UND: u += 1
        elif c["term"] in BRK: b += 1
        elif (c["path"], c["term"]) != (g["path"], g["term"]): rr += 1
    d = n - u
    return n, b, rr, u, (b + rr) / d if d else None

gold = {}
cop = {r["candidate_id"]: r for r in csv.DictReader(
    (REPO / "analysis/v3_independent/independent_r.csv").open(newline="", encoding="utf8"))}
rows = []; mism_cop = mism_an = 0
for c in man["candidates"]:
    tn, cid = c["topology"], c["candidate_id"]
    spec = T3.resolve(tn); P = pairs(spec)
    if tn not in gold:
        gold[tn] = fm.measure_paths(state(runs / f"golden-{tn}"), spec, P)
    cp = fm.measure_paths(state(runs / cid), spec, P)
    n, b, rr, u, r = rib_r(cp, gold[tn])
    # analytic: apply the candidate's actual scenario change to the Fabric
    sc = read_sc(root / "candidates" / cid / "scenario.json")
    fab = Fabric(spec); g = __import__("nrl.topologies", fromlist=["build_golden"]).build_golden(spec)
    cost_ov, bh = {}, []
    for nd, dv in sc.devices.items():
        gd = g.devices[nd]
        for f in dv.ifaces:
            gf = next(x for x in gd.ifaces if x.name == f.name)
            if f.ospf_cost != gf.ospf_cost:
                for (a, ai, aa, bb, bi, ba, *_rest) in spec.links:
                    if (a == nd and ai == f.name) or (bb == nd and bi == f.name):
                        cost_ov[tuple(sorted((a, bb)))] = f.ospf_cost
        for s in dv.statics or []:
            if str(s.nexthop).lower() == "blackhole":
                ep = next(e for e, _ in fab.endpoints if R3.endpoint_prefix(spec, e) == s.prefix)
                bh.append((nd, ep))
    an = fab.predict(cost_override=cost_ov or None, blackholes=bh)["r"]
    cr = float(cop[cid]["r"]) if cid in cop else None
    mism_cop += (cr is None or abs(cr - r) > 5e-6)
    mism_an += (an is None or abs(an - r) > 5e-6)
    rows.append({"candidate_id": cid, "topology": tn, "mechanism": c["mechanism"],
                 "golden_flows": n, "broken": b, "rerouted": rr, "undet": u,
                 "r_rib": round(r, 6), "r_analytic_from_scenario": round(an, 6),
                 "r_copilot": cr, "pred_manifest": c["predicted_severity"]})
out = REPO / "analysis/v3_claude_final/r_three_way.csv"
with out.open("w", newline="", encoding="utf8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
import statistics as st
rs = [x["r_rib"] for x in rows]
print(f"candidates {len(rows)}  undetermined flows total {sum(x['undet'] for x in rows)}")
print(f"RIB-walk vs Copilot independent_r.csv  mismatches: {mism_cop}")
print(f"RIB-walk vs analytic-from-actual-scenario mismatches: {mism_an}")
print(f"r: distinct {len(set(rs))} mean {st.mean(rs):.6f} median {st.median(rs):.6f} "
      f"min {min(rs):.6f} max {max(rs):.6f} zeros {sum(1 for v in rs if v==0)}")
print(f"golden_flows range {min(x['golden_flows'] for x in rows)}-{max(x['golden_flows'] for x in rows)}")
print(f"broken>0 in {sum(1 for x in rows if x['broken']>0)} cands; rerouted>0 in {sum(1 for x in rows if x['rerouted']>0)}")
