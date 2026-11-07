"""Does Batfish ALONE, pre-deployment, reproduce the emulator forwarding paths and r?

Exploratory. Converts each candidate's saved Batfish main RIB (phase2/raw/<C>/questions/routes.json)
into the per-router route format nrl.flowmatrix walks, then compares, for every ordered endpoint
pair, the Batfish path with the Phase 3 FRR path of the same candidate. Also recomputes r with
Batfish candidate paths against the golden paths (FRR golden run; and, where a topology has an
RC-noop candidate, against that noop candidate Batfish paths).
"""
import ipaddress, json, sys
from collections import defaultdict
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(REPO))
import pandas as pd
from nrl import flowmatrix as fm, topologies_v3 as T3

root = REPO / "data/pilot-v3"; runs = root / "phase3/runs"
man = json.loads((root / "manifest.json").read_text())
UND = ("NO_RIB", "UNKNOWN_NH", "MAX_HOPS"); BRK = ("NO_ROUTE", "LOOP", "BLACKHOLE")


def bf_state(cid):
    recs = json.loads((root / "phase2/raw" / cid / "questions/routes.json").read_text())["records"]
    ribs = defaultdict(lambda: defaultdict(list))
    for r in recs:
        if r.get("VRF", "default") != "default":
            continue
        nh = r.get("Next_Hop") or {}
        typ = str(nh.get("type", "")).lower()
        ip = r.get("Next_Hop_IP")
        try:
            ipaddress.ip_address(ip)
        except (ValueError, TypeError):
            ip = None
        iface = str(r.get("Next_Hop_Interface") or "")
        hole = typ in ("discard", "null") or "null" in iface.lower()
        ribs[r["Node"]][r["Network"]].append({"ip": ip, "blackhole": hole, "interfaceName": iface,
                                              "_proto": str(r["Protocol"]).lower(),
                                              "_ad": r.get("Admin_Distance"), "_m": r.get("Metric")})
    state = {}
    for node, pref in ribs.items():
        out = {}
        for p, nhs in pref.items():
            out[p] = [{"protocol": nhs[0]["_proto"], "selected": True, "installed": True,
                       "distance": nhs[0]["_ad"], "metric": nhs[0]["_m"],
                       "nexthops": [{"ip": x["ip"], "blackhole": x["blackhole"],
                                     "interfaceName": x["interfaceName"]} for x in nhs]}]
        state[node] = {"route": {"json": out}}
    return state


def frr_state(rd):
    return {f.name[:-11]: {"route": json.loads(f.read_text())} for f in (rd / "state").glob("*.route.json")}


def pairs(spec):
    e = fm.endpoints(spec)
    return [{"flow_id": s["name"] + "->" + d["name"], "src_name": s["name"], "dst_name": d["name"],
             "src_addr": s["addr"], "dst_addr": d["addr"]} for s in e for d in e if s["addr"] != d["addr"]]


def r_of(cp, gp):
    n = b = rr = u = 0
    for k, g in gp.items():
        if g["term"] in UND or g["term"] in BRK:
            continue
        n += 1; c = cp.get(k)
        if c is None or c["term"] in UND: u += 1
        elif c["term"] in BRK: b += 1
        elif (c["path"], c["term"]) != (g["path"], g["term"]): rr += 1
    d = n - u
    return (b + rr) / d if d else None, u


meas = pd.read_csv(REPO / "analysis/v3_claude_final/r_three_way.csv").set_index("candidate_id")
noop = {}
for c in man["candidates"]:
    if c["repair_id"].startswith("RC-noop"):
        noop.setdefault(c["topology"], c["candidate_id"])
rows, flows_total, flows_equal = [], 0, 0
gold_frr, gold_bf = {}, {}
for c in man["candidates"]:
    tn, cid = c["topology"], c["candidate_id"]
    spec = T3.resolve(tn); P = pairs(spec)
    if tn not in gold_frr:
        gold_frr[tn] = fm.measure_paths(frr_state(runs / ("golden-" + tn)), spec, P)
        gold_bf[tn] = fm.measure_paths(bf_state(noop[tn]), spec, P) if tn in noop else None
    bp = fm.measure_paths(bf_state(cid), spec, P)
    fp = fm.measure_paths(frr_state(runs / cid), spec, P)
    eq = sum((bp[k]["path"], bp[k]["term"]) == (fp[k]["path"], fp[k]["term"]) for k in fp)
    flows_total += len(fp); flows_equal += eq
    r_bf_vs_frr_golden, und = r_of(bp, gold_frr[tn])
    r_bf_only = r_of(bp, gold_bf[tn])[0] if gold_bf[tn] is not None else None
    rows.append({"candidate_id": cid, "topology": tn, "flows": len(fp), "flows_path_equal": eq,
                 "r_measured": meas.loc[cid, "r_rib"], "r_batfish_vs_frr_golden": r_bf_vs_frr_golden,
                 "r_batfish_vs_batfish_noop": r_bf_only, "undetermined": und})
df = pd.DataFrame(rows)
df.to_csv(REPO / "analysis/v3_expansion_planning/batfish_computes_r.csv", index=False)
ok = df.dropna(subset=["r_batfish_vs_frr_golden"])
m1 = (ok.r_batfish_vs_frr_golden - ok.r_measured).abs()
ok2 = df.dropna(subset=["r_batfish_vs_batfish_noop"])
m2 = (ok2.r_batfish_vs_batfish_noop - ok2.r_measured).abs()
print("candidates", len(df), " per-flow path+terminal equality Batfish vs FRR:", flows_equal, "/", flows_total,
      "=", round(flows_equal / flows_total, 6))
print("candidates with ALL flows equal:", int((df.flows == df.flows_path_equal).sum()), "/", len(df))
print("r from Batfish candidate RIB vs FRR golden: exact(<=1e-6)", int((m1 <= 1e-6).sum()), "/", len(ok),
      " MAE", round(m1.mean(), 8), " undetermined flows", int(df.undetermined.sum()))
print("r from Batfish ONLY (candidate vs noop candidate in same topology):", int((m2 <= 1e-6).sum()), "/", len(ok2),
      " MAE", round(m2.mean(), 8), " topologies with a noop:", sorted(noop))
bad = df[df.flows != df.flows_path_equal]
if len(bad):
    print("mismatching candidates:", bad[["candidate_id", "topology", "flows", "flows_path_equal"]].head(10).to_dict("records"))
