"""Build the V4 transient pilot: select changes by a fixed rule, write artifacts, lock them, compute
pre-deployment features, and write the run plans. No lab, no Batfish, no measurement.

    ./.venv/Scripts/python.exe v4_transient/pilot/build_pilot.py

Selection rule (docs/PILOT-PREREGISTRATION.md; recorded here before any measurement), fixed before any measurement:
  topologies  t05_ring6, t13_bowtie7, t14_ladder8, t15_campus12 (four shapes, 6-12 routers; frozen v3 designs)
  per topology, 5 population changes, predicted SPEC-PASS (confirmed later by Batfish):
    cost-hi   single link x20 both ends, highest analytic r_exact
    cost-mid  single link x20 both ends, r_exact closest to the median of the remaining non-zero values
    drain-hi  every link of one router x20 both ends, highest r_exact
    drain-lo  every link of one router x20 both ends, lowest non-zero r_exact
    bh        router-loopback /32 static blackhole, highest r_exact
  ties broken by the target's string form. Controls: 10 no-change (re-push an unchanged cost) and
  4 positive controls (shutdown of the highest-betweenness link; SPEC-FAIL by design, not in population).

Amendment A4 (2026-09-15, after engineering smoke 2, before any pilot run; docs/V4-LAUNCH-AUDIT-2.md):
  the positive control is the shutdown of the highest-betweenness link AMONG LINKS WHOSE REMOVAL LEAVES EVERY
  GOLDEN-CARRIED FLOW DELIVERABLE (analytic r_broken == 0), same tie-break. A cut edge breaks its flows permanently,
  so T1 (which subtracts final-state breakage) is 0 by definition and cannot test transient sensitivity. Inputs are the
  frozen topology and analytic model only. Where the frozen rule picked a cut edge, that control is KEPT as
  kind 'control_positive_retired' (artifacts and smoke-2 evidence untouched, no pilot run) and the replacement gets the
  next V4P id, placed right after it so the seeded run order of every other run is unchanged.
"""
from __future__ import annotations

import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from nrl import repairs_v3 as R3                                  # noqa: E402
from nrl import topologies_v3 as T3                               # noqa: E402
from nrl.emit import write_artifact                               # noqa: E402
from nrl.render import render_frr_conf                            # noqa: E402
from nrl.scenario_io import write as write_scenario               # noqa: E402
from nrl.severity import Fabric                                   # noqa: E402
from nrl.topologies import build_golden                           # noqa: E402

from v4lib import EXPERIMENT_ID                                   # noqa: E402
from v4lib.analytic import features                               # noqa: E402

#: the protocol version the design manifest was built under (2026-09-14). Amendments A3-A5 changed the instrument,
#: controls and runner, not the population design; each run records the runtime PROTOCOL_VERSION itself.
MANIFEST_PROTOCOL_VERSION = "transient-1.0.0"

TOPOLOGIES = ("t05_ring6", "t13_bowtie7", "t14_ladder8", "t15_campus12")
MULT = R3.COST_MULTIPLIER
N_REPLICATES = 5
NOOP_PER_TOPOLOGY = {"t05_ring6": 3, "t13_bowtie7": 3, "t14_ladder8": 2, "t15_campus12": 2}
ORDER_SEED = 20260914
ART = V4 / "pilot" / "artifacts"
MAN = V4 / "manifests"


def reaches(fab, co):
    p = fab.paths(cost_override=co)
    return p.get(("hosta", "hostb")) is not None and p.get(("hostb", "hosta")) is not None


def push_plan(golden, cand):
    plan = {}
    for node in sorted(cand.devices):
        g, c = golden.devices[node], cand.devices[node]
        if c.kind != "frr":
            continue
        cmds = []
        for ci in c.ifaces:
            gi = g.iface(ci.name)
            for attr in ("addresses", "ospf_area", "ospf_passive", "ospf_network"):
                if getattr(ci, attr) != getattr(gi, attr):
                    raise ValueError(f"{node}:{ci.name} {attr} differs; not a supported runtime change")
            ic = []
            if ci.ospf_cost != gi.ospf_cost:
                ic.append(f"ip ospf cost {ci.ospf_cost}")
            if ci.up != gi.up:
                ic.append("shutdown" if not ci.up else "no shutdown")
            if ic:
                cmds += [f"interface {ci.name}"] + ic + ["exit"]
        gs = {(s.prefix, s.nexthop, s.distance) for s in g.statics}
        cs = {(s.prefix, s.nexthop, s.distance) for s in c.statics}
        for p, nh, dist in sorted(cs - gs, key=str):
            cmds.append(f"ip route {p} {nh}" + (f" {dist}" if dist else ""))
        for p, nh, dist in sorted(gs - cs, key=str):
            cmds.append(f"no ip route {p} {nh}" + (f" {dist}" if dist else ""))
        if cmds:
            plan[node] = cmds
        elif render_frr_conf(g) != render_frr_conf(c):
            raise ValueError(f"{node}: rendered config differs but no runtime command explains it")
    return plan


def select(tname):
    spec = T3.resolve(tname)
    fab = Fabric(spec)
    golden = build_golden(spec)
    cat = R3.catalogue(spec, fab)
    picks = []

    cost = sorted([d for d in cat if d["mech"] == "cost" and d["spec_pass"]],
                  key=lambda d: (-d["r"], str(d["target"])))
    hi = cost[0]
    rest = [d for d in cost[1:] if d["r"] > 0]
    med = statistics.median([d["r"] for d in rest])
    mid = min(rest, key=lambda d: (abs(d["r"] - med), str(d["target"])))
    for role, d in (("cost-hi", hi), ("cost-mid", mid)):
        sc = golden.clone()
        assert R3._set_cost(sc, spec, d["target"], MULT)
        picks.append({"role": role, "mechanism": "cost", "target": list(d["target"]), "scenario": sc,
                      "change": {"mechanism": "cost", "cost_override": {d["target"]: fab.cost[d["target"]] * MULT}}})

    drains = []
    for x in fab.routers:
        links = sorted(lk for lk in fab.cost if x in lk)
        if len(links) < 2:
            continue
        co = {lk: fab.cost[lk] * MULT for lk in links}
        if not reaches(fab, co):
            continue
        drains.append({"router": x, "links": links, "co": co, "r": fab.predict(cost_override=co)["r"]})
    drains.sort(key=lambda d: (-d["r"], d["router"]))
    nz = [d for d in drains if d["r"] > 0]
    lo = min(nz, key=lambda d: (d["r"], d["router"])) if nz else drains[-1]
    for role, d in (("drain-hi", drains[0]), ("drain-lo", lo)):
        if role == "drain-lo" and d["router"] == drains[0]["router"]:
            raise RuntimeError(f"{tname}: drain-hi and drain-lo coincide")
        sc = golden.clone()
        for lk in d["links"]:
            assert R3._set_cost(sc, spec, lk, MULT)
        picks.append({"role": role, "mechanism": "drain", "target": d["router"], "scenario": sc,
                      "change": {"mechanism": "drain", "cost_override": d["co"]}})

    bh = sorted([d for d in cat if d["mech"] == "blackhole" and d["spec_pass"] and d["target"][1] in spec.routers],
                key=lambda d: (-d["r"], str(d["target"])))[0]
    sc = golden.clone()
    assert R3._blackhole(sc, bh["target"][0], bh["target"][2])
    picks.append({"role": "bh", "mechanism": "blackhole", "target": list(bh["target"]), "scenario": sc,
                  "change": {"mechanism": "blackhole", "blackholes": [(bh["target"][0], bh["target"][1])]}})

    # controls
    first = sorted(fab.cost)[0]
    iface, c = R3._iface(spec, first[0], first[1])
    noop_plan = {first[0]: [f"interface {iface}", f"ip ospf cost {c}", "exit"]}
    bet = fab.link_betweenness()
    top = max(sorted(bet), key=lambda k: bet[k])                     # frozen rule (§20, 2026-09-14)
    pos = positive_control_link(fab)                                 # amendment A4
    retired = None if pos == top else {"target": list(top), "scenario": _shut(golden, spec, top)}
    return spec, fab, golden, picks, noop_plan, {"target": list(pos), "scenario": _shut(golden, spec, pos),
                                                 "retired": retired}


def _shut(golden, spec, link):
    sd = golden.clone()
    assert R3._shutdown(sd, spec, link)
    return sd


def positive_control_link(fab):
    """Amendment A4: highest golden link betweenness among links whose removal leaves every golden-carried flow
    deliverable (analytic r_broken == 0); ties -> first maximum in sorted link order, as the frozen rule. Uses only the
    frozen topology and analytic model: no lab, Batfish, smoke or target value."""
    bet = fab.link_betweenness()
    deliverable = [k for k in sorted(bet) if fab.predict(removed=[k])["r_broken"] == 0]
    if not deliverable:
        raise RuntimeError("no link whose shutdown keeps every carried flow deliverable: no valid positive control")
    return max(deliverable, key=lambda k: bet[k])


def _positive(changes, lock, spec, golden, tname, ch, pos, kind, extra):
    hh = write_artifact(ART / ch, pos["scenario"], f"nrlv4-{ch.lower()}")
    lock.update({f"{ch}/{k}": v for k, v in hh.items()})
    write_scenario(ART / ch / "scenario.json", pos["scenario"])
    plan = push_plan(golden, pos["scenario"])
    changes.append({"change_id": ch, "kind": kind, "topology": tname, "role": "shutdown",
                    "mechanism": "shutdown", "target": pos["target"], "push_plan": plan,
                    "features": features(spec, {"mechanism": "shutdown", "removed": [tuple(pos["target"])]}, plan),
                    **extra})


def main():
    ART.mkdir(parents=True, exist_ok=True)
    MAN.mkdir(parents=True, exist_ok=True)
    lock, changes, runs = {}, [], []
    cid = nid = pid = a4 = 0
    for tname in TOPOLOGIES:
        spec, fab, golden, picks, noop_plan, pos = select(tname)
        gname = f"golden-{tname}"
        h = write_artifact(ART / gname, golden, f"nrlv4-{tname.split('_')[0]}")
        lock.update({f"{gname}/{k}": v for k, v in h.items()})
        write_scenario(ART / gname / "scenario.json", golden)
        for p in picks:
            cid += 1
            ch = f"V4C-{cid:02d}"
            hh = write_artifact(ART / ch, p["scenario"], f"nrlv4-{ch.lower()}")
            lock.update({f"{ch}/{k}": v for k, v in hh.items()})
            write_scenario(ART / ch / "scenario.json", p["scenario"])
            plan = push_plan(golden, p["scenario"])
            changes.append({"change_id": ch, "kind": "population", "topology": tname, "role": p["role"],
                            "mechanism": p["mechanism"], "target": p["target"], "push_plan": plan,
                            "features": features(spec, p["change"], plan)})
        for _ in range(NOOP_PER_TOPOLOGY[tname]):
            nid += 1
            ch = f"V4N-{nid:02d}"
            changes.append({"change_id": ch, "kind": "control_noop", "topology": tname, "role": "noop",
                            "mechanism": "noop", "target": list(noop_plan), "push_plan": noop_plan,
                            "features": features(spec, {"mechanism": "noop"}, noop_plan),
                            "batfish_snapshot": f"{gname}/batfish-snapshot"})
        pid += 1
        ch = f"V4P-{pid:02d}"
        extra = {}
        if pos["retired"] is not None:                               # amendment A4
            a4 += 1
            new = f"V4P-{len(TOPOLOGIES) + a4:02d}"
            _positive(changes, lock, spec, golden, tname, ch, pos["retired"], "control_positive_retired",
                      {"retired_by": "A4", "replaced_by": new,
                       "retired_reason": "cut edge for carried flows: analytic r_rerouted_exact = 0, so T1 = 0 by "
                                         "definition (docs/V4-LAUNCH-AUDIT-2.md §1)"})
            ch, extra = new, {"amendment": "A4", "replaces": ch}
        _positive(changes, lock, spec, golden, tname, ch, pos, "control_positive", extra)

    for c in changes:
        if c["kind"] == "control_positive_retired":                  # kept for provenance, never run in the pilot
            c.setdefault("batfish_snapshot", f"{c['change_id']}/batfish-snapshot")
            c["lab_artifact"] = f"golden-{c['topology']}"
            c["candidate_scenario"] = f"{c['change_id']}/scenario.json"
            continue
        reps = N_REPLICATES if c["kind"] == "population" else 1
        c.setdefault("batfish_snapshot", f"{c['change_id']}/batfish-snapshot")
        c["lab_artifact"] = f"golden-{c['topology']}"
        c["candidate_scenario"] = (f"golden-{c['topology']}/scenario.json" if c["kind"] == "control_noop"
                                   else f"{c['change_id']}/scenario.json")
        for k in range(1, reps + 1):
            runs.append({"run_id": f"{c['change_id']}.rep{k}", "change_id": c["change_id"], "replicate": k})
    rng = random.Random(ORDER_SEED)
    rng.shuffle(runs)
    for i, r in enumerate(runs):
        r["order"] = i

    pop = [c for c in changes if c["kind"] == "population"]
    t05 = [c for c in pop if c["topology"] == "t05_ring6"]
    smoke_changes = [t05[0]["change_id"], next(c for c in t05 if c["mechanism"] == "drain")["change_id"]]
    smoke = [{"run_id": f"SMOKE-{ch}.rep{k}", "change_id": ch, "replicate": k, "order": i}
             for i, (ch, k) in enumerate((ch, k) for ch in smoke_changes for k in (1, 2))]
    # engineering-only failure injection: corrupts the expected artifact hash in memory, so staging fails,
    # the single retry fails too, and both attempts must be preserved. No lab is deployed.
    smoke.append({"run_id": f"SMOKE-FAILINJ-{smoke_changes[0]}.rep1", "change_id": smoke_changes[0],
                  "replicate": 1, "order": len(smoke), "inject": "staging"})

    digest = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    manifest = {"experiment_id": EXPERIMENT_ID, "protocol_version": MANIFEST_PROTOCOL_VERSION,
                "topologies": list(TOPOLOGIES), "cost_multiplier": MULT, "n_replicates": N_REPLICATES,
                "order_seed": ORDER_SEED, "artifact_lock_digest": digest, "changes": changes,
                "frozen_sources": "nrl/topologies_v3.py, nrl/repairs_v3.py, nrl/severity.py (read-only)"}
    (MAN / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8", newline="\n")
    (MAN / "artifact_lock.json").write_text(json.dumps({"digest": digest, "sha256": lock}, indent=2), encoding="utf-8", newline="\n")
    (MAN / "run_plan_pilot.json").write_text(json.dumps({"plan": "pilot", "runs": runs}, indent=2), encoding="utf-8", newline="\n")
    (MAN / "run_plan_smoke.json").write_text(json.dumps({"plan": "smoke", "runs": smoke}, indent=2), encoding="utf-8", newline="\n")
    print(f"changes: {len(pop)} population, {sum(c['kind']=='control_noop' for c in changes)} no-op, "
          f"{sum(c['kind']=='control_positive' for c in changes)} positive; runs {len(runs)}; smoke {len(smoke)}")
    for c in changes:
        f = c["features"]
        print(f"  {c['change_id']} {c['topology']:13s} {c['role']:9s} r_exact {f['r_exact']:.3f} "
              f"fib_changed {f['n_fib_entries_changed']:3d} pml {f['pml_flow_frac']:.3f} devices {f['n_devices_pushed']} "
              f"push {json.dumps(c['push_plan'])[:90]}")
    print("lock digest", digest)


if __name__ == "__main__":
    main()
