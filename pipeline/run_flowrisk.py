"""PHASE 2 -- does flow-level measurement produce a real probability?

    python pipeline/run_flowrisk.py --pilot data/pilot-v2 --workdir /root/nrl-flow \
        --candidates 12 --replicates 2 --no-churn

THE QUESTION

Gate 0 established that the steady-state label is deterministic: 40/40 perturbed
runs reproduced their frozen outcome exactly. But that label is one bit produced
by four probes thresholded at 100% packet loss, and the underlying damage is not
one bit -- 79 harmful candidates produce only six distinct violation signatures,
ranging from "traffic takes the backup WAN" to "the network is down".

This measures r(x), the fraction of the topology's flows that the repair breaks,
against the golden baseline (nrl/flowmatrix.py). If r(x) lands strictly between
0 and 1 for a meaningful share of candidates, a calibrated risk model has a
target to aim at. If r(x) is still stuck at 0 or 1, it is not the instrument --
harm in this domain really is all-or-nothing, and the ML arm is finished.

r(x) = (flows broken + flows rerouted) / (flows the golden network carries),
where a flow's forwarding path is reconstructed from the RIBs each run already
captures. Connectivity alone was blind to 53% of the harm; hop count was
sign-inverted on the backup link; OSPF cost was false-positive on cost
renumbering. See nrl.flowmatrix.forwarding_path for what each one got wrong.

PRE-REGISTERED GATE, fixed before the first lab:

    >= 8 of 12 candidates with 0 < r(x) < 1, AND >= 5 distinct values of r(x)
        -> PROCEED to the generator upgrade and pilot corpus
    otherwise
        -> STOP the ML arm; publish the measurement study

Churn is OFF by default here. Phase 2 asks whether the DAMAGE is graded, which
is a property of the repair. Environmental variance is a separate mechanism,
already built and validated, and mixing them would make a null result
uninterpretable.

Writes only to analysis/flowrisk/. data/ is opened read-only.
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
from nrl import env_randomize as envr                             # noqa: E402
from nrl import flowmatrix as fm                                  # noqa: E402
from nrl.scenario_io import read as read_scenario                 # noqa: E402
from nrl.topologies import resolve as resolve_topology            # noqa: E402

#: PHASE 2b GATE -- re-registered after Phase 2a failed 4/12 on connectivity
#: alone. The target changed, so the criterion changed with it: Phase 2a asked
#: for probability mass away from 0 and 1 (right for a binary event), this asks
#: for a NON-DEGENERATE CONTINUOUS target (right for a fraction-of-flows
#: regression). Fixed before the run. This is the second and final measurement
#: change; if it fails, the ML arm stops and the measurement study is the paper.
GATE_MIN_NONDEGENERATE = 8      # candidates with 0 < r_total < 1
GATE_MIN_DISTINCT = 5           # distinct values of r_total
GATE_LO, GATE_HI = 0.0, 1.0


def _load_rp3():
    spec = importlib.util.spec_from_file_location(
        "_rp3", REPO / "pipeline" / "run_phase3.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def wj(p: Path, o) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, indent=2, default=str), encoding="utf-8")


def _mean(xs):
    """Mean over the values that exist. Dividing by the row count instead
    would quietly deflate a candidate whose probe errored on one replicate."""
    v = [x for x in xs if x is not None]
    return round(sum(v) / len(v), 6) if v else None


def pick(outcomes_csv: Path, manifest: dict, n: int):
    """Span the damage spectrum, not the class labels.

    Stratifying by repair_class would spend the budget on `correct` (0/153
    harmful) and tell us nothing about gradation. The six violation signatures
    ARE the gradation the frozen label discards, so sample across those, plus
    SAFE candidates as the r(x)=0 anchor.
    """
    rows = list(csv.DictReader(outcomes_csv.open(newline="", encoding="utf-8")))
    meta = {c["candidate_id"]: c for c in manifest["candidates"]}
    by_sig = defaultdict(list)
    for r in rows:
        if r["outcome_harm_v1"] not in ("SAFE", "HARMFUL"):
            continue
        m = meta.get(r["candidate_id"])
        if not m:
            continue
        sig = tuple(sorted(p for p in r["violations_vs_golden"].split(";") if p))
        by_sig[sig or ("SAFE",)].append({
            "candidate_id": r["candidate_id"], "incident_id": r["incident_id"],
            "topology": m.get("topology"), "fault_family": m.get("fault_family"),
            "repair_class": m.get("repair_class"), "repair_id": m.get("repair_id"),
            "frozen_outcome": r["outcome_harm_v1"], "signature": ";".join(sig)})
    order = sorted(by_sig, key=lambda s: (-len(by_sig[s]), s))
    chosen, i = [], 0
    while len(chosen) < n and any(by_sig[s] for s in order):
        s = order[i % len(order)]
        pool = sorted(by_sig[s], key=lambda c: c["candidate_id"])
        if pool:
            chosen.append(pool[0])
            by_sig[s] = pool[1:]
        i += 1
    return sorted(chosen[:n], key=lambda c: c["candidate_id"])


def preflight(root: Path, workdir: Path) -> bool:
    ok = True

    def chk(name, cond, detail=""):
        nonlocal ok
        print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
        ok = ok and bool(cond)

    print("PREFLIGHT")
    chk("linux", platform.system() == "Linux", platform.system())
    chk("root", hasattr(os, "geteuid") and os.geteuid() == 0)
    d = clab.run(["docker", "info", "--format", "{{.ServerVersion}}"])
    chk("docker daemon", d.get("status") == "OK", (d.get("stdout") or "").strip())
    chk("containerlab", clab.run(["containerlab", "version"]).get("status") == "OK")
    chk("pilot lock", (root / "pilot.lock.json").exists())
    workdir.mkdir(parents=True, exist_ok=True)
    chk("workdir writable", os.access(workdir, os.W_OK), str(workdir))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--candidates", type=int, default=12)
    ap.add_argument("--replicates", type=int, default=2)
    ap.add_argument("--flows", type=int, default=fm.DEFAULT_N_FLOWS)
    ap.add_argument("--no-churn", action="store_true")
    ap.add_argument("--out", default="analysis/flowrisk")
    a = ap.parse_args()

    root = (REPO / a.pilot).resolve()
    out = (REPO / a.out).resolve()
    workdir = Path(a.workdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not preflight(root, workdir):
        print("\nBLOCKED: preflight failed.")
        return 2

    rp3 = _load_rp3()
    manifest = json.loads((root / "manifest.json").read_text())
    lock = json.loads((root / "pilot.lock.json").read_text())
    sample = pick(root / "phase3" / "containerlab_outcomes.csv", manifest,
                  a.candidates)
    topos = sorted({c["topology"] for c in sample})

    print(f"\nsample: {len(sample)} candidates over {len(topos)} topologies")
    for k, v in sorted(Counter(c["signature"] or "SAFE" for c in sample).items()):
        print(f"    signature {k or 'SAFE':45s} {v}")
    print(f"churn: {'OFF (damage gradation only)' if a.no_churn else 'ON'}")
    print(f"flows per topology: {a.flows}")

    flow_sink: dict = {}
    plan_holder: dict = {"plan": None}
    fm.install(lambda: plan_holder["plan"], flow_sink, rp3)
    env_sink: dict = {}
    cur_env: dict = {"env": None}
    if not a.no_churn:
        envr.install(lambda: cur_env["env"], env_sink)

    def run(run_id, src, spec, scenario, kind, env=None, flows=None):
        """One lab, with the frozen LAB_INVALID retry policy applied.

        ANALYSIS-PLAN 14.1 allows exactly one retry of the SAME artifact when
        `verify_ospf_binding` reports MISMATCH -- the S-020 containerlab race
        where ospfd ends up unbound to an interface the artifact puts in OSPF.
        run_phase3's own loop implements this; calling run_one directly skipped
        it, and Phase 2b lost C-00982~f0 silently: the candidate was scored
        from one replicate while n_runs reported two. The trigger is evaluated
        before any property is measured, so it cannot see the label and cannot
        select on it.
        """
        rdir = out / "runs" / run_id
        plan_holder["plan"] = flows
        cur_env["env"] = env
        flow_sink.pop("flowmatrix", None)
        if (rdir / "run.json").exists():
            return json.loads((rdir / "run.json").read_text())

        def _one(attempt):
            flow_sink.pop("flowmatrix", None)
            r = rp3.run_one(run_id, src, workdir, lock, scenario, out, False,
                            spec, kind=kind, attempt=attempt)
            r["flowmatrix"] = flow_sink.get("flowmatrix") or {}
            if env is not None:
                r["gate0"] = env_sink.get("perturbation") or {}
            return r

        rec = _one(1)
        attempts = 1
        if rec.get("status") == "LAB_INVALID":
            arch = out / "runs" / f"{run_id}.attempt1"
            if arch.exists():
                shutil.rmtree(arch)
            if rdir.exists():
                rdir.rename(arch)
            print(f"         LAB_INVALID -- one retry (ANALYSIS-PLAN 14.1); "
                  f"attempt 1 archived to {arch.name}")
            rec = _one(2)
            attempts = 2
        rec["_attempts"] = attempts
        wj(rdir / "run.json", rec)
        return rec

    t0 = time.time()
    # ---- 1. golden baselines, one per topology, never perturbed -----------
    print(f"\n=== 1. GOLDEN BASELINES ({len(topos)} labs) ===")
    baseline = {}
    for i, tn in enumerate(topos, 1):
        spec = resolve_topology(tn)
        flows = fm.sample_flows(spec, a.flows)
        src = root / "reference" / f"golden-{tn}"
        sc = rp3.scenario_for(src, f"golden-{tn}", {})
        print(f"[{i:2d}/{len(topos)}] golden-{tn}  ({len(flows)} flows)", flush=True)
        rec = run(f"golden-{tn}~flow", src, spec, sc, "golden", None, flows)
        f = rec.get("flowmatrix") or {}
        baseline[tn] = f
        # n_with_ttl is the one to watch: no TTL means no hop count, which
        # silently disables degradation detection -- the entire point of 2b.
        print(f"         {rec.get('status')}  reachable={f.get('n_reachable')}/"
              f"{f.get('n_flows')} ttl={f.get('n_with_ttl')} "
              f"err={f.get('n_error')}  {rec.get('wall_seconds')}s")

    # ---- 2. candidates ----------------------------------------------------
    todo = [(c, r) for c in sample for r in range(a.replicates)]
    print(f"\n=== 2. CANDIDATES ({len(todo)} labs) ===")
    rows = []
    for n, (c, rep) in enumerate(todo, 1):
        cid, tn = c["candidate_id"], c["topology"]
        spec = resolve_topology(tn)
        flows = fm.sample_flows(spec, a.flows)
        src = root / "candidates" / cid
        sc = rp3.scenario_for(src, cid, {})
        env = None
        if not a.no_churn:
            inc = root / "incidents" / c["incident_id"]
            env = envr.sample_environment(
                cid, rep, spec,
                read_scenario(src / "scenario.json") if (src / "scenario.json").exists() else None,
                read_scenario(inc / "scenario.json") if (inc / "scenario.json").exists() else None)
        eta = f"  eta {int((time.time()-t0)/max(1,n-1)*(len(todo)-n+1)/60)}m" if n > 1 else ""
        print(f"[{n:3d}/{len(todo)}] {cid}~f{rep}  {c['signature'] or 'SAFE'}{eta}", flush=True)
        rec = run(f"{cid}~f{rep}", src, spec, sc, "candidate", env, flows)
        risk = fm.risk(rec.get("flowmatrix") or {}, baseline.get(tn) or {})
        rows.append({
            "run_id": f"{cid}~f{rep}", "candidate_id": cid, "replicate": rep,
            "incident_id": c["incident_id"], "topology": tn,
            "fault_family": c["fault_family"], "repair_class": c["repair_class"],
            "repair_id": c["repair_id"], "frozen_outcome": c["frozen_outcome"],
            "frozen_signature": c["signature"], "run_status": rec.get("status"),
            **{k: v for k, v in risk.items()
               if k not in ("broken_flows", "rerouted_flows")},
            "broken_flows": ";".join(risk.get("broken_flows") or []),
            "rerouted_flows": ";".join(risk.get("rerouted_flows") or []),
            "attempts": rec.get("_attempts", 1),
            "wall_seconds": rec.get("wall_seconds"),
        })
        print(f"         {rec.get('status'):14s} r={risk.get('risk_r')}  "
              f"broken={risk.get('n_broken')} rerouted={risk.get('n_rerouted')}"
              f" /{risk.get('n_decidable')}  "
              f"undet={risk.get('n_undeterminable')}  {rec.get('wall_seconds')}s")
        with (out / "flowrisk_runs.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

    fm.uninstall(rp3)
    if not a.no_churn:
        envr.uninstall()

    # ---- 3. per-candidate aggregation and the gate ------------------------
    agg = []
    by = defaultdict(list)
    for r in rows:
        by[r["candidate_id"]].append(r)
    for cid, rs in sorted(by.items()):
        vals = [r["risk_r"] for r in rs if r["risk_r"] is not None]
        mean = sum(vals) / len(vals) if vals else None
        c0 = rs[0]
        agg.append({
            "candidate_id": cid, "topology": c0["topology"],
            "repair_class": c0["repair_class"], "repair_id": c0["repair_id"],
            "frozen_outcome": c0["frozen_outcome"],
            "frozen_signature": c0["frozen_signature"],
            "n_runs": len(rs), "risk_values": ";".join(str(v) for v in vals),
            "risk_mean": round(mean, 6) if mean is not None else None,
            "risk_min": min(vals) if vals else None,
            "risk_max": max(vals) if vals else None,
            "broken_mean": _mean([r["risk_r_broken"] for r in rs]),
            "rerouted_mean": _mean([r["risk_r_rerouted"] for r in rs]),
            "intermediate": (mean is not None and GATE_LO < mean < GATE_HI),
        })
    with (out / "flowrisk_candidates.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(agg[0].keys()))
        w.writeheader(); w.writerows(agg)

    scored = [x for x in agg if x["risk_mean"] is not None]
    inter = [x for x in scored if x["intermediate"]]
    distinct = sorted({x["risk_mean"] for x in scored})
    pass_n = len(inter) >= GATE_MIN_NONDEGENERATE
    pass_d = len(distinct) >= GATE_MIN_DISTINCT
    verdict = "PROCEED" if (pass_n and pass_d) else "STOP"
    summary = {
        "generated_utc": now(), "phase": "2b -- flow-level risk viability",
        "target": "r_total = (broken + degraded) / golden-carried flows",
        "candidates": len(agg), "replicates": a.replicates,
        "flows_per_topology": a.flows, "churn": not a.no_churn,
        "labs": len(rows) + len(topos),
        "candidates_scored": len(scored),
        "candidates_nondegenerate": len(inter),
        "distinct_r_values": distinct,
        "n_distinct": len(distinct),
        "gate_min_nondegenerate": GATE_MIN_NONDEGENERATE,
        "gate_min_distinct": GATE_MIN_DISTINCT,
        "gate_nondegenerate_pass": pass_n,
        "gate_distinct_pass": pass_d,
        "verdict": verdict,
        "wall_seconds": round(time.time() - t0, 1),
    }
    wj(out / "flowrisk_summary.json", summary)

    print("\n" + "=" * 84)
    print(f"{'candidate':13s} {'class':11s} {'signature':22s} "
          f"{'brk':>5s} {'rer':>5s} {'r_total':>8s}")
    for x in sorted(agg, key=lambda x: -(x["risk_mean"] or 0)):
        sig = (x["frozen_signature"] or "SAFE")[:22]
        print(f"{x['candidate_id']:13s} {x['repair_class']:11s} {sig:22s} "
              f"{(x['broken_mean'] or 0):5.2f} {(x['rerouted_mean'] or 0):5.2f} "
              f"{(x['risk_mean'] if x['risk_mean'] is not None else float('nan')):8.3f}"
              + ("  <--" if x["intermediate"] else ""))
    print("=" * 84)
    print(f"PHASE 2b GATE (both must pass, fixed before the run):")
    print(f"  non-degenerate 0 < r < 1 : {len(inter):2d}/{len(scored)}  "
          f"need >= {GATE_MIN_NONDEGENERATE}   {'PASS' if pass_n else 'FAIL'}")
    print(f"  distinct r values        : {len(distinct):2d}     "
          f"need >= {GATE_MIN_DISTINCT}   {'PASS' if pass_d else 'FAIL'}")
    print(f"  values: {distinct}")
    print(f"VERDICT: {verdict}")
    print("=" * 84)
    print(f"wrote {out/'flowrisk_runs.csv'}\nwrote {out/'flowrisk_candidates.csv'}"
          f"\nwrote {out/'flowrisk_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
