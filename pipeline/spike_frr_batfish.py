"""THE GATE -- is the common FRR artifact SEMANTICALLY represented by Batfish?

    docker run --name batfish -d -v batfish-data:/data -p 8888:8888 -p 9997:9997 -p 9996:9996 batfish/allinone
    python pipeline\\spike_frr_batfish.py

Byte-identity between what Containerlab mounts and what Batfish reads is
necessary and NOT sufficient. Batfish can accept a construct, emit no parse
warning, and model nothing -- which is exactly what happened to the retired F10
distribute-list. The artifact was byte-identical and semantically different, and
byte-level checking could never have caught it.

So this gate checks COVERAGE: for every construct the renderer can emit, in
every one of the 11 snapshots, does Batfish's model actually contain it?

Expectations are derived from nrl's own Scenario model, never hardcoded. The
previous version of this script hardcoded node names in mixed case and reported
15 false failures because Batfish lowercases hostnames -- a check that restates
the artifact instead of deriving from it is a check that can lie.

VERDICT
  GO   -> every construct is modelled; Phase 2 may run
  STOP -> a construct is missing or mismatched. Fix the artifact or retire the
          construct. Do NOT translate configs or switch vendors to make this
          pass -- that would reintroduce the confound the whole design avoids.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl.faults import FAULTS                                      # noqa: E402
from nrl.scenario_io import read as read_scenario                  # noqa: E402
from nrl.topologies import (expected_ospf_pairs,                   # noqa: E402
                            resolve as resolve_topology)
from nrl.topology import LINKS, ROUTERS, build_golden              # noqa: E402

PILOT = REPO / "data" / "pilot-v1"     # placeholder only; --pilot is REQUIRED
# Not a default. main() overwrites this from --pilot, which argparse now
# refuses to omit. The old default silently spiked pilot-v1 while the
# operator believed they were spiking pilot-v2.

V: dict = {}
NOTES: list = []
SCHEMA: dict = {}


def norm(x) -> str:
    """Batfish lowercases hostnames. Normalise on both sides, always."""
    return str(x).strip().lower()


def split_iface(x):
    s = str(x)
    return (norm(s.split("[")[0]), s.split("[")[1].rstrip("]")) if "[" in s \
        else (norm(s), None)


def pick_family(man, loaded, family, v1_default):
    """An incident of this family that is actually LOADED. Returns None rather
    than silently falling through to a snapshot from a different pilot."""
    if man is None:
        return v1_default if v1_default in loaded else None
    for inc in man.get("incidents", []):
        if inc["fault_family"] == family and inc["incident_id"] in loaded:
            return inc["incident_id"]
    return None


def node_for(man, iid, default):
    if man is None:
        return default
    for inc in man.get("incidents", []):
        if inc["incident_id"] == iid:
            return inc.get("fault_params", {}).get("node", default)
    return default


def show(title, frame, n=15):
    print(f"\n--- {title} ---")
    print("(0 rows)" if frame is None or len(frame) == 0
          else frame.head(n).to_string())
    return frame


def same_value(got, want) -> bool:
    """Compare a model value against Batfish's.

    Batfish returns enums in SCREAMING_SNAKE (`POINT_TO_POINT`) while the
    artifact writes vendor syntax (`point-to-point`). The first version of this
    helper stripped `-` but not `_` and reported 131 false mismatches -- the
    second time a hand-rolled normaliser in this file produced a confident
    wrong answer. Normalise separators and case, once, here.
    """
    if isinstance(want, bool):
        return bool(got) == want
    if isinstance(want, int):
        try:
            return int(got) == want
        except (TypeError, ValueError):
            return False
    def n(x):
        return str(x).strip().lower().replace("-", "").replace("_", "")
    if n(got) == n(want):
        return True
    # areas may be rendered 0.0.0.0 or 0
    try:
        return int(str(got).replace(".", "")) == int(str(want).replace(".", ""))
    except (TypeError, ValueError):
        return False


def peer_map(spec):
    """FRR<->FRR layer-1 peers FOR ONE TOPOLOGY.

    This used to be built once from the pilot-v1 network. Interface names repeat
    across topologies, so (corea, eth2) resolved to t2's wan1 -- absent in
    t01 (KeyError) and, more dangerously, PRESENT but wrong in t02, where the
    carrier check would have silently compared against the wrong peer.
    """
    m = {}
    for l in spec.links:
        a, ai, b, bi = l[0], l[1], l[3], l[4]
        if a in spec.routers and b in spec.routers:
            m[(a, ai)] = (b, bi)
            m[(b, bi)] = (a, ai)
    return m


def col(frame, *names):
    """Find the first column that exists, case-insensitively."""
    if frame is None or len(frame) == 0:
        return None
    low = {str(c).lower(): c for c in frame.columns}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def scenarios(pilot: Path, per_topology: int = 3):
    """Every snapshot worth spiking, with the model it was rendered from and
    the topology spec it must be judged against.

    Discovered from the manifest, so it works for pilot-v1 (one network, no
    topology field) and pilot-v2 (ten networks) without a code change. Yields
    (id, snapshot_dir, scenario, spec).
    """
    man = json.loads((pilot / "manifest.json").read_text())
    topos = sorted({i.get("topology") for i in man.get("incidents", [])
                    if i.get("topology")})
    if topos:
        for tn in topos:
            d = pilot / "reference" / f"golden-{tn}"
            yield (f"golden-{tn}", d / "batfish-snapshot",
                   read_scenario(d / "scenario.json"), resolve_topology(tn))
        # Rotate the family offset per topology so the sample covers EVERY
        # fault family. Taking the first N per topology sampled only the first
        # N families -- which is why `static_route checked=0` was reported as
        # "ok": no sampled snapshot contained a static route.
        by_topo = {}
        for inc in man["incidents"]:
            by_topo.setdefault(inc["topology"], []).append(inc)
        chosen = []
        for ti, tn in enumerate(sorted(by_topo)):
            lst = by_topo[tn]
            for k in range(min(per_topology, len(lst))):
                chosen.append(lst[(ti * per_topology + k) % len(lst)])
        for inc in chosen:
            tn = inc["topology"]
            d = pilot / "incidents" / inc["incident_id"]
            yield (inc["incident_id"], d / "batfish-snapshot",
                   read_scenario(d / "scenario.json"), resolve_topology(tn))
        return
    # pilot-v1: one network, scenarios regenerated as before
    spec = resolve_topology(None)
    golden = build_golden()
    yield "golden", pilot / "reference" / "golden" / "batfish-snapshot", golden, spec
    for idx, fault in enumerate(FAULTS, start=1):
        iid = f"I-{idx:02d}"
        yield (iid, pilot / "incidents" / iid / "batfish-snapshot",
               fault.apply(golden), spec)


def resolve_pilot(raw: str) -> Path:
    """Resolve --pilot and REFUSE a directory that is not a pilot.

    A mistyped path (`data\\pilot-v` for `data\\pilot-v2` -- a shell wrapping
    the last character) used to get several steps in: the header printed
    "pilot.lock.json: UNREADABLE", a Batfish network `nrl-spike-pilot-v` was
    created, and only then did it die on a missing manifest. Half-executing
    against a target that does not exist is the wrong-target failure this
    project has already been bitten by; the run must stop at the first step.
    """
    p = Path(raw)
    if not p.is_absolute():
        p = (REPO / p).resolve()
    if not p.is_dir():
        raise SystemExit(f"BLOCKED: no such pilot directory: {p}\n"
                         f"         (check for a truncated or wrapped path)")
    missing = [f for f in ("manifest.json", "pilot.lock.json")
               if not (p / f).exists()]
    if missing:
        raise SystemExit(f"BLOCKED: {p} is not a pilot directory -- missing "
                         f"{', '.join(missing)}.\n"
                         f"         Run build_pilot_v2.py first.")
    return p


def main() -> int:
    global PILOT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. There is deliberately NO default: a default of data/pilot-v1 once ran every command against the old pilot whose ledger was already complete, and printed success.")
    ap.add_argument("--per-topology", type=int, default=3)
    a = ap.parse_args()
    PILOT = resolve_pilot(a.pilot)

    try:
        from pybatfish.client.session import Session
    except ImportError:
        print("pybatfish not importable. Activate .venv first.")
        return 1

    print("=" * 74)
    print("FRR / BATFISH SEMANTIC COMPATIBILITY SPIKE")
    print(f"  pilot           : {PILOT}")
    try:
        _lk = json.loads((PILOT / "pilot.lock.json").read_text())
        print(f"  snapshot_digest : {str(_lk.get('snapshot_digest'))[:16]}")
        print(f"  built_utc       : {_lk.get('built_utc')}")
    except Exception as _exc:                                      # noqa: BLE001
        print(f"  pilot.lock.json : UNREADABLE ({_exc})")
    print("=" * 74)

    try:
        bf = Session(host="localhost")
    except Exception as exc:                                       # noqa: BLE001
        print(f"cannot reach Batfish at localhost:9996 -- {exc}")
        return 1
    # Per-pilot network. A shared one let CHECK 5/6 silently read pilot-v1
    # snapshots ("I-10", "I-08") that Batfish still held from an earlier run,
    # so two checks validated the WRONG PILOT and reported PASS.
    net = f"nrl-spike-{PILOT.name}"
    bf.set_network(net)
    print(f"batfish network: {net}")
    snaps = list(scenarios(PILOT, a.per_topology))
    loaded = {}
    print(f"\nloading {len(snaps)} snapshots")
    man_for_checks = None
    mp = PILOT / "manifest.json"
    if mp.exists():
        _m = json.loads(mp.read_text())
        if _m.get("topologies"):
            man_for_checks = _m
    specs = {}
    for name, path, sc, spec in snaps:
        bf.init_snapshot(str(path), name=name, overwrite=True)
        loaded[name] = sc
        specs[name] = spec
        print(f"  {name}  [{spec.name}]")

    # ---- CHECK 1: parse health, EVERY snapshot ------------------------
    print("\nCHECK 1 -- parse health across all snapshots")
    parse_bad, warn_total = [], 0
    for name, _, sc, _spec in snaps:
        bf.set_snapshot(name)
        fps = bf.q.fileParseStatus().answer().frame()
        pw = bf.q.parseWarning().answer().frame()
        ii = bf.q.initIssues().answer().frame()
        warn_total += len(pw)
        n_routers = len([d for d in sc.devices.values() if d.kind == "frr"])
        ok = (len(fps) == n_routers and (fps["Status"] == "PASSED").all()
              and len(pw) == 0 and len(ii) == 0)
        print(f"  {name:8s} files={len(fps)}/{n_routers} "
              f"passed={int((fps['Status'] == 'PASSED').sum())} "
              f"warnings={len(pw)} initIssues={len(ii)}  "
              f"{'ok' if ok else 'PROBLEM'}")
        if not ok:
            parse_bad.append(name)
            if len(pw):
                show(f"parseWarning [{name}]", pw, 40)
            if len(ii):
                show(f"initIssues [{name}]", ii, 40)
    V["parse"] = not parse_bad
    NOTES.append(f"total parse warnings across all snapshots: {warn_total}")

    # ---- CHECK 2: format detection ------------------------------------
    print("\nCHECK 2 -- vendor format detection")
    g0 = snaps[0][0]
    bf.set_snapshot(g0)
    nodes = bf.q.nodeProperties(
        properties="Configuration_Format,Interfaces").answer().frame()
    fmts = {str(f) for f in nodes["Configuration_Format"]}
    got_nodes = {norm(n) for n in nodes["Node"]}
    want_nodes = set(specs[g0].routers)
    print(f"  formats: {fmts}")
    print(f"  nodes  : {sorted(got_nodes)}")
    V["format"] = (got_nodes == want_nodes and
                   all("CUMULUS" in f.upper() or "FRR" in f.upper()
                       for f in fmts))
    if got_nodes != want_nodes:
        print(f"  node-name mismatch: expected {sorted(want_nodes)}")

    # ---- CHECK 3: CONSTRUCT COVERAGE ----------------------------------
    print("\nCHECK 3 -- construct coverage (the check that would have caught F10)")
    print("  For every construct the renderer emits, in every snapshot:")
    print("  is it present in Batfish's model with the value we wrote?\n")

    cov = {k: {"checked": 0, "mismatch": [], "unverifiable": []} for k in
           ("address", "active", "ospf_area", "ospf_cost", "ospf_passive",
            "ospf_network", "static_route", "named_structure")}

    for name, _, sc, _spec in snaps:
        bf.set_snapshot(name)
        peers = peer_map(_spec)          # per-topology, never global
        ifp = bf.q.interfaceProperties().answer().frame()
        ospf = bf.q.ospfInterfaceConfiguration().answer().frame()
        ds = bf.q.definedStructures().answer().frame()
        if name == "golden":
            SCHEMA["interfaceProperties"] = [str(c) for c in ifp.columns]
            SCHEMA["ospfInterfaceConfiguration"] = \
                [str(c) for c in ospf.columns] if len(ospf) else []
            SCHEMA["definedStructures"] = [str(c) for c in ds.columns] \
                if len(ds) else []

        c_if = col(ifp, "Interface")
        c_pref = col(ifp, "All_Prefixes")
        c_admin = col(ifp, "Admin_Up")
        c_act = col(ifp, "Active")
        ip_map, act_map, admin_map = {}, {}, {}
        for _, r in ifp.iterrows():
            k = split_iface(r[c_if])
            ip_map[k] = [str(x) for x in (r[c_pref] or [])] if c_pref else []
            if c_act is not None:
                act_map[k] = bool(r[c_act])
            if c_admin is not None:
                admin_map[k] = bool(r[c_admin])

        o_if = col(ospf, "Interface")
        o_area = col(ospf, "OSPF_Area_Name", "Area", "OSPF_Area")
        o_cost = col(ospf, "OSPF_Cost", "Cost")
        o_pass = col(ospf, "OSPF_Passive", "Passive")
        o_net = col(ospf, "OSPF_Network_Type", "Network_Type")
        o_map = {}
        if o_if is not None:
            for _, r in ospf.iterrows():
                o_map[split_iface(r[o_if])] = r

        struct_names = {str(x) for x in ds[col(ds, "Structure_Name")]} \
            if len(ds) and col(ds, "Structure_Name") else set()

        routes = bf.q.routes(protocols="static").answer().frame()
        static_nets = {str(r[col(routes, "Network")]) for _, r in routes.iterrows()} \
            if len(routes) else set()

        for dname, dev in sc.devices.items():
            if dev.kind != "frr":
                continue
            for i in dev.ifaces:
                key = (norm(dname), i.name)
                for a in i.addresses:
                    cov["address"]["checked"] += 1
                    if a not in ip_map.get(key, []):
                        cov["address"]["mismatch"].append(
                            f"{name}/{dname}:{i.name} want {a} "
                            f"got {ip_map.get(key)}")
                # Batfish's `Active` is DERIVED: an interface whose layer-1
                # peer is admin-down is reported inactive, because a link with
                # one end shut has no carrier. That is correct modelling, so
                # the expectation has to account for it rather than compare
                # against admin state alone. `Admin_Up`, where present, is the
                # configured value and is compared directly.
                cov["active"]["checked"] += 1
                pk = peers.get((dname, i.name))
                peer_up = True
                if pk:
                    peer_up = sc.devices[pk[0]].iface(pk[1]).up
                want_active = i.up and peer_up
                if key in act_map and act_map[key] != want_active:
                    cov["active"]["mismatch"].append(
                        f"{name}/{dname}:{i.name} want active={want_active} "
                        f"(admin={i.up}, peer_up={peer_up}) got {act_map[key]}")
                if key in admin_map and admin_map[key] != i.up:
                    cov["active"]["mismatch"].append(
                        f"{name}/{dname}:{i.name} want admin_up={i.up} "
                        f"got {admin_map[key]}")
                if i.ospf_area is not None:
                    row = o_map.get(key)
                    for label, cname, want in (
                            ("ospf_area", o_area, i.ospf_area),
                            ("ospf_cost", o_cost, i.ospf_cost),
                            ("ospf_passive", o_pass, i.ospf_passive),
                            ("ospf_network", o_net, i.ospf_network)):
                        if want is None:
                            continue
                        cov[label]["checked"] += 1
                        if cname is None or row is None:
                            cov[label]["unverifiable"].append(
                                f"{name}/{dname}:{i.name} (no column/row)")
                            continue
                        got = row[cname]
                        same = same_value(got, want)
                        if not same:
                            cov[label]["mismatch"].append(
                                f"{name}/{dname}:{i.name} want {want} got {got}")
            for s in dev.statics:
                cov["static_route"]["checked"] += 1
                if s.prefix not in static_nets:
                    cov["static_route"]["mismatch"].append(
                        f"{name}/{dname} static {s.prefix} not in RIB")
            for group in (dev.access_lists, dev.prefix_lists, dev.route_maps):
                for sname in group:
                    cov["named_structure"]["checked"] += 1
                    if sname not in struct_names:
                        cov["named_structure"]["mismatch"].append(
                            f"{name}/{dname} structure {sname} NOT MODELLED")

    for k, v in cov.items():
        mark = "ok " if not v["mismatch"] else "BAD"
        extra = f"  unverifiable={len(v['unverifiable'])}" \
            if v["unverifiable"] else ""
        print(f"  {mark} {k:16s} checked={v['checked']:4d} "
              f"mismatches={len(v['mismatch'])}{extra}")
        for m in v["mismatch"][:6]:
            print(f"        {m}")
        for m in v["unverifiable"][:3]:
            print(f"        UNVERIFIABLE {m}")
    # `checked=0` printed as "ok" is how the static-route gap hid. If the
    # sampled scenarios contain a construct, it MUST have been checked.
    present = {"address": True, "active": True, "ospf_area": True,
               "ospf_cost": True, "ospf_passive": True, "ospf_network": True,
               "static_route": any(d.statics for _n, _p, sc, _s in snaps
                                   for d in sc.devices.values()),
               "named_structure": any(
                   d.access_lists or d.prefix_lists or d.route_maps
                   for _n, _p, sc, _s in snaps for d in sc.devices.values())}
    unchecked = [k for k, v in cov.items()
                 if present.get(k) and v["checked"] == 0]
    if unchecked:
        print(f"  BAD constructs present in the artifact but NEVER CHECKED: "
              f"{unchecked}")
    V["coverage"] = (all(not v["mismatch"] for v in cov.values())
                     and not unchecked)
    unver = {k: len(v["unverifiable"]) for k, v in cov.items()
             if v["unverifiable"]}
    if unver:
        NOTES.append(f"unverifiable constructs (column not found): {unver}")

    # ---- CHECK 4: OSPF adjacencies on golden --------------------------
    print("\nCHECK 4 -- OSPF adjacencies, per topology golden")
    adj_bad = []
    for name in [n for n, _, _, _ in snaps if n.startswith("golden")]:
        bf.set_snapshot(name); bf.generate_dataplane()
        oo = bf.q.ospfSessionCompatibility().answer().frame()
        pp = {frozenset((split_iface(r["Interface"])[0],
                         split_iface(r["Remote_Interface"])[0]))
              for _, r in oo.iterrows()} if len(oo) else set()
        want = expected_ospf_pairs(specs[name])
        est = len(oo) > 0 and all(str(s) == "ESTABLISHED"
                                  for s in oo["Session_Status"])
        ok = pp == want and est
        print(f"  {name:22} [{specs[name].name}] observed={len(pp)} "
              f"expected={len(want)} established={est}  {'ok' if ok else 'PROBLEM'}")
        if not ok:
            adj_bad.append(name)
    V["ospf_all_topologies"] = not adj_bad
    bf.set_snapshot(g0)
    o = bf.q.ospfSessionCompatibility().answer().frame()
    pairs = {frozenset((split_iface(r["Interface"])[0],
                        split_iface(r["Remote_Interface"])[0]))
             for _, r in o.iterrows()} if len(o) else set()
    est = len(o) > 0 and all(str(s) == "ESTABLISHED"
                             for s in o["Session_Status"])
    print(f"  expected {sorted(tuple(sorted(p)) for p in expected_ospf_pairs(specs[g0]))}")
    print(f"  observed {sorted(tuple(sorted(p)) for p in pairs)}")
    print(f"  rows={len(o)}  all ESTABLISHED={est}")
    V["ospf"] = pairs == expected_ospf_pairs(specs[g0]) and est

    # ---- CHECK 5: the F10 replacement is actually observable ----------
    print("\nCHECK 5 -- the replacement fault family is observable")
    print("  A /32 for a host is installed pointing back at the upstream")
    print("  neighbour. It beats the connected /24 locally, while upstream")
    print("  OSPF still points here. That is a two-hop loop.")
    loop_id = pick_family(man_for_checks, loaded, "static_route_loop", "I-10")
    if loop_id is None:
        print("  SKIPPED: no static_route_loop snapshot in the sample")
        V["f10_observable"] = False
        NOTES.append(
            "CHECK 5 skipped: this corpus has no static_route_loop "
            "snapshot. Recorded FAILED, never passed -- a check that "
            "did not run has not passed. A corpus without fault "
            "families needs a documented substitute, not a waiver.")
    else:
        bf.set_snapshot(loop_id)
        bf.generate_dataplane()
        loops = show(f"detectLoops [{loop_id}]",
                     bf.q.detectLoops().answer().frame(), 10)

        from pybatfish.datamodel import HeaderConstraints
        tr = bf.q.traceroute(
            startLocation="@enter(edgea[eth1])",
            headers=HeaderConstraints(srcIps="10.10.0.10", dstIps="10.20.0.10",
                                      ipProtocols=["ICMP"], icmpTypes=[8],
                                      icmpCodes=[0])).answer().frame()
        disps = []
        for _, row in tr.iterrows():
            for x in row["Traces"]:
                disps.append(str(x.disposition))
        print(f"  traceroute hosta -> hostb dispositions: {disps}")

        # the golden of THIS incident's topology, not a hardcoded "golden"
        gname = (f"golden-{specs[loop_id].name}"
                 if f"golden-{specs[loop_id].name}" in loaded else "golden")
        baseline = bf.q.detectLoops().answer(snapshot=gname).frame()
        print(f"  {gname} loop rows (must be 0): {len(baseline)}")
        V["f10_observable"] = bool(
            (len(loops) > 0 or any(d == "LOOP" for d in disps)) and len(baseline) == 0)
        if not V["f10_observable"]:
            print("  Batfish does not see the loop. Retire F10 again and choose")
            print("  another construct -- do not keep a fault only one tool sees.")

    # ---- CHECK 6: statics -------------------------------------------
    print("\nCHECK 6 -- static routes reach the RIB (I-08 blackhole)")
    bh_id = pick_family(man_for_checks, loaded, "static_blackhole", "I-08")
    if bh_id is None:
        print("  SKIPPED: no static_blackhole snapshot in the sample")
        V["statics"] = False
        NOTES.append(
            "CHECK 6 skipped: this corpus has no static_blackhole "
            "snapshot. Recorded FAILED, never passed.")
    else:
        bf.set_snapshot(bh_id)
        bh_node = node_for(man_for_checks, bh_id, "corea")
        st = bf.q.routes(nodes=bh_node, protocols="static").answer().frame()
        show("static routes on corea [I-08]", st)
        V["statics"] = len(st) > 0

    # ---- verdict ------------------------------------------------------
    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    V_clean = {k: bool(v) for k, v in V.items()}   # numpy.bool_ is not JSON-able
    for k, v in V_clean.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    for n in NOTES:
        print(f"  note: {n}")
    go = all(V_clean.values())

    out = PILOT / "phase2"
    out.mkdir(parents=True, exist_ok=True)
    try:
        import pybatfish
        pbv = getattr(pybatfish, "__version__", "unknown")
    except Exception:                                              # noqa: BLE001
        pbv = "unknown"
    # Stamp which artifact this verdict is about. run_phase2.py compares it
    # against the current lock and refuses if the pilot has been rebuilt --
    # otherwise a stale GO from a previous artifact would wave Phase 2 through.
    try:
        lock = json.loads((PILOT / "pilot.lock.json").read_text())
        digest = lock.get("artifact_digest")
        snap = lock.get("snapshot_digest")
    except Exception:                                              # noqa: BLE001
        digest = snap = None

    payload = {
        "verdict": "GO" if go else "STOP",
        "artifact_digest": digest,
        "snapshot_digest": snap,
        "checks": V_clean,
        "notes": NOTES,
        "coverage": {k: {"checked": int(v["checked"]),
                         "mismatches": len(v["mismatch"]),
                         "unverifiable": len(v["unverifiable"]),
                         "examples": v["mismatch"][:10]}
                     for k, v in cov.items()},
        "batfish_schema_observed": SCHEMA,
        "snapshots_checked": [s[0] for s in snaps],
        "total_parse_warnings": int(warn_total),
        "formats_detected": sorted(fmts),
        "pybatfish_version": pbv,
        "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "run_phase2.py reads this and refuses unless verdict == GO.",
    }
    (out / "spike_result.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        newline="\n", encoding="utf-8")
    print(f"\nverdict written to {out / 'spike_result.json'}")
    if digest:
        print(f"  artifact digest: {digest[:16]}...")

    print()
    if go:
        print("GO. Every construct in the artifact is represented in Batfish's")
        print(f"model, across all {len(snaps)} snapshots. Record the image digest in")
        print("notes/lab-notebook.md and PIN IT -- a future 'latest' can regress")
        print("FRR grammar underneath you. Then:")
        print("    python pipeline\\run_phase2.py --limit 3")
    else:
        print("STOP. Do not run Phase 2. Work the failing checks top-down.")
        print("A coverage mismatch means Containerlab would enforce something")
        print("Batfish cannot see -- retire that construct rather than")
        print("translating configs or changing vendor to make the test pass.")
    return 0 if go else 2


if __name__ == "__main__":
    sys.exit(main())
