"""Controls for the OSPF-binding validity check (S-020). No Docker.

Replays the two real Stage 1 runs of C-01361 -- the one that measured 16
adjacencies and the byte-identical re-run that measured 15 -- straight off the
captured state on disk. If this check cannot tell those two apart, it cannot
stop the label flip that motivated it.

    python pipeline/test_lab_validity.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from nrl import clab                                              # noqa: E402
from nrl.scenario_io import read as read_scenario                 # noqa: E402

FAIL = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAIL.append(label)
        if detail:
            print(f"         {detail}")


def load_state(run_dir: Path) -> dict:
    """Rebuild the state dict from the per-node files the run wrote."""
    state = {}
    for f in sorted((run_dir / "state").glob("*.json")):
        node, label = f.name[:-5].split(".", 1)
        state.setdefault(node, {})[label] = json.loads(f.read_text())
    return state


def main():
    print("=" * 62)
    print("LAB VALIDITY CONTROLS -- S-020 OSPF binding")
    print("=" * 62)

    archive = sorted(Path("data/pilot-v2").glob("phase3*/runs"))
    good = bad = None
    for runs in archive:
        if (runs / "C-01361" / "state").is_dir():
            good = runs / "C-01361"
        if (runs / "C-01361~r1" / "state").is_dir():
            bad = runs / "C-01361~r1"
    if not good or not bad:
        print("  [SKIP] the Stage 1 C-01361 runs are not on disk "
              "(nothing to replay)")
        return 0

    sc = read_scenario(Path("data/pilot-v2/candidates/C-01361/scenario.json"))

    print("\nthe run that measured 16 adjacencies")
    r = clab.verify_ospf_binding(load_state(good), sc)
    check("passes the binding check", r["status"] == "OK", str(r["problems"]))

    print("\nthe identical re-run that measured 15 and flipped the label")
    r = clab.verify_ospf_binding(load_state(bad), sc)
    check("is caught as invalid", r["status"] == "MISMATCH",
          "if this passes, the check does not detect the defect it exists for")
    check("and names the interface", any("b1:eth2" in p for p in r["problems"]),
          str(r["problems"]))

    print("\nthe checks that were already there both passed on that lab")
    st = load_state(bad)
    check("verify_running_config says OK",
          clab.verify_running_config(st, sc)["status"] == "OK",
          "the config text really is correct -- that is the point")
    check("verify_addresses says OK",
          clab.verify_addresses(st, sc)["status"] == "OK",
          "the addresses really are present -- that is the point")

    print("\nNEGATIVE CONTROL -- an artifact interface not in OSPF is not "
          "expected in ospfd")
    # Guards against the check being trivially satisfiable: if it demanded
    # every artifact interface, a legitimately non-OSPF interface would fail.
    non_ospf = [(n, i.name) for n, d in sc.devices.items()
                if d.kind == "frr" for i in d.ifaces
                if i.ospf_area is None and i.name != "lo"]
    r = clab.verify_ospf_binding(load_state(good), sc)
    check("a clean lab with non-OSPF interfaces still passes",
          r["status"] == "OK",
          f"{len(non_ospf)} non-OSPF artifact interfaces: {non_ospf[:3]}")

    print("\nPOSITIVE CONTROL -- a fabricated missing binding is caught")
    st = load_state(good)
    victim = None
    for n, d in sc.devices.items():
        if d.kind != "frr":
            continue
        for i in d.ifaces:
            if i.ospf_area is not None and i.up and i.name != "lo":
                victim = (n, i.name)
                break
        if victim:
            break
    n, name = victim
    st[n]["ospf_interface"]["json"]["interfaces"].pop(name, None)
    r = clab.verify_ospf_binding(st, sc)
    check(f"removing {n}:{name} from ospfd is detected",
          r["status"] == "MISMATCH" and any(f"{n}:{name}" in p
                                            for p in r["problems"]),
          str(r["problems"])[:200])

    print("\nNEGATIVE CONTROL -- a faulted lab is NOT flagged")
    # The two iface_down incidents. ospfd legitimately drops an interface whose
    # link is down; an earlier version of this check flagged both, which is
    # v1.0.0's mistake (requiring expected adjacencies) in a new place.
    for iid, node in (("I-00001", "corea"), ("I-00181", "agga")):
        rd = None
        for runs in archive:
            if (runs / iid / "state").is_dir():
                rd = runs / iid
        if not rd:
            continue
        isc = read_scenario(Path(f"data/pilot-v2/incidents/{iid}/scenario.json"))
        r = clab.verify_ospf_binding(load_state(rd), isc)
        check(f"{iid} (iface_down on {node}) is not flagged",
              r["status"] == "OK",
              f"{r['problems']} -- the fault takes the link down; demanding "
              f"the adjacency back fails every faulted lab by construction")

    print("\n" + "=" * 62)
    print("ALL LAB VALIDITY CONTROLS PASSED" if not FAIL else "FAILED")
    for f in FAIL:
        print(f"   {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
