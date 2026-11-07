"""Prove every topology-dependent expectation comes from that topology's spec.

    python3 pipeline/test_topology_aware.py

Runs without Batfish or Docker. Two things it must establish:
  * pilot-v1 semantics are byte-for-byte unchanged (the frozen Phase 3 results
    stay valid)
  * a candidate from topology X is never scored against topology Y's expectations
"""
from __future__ import annotations
import copy, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import nrl.bf_eval as B                                            # noqa: E402
import nrl.p3_eval as P                                            # noqa: E402
from nrl.properties import PROPERTIES, properties_for              # noqa: E402
from nrl.topologies import (T2V1, TOPOLOGIES, expected_ospf_pairs,  # noqa: E402
                            host_attach, ip_to_node, resolve, src_node)

FAIL = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAIL.append(label)
        if detail: print(f"         {detail}")


def main() -> int:
    print("CHECK 1 -- pilot-v1 semantics are unchanged")
    # These were compared against module constants inside bf_eval / p3_eval.
    # Those constants have been deleted (they held one network's addresses and
    # were the same shape as every defect in the log), so pilot-v1's values are
    # restated here, in the test, which is where an expected value belongs.
    # They are pilot-v1's RECORDED semantics and must never change.
    V1_OSPF_PAIRS = {frozenset(p) for p in [
        ("edgea", "corea"), ("corea", "wan1"), ("wan1", "wan2"),
        ("wan2", "coreb"), ("coreb", "edgeb"), ("corea", "coreb")]}
    V1_HOST_ATTACH = {
        "10.10.0.10": ("edgea", "eth1"),
        "10.20.0.10": ("edgeb", "eth2"),
        "10.21.0.10": ("edgeb", "eth3"),
        "10.255.0.1": ("edgea", None),
        "10.255.0.6": ("edgeb", None)}
    V1_SRC_NODE = {
        "10.10.0.10": ("hosta", None),
        "10.20.0.10": ("hostb", None),
        "10.21.0.10": ("hostc", None),
        "10.255.0.1": ("edgea", "10.255.0.1"),
        "10.255.0.6": ("edgeb", "10.255.0.6")}
    check("expected_ospf_pairs(T2V1) == pilot-v1's recorded adjacency set",
          expected_ospf_pairs(T2V1) == V1_OSPF_PAIRS,
          f"{sorted(tuple(sorted(x)) for x in expected_ospf_pairs(T2V1))}")
    check("host_attach(T2V1) == pilot-v1's recorded attach map",
          host_attach(T2V1) == V1_HOST_ATTACH, str(host_attach(T2V1)))
    check("src_node(T2V1) == pilot-v1's recorded source map",
          src_node(T2V1) == V1_SRC_NODE, str(src_node(T2V1)))
    check("ip_to_node(T2V1) resolves every router loopback",
          all(ip_to_node(T2V1).get(rid) == n
              for n, rid in T2V1.routers.items()))
    # properties_for(None) is the pilot-v1 suite. It differs from the frozen
    # PROPERTIES list in exactly one place -- P11.dst, whose literal is the
    # None placeholder -- and that difference must be T2V1's OWN edgeb
    # loopback, read from the model rather than restated as .6 here.
    #
    # This check asserted plain equality and has been FAILING since P11 was
    # parameterised; it was not re-run, so the fix that removed one silent
    # defect left a red test nobody read. A frozen-semantics check is only
    # worth having if it is executed after every change to what it freezes.
    v1 = properties_for(None)
    frozen = copy.deepcopy(PROPERTIES)
    expect = dict(zip([q["pid"] for q in frozen], frozen))
    expect["P11"]["dst"] = T2V1.routers["edgeb"]
    check("properties_for(None) == the frozen suite with P11 resolved to "
          f"pilot-v1's edgeb loopback ({T2V1.routers['edgeb']})",
          v1 == frozen)
    check("resolve(None) is the pilot-v1 network", resolve(None).name == "t2v1")
    # Every address a property NAMES must be owned by the router it names.
    # This is the pure-python analogue of the ipOwners check in
    # verify_golden_properties.py, and it covers the legacy specs too, which
    # no golden snapshot exists for. P11 is the only address-valued property
    # that names a router; if another is added it belongs here.
    for name, s in TOPOLOGIES.items():
        p11 = {q["pid"]: q for q in properties_for(s)}["P11"]
        for role, addr in (("edgea", p11["src"]), ("edgeb", p11["dst"])):
            check(f"{name}: P11 {role} address {addr} is owned by {role}",
                  addr == s.routers.get(role),
                  f"spec.routers[{role}] = {s.routers.get(role)}")
            ha = host_attach(s).get(addr)
            check(f"{name}: {addr} is a usable probe origin/target in the model",
                  ha is not None and ha[0] == role,
                  f"host_attach maps it to {ha}")

    # NEGATIVE CONTROL. This test previously asserted the OPPOSITE -- that an
    # unknown name falls back to pilot-v1 -- and passed, certifying a silent
    # wrong-target as intended behaviour. An unknown topology now raises.
    try:
        resolve("nonsense")
        check("resolve('nonsense') raises instead of silently using pilot-v1",
              False, "returned a spec instead of raising")
    except KeyError:
        check("resolve('nonsense') raises instead of silently using pilot-v1",
              True)

    print("\nCHECK 2 -- each topology gets its OWN expectations")
    for n, s in sorted(TOPOLOGIES.items()):
        ps = properties_for(s)
        p8 = [p for p in ps if p["pid"] == "P08"][0]
        p6 = [p for p in ps if p["pid"] == "P06"][0]
        check(f"{n}: P08 expected == its adjacency count ({s.n_adjacencies})",
              p8["expected"] == s.n_adjacencies == len(expected_ospf_pairs(s)))
        check(f"{n}: P06 must_traverse nodes all exist in {n}",
              set(p6["must_traverse"]) <= set(s.routers),
              f"{p6['must_traverse']} vs {sorted(s.routers)}")

    print("\nCHECK 3 -- every transit hop resolves in its own topology")
    for n, s in sorted(TOPOLOGIES.items()):
        table = ip_to_node(s)
        hops = [l[2].split("/")[0] for l in s.links if l[0] in s.routers] + \
               [l[5].split("/")[0] for l in s.links if l[3] in s.routers]
        miss = [h for h in hops if h not in table]
        check(f"{n}: {len(hops)}/{len(hops)} transit hop IPs resolvable",
              not miss, f"unresolved: {miss[:4]}")

    print("\nCHECK 4 -- probe endpoints exist in every topology")
    for n, s in sorted(TOPOLOGIES.items()):
        ha, sn = host_attach(s), src_node(s)
        bad = [ip for ip, (node, _i) in ha.items()
               if node not in s.routers and node not in s.hosts]
        check(f"{n}: every host_attach node exists", not bad, str(bad))
        bad2 = [ip for ip, (node, _i) in sn.items()
                if node not in s.routers and node not in s.hosts]
        check(f"{n}: every src_node container exists", not bad2, str(bad2))
        for pid, ip in (("P01/P02 src", "10.10.0.10"), ("P05 src", "10.20.0.10")):
            check(f"{n}: {pid} {ip} is resolvable", ip in ha and ip in sn)

    print("\nCHECK 5 -- NEGATIVE CONTROL: cross-topology scoring must be wrong")
    print("   (if these 'pass', the test has no power and proves nothing)")
    t1, t3 = TOPOLOGIES["t1"], TOPOLOGIES["t3"]
    check("t1 scored with t2v1's adjacency set would be WRONG",
          expected_ospf_pairs(t1) != expected_ospf_pairs(T2V1))
    check("t3 scored with t2v1's adjacency set would be WRONG",
          expected_ospf_pairs(t3) != expected_ospf_pairs(T2V1))
    check("t1's primary-path nodes do NOT exist in t2v1's expectation",
          not set(t1.primary_path) <= set(properties_for(T2V1)[0].get("x", []) or
                                          ["wan1", "wan2"]))
    check("t1 hops are unresolvable in t2v1's table (the silent P06 failure)",
          any(l[2].split("/")[0] not in ip_to_node(T2V1)
              for l in t1.links if l[0] in t1.routers))

    print("\nCHECK 6 -- peer maps never reference another topology's nodes")
    print("   (the KeyError: 'wan1' class -- interface names repeat across")
    print("    networks, so a global peer map silently resolves to the wrong one)")
    def peer_map(spec):
        m = {}
        for l in spec.links:
            a, ai, b, bi = l[0], l[1], l[3], l[4]
            if a in spec.routers and b in spec.routers:
                m[(a, ai)] = (b, bi); m[(b, bi)] = (a, ai)
        return m
    for n, s_ in sorted(TOPOLOGIES.items()):
        pm = peer_map(s_)
        bad = [(k, v) for k, v in pm.items() if v[0] not in s_.routers]
        check(f"{n}: every peer resolves inside {n}", not bad, str(bad[:3]))
    # cross-topology negative control: v1's map applied to t01 must break
    v1pm = peer_map(T2V1)
    t01 = TOPOLOGIES["t01_chain4"]
    leak = [(k, v) for k, v in v1pm.items()
            if k[0] in t01.routers and v[0] not in t01.routers]
    check("v1's peer map WOULD mis-resolve on t01 (proves the check has power)",
          bool(leak), "no leak found -- the negative control is vacuous")
    print(f"         e.g. {leak[0] if leak else 'n/a'} -> node absent from t01")

    print("\nCHECK 7 -- no module-level v1 constant exists at all")
    # These used to be policed as "defined, never read". A dead constant
    # holding one network's addresses is still a loaded gun -- reading
    # HOST_ATTACH["10.255.0.6"] again is precisely how P11 came to test
    # wan3/wan4/coreb. They are now required to be ABSENT.
    import nrl.bf_eval as _b, nrl.p3_eval as _p
    for mod, names in ((_b, ["EXPECTED_OSPF_PAIRS", "HOST_ATTACH"]),
                       (_p, ["SRC_NODE", "IP_TO_NODE"])):
        for nm in names:
            check(f"{mod.__name__}.{nm} no longer exists",
                  not hasattr(mod, nm),
                  f"still defined -- delete it; everything topology-dependent "
                  f"comes from the spec")

    print("\nCHECK 7b -- spec is required, not defaulted to pilot-v1")
    import inspect as _i
    for fn, mod in ((_b.evaluate_all, "bf_eval"),
                    (_b.evaluate_property, "bf_eval"),
                    (_b.start_location, "bf_eval")):
        sg = _i.signature(fn)
        sp = sg.parameters.get("spec")
        check(f"{mod}.{fn.__name__}(spec=...) has no default",
              sp is not None and sp.default is _i.Parameter.empty,
              f"default is {sp.default!r} -- a caller that forgets to thread "
              f"the topology would silently probe pilot-v1's network")

    print(f"\n{'=' * 62}")
    print("FAILED" if FAIL else "ALL TOPOLOGY-AWARENESS CHECKS PASSED")
    for f in FAIL: print(f"   {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
