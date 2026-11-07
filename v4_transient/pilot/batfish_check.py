"""Batfish verdicts for every pilot change. Runs inside WSL with the Batfish service on localhost.

    /mnt/c/Users/karth/network-research-lab/.venv-wsl/bin/python v4_transient/pilot/batfish_check.py

For each change: frozen property suite (nrl.properties, SUITE_VERSION 1.1.0) evaluated by the frozen
nrl.bf_eval; SPEC verdict = P01, P02, P05, P07, P08 all PASS. Population changes MUST pass; positive
controls (shutdown) are expected to FAIL P08. Also recomputes steady-state r from Batfish's own main
RIB (candidate vs golden snapshot) and compares it with the analytic r_exact in the manifest.
Writes manifests/batfish_check.json. Read-only with respect to everything else.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from nrl import flowmatrix as fm                                   # noqa: E402
from nrl import topologies_v3 as T3                                # noqa: E402
from nrl.bf_eval import evaluate_all, frame_to_records             # noqa: E402
from nrl.properties import SPEC, SUITE_VERSION                     # noqa: E402

ART = V4 / "pilot" / "artifacts"
MAN = V4 / "manifests"
SPEC_PIDS = sorted(p["pid"] for p in SPEC)


def rib_state(records):
    ribs = defaultdict(lambda: defaultdict(list))
    for r in records:
        if r.get("VRF", "default") != "default":
            continue
        nh = r.get("Next_Hop") or {}
        typ = str(nh.get("type", "") if isinstance(nh, dict) else nh).lower()
        ip = r.get("Next_Hop_IP")
        try:
            ipaddress.ip_address(ip)
        except (ValueError, TypeError):
            ip = None
        iface = str(r.get("Next_Hop_Interface") or "")
        hole = typ in ("discard", "null") or "null" in iface.lower()
        ribs[r["Node"]][r["Network"]].append({"ip": ip, "blackhole": hole, "proto": str(r["Protocol"]).lower(),
                                              "ad": r.get("Admin_Distance"), "m": r.get("Metric")})
    out = {}
    for node, pref in ribs.items():
        out[node] = {"route": {"json": {p: [{"protocol": n[0]["proto"], "selected": True, "distance": n[0]["ad"],
                                             "metric": n[0]["m"],
                                             "nexthops": [{"ip": x["ip"], "blackhole": x["blackhole"]} for x in n]}]
                                        for p, n in pref.items()}}}
    return out


def paths(state, spec):
    e = fm.endpoints(spec)
    fl = [{"flow_id": f"{s['name']}->{d['name']}", "src_name": s["name"], "dst_name": d["name"],
           "src_addr": s["addr"], "dst_addr": d["addr"]} for s in e for d in e if s["addr"] != d["addr"]]
    return fm.measure_paths(state, spec, fl)


def r_of(cand, gold):
    und, brk = ("NO_RIB", "UNKNOWN_NH", "MAX_HOPS"), ("NO_ROUTE", "LOOP", "BLACKHOLE")
    n = b = rr = u = 0
    for k, g in gold.items():
        if g["term"] in und + brk:
            continue
        n += 1
        c = cand[k]
        if c["term"] in und:
            u += 1
        elif c["term"] in brk:
            b += 1
        elif (c["path"], c["term"]) != (g["path"], g["term"]):
            rr += 1
    return (b + rr) / (n - u) if n - u else None, u


def main() -> int:
    from pybatfish.client.session import Session
    import pybatfish
    logging.getLogger("pybatfish").setLevel(logging.ERROR)
    man = json.loads((MAN / "pilot_manifest.json").read_text())
    bf = Session(host="localhost")
    bf.set_network("nrl-v4-transient-pilot")
    out = {"suite_version": SUITE_VERSION, "spec_pids": SPEC_PIDS, "pybatfish": pybatfish.__version__,
           "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "changes": {}}
    gold_paths = {}
    for t in man["topologies"]:
        name = f"golden-{t}"
        bf.init_snapshot(str(ART / name / "batfish-snapshot"), name=name, overwrite=True)
        bf.set_snapshot(name)
        gold_paths[t] = paths(rib_state(frame_to_records(bf.q.routes().answer().frame())), T3.resolve(t))
    problems = []
    for c in man["changes"]:
        spec = T3.resolve(c["topology"])
        snap = c["batfish_snapshot"]
        name = snap.split("/")[0]
        t0 = time.time()
        bf.init_snapshot(str(ART / snap), name=name, overwrite=True)
        bf.set_snapshot(name)
        bf.generate_dataplane()                            # as pipeline/run_phase2.py does
        props = evaluate_all(bf, spec)
        verdicts = {p["property_id"]: p.get("verdict") for p in props}
        spec_pass = all(verdicts.get(pid) == "PASS" for pid in SPEC_PIDS)
        rbf, und = r_of(paths(rib_state(frame_to_records(bf.q.routes().answer().frame())), spec), gold_paths[c["topology"]])
        r_exact = c["features"]["r_exact"]
        rec = {"kind": c["kind"], "spec_pass": spec_pass, "verdicts": verdicts, "r_batfish": rbf,
               "r_exact": r_exact, "r_match": rbf is not None and abs(rbf - r_exact) < 1e-6,
               "undetermined_flows": und, "seconds": round(time.time() - t0, 2)}
        out["changes"][c["change_id"]] = rec
        expected = not c["kind"].startswith("control_positive")     # A4-retired controls remain SPEC-FAIL
        if spec_pass != expected:
            problems.append(f"{c['change_id']} ({c['kind']}): spec_pass={spec_pass}, expected {expected}")
        if not rec["r_match"]:
            problems.append(f"{c['change_id']}: Batfish r {rbf} != analytic r_exact {r_exact}")
        print(f"{c['change_id']} {c['topology']:13s} {c['role']:9s} SPEC {'PASS' if spec_pass else 'FAIL'} "
              f"r_batfish {rbf} r_exact {r_exact:.6f} {'match' if rec['r_match'] else 'MISMATCH'}", flush=True)
    out["problems"] = problems
    out["verdict"] = "OK" if not problems else "PROBLEMS"
    (MAN / "batfish_check.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8", newline="\n")
    print(f"\nverdict {out['verdict']}; problems: {problems}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
