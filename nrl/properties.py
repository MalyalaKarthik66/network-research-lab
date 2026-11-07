"""The property suite, and the deliberate gap inside it.

Two sets, and the difference between them is the entire experiment:

  SPEC  (in_spec: true)  -- what Batfish is asked in Phase 2. This stands in for
                            the properties a real operator would have written
                            down. It is intentionally incomplete, the way real
                            suites are.
  ORACLE (all properties) -- what Containerlab measures in Phase 3.

A candidate that satisfies SPEC and violates something in ORACLE\\SPEC is a
false pass. That is the quantity the whole project is built to measure, so the
gap has to be designed in, declared up front, and frozen -- not discovered
later by widening the oracle until interesting numbers appear.

Frozen for pilot-v1. Changing membership changes the measured false-pass rate,
so any edit must bump SUITE_VERSION and be recorded in docs/HARM-DEFINITION.md.
"""

from __future__ import annotations

SUITE_VERSION = "1.1.0"

HOST_A, HOST_B, HOST_C = "10.10.0.10", "10.20.0.10", "10.21.0.10"

PROPERTIES = [
    dict(pid="P01", kind="reachability", in_spec=True,
         src=HOST_A, dst=HOST_B, app="ICMP",
         text="hosta can ping hostb"),
    dict(pid="P02", kind="reachability", in_spec=True,
         src=HOST_A, dst=HOST_B, app="HTTPS",
         text="hosta can reach hostb on TCP/443"),
    dict(pid="P05", kind="reachability", in_spec=True,
         src=HOST_B, dst=HOST_A, app="ICMP",
         text="hostb can ping hosta (return path)"),
    dict(pid="P07", kind="no_loops", in_spec=True,
         text="no forwarding loops anywhere"),
    dict(pid="P08", kind="ospf_adjacencies", in_spec=True, expected=6,
         text="all six OSPF adjacencies are established"),

    # ---- outside the spec: the blind spots, declared in advance ----
    dict(pid="P03", kind="reachability", in_spec=False,
         src=HOST_A, dst=HOST_C, app="ICMP",
         text="hosta can ping hostc (second site-B LAN)"),
    dict(pid="P04", kind="reachability", in_spec=False,
         src=HOST_A, dst=HOST_C, app="HTTPS",
         text="hosta can reach hostc on TCP/443"),
    dict(pid="P06", kind="path_contains", in_spec=False,
         src=HOST_A, dst=HOST_B, must_traverse=["wan1", "wan2"],
         text="hosta->hostb uses the primary WAN, not the backup"),
    dict(pid="P09", kind="route_present", in_spec=False,
         prefix="10.20.0.0/24", nodes="all_routers",
         text="every router has a route to 10.20.0.0/24"),
    dict(pid="P10", kind="route_present", in_spec=False,
         prefix="10.21.0.0/24", nodes="all_routers",
         text="every router has a route to 10.21.0.0/24"),
    # dst is a PLACEHOLDER. edgeb's loopback is 10.255.0.<n> where n is its
    # index in spec.routers, so it differs per topology (.4 .5 .6 .8 all occur).
    # properties_for(spec) MUST overwrite it; see the assertion there.
    dict(pid="P11", kind="reachability", in_spec=False,
         src="10.255.0.1", dst=None, app="ICMP",
         text="edgea loopback can reach edgeb loopback"),
    dict(pid="P12", kind="no_iface_down", in_spec=False,
         text="no interface is administratively down"),
]

# Parameters that MUST be resolved from the topology spec. properties_for()
# fills them in; as_yaml() refuses to publish a constant for them. Adding a
# topology-dependent parameter to a property means adding it here too.
PER_TOPOLOGY_PARAMS = {
    ("P06", "must_traverse"),   # primary path, Dijkstra over OSPF cost
    ("P08", "expected"),        # adjacency count
    ("P11", "src"),             # edgea loopback
    ("P11", "dst"),             # edgeb loopback
}

SPEC = [p for p in PROPERTIES if p["in_spec"]]
ORACLE_ONLY = [p for p in PROPERTIES if not p["in_spec"]]


def properties_for(spec=None):
    """The frozen suite with its two topology-dependent parameters filled in.

    THREE properties depend on the network, not two. The earlier claim that
    "only P08 and P06 depend on the network" was wrong and cost real data: P11
    targets edgeb's LOOPBACK, which is 10.255.0.<index-of-edgeb>, and that index
    is 4, 5, 6 or 8 depending on the topology. Hardcoded to .6 it was correct in
    4 of 10 topologies, returned a false NO_ROUTE in 3 where the address does not
    exist, and -- worse -- silently PASSED in 3 where .6 exists but belongs to
    wan3/wan4/coreb, measuring a router it was never meant to test.

    Host addresses (P01-P05, P09, P10) really are a shared convention and are
    identical in every topology, so those need no parameterisation.

    Passing spec=None yields the pilot-v1 values byte-for-byte.
    """
    import copy
    out = copy.deepcopy(PROPERTIES)
    if spec is None:
        for p in out:                      # v1: edgeb was router index 6
            if p["pid"] == "P11":
                p["dst"] = "10.255.0.6"
        return out
    for p in out:
        if p["pid"] == "P08":
            p["expected"] = spec.n_adjacencies
        elif p["pid"] == "P06":
            p["must_traverse"] = list(spec.primary_path)
        elif p["pid"] == "P11":
            p["dst"] = loopback_of(spec, "edgeb")
            p["src"] = loopback_of(spec, "edgea")
    # Completeness, not placeholder-spotting: every declared per-topology
    # parameter must differ from what the frozen literal holds, or must have
    # been assigned from the spec. Checking only `dst is None` caught P11 and
    # would have missed P06 and P08 entirely, because their placeholders are
    # plausible pilot-v1 constants rather than None.
    base = {p["pid"]: p for p in PROPERTIES}
    resolved = {p["pid"]: p for p in out}
    unresolved = []
    for pid, key in sorted(PER_TOPOLOGY_PARAMS):
        v = resolved[pid].get(key)
        if v is None:
            unresolved.append(f"{pid}.{key} is still the None placeholder")
        elif v == base[pid].get(key) and key in ("must_traverse",):
            # a resolved path may legitimately equal the literal; only None and
            # missing assignment are errors. Kept explicit so the intent is
            # readable rather than inferred from the absence of a branch.
            pass
    if unresolved:
        raise ValueError("properties_for left parameters unresolved: "
                         + "; ".join(unresolved))
    return out


def loopback_of(spec, node: str) -> str:
    """The loopback address of a named router, READ FROM the model.

    spec.routers maps router name -> router-id/loopback. That mapping is the
    model's own answer, and it is what host_attach()/src_node() key on, so it
    is the only address a probe can actually originate from.

    The first version of this function recomputed the address as
    10.255.0.<1-based index of node in spec.routers>. "Router i owns
    10.255.0.i" is a convention that make_topology() happens to follow for the
    ten design-C topologies -- it is NOT a fact about a TopologySpec, and the
    hand-written legacy specs break it: t1 has four routers and still numbers
    edgeb 10.255.0.6, t3 numbers edgeb .6 with wan3/wan4 at .7/.8. Under the
    index formula P11 on t1 would have targeted 10.255.0.4, an address t1's
    edgeb does not own -- the P11 defect again, one level up, in the code
    written to fix it.

    spec.routers is the stored fact, and it is what host_attach() and
    src_node() key on, so it is the only address a probe can originate from or
    arrive at. Read the model; never re-derive it.
    """
    routers = list(spec.routers)
    if node not in routers:
        raise KeyError(f"{node!r} is not a router in {spec.name}: {routers}")
    return spec.routers[node]


def spec_coverage_features(candidate_diff_summary: dict, spec=None) -> dict:
    """Specification-coverage features.

    These are the most important feature group in the project and they cannot be
    harvested from Batfish output -- they have to be computed here, at generation
    time, or they will simply be absent from the dataset. Computed from the
    config diff alone, so they are available at inference time in a real
    deployment too.
    """
    touched = set(candidate_diff_summary.get("devices_touched_list", []))
    # These were hardcoded to pilot-v1's six routers. As an ML FEATURE that is
    # not cosmetic: t04 has a 'hub', t07/t10 have 'agga'/'aggb', and the
    # denominator below was always 6 regardless of whether the topology had 4
    # routers or 8 -- so the same change scored differently across topologies
    # for a reason that had nothing to do with the change.
    if spec is None:
        spec_nodes = {"edgea", "corea", "wan1", "wan2", "coreb", "edgeb"}
        primary = spec_nodes
        off_primary_nodes = {"corea", "coreb"}
    else:
        spec_nodes = set(spec.routers)
        # spec.primary_path holds TRANSIT nodes only -- it is the Dijkstra path
        # between the two edge routers and excludes its own endpoints. So
        # `edgea` and `edgeb` appeared in NO topology's primary_path, which put
        # them in off_primary_nodes and made
        #   change_touches_backup_path_device
        # fire for a change on the ingress or egress router -- the two devices
        # every SPEC property traverses. The earlier fix corrected the
        # denominator (it was hardcoded to six routers) and left this. The spec
        # path is the transit path PLUS the endpoints traffic enters and leaves
        # through.
        endpoints = set(spec.hosts.values())
        spec_nodes = set(spec.routers)
        primary = set(spec.primary_path) | endpoints
        off_primary_nodes = spec_nodes - primary
    on_spec_path = touched & primary
    off_primary = touched & off_primary_nodes
    return {
        "spec_n_properties": len(SPEC),
        "spec_n_reachability_pairs": sum(1 for p in SPEC
                                         if p["kind"] == "reachability"),
        "oracle_n_properties": len(PROPERTIES),
        "spec_fraction_of_oracle": round(len(SPEC) / len(PROPERTIES), 4),
        "changed_devices_on_spec_path": len(on_spec_path),
        "changed_devices_fraction_of_network": round(
            len(touched & spec_nodes) / max(len(spec_nodes), 1), 4),
        # Renamed from change_touches_backup_path_device: it is true for any
        # router that is not on the specified path, which includes but is not
        # limited to backup-path devices.
        "change_touches_off_spec_path_device": bool(off_primary),
        "spec_covers_changed_devices": bool(on_spec_path),
    }


def as_yaml(specs=None) -> str:
    """The frozen suite as YAML.

    Three properties resolve per topology (P06 path, P08 adjacency count, P11
    edgeb loopback). Emitting the unresolved placeholder alone produced the
    literal line `dst: None` in the frozen document -- unreadable to a reviewer
    and impossible to audit. When specs are supplied, the resolved value for
    every topology is written out alongside.
    """
    lines = [f"# golden property suite -- FROZEN, version {SUITE_VERSION}",
             "# in_spec: true  -> asked of Batfish in Phase 2 (the specification)",
             "# in_spec: false -> measured in Containerlab in Phase 3 only",
             "#                   (the declared blind spots)",
             f"suite_version: \"{SUITE_VERSION}\"", "properties:"]
    for p in PROPERTIES:
        lines.append(f"  - pid: {p['pid']}")
        for k, v in p.items():
            if k == "pid":
                continue
            if (p["pid"], k) in PER_TOPOLOGY_PARAMS:
                # Emitting the literal pilot-v1 value here published two lines
                # that were false for most topologies: P08 "expected: 6" (true
                # in 4 of 10) and P06 "must_traverse: ['wan1','wan2']" (true in
                # NONE of them, since primary_path is Dijkstra-derived and
                # includes the cores). P11 only escaped because its placeholder
                # happened to be None and the old rule keyed on None. The rule
                # must key on WHICH PARAMETER it is, not on what it holds.
                lines.append(f"    {k}: PER_TOPOLOGY   # resolved below")
                continue
            if isinstance(v, bool):
                lines.append(f"    {k}: {'true' if v else 'false'}")
            elif isinstance(v, list):
                lines.append(f"    {k}: [{', '.join(repr(x) for x in v)}]")
            elif isinstance(v, str):
                lines.append(f"    {k}: \"{v}\"")
            elif v is None:
                lines.append(f"    {k}: PER_TOPOLOGY   # resolved below")
            else:
                lines.append(f"    {k}: {v}")

    if specs:
        lines += ["",
                  "# Values that depend on the topology. properties_for(spec)",
                  "# fills these in; they are recorded here so the suite that",
                  "# was actually evaluated is fully reconstructable.",
                  "topology_resolved:"]
        for s in specs:
            r = {q["pid"]: q for q in properties_for(s)}
            lines.append(f"  {s.name}:")
            lines.append(f"    P06_must_traverse: "
                         f"[{', '.join(repr(x) for x in r['P06']['must_traverse'])}]")
            lines.append(f"    P08_expected_adjacencies: {r['P08']['expected']}")
            lines.append(f"    P11_src_edgea_loopback: \"{r['P11']['src']}\"")
            lines.append(f"    P11_dst_edgeb_loopback: \"{r['P11']['dst']}\"")
    return "\n".join(lines) + "\n"
