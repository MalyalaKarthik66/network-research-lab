"""
GATE: every property in the suite must hold on every GOLDEN topology.

The golden is the network before any fault. By construction it is healthy, so
all twelve properties must PASS on all ten topologies. Any FAIL means the
PROPERTY is wrong, not the network -- and a wrong property silently poisons
every candidate that inherits it.

This gate did not exist, and its absence cost a run. P11 targeted edgeb's
loopback but hardcoded 10.255.0.6 from pilot-v1. edgeb's loopback index is 4,
5, 6 or 8 depending on topology, so P11 was:
    right          in t02 t06 t07 t09
    a false FAIL   in t01 t04 t05      (.6 does not exist -> NO_ROUTE)
    a false PASS   in t03 t08 t10      (.6 exists, but it is wan3/wan4/coreb)
The false-PASS group is why "all green" was not evidence: the property was
answering confidently about a router it was never meant to test.

Three things this gate asserts, in increasing order of what they cost to learn:

1. COMPLETENESS. Every topology in the lock was visited and every property in
   the suite was evaluated on it. The first version of this gate had no such
   assertion: an empty manifest, or an evaluate_all() that returned [], would
   have printed "PASS -- every property holds on every golden" having evaluated
   nothing at all. That is the exact defect class the gate exists to catch,
   inside the gate.

2. TARGET OWNERSHIP. For the address-valued properties, the address is checked
   against Batfish's own ipOwners answer -- an independent source -- to confirm
   it belongs to the router the property NAMES. Reachability alone cannot catch
   the false-PASS case, because pinging the wrong router succeeds.

3. HEALTH. Every property PASSes on every golden.

Run this after ANY change to the property suite and before any Phase 2 batch.

    python pipeline/verify_golden_properties.py --pilot data/pilot-v2
    python pipeline/verify_golden_properties.py --pilot data/pilot-v2 --negative-control

--negative-control asks four properties that MUST fail on a healthy network
(an unassigned loopback, a prefix nobody originates, a path through a router
that does not exist, one more adjacency than the topology has). If any of them
PASSes, the evaluator is not discriminating and a green main run means nothing.
A gate that has never been observed failing has not been tested, only run.
"""
from __future__ import annotations
import argparse, json, logging, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl.properties import (PROPERTIES, properties_for, loopback_of,   # noqa: E402
                            SUITE_VERSION)
from nrl.topologies import resolve                                     # noqa: E402
from nrl.bf_eval import evaluate_all, evaluate_property                # noqa: E402

EXPECTED_PIDS = [p["pid"] for p in PROPERTIES]




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

def owner_of(bf, ip: str):
    """Which node Batfish thinks owns an address. Independent of reachability."""
    try:
        f = bf.q.ipOwners().answer().frame()
    except Exception as exc:                                   # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    hits = {str(r["Node"]) for _, r in f.iterrows() if str(r["IP"]) == ip}
    return hits, None


def negative_control(bf, spec) -> list:
    """Properties that must FAIL on a healthy golden. Returns the ones that did
    not -- i.e. the evidence that the evaluator is inert."""
    probes = [
        dict(pid="NC1", kind="reachability", in_spec=False,
             src=loopback_of(spec, "edgea"), dst="10.255.0.99", app="ICMP",
             text="NEGATIVE: unassigned loopback must be unreachable"),
        dict(pid="NC2", kind="route_present", in_spec=False,
             prefix="192.0.2.0/24", nodes="all_routers",
             text="NEGATIVE: no router may have a route to TEST-NET-1"),
        dict(pid="NC3", kind="path_contains", in_spec=False,
             src="10.10.0.10", dst="10.20.0.10",
             must_traverse=["nosuchrouter"],
             text="NEGATIVE: path cannot traverse a router that does not exist"),
        dict(pid="NC4", kind="ospf_adjacencies", in_spec=False,
             expected=spec.n_adjacencies + 1,
             text="NEGATIVE: one more adjacency than the topology has"),
    ]
    inert = []
    for p in probes:
        r = evaluate_property(bf, p, spec=spec)
        if r.get("status") != "OK":
            inert.append((p["pid"], f"ERROR {r.get('error')}"))
        elif r.get("verdict") != "FAIL":
            inert.append((p["pid"], f"returned {r.get('verdict')}, expected FAIL"))
    return inert


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--negative-control", action="store_true",
                    help="also run probes that MUST fail on a healthy golden")
    a = ap.parse_args()
    root = resolve_pilot(a.pilot)

    lock = json.loads((root / "pilot.lock.json").read_text())
    man = json.loads((root / "manifest.json").read_text())
    topos = sorted({c["topology"] for c in man["candidates"]})
    locked = sorted(lock.get("topologies") or [])

    print("=" * 72)
    print(f"GOLDEN PROPERTY GATE -- suite {SUITE_VERSION}")
    print(f"  pilot           : {root}")
    print(f"  snapshot_digest : {str(lock.get('snapshot_digest'))[:16]}")
    print(f"  artifact_digest : {str(lock.get('artifact_digest'))[:16]}")
    print(f"  topologies      : {len(topos)} in manifest, {len(locked)} in lock")
    print(f"  properties      : {len(EXPECTED_PIDS)}  {','.join(EXPECTED_PIDS)}")
    print("=" * 72)

    # ---- COMPLETENESS, before anything is evaluated -----------------------
    if not topos:
        print("FAIL -- the manifest lists no topologies. Nothing would have")
        print("been evaluated and this gate would have printed PASS.")
        return 1
    if topos != locked:
        print("FAIL -- manifest topologies do not match the lock.")
        print(f"  manifest only: {sorted(set(topos) - set(locked))}")
        print(f"  lock only    : {sorted(set(locked) - set(topos))}")
        print("  The gate would have skipped whatever is missing and still")
        print("  reported PASS for the ones it did visit.")
        return 1

    logging.getLogger("pybatfish").setLevel(logging.ERROR)
    from pybatfish.client.session import Session
    bf = Session(host="localhost")
    bf.set_network(f"nrl-goldengate-{root.name}")

    failures, errors, structural, inert = [], [], [], []
    n_eval = 0
    for tn in topos:
        spec = resolve(tn)
        snap = root / "reference" / f"golden-{tn}" / "batfish-snapshot"
        if not snap.is_dir():
            structural.append((tn, "-", f"missing snapshot {snap}"))
            print(f"  FAIL {tn:12s} snapshot directory missing")
            continue
        bf.init_snapshot(str(snap), name=f"gg-{tn}", overwrite=True)
        bf.generate_dataplane()

        res = evaluate_all(bf, spec=spec)
        n_eval += len(res)

        # every property, exactly once. A short list is not a clean run.
        got = [r.get("property_id") or r.get("pid") for r in res]
        if sorted(got) != sorted(EXPECTED_PIDS):
            structural.append((tn, "-",
                               f"evaluated {sorted(got)}, expected "
                               f"{sorted(EXPECTED_PIDS)}"))

        # the address a property NAMES must belong to the router it names
        for node in ("edgea", "edgeb"):
            ip = loopback_of(spec, node)
            owners, err = owner_of(bf, ip)
            if err:
                structural.append((tn, "P11", f"ipOwners: {err}"))
            elif owners != {node}:
                structural.append(
                    (tn, "P11", f"{ip} is owned by {sorted(owners) or 'nobody'}, "
                                f"but the property names {node}"))

        bad, err = [], []
        for r in res:
            pid = r.get("property_id") or r.get("pid")
            if (r.get("status") or "OK") != "OK":
                err.append(pid); errors.append((tn, pid, r.get("error")))
            elif r.get("verdict") != "PASS":
                bad.append(pid); failures.append((tn, pid, r.get("text")))

        if a.negative_control:
            for pid, why in negative_control(bf, spec):
                inert.append((tn, pid, why))

        struct_here = [x for x in structural if x[0] == tn]
        mark = "ok  " if not (bad or err or struct_here) else "FAIL"
        print(f"  {mark} {tn:12s} {len(res)}/{len(EXPECTED_PIDS)} properties"
              f"{'  violated=' + ','.join(bad) if bad else ''}"
              f"{'  errored=' + ','.join(err) if err else ''}"
              f"{'  STRUCTURAL' if struct_here else ''}")

    print("=" * 72)
    expected_total = len(topos) * len(EXPECTED_PIDS)
    print(f"evaluated {n_eval}/{expected_total} property instances")
    if n_eval != expected_total:
        structural.append(("-", "-",
                           f"{n_eval} evaluations, expected {expected_total}"))

    if not (failures or errors or structural or inert):
        print(f"PASS -- {expected_total} property instances, all PASS, on "
              f"{len(topos)} goldens.")
        if a.negative_control:
            print("Negative control: all four must-fail probes failed. The "
                  "evaluator discriminates.")
        else:
            print("Negative control NOT run. Add --negative-control before "
                  "trusting a green result on a suite you just changed.")
        print("The suite is safe to evaluate against candidates.")
        return 0

    for tn, pid, why in structural:
        print(f"  STRUCTURAL {tn:12s} {pid}  {why}")
    for tn, pid, why in failures:
        print(f"  VIOLATED   {tn:12s} {pid}  {why}")
    for tn, pid, why in errors:
        print(f"  ERRORED    {tn:12s} {pid}  {why}")
    for tn, pid, why in inert:
        print(f"  INERT      {tn:12s} {pid}  {why}")
    print()
    if structural:
        print("A STRUCTURAL failure means the gate could not have measured what")
        print("it claims -- a property was not evaluated, or an address belongs")
        print("to a router other than the one the property names. This is the")
        print("P11 shape. Do not proceed.")
    if inert:
        print("An INERT result means a property that must fail on a HEALTHY")
        print("network did not. The evaluator is not discriminating, so the")
        print("main run's PASSes carry no information.")
    if failures or errors:
        print("A property that fails on a HEALTHY network is measuring something")
        print("other than what its text claims. Fix the property. Do not proceed")
        print("to Phase 2 -- every candidate would inherit the same defect.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
