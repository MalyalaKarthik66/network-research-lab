"""ZERO-INFLATION DIAGNOSTIC -- how much of the corpus is a trivial r = 0?

    python pipeline/run_zeroinflation.py --pilot data/pilot-v2 \
        --workdir /root/nrl-zi --candidates 30

THE QUESTION

Phase 2 established that r(x) -- the fraction of flows a repair breaks or
reroutes -- is graded and non-degenerate. But both of its two zeros were
`correct` repairs, and `correct` is 153 of 299 candidates (51%) and recoverable
from the config diff at AUC 0.999.

If every `correct` repair scores exactly 0, then half the training set is a
trivially predictable zero attached to a class the model can already identify
perfectly, and "the model predicts risk" collapses back into "the model
recognises the operator" on that half. The learnable task would live only among
the rest.

Designing the generator upgrade without knowing this number would be guessing.
So measure it before building anything:

    P(r = 0 | repair_class)   for correct / incomplete / regressive
    the distribution of r within each class
    whether any `correct` repair moves traffic at all

TWO MEASUREMENTS, ONE LAB

  r_sampled   probed flows (data-plane truth: did the packet arrive?)
  r_allpaths  EVERY ordered endpoint pair, forwarding path reconstructed from
              the RIBs the run already captured

The second is exact rather than sampled and costs nothing -- no probes, no extra
time. It matters here specifically: a `correct` repair that moves one obscure
path could be missed by a 24-flow sample and would then be recorded as a clean
zero, which is the very thing this diagnostic exists to rule out. Where the two
disagree, that disagreement is itself a finding: the RIB says the route changed
and the data plane still delivered, or vice versa.

Candidates are drawn only from topologies whose golden baseline already exists
from Phase 2, so this costs 30 candidate labs and no golden labs.

Writes only to analysis/zeroinflation/. data/ is opened read-only.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import platform
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl import clab                                              # noqa: E402
from nrl import flowmatrix as fm                                  # noqa: E402
from nrl.topologies import resolve as resolve_topology            # noqa: E402

#: quotas -- deliberately NOT proportional. `correct` is the class under
#: suspicion and `incomplete` showed the widest spread in Phase 2, so the budget
#: goes where the uncertainty is, not where the rows are.
QUOTA = {"correct": 12, "incomplete": 12, "regressive": 6}
FLOWS = 24          # matches the Phase 2 golden flow set so goldens are reused


def _load_rp3():
    spec = importlib.util.spec_from_file_location(
        "_rp3", REPO / "pipeline" / "run_phase3.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wj(p: Path, o) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, indent=2, default=str), encoding="utf-8")


def state_from_disk(run_dir: Path) -> dict:
    """Rebuild the shape measure_paths expects from the saved RIBs.

    Lets any historical run be rescored without re-running it -- which is how
    the Phase 2 goldens are reused here instead of costing six more labs.
    """
    st = {}
    d = run_dir / "state"
    if not d.is_dir():
        return st
    for f in d.glob("*.route.json"):
        try:
            st[f.name[:-len(".route.json")]] = {
                "route": json.loads(f.read_text())}
        except Exception:                                          # noqa: BLE001
            continue
    return st


def all_pairs(spec):
    """Every ordered endpoint pair, as flow records."""
    eps = fm.endpoints(spec)
    return [{"flow_id": f"{s['name']}->{d['name']}",
             "src_name": s["name"], "src_container": s["container"],
             "src_addr": s["addr"], "src_flag": s["src_flag"],
             "dst_name": d["name"], "dst_addr": d["addr"]}
            for s in eps for d in eps if s["addr"] != d["addr"]]


def path_risk(cand_paths: dict, gold_paths: dict) -> dict:
    """r over paths alone. Same rules as flowmatrix.risk, no probe involved."""
    UNDET = ("NO_RIB", "UNKNOWN_NH", "MAX_HOPS")
    BROKEN = ("NO_ROUTE", "LOOP", "BLACKHOLE")
    base = brk = rer = und = 0
    for fid, gp in gold_paths.items():
        if gp["term"] in UNDET or gp["term"] in BROKEN:
            continue                      # golden cannot carry it
        base += 1
        cp = cand_paths.get(fid)
        if cp is None or cp["term"] in UNDET:
            und += 1
        elif cp["term"] in BROKEN:
            brk += 1
        elif (cp["path"], cp["term"]) != (gp["path"], gp["term"]):
            rer += 1
    dec = base - und
    return {"n_pairs": base, "n_broken": brk, "n_rerouted": rer,
            "n_undeterminable": und, "n_decidable": dec,
            "r": round((brk + rer) / dec, 6) if dec else None}


def pick(outcomes_csv: Path, manifest: dict, have_golden: set):
    rows = list(csv.DictReader(outcomes_csv.open(newline="", encoding="utf-8")))
    meta = {c["candidate_id"]: c for c in manifest["candidates"]}
    by = defaultdict(list)
    for r in rows:
        if r["outcome_harm_v1"] not in ("SAFE", "HARMFUL"):
            continue
        m = meta.get(r["candidate_id"])
        if not m or m.get("topology") not in have_golden:
            continue
        by[m["repair_class"]].append({
            "candidate_id": r["candidate_id"], "incident_id": r["incident_id"],
            "topology": m["topology"], "fault_family": m.get("fault_family"),
            "repair_class": m["repair_class"], "repair_id": m.get("repair_id"),
            "frozen_outcome": r["outcome_harm_v1"],
            "signature": ";".join(sorted(
                p for p in r["violations_vs_golden"].split(";") if p))})
    chosen = []
    for cls, want in QUOTA.items():
        items = sorted(by.get(cls, []), key=lambda c: c["candidate_id"])
        # TOPOLOGY-first round-robin, operator-second. Cycling (topology,
        # operator) pairs in sorted order put 19 of 30 in t01_chain4, which has
        # the most candidates AND is the 4-router chain -- the topology with the
        # fewest alternative paths, so the least able to show a reroute. That
        # would have biased P(r=0) downward by construction.
        by_topo = defaultdict(lambda: defaultdict(list))
        for it in items:
            by_topo[it["topology"]][it["repair_id"]].append(it)
        topos = sorted(by_topo)
        if not topos:
            continue
        ti = 0
        got = 0
        while got < want:
            progressed = False
            for _ in range(len(topos)):
                tn = topos[ti % len(topos)]
                ti += 1
                ops = by_topo[tn]
                for op in sorted(ops):
                    if ops[op]:
                        chosen.append(ops[op].pop(0))
                        got += 1
                        progressed = True
                        break
                if progressed:
                    break
            if not progressed:
                break
    return sorted(chosen, key=lambda c: c["candidate_id"])


def preflight(root: Path, workdir: Path) -> bool:
    ok = True

    def chk(n, c, d=""):
        nonlocal ok
        print(f"  [{'OK ' if c else 'FAIL'}] {n}" + (f" -- {d}" if d else ""))
        ok = ok and bool(c)

    print("PREFLIGHT")
    chk("linux", platform.system() == "Linux", platform.system())
    chk("root", hasattr(os, "geteuid") and os.geteuid() == 0)
    chk("docker daemon", clab.run(["docker", "info", "-f", "{{.ServerVersion}}"]
                                  ).get("status") == "OK")
    chk("containerlab", clab.run(["containerlab", "version"]).get("status") == "OK")
    chk("pilot lock", (root / "pilot.lock.json").exists())
    workdir.mkdir(parents=True, exist_ok=True)
    chk("workdir writable", os.access(workdir, os.W_OK), str(workdir))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--candidates", type=int, default=30)
    ap.add_argument("--flows", type=int, default=FLOWS)
    ap.add_argument("--out", default="analysis/zeroinflation")
    ap.add_argument("--golden-from", default="analysis/flowrisk/runs")
    a = ap.parse_args()

    root = (REPO / a.pilot).resolve()
    out = (REPO / a.out).resolve()
    gsrc = (REPO / a.golden_from).resolve()
    workdir = Path(a.workdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not preflight(root, workdir):
        print("\nBLOCKED: preflight failed.")
        return 2

    have_golden = {d.name[len("golden-"):-len("~flow")] for d in gsrc.glob("golden-*~flow")
                   if (d / "state").is_dir()}
    print(f"\ngolden baselines reused from {gsrc}: {sorted(have_golden)}")
    if not have_golden:
        print("BLOCKED: no reusable goldens. Run run_flowrisk.py first.")
        return 2

    rp3 = _load_rp3()
    manifest = json.loads((root / "manifest.json").read_text())
    lock = json.loads((root / "pilot.lock.json").read_text())
    sample = pick(root / "phase3" / "containerlab_outcomes.csv", manifest,
                  have_golden)[:a.candidates]
    print(f"\nsample: {len(sample)} candidates")
    for k, v in sorted(Counter(c["repair_class"] for c in sample).items()):
        print(f"    {k:11s} {v}")
    print(f"    topologies {len({c['topology'] for c in sample})}  "
          f"operators {len({c['repair_id'] for c in sample})}  "
          f"incidents {len({c['incident_id'] for c in sample})}")

    # golden paths over ALL pairs, from the RIBs already on disk
    gold = {}
    for tn in sorted(have_golden):
        spec = resolve_topology(tn)
        gold[tn] = fm.measure_paths(state_from_disk(gsrc / f"golden-{tn}~flow"),
                                    spec, all_pairs(spec))
    print(f"\ngolden all-pair paths reconstructed (no labs run): "
          f"{ {k: len(v) for k, v in gold.items()} }")

    sink: dict = {}
    plan: dict = {"p": None}
    fm.install(lambda: plan["p"], sink, rp3)

    rows, t0 = [], time.time()
    for n, c in enumerate(sample, 1):
        cid, tn = c["candidate_id"], c["topology"]
        spec = resolve_topology(tn)
        flows = fm.sample_flows(spec, a.flows)
        src = root / "candidates" / cid
        rid = f"{cid}~zi"
        rdir = out / "runs" / rid
        eta = f"  eta {int((time.time()-t0)/max(1,n-1)*(len(sample)-n+1)/60)}m" if n > 1 else ""
        print(f"[{n:3d}/{len(sample)}] {rid}  {c['repair_class']:11s} "
              f"{tn:14s} {c['repair_id']}{eta}", flush=True)
        if (rdir / "run.json").exists():
            rec = json.loads((rdir / "run.json").read_text())
        else:
            plan["p"] = flows
            sink.pop("flowmatrix", None)
            sc = rp3.scenario_for(src, cid, {})
            rec = rp3.run_one(rid, src, workdir, lock, sc, out, False, spec,
                              kind="candidate", attempt=1)
            rec["flowmatrix"] = sink.get("flowmatrix") or {}
            if rec.get("status") == "LAB_INVALID":          # ANALYSIS-PLAN 14.1
                arch = out / "runs" / f"{rid}.attempt1"
                if arch.exists():
                    shutil.rmtree(arch)
                if rdir.exists():
                    rdir.rename(arch)
                print("         LAB_INVALID -- one retry (14.1)")
                sink.pop("flowmatrix", None)
                rec = rp3.run_one(rid, src, workdir, lock, sc, out, False, spec,
                                  kind="candidate", attempt=2)
                rec["flowmatrix"] = sink.get("flowmatrix") or {}
            wj(rdir / "run.json", rec)

        # sampled (probe) risk, and exact all-pair path risk
        gflow = json.loads((gsrc / f"golden-{tn}~flow" / "run.json").read_text()
                           ).get("flowmatrix", {})
        gflow = dict(gflow)
        gflow["paths"] = fm.measure_paths(
            state_from_disk(gsrc / f"golden-{tn}~flow"), spec,
            [{"flow_id": k, "src_name": v["src_name"], "dst_name": v["dst_name"],
              "src_addr": v["src_addr"], "dst_addr": v["dst_addr"]}
             for k, v in gflow.get("flows", {}).items()])
        cflow = dict(rec.get("flowmatrix") or {})
        if "paths" not in cflow:
            cflow["paths"] = fm.measure_paths(
                state_from_disk(rdir), spec,
                [{"flow_id": k, "src_name": v["src_name"],
                  "dst_name": v["dst_name"], "src_addr": v["src_addr"],
                  "dst_addr": v["dst_addr"]}
                 for k, v in cflow.get("flows", {}).items()])
        rs = fm.risk(cflow, gflow)
        cp = fm.measure_paths(state_from_disk(rdir), spec, all_pairs(spec))
        rp = path_risk(cp, gold[tn])
        rows.append({
            "candidate_id": cid, "topology": tn, "incident_id": c["incident_id"],
            "repair_class": c["repair_class"], "repair_id": c["repair_id"],
            "fault_family": c["fault_family"],
            "frozen_outcome": c["frozen_outcome"], "frozen_signature": c["signature"],
            "run_status": rec.get("status"),
            "r_sampled": rs.get("risk_r"),
            "r_sampled_broken": rs.get("risk_r_broken"),
            "r_sampled_rerouted": rs.get("risk_r_rerouted"),
            "r_allpaths": rp["r"], "ap_pairs": rp["n_pairs"],
            "ap_broken": rp["n_broken"], "ap_rerouted": rp["n_rerouted"],
            "ap_undeterminable": rp["n_undeterminable"],
            "wall_seconds": rec.get("wall_seconds"),
        })
        print(f"         {rec.get('status'):13s} r_sampled={rs.get('risk_r')}  "
              f"r_allpaths={rp['r']} (brk={rp['n_broken']} rer={rp['n_rerouted']}"
              f"/{rp['n_decidable']})  {rec.get('wall_seconds')}s")
        with (out / "zeroinflation.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

    fm.uninstall(rp3)

    # ---- report ---------------------------------------------------------
    print("\n" + "=" * 86)
    print("ZERO-INFLATION BY REPAIR CLASS   (r_allpaths: exact, every ordered pair)")
    print("=" * 86)
    summary = {}
    for cls in ("correct", "incomplete", "regressive"):
        rs_ = [r for r in rows if r["repair_class"] == cls
               and r["r_allpaths"] is not None]
        if not rs_:
            continue
        z = [r for r in rs_ if r["r_allpaths"] == 0]
        nz = sorted(r["r_allpaths"] for r in rs_ if r["r_allpaths"] > 0)
        summary[cls] = {"n": len(rs_), "n_zero": len(z),
                        "p_zero": round(len(z) / len(rs_), 4),
                        "nonzero_values": nz,
                        "n_distinct_nonzero": len(set(nz))}
        print(f"  {cls:11s} n={len(rs_):3d}  r=0 in {len(z):3d}  "
              f"P(r=0)={len(z)/len(rs_):.2f}  distinct non-zero={len(set(nz))}")
        if nz:
            print(f"              non-zero r: {[round(x,4) for x in nz]}")
    allv = [r["r_allpaths"] for r in rows if r["r_allpaths"] is not None]
    zero = sum(1 for v in allv if v == 0)
    print(f"\n  OVERALL  n={len(allv)}  r=0 in {zero} ({zero/max(1,len(allv)):.0%})  "
          f"distinct values={len(set(allv))}")
    dis = [r for r in rows if r["r_sampled"] is not None
           and r["r_allpaths"] is not None
           and (r["r_sampled"] == 0) != (r["r_allpaths"] == 0)]
    print(f"  sampled-vs-allpaths zero disagreement: {len(dis)} "
          f"{[d['candidate_id'] for d in dis]}")
    wj(out / "zeroinflation_summary.json", {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_candidates": len(rows), "flows_sampled": a.flows,
        "by_class": summary,
        "overall_zero_fraction": round(zero / max(1, len(allv)), 4),
        "distinct_r_values": sorted(set(allv)),
        "sampled_vs_allpaths_zero_disagreement":
            [d["candidate_id"] for d in dis],
        "wall_seconds": round(time.time() - t0, 1)})
    print(f"\nwrote {out/'zeroinflation.csv'}")
    print(f"wrote {out/'zeroinflation_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
