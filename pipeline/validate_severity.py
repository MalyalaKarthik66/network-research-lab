"""Does FRR reroute the way Dijkstra says it will?

    python pipeline/validate_severity.py --pilot data/pilot-v2 \
        --workdir /root/nrl-sev --topologies t14_ladder8,t15_campus12,t20_leafspine12

WHY THIS RUNS BEFORE THE GENERATOR IS BUILT

nrl/severity.py predicts r(x) analytically and matches the lab EXACTLY on all
six RR-blackhole candidates. But blackholes are the one mechanism the existing
corpus happens to contain. The proposed generator rests on two others --
clean cost-reroute (which is what kills the `correct` zero-tag) and link
shutdown (which carries the entire high-severity range) -- and NEITHER has ever
been checked against a real FRR.

Dijkstra on paper and OSPF on a box can disagree: equal-cost multipath, a cost
ceiling, reference-bandwidth interactions, or an adjacency that drops when a
cost is raised rather than simply re-weighting. Assuming otherwise is exactly
the kind of untested premise that produced three wrong severity metrics in a
row, each of which passed its gate.

HOW, WITHOUT BUILDING A CORPUS

No new artifacts and no lock-file changes. Deploy the GOLDEN lab that already
exists and is byte-verified, then apply each intervention live with vtysh,
re-read the RIB, compare the forwarding paths against the prediction, and revert.
Many interventions amortise over one deploy, so this costs minutes rather than
one lab per data point.

    deploy golden -> baseline paths
      for each intervention:
          apply via vtysh -> settle -> read RIB -> measured r
          revert         -> settle
    compare measured r against severity.Fabric.predict()

SETTLE TIME IS DELIBERATELY SHORT HERE

The frozen measurement waits MIN_SETTLE_S=45 s because it is producing LABELS.
This produces no labels -- it compares two forwarding tables -- so it polls the
RIB until it stops changing and moves on, typically in about ten seconds. The
frozen path is untouched and no outcome recorded here enters any dataset.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl import clab                                              # noqa: E402
from nrl import flowmatrix as fm                                  # noqa: E402
from nrl.severity import Fabric                                   # noqa: E402
from nrl.topologies import resolve as resolve_topology            # noqa: E402

SETTLE_POLL_S = 3
SETTLE_STABLE = 2
SETTLE_MAX_S = 75
COST_MULTIPLIER = 20


def wj(p: Path, o) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, indent=2, default=str), encoding="utf-8")


def lab_name_from_artifact(art: Path) -> str:
    """Read the lab name out of the artifact, never rebuild it.

    Same rule as run_phase3.lab_name_from_artifact, and for the same reason:
    S-018 recorded 29/29 labs reporting CONTAINERS_MISSING because the name was
    re-derived instead of read. The file is `topology.clab.yml`, so deriving it
    from the filename yields "topology" -- which deploys fine and then makes
    every `docker ps` lookup search for containers that do not exist.
    """
    f = art / "topology.clab.yml"
    if not f.exists():
        raise FileNotFoundError(f"no topology.clab.yml in {art}")
    for line in f.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^name:\s*(\S+)\s*$", line)
        if m:
            return m.group(1)
    raise ValueError(f"{f} has no top-level `name:` line")


def iface_of(spec, a: str, b: str):
    """a's interface facing b, and the configured cost."""
    for (n, i, aa, peer, pi, pa, label, cost) in spec.transit:
        if n == a and peer == b:
            return i, cost
    return None, None


def vtysh_config(lab: str, node: str, lines):
    argv = ["vtysh", "-c", "configure terminal"]
    for ln in lines:
        argv += ["-c", ln]
    return clab.dexec(lab, node, argv, timeout=30)


def ribs(lab: str, routers):
    st = {}
    for n in routers:
        st[n] = {"route": clab.vtysh(lab, n, "show ip route json")}
    return st


def settle(lab: str, routers) -> float:
    """Poll until the RIB stops changing. No labels depend on this."""
    t0 = time.time()
    prev, stable = None, 0
    while time.time() - t0 < SETTLE_MAX_S:
        key = json.dumps({n: (v["route"].get("json") or {})
                          for n, v in ribs(lab, routers).items()}, sort_keys=True)
        stable = stable + 1 if key == prev else 0
        prev = key
        if stable >= SETTLE_STABLE:
            break
        time.sleep(SETTLE_POLL_S)
    return round(time.time() - t0, 1)


def paths_now(lab: str, spec, flows):
    return fm.measure_paths(ribs(lab, sorted(spec.routers)), spec, flows)


def measured_r(cur, base) -> dict:
    UND = ("NO_RIB", "UNKNOWN_NH", "MAX_HOPS")
    BRK = ("NO_ROUTE", "LOOP", "BLACKHOLE")
    n = brk = rer = und = 0
    for fid, gp in base.items():
        if gp["term"] in UND or gp["term"] in BRK:
            continue
        n += 1
        cp = cur.get(fid)
        if cp is None or cp["term"] in UND:
            und += 1
        elif cp["term"] in BRK:
            brk += 1
        elif (cp["path"], cp["term"]) != (gp["path"], gp["term"]):
            rer += 1
    dec = n - und
    return {"n": n, "broken": brk, "rerouted": rer, "undet": und,
            "r": round((brk + rer) / dec, 6) if dec else None}


def preflight(root: Path, workdir: Path) -> bool:
    ok = True

    def chk(n, c, d=""):
        nonlocal ok
        print(f"  [{'OK ' if c else 'FAIL'}] {n}" + (f" -- {d}" if d else ""))
        ok = ok and bool(c)

    print("PREFLIGHT")
    chk("linux", platform.system() == "Linux", platform.system())
    chk("root", hasattr(os, "geteuid") and os.geteuid() == 0)
    chk("docker", clab.run(["docker", "info", "-f", "{{.ServerVersion}}"]).get("status") == "OK")
    chk("containerlab", clab.run(["containerlab", "version"]).get("status") == "OK")
    chk("pilot lock", (root / "pilot.lock.json").exists())
    workdir.mkdir(parents=True, exist_ok=True)
    chk("workdir writable", os.access(workdir, os.W_OK), str(workdir))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--topologies",
                    default="t14_ladder8,t15_campus12,t20_leafspine12")
    ap.add_argument("--per-topology", type=int, default=5,
                    help="links to test; each gives one cost-reroute and one shutdown")
    ap.add_argument("--out", default="analysis/severity_validation")
    a = ap.parse_args()

    root = (REPO / a.pilot).resolve()
    out = (REPO / a.out).resolve()
    workdir = Path(a.workdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not preflight(root, workdir):
        print("\nBLOCKED: preflight failed.")
        return 2
    lock = json.loads((root / "pilot.lock.json").read_text())

    rows, t0 = [], time.time()
    for tn in [x.strip() for x in a.topologies.split(",") if x.strip()]:
        spec = resolve_topology(tn)
        fab = Fabric(spec)
        routers = sorted(spec.routers)
        flows = [{"flow_id": f"{s['name']}->{d['name']}", "src_name": s["name"],
                  "dst_name": d["name"], "src_addr": s["addr"],
                  "dst_addr": d["addr"]}
                 for s in fm.endpoints(spec) for d in fm.endpoints(spec)
                 if s["addr"] != d["addr"]]
        # links spread across the betweenness range, so the check covers the
        # whole severity spectrum rather than five near-identical central links
        lb = fab.link_betweenness()
        order = sorted(lb, key=lambda k: lb[k])
        idx = [int(q * (len(order) - 1)) for q in
               [i / max(1, a.per_topology - 1) for i in range(a.per_topology)]]
        targets = [order[i] for i in sorted(set(idx))]

        src = root / "reference" / f"golden-{tn}"
        staged = workdir / f"sev-{tn}"
        lab = None
        print(f"\n=== {tn}: {len(targets)} links, betweenness "
              f"{[round(lb[t],3) for t in targets]} ===", flush=True)
        st = clab.stage_artifact(src / "artifact", staged, lock["sha256"],
                                 f"reference/golden-{tn}")
        if st["status"] != "OK":
            print(f"  STAGING FAILED: {st.get('error')}")
            continue
        try:
            lab = lab_name_from_artifact(staged)
            dep = clab.deploy(staged, lab)
            if dep["status"] != "OK":
                print(f"  DEPLOY FAILED: {(dep.get('stderr') or '')[-300:]}")
                continue
            up = clab.containers_up(lab, routers + sorted(spec.hosts))
            if up["status"] != "OK":
                print(f"  CONTAINERS MISSING: {up.get('error')}")
                continue
            settle(lab, routers)
            base = paths_now(lab, spec, flows)
            bad = sum(1 for v in base.values() if v["term"] != "OK")
            print(f"  baseline: {len(base)} pairs, {bad} not OK")

            for lk in targets:
                x, y = lk
                ix, cx = iface_of(spec, x, y)
                iy, cy = iface_of(spec, y, x)
                if not ix or not iy:
                    continue
                for kind in ("cost", "shutdown"):
                    if kind == "cost":
                        pred = fab.predict(cost_override={lk: cx * COST_MULTIPLIER})
                        apply_ = [(x, [f"interface {ix}",
                                       f"ip ospf cost {cx * COST_MULTIPLIER}"]),
                                  (y, [f"interface {iy}",
                                       f"ip ospf cost {cy * COST_MULTIPLIER}"])]
                        revert = [(x, [f"interface {ix}", f"ip ospf cost {cx}"]),
                                  (y, [f"interface {iy}", f"ip ospf cost {cy}"])]
                    else:
                        pred = fab.predict(removed=[lk])
                        apply_ = [(x, [f"interface {ix}", "shutdown"])]
                        revert = [(x, [f"interface {ix}", "no shutdown"])]
                    for node, lines in apply_:
                        vtysh_config(lab, node, lines)
                    s1 = settle(lab, routers)
                    meas = measured_r(paths_now(lab, spec, flows), base)
                    for node, lines in revert:
                        vtysh_config(lab, node, lines)
                    s2 = settle(lab, routers)
                    back = measured_r(paths_now(lab, spec, flows), base)
                    agree = (meas["r"] is not None and pred["r"] is not None
                             and abs(meas["r"] - pred["r"]) < 1e-6)
                    rows.append({
                        "topology": tn, "link": f"{x}-{y}", "kind": kind,
                        "betweenness": round(lb[lk], 4),
                        "predicted_r": pred["r"],
                        "predicted_broken": pred["r_broken"],
                        "predicted_rerouted": pred["r_rerouted"],
                        "measured_r": meas["r"], "measured_broken": meas["broken"],
                        "measured_rerouted": meas["rerouted"],
                        "measured_undet": meas["undet"],
                        "agree": agree,
                        "revert_clean": back["r"] == 0,
                        "settle_apply_s": s1, "settle_revert_s": s2})
                    print(f"  {x}-{y:<12s} {kind:8s} bt={lb[lk]:.3f}  "
                          f"pred={pred['r']:.4f}  meas={meas['r']}  "
                          f"{'AGREE' if agree else 'DISAGREE'}"
                          f"{'' if back['r'] == 0 else '   !! revert dirty'}",
                          flush=True)
                    with (out / "severity_validation.csv").open(
                            "w", newline="", encoding="utf-8") as fh:
                        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                        w.writeheader(); w.writerows(rows)
        finally:
            if lab:
                clab.destroy(staged, lab, quiet=True)
            clab.rm_tree(staged)

    # ---- report ---------------------------------------------------------
    print("\n" + "=" * 80)
    by = defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["kind"]][1] += 1
        by[r["kind"]][0] += bool(r["agree"])
    for k, (ok, n) in sorted(by.items()):
        print(f"  {k:9s} {ok}/{n} predictions exact")
    dirty = [r for r in rows if not r["revert_clean"]]
    print(f"  reverts that did not restore the baseline: {len(dirty)}")
    allok = sum(1 for r in rows if r["agree"])
    print(f"\n  OVERALL {allok}/{len(rows)} exact")
    print(f"  VERDICT: {'MODEL VALIDATED' if allok == len(rows) and not dirty else 'MODEL NEEDS WORK'}")
    print("=" * 80)
    wj(out / "severity_validation_summary.json", {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n": len(rows), "exact": allok,
        "by_kind": {k: {"exact": v[0], "n": v[1]} for k, v in by.items()},
        "dirty_reverts": [f"{r['topology']}:{r['link']}:{r['kind']}" for r in dirty],
        "wall_seconds": round(time.time() - t0, 1)})
    print(f"wrote {out/'severity_validation.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
