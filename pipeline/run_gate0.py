"""GATE 0 -- the viability experiment. Does per-candidate risk exist at all?

    python pipeline/run_gate0.py --pilot data/pilot-v2 --workdir /root/nrl-gate0 \
        --candidates 40 --replicates 10

THE QUESTION

Stage 3 produced no irreducible risk: at Tier C no two candidates with
identical features ever disagree on the outcome, the pre-registered transient
label found zero transient harm in 299 runs, and the 10 Stage 1 replicate pairs
agree 10/10. Outcome is a deterministic function of configuration, so
P(harm | X) is 0 or 1 and there is nothing to calibrate.

This experiment asks whether that is a property of the DOMAIN or a property of
the HARNESS. It re-runs a stratified sample of already-labelled candidates
R times each, every run under an independently randomised execution
environment (nrl/env_randomize.py). The artifact is unchanged and still
byte-verified; only the conditions it converges under differ.

    per-candidate harm rate = k / R,  k = runs measured HARMFUL or NO_CONVERGENCE

PRE-REGISTERED GATE, fixed here before the first lab runs:

    >= 25% of candidates have k/R strictly inside (0.1, 0.9)
        -> aleatoric risk exists. A calibrated per-candidate risk model is a
           coherent target. Proceed to the redesigned corpus.

    otherwise
        -> harm stays deterministic even under environmental randomisation.
           No architecture fixes that. Stop the ML arm and publish the
           measurement study.

Nothing here writes inside data/. Outputs go to analysis/gate0/. The frozen
golden and incident runs under data/pilot-v2/phase3/runs/ are opened read-only
as the comparison baselines, exactly as the frozen pipeline uses them.

Resumable: a replicate whose run.json exists is skipped, so an interrupted run
is restarted with the same command.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl import clab                                              # noqa: E402
from nrl import env_randomize as envr                             # noqa: E402
from nrl.properties import PROPERTIES, SUITE_VERSION              # noqa: E402
from nrl.scenario_io import read as read_scenario                 # noqa: E402
from nrl.topologies import resolve as resolve_topology            # noqa: E402

PIDS = [p["pid"] for p in PROPERTIES]
SPEC_PIDS = [p["pid"] for p in PROPERTIES if p["in_spec"]]
GATE_FRACTION = 0.25
GATE_LO, GATE_HI = 0.1, 0.9
HARMFUL_OUTCOMES = ("HARMFUL", "NO_CONVERGENCE")


def _load_run_phase3():
    """Load the frozen runner by path and reuse run_one verbatim.

    pipeline/ is not a package. Importing by path keeps staging, byte
    verification, deploy, the S-020 binding check, measurement and teardown on
    exactly the code that produced the frozen corpus -- so a Gate 0 outcome and
    a Stage 3 outcome are the same instrument reading different conditions.
    main() is guarded by __main__, so this executes nothing.
    """
    spec = importlib.util.spec_from_file_location(
        "_rp3", REPO / "pipeline" / "run_phase3.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def wj(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def outcome_of(run: dict, before: dict, golden: dict):
    """The frozen harm definition v1.1.0, applied mechanically.

    Mirrors the rule inside run_phase3.build_datasets so a Gate 0 label and a
    Stage 3 label mean the same thing. Property is in G iff it holds on the
    golden; a candidate is HARMFUL iff any property in G stops holding.
    """
    gby = {m["property_id"]: m for m in (golden or {}).get("measurements", [])}
    bby = {m["property_id"]: m for m in (before or {}).get("measurements", [])}
    aby = {m["property_id"]: m for m in (run or {}).get("measurements", [])}
    in_g, viol, undet = [], [], []
    for pid in PIDS:
        gm, bm, am = gby.get(pid, {}), bby.get(pid, {}), aby.get(pid, {})
        if gm.get("holds") is not True:
            continue
        in_g.append(pid)
        if any(x.get("status") == "ERROR" for x in (gm, bm, am)):
            undet.append(pid)
        elif am.get("holds") is False:
            viol.append(pid)
    status = run.get("status")
    if status == "NO_CONVERGENCE":
        oc = "NO_CONVERGENCE"
    elif status != "OK":
        oc = "EXECUTION_FAILED"
    elif viol:
        oc = "HARMFUL"
    elif undet:
        oc = "UNDETERMINED"
    else:
        oc = "SAFE"
    return oc, in_g, viol, undet


def stratified_candidates(outcomes_csv: Path, manifest: dict, n: int):
    """Deterministic sample across (repair_class x frozen outcome).

    `correct` contributes 0/153 harmful in the frozen corpus and `incomplete`
    and `regressive` around 55% each, so the interesting question differs by
    stratum: do SAFE candidates ever become harmful under churn, and do HARMFUL
    ones ever become safe. Sampling proportionally would spend most of the
    budget on `correct` and answer only the first.
    """
    rows = list(csv.DictReader(outcomes_csv.open(newline="", encoding="utf-8")))
    meta = {c["candidate_id"]: c for c in manifest["candidates"]}
    pool = []
    for r in rows:
        if r["outcome_harm_v1"] not in ("SAFE", "HARMFUL", "NO_CONVERGENCE"):
            continue
        m = meta.get(r["candidate_id"])
        if not m:
            continue
        pool.append({"candidate_id": r["candidate_id"],
                     "incident_id": r["incident_id"],
                     "topology": m.get("topology"),
                     "fault_family": m.get("fault_family"),
                     "repair_class": m.get("repair_class"),
                     "repair_id": m.get("repair_id"),
                     "frozen_outcome": r["outcome_harm_v1"]})
    quota = {("correct", "SAFE"): 10, ("incomplete", "SAFE"): 8,
             ("incomplete", "HARMFUL"): 8, ("regressive", "SAFE"): 7,
             ("regressive", "HARMFUL"): 7}
    by = defaultdict(list)
    for p in pool:
        oc = "HARMFUL" if p["frozen_outcome"] in HARMFUL_OUTCOMES else "SAFE"
        by[(p["repair_class"], oc)].append(p)
    chosen = []
    for key, want in quota.items():
        items = sorted(by.get(key, []), key=lambda p: p["candidate_id"])
        if not items:
            continue
        # spread across topologies deterministically: round-robin the groups
        groups = defaultdict(list)
        for it in items:
            groups[it["topology"]].append(it)
        order = sorted(groups)
        picked, i = [], 0
        while len(picked) < min(want, len(items)):
            g = groups[order[i % len(order)]]
            if g:
                picked.append(g.pop(0))
            i += 1
            if i > 10000:
                break
        chosen += picked
    # top up deterministically if a stratum was short
    if len(chosen) < n:
        have = {c["candidate_id"] for c in chosen}
        for p in sorted(pool, key=lambda p: p["candidate_id"]):
            if p["candidate_id"] not in have:
                chosen.append(p)
                have.add(p["candidate_id"])
            if len(chosen) >= n:
                break
    return sorted(chosen[:n], key=lambda p: p["candidate_id"])


def preflight(root: Path, workdir: Path, frozen_runs: Path) -> bool:
    ok = True

    def chk(name, cond, detail=""):
        nonlocal ok
        print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
        ok = ok and bool(cond)

    print("PREFLIGHT")
    chk("linux", platform.system() == "Linux", platform.system())
    import os
    chk("root", hasattr(os, "geteuid") and os.geteuid() == 0)
    d = clab.run(["docker", "info", "--format", "{{.ServerVersion}}"])
    chk("docker daemon", d.get("status") == "OK", (d.get("stdout") or "").strip())
    c = clab.run(["containerlab", "version"])
    chk("containerlab", c.get("status") == "OK")
    chk("pilot lock", (root / "pilot.lock.json").exists())
    chk("frozen golden/incident runs readable", frozen_runs.is_dir(),
        str(frozen_runs))
    chk("perturbation window closes before MIN_SETTLE_S",
        envr.MAX_DELAY_S + envr.MAX_DOWN_S < clab.MIN_SETTLE_S,
        f"{envr.MAX_DELAY_S}+{envr.MAX_DOWN_S} < {clab.MIN_SETTLE_S}")
    workdir.mkdir(parents=True, exist_ok=True)
    chk("workdir writable", os.access(workdir, os.W_OK), str(workdir))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--candidates", type=int, default=40)
    ap.add_argument("--replicates", type=int, default=10)
    ap.add_argument("--out", default="analysis/gate0")
    ap.add_argument("--smoke", type=int, default=0,
                    help="run only the first N labs, for validation")
    ap.add_argument("--keep-lab", action="store_true")
    a = ap.parse_args()

    root = (REPO / a.pilot).resolve()
    out = (REPO / a.out).resolve()
    workdir = Path(a.workdir).resolve()
    frozen_runs = root / "phase3" / "runs"
    out.mkdir(parents=True, exist_ok=True)

    if not preflight(root, workdir, frozen_runs):
        print("\nBLOCKED: preflight failed. Nothing was run.")
        return 2

    rp3 = _load_run_phase3()
    manifest = json.loads((root / "manifest.json").read_text())
    lock = json.loads((root / "pilot.lock.json").read_text())

    sample = stratified_candidates(
        root / "phase3" / "containerlab_outcomes.csv", manifest, a.candidates)
    print(f"\nsample: {len(sample)} candidates, "
          f"{len({c['topology'] for c in sample})} topologies, "
          f"{len({c['incident_id'] for c in sample})} incidents, "
          f"{len({c['fault_family'] for c in sample})} fault families")
    for k, v in sorted(Counter((c["repair_class"], c["frozen_outcome"])
                               for c in sample).items()):
        print(f"    {k[0]:12s} frozen={k[1]:15s} {v}")

    # frozen baselines, read-only
    def load_run(rid: str):
        p = frozen_runs / rid / "run.json"
        return json.loads(p.read_text()) if p.exists() else None

    todo = [(c, r) for c in sample for r in range(a.replicates)]
    if a.smoke:
        todo = todo[:a.smoke]
    print(f"\n{len(todo)} labs to run "
          f"({len(sample)} candidates x {a.replicates} replicates)")

    sink: dict = {}
    current: dict = {"env": None}
    envr.install(lambda: current["env"], sink)

    rows, t_start, done = [], time.time(), 0
    rows_path = out / "gate0_runs.csv"
    try:
        for n, (cand, rep) in enumerate(todo, start=1):
            cid = cand["candidate_id"]
            rid = f"{cid}~g0r{rep:02d}"
            rdir = out / "runs" / rid
            spec = resolve_topology(cand["topology"])
            src = root / "candidates" / cid
            inc_src = root / "incidents" / cand["incident_id"]
            env = envr.sample_environment(
                cid, rep, spec,
                read_scenario(src / "scenario.json")
                if (src / "scenario.json").exists() else None,
                read_scenario(inc_src / "scenario.json")
                if (inc_src / "scenario.json").exists() else None)

            if (rdir / "run.json").exists():
                rec = json.loads((rdir / "run.json").read_text())
                print(f"[{n:4d}/{len(todo)}] {rid}  (resumed)")
            else:
                eta = ""
                if done:
                    per = (time.time() - t_start) / done
                    eta = f"  eta {int(per * (len(todo) - n + 1) / 60)}m"
                print(f"[{n:4d}/{len(todo)}] {rid}  churn="
                      f"{env.get('node')}:{env.get('iface')} "
                      f"t+{env.get('delay_s')}s for {env.get('down_s')}s{eta}",
                      flush=True)
                current["env"] = env
                sink.pop("perturbation", None)
                sc = rp3.scenario_for(src, cid, {})
                rec = rp3.run_one(rid, src, workdir, lock, sc, out,
                                  a.keep_lab, spec, kind="gate0_replicate",
                                  attempt=1)
                rec["gate0"] = sink.get("perturbation") or {}
                wj(rdir / "run.json", rec)
                wj(rdir / "gate0_environment.json", rec["gate0"])
                done += 1

            golden = load_run(f"golden-{cand['topology']}")
            before = load_run(cand["incident_id"])
            oc, in_g, viol, undet = outcome_of(rec, before, golden)
            pert = rec.get("gate0", {}) or {}
            conv_path = rdir / "convergence.json"
            nflaps = (envr.neighbour_flaps(json.loads(conv_path.read_text()))
                      if conv_path.exists() else {})
            row = {
                "run_id": rid, "candidate_id": cid,
                "incident_id": cand["incident_id"],
                "topology": cand["topology"],
                "fault_family": cand["fault_family"],
                "repair_class": cand["repair_class"],
                "repair_id": cand["repair_id"],
                "replicate": rep,
                "frozen_outcome": cand["frozen_outcome"],
                "run_status": rec.get("status"),
                "outcome_harm_v1": oc,
                "golden_properties_in_G": len(in_g),
                "violations_vs_golden": ";".join(viol),
                "violation_count": len(viol),
                "undetermined_properties": ";".join(undet),
                "converged": (rec.get("convergence") or {}).get("converged"),
                "convergence_seconds": (rec.get("convergence") or {}).get("seconds"),
                "converged_phase1": (rec.get("convergence") or {}).get("converged_phase1"),
                "convergence_seconds_phase1": (rec.get("convergence") or {}).get("seconds_phase1"),
                # key names are clab.transient_summary's, verbatim. The first
                # version invented three of them and wrote blank columns that
                # looked like measured zeros.
                "transient_flapped": (rec.get("transient") or {}).get("flapped"),
                "transient_adjacency_flaps": (rec.get("transient") or {}).get("adjacency_flaps_after_full"),
                "transient_outage_after_reachable": (rec.get("transient") or {}).get("transient_outage_after_reachable"),
                "transient_unreachable_polls": (rec.get("transient") or {}).get("probe_unreachable_polls"),
                "transient_probe_polls": (rec.get("transient") or {}).get("probe_polls"),
                "transient_rib_changes_total": (rec.get("transient") or {}).get("rib_changes_total"),
                "transient_polls": (rec.get("transient") or {}).get("polls"),
                # finer per-neighbour flap metric; see env_randomize.neighbour_flaps
                "neighbour_flaps_total": nflaps.get("neighbour_flaps_total"),
                "flapped_any_neighbour": nflaps.get("flapped_any_neighbour"),
                "env_seed": (pert.get("environment") or {}).get("seed"),
                "churn_node": (pert.get("environment") or {}).get("node"),
                "churn_iface": (pert.get("environment") or {}).get("iface"),
                "churn_delay_s": (pert.get("environment") or {}).get("delay_s"),
                "churn_down_s": (pert.get("environment") or {}).get("down_s"),
                "churn_touched_by_repair": (pert.get("environment") or {}).get("touched_by_repair"),
                "churn_completed": pert.get("completed"),
                "churn_link_restored": pert.get("link_restored"),
                "churn_phase": pert.get("phase"),
                "wall_seconds": rec.get("wall_seconds"),
                "harm_definition_version": "1.1.0",
                "suite_version": SUITE_VERSION,
            }
            rows.append(row)
            cv = rec.get("convergence") or {}
            print(f"         {rec.get('status'):16s} -> {oc:16s} "
                  f"churn={pert.get('phase')}/{pert.get('completed')} "
                  f"conv={cv.get('seconds_phase1')}s+{cv.get('seconds')}s "
                  f"flaps={nflaps.get('neighbour_flaps_total')} "
                  f"outage={(rec.get('transient') or {}).get('transient_outage_after_reachable')} "
                  f"{rec.get('wall_seconds')}s")
            # write after every lab so an interrupted run keeps its results
            if rows:
                with rows_path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
    finally:
        envr.uninstall()

    # ---- per-candidate aggregation -------------------------------------
    agg, by_cand = [], defaultdict(list)
    for r in rows:
        by_cand[r["candidate_id"]].append(r)
    for cid, rs in sorted(by_cand.items()):
        decidable = [r for r in rs if r["outcome_harm_v1"] in
                     ("SAFE", "HARMFUL", "NO_CONVERGENCE")]
        excluded = [r for r in rs if r not in decidable]
        k = sum(1 for r in decidable if r["outcome_harm_v1"] in HARMFUL_OUTCOMES)
        R = len(decidable)
        c0 = rs[0]
        agg.append({
            "candidate_id": cid, "incident_id": c0["incident_id"],
            "topology": c0["topology"], "fault_family": c0["fault_family"],
            "repair_class": c0["repair_class"], "repair_id": c0["repair_id"],
            "frozen_outcome": c0["frozen_outcome"],
            "R_attempted": len(rs), "R_decidable": R, "k_harmful": k,
            "harm_rate": round(k / R, 4) if R else None,
            "n_excluded": len(excluded),
            "intermediate": (R > 0 and GATE_LO < k / R < GATE_HI),
            "agrees_with_frozen_majority": (
                None if not R else
                (("HARMFUL" if k * 2 > R else "SAFE") ==
                 ("HARMFUL" if c0["frozen_outcome"] in HARMFUL_OUTCOMES else "SAFE"))),
        })
    with (out / "gate0_candidates.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0].keys()))
        w.writeheader()
        w.writerows(agg)

    scored = [x for x in agg if x["harm_rate"] is not None]
    inter = [x for x in scored if x["intermediate"]]
    frac = len(inter) / len(scored) if scored else 0.0
    verdict = "GO" if frac >= GATE_FRACTION else "NO-GO"
    summary = {
        "generated_utc": now(),
        "status": "GATE 0 -- viability experiment",
        "pilot": str(root), "out": str(out),
        "candidates": len(agg), "replicates_requested": a.replicates,
        "labs_attempted": len(rows),
        "outcome_counts": dict(Counter(r["outcome_harm_v1"] for r in rows)),
        "run_status_counts": dict(Counter(r["run_status"] for r in rows)),
        "churn_completed": dict(Counter(str(r["churn_completed"]) for r in rows)),
        "candidates_scored": len(scored),
        "candidates_intermediate": len(inter),
        "fraction_intermediate": round(frac, 4),
        "gate_threshold": GATE_FRACTION,
        "gate_band": [GATE_LO, GATE_HI],
        "verdict": verdict,
        "wall_seconds": round(time.time() - t_start, 1),
    }
    wj(out / "gate0_summary.json", summary)
    print("\n" + "=" * 74)
    print(f"GATE 0: {len(inter)}/{len(scored)} candidates with harm rate in "
          f"({GATE_LO}, {GATE_HI}) = {frac:.1%}   threshold {GATE_FRACTION:.0%}")
    print(f"VERDICT: {verdict}")
    print("=" * 74)
    print(f"wrote {rows_path}")
    print(f"wrote {out / 'gate0_candidates.csv'}")
    print(f"wrote {out / 'gate0_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
