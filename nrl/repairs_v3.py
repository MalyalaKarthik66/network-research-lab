"""Severity-targeted repair generation.

WHAT THE MEASUREMENTS DEMANDED

The zero-inflation diagnostic (30 candidates, exact all-pair path measurement)
found two defects in the v2 generator, and this module exists to fix exactly
those two:

    correct     12/12 at r=0     P(r=0)=1.00   -- a perfect zero-tag on a class
                                                  recoverable from the diff at
                                                  AUC 0.999
    regressive  0.018 - 0.089    disjoint from
    incomplete  0.182 - 0.509    -- class predicted the severity BAND

HOW

v2 chose a target and discovered the severity afterwards. v3 inverts that: it
enumerates every (mechanism, target) pair, predicts r for each with
nrl.severity.Fabric -- validated 36/36 against real FRR across three mechanisms
and six topologies -- and then SELECTS targets at chosen severity quantiles.

Three consequences follow, and each addresses a measured defect:

1.  `correct` stops being a zero-tag. A correct repair restores service; it is
    not obliged to restore the golden FORWARDING. RC-reroute fixes the fault and
    leaves traffic on a different working path: nothing breaks, paths move. That
    is also the most realistic operator in the set -- an engineer fixing an
    outage picks a configuration that works, not one byte-identical to what was
    there before.

2.  Classes stop owning severity bands, because every class draws targets across
    the whole quantile range. Blackholing a prefix nothing routes through is a
    genuine regression with r near zero; shutting a spine link is an incomplete
    repair with r near 0.5.

3.  Mechanism stops tagging class. `correct` and `regressive` both use cost
    changes; `incomplete` and `regressive` both use shutdown and blackhole. In
    v2, RR-* meant blackhole and RI-* meant cost-reroute, so the mechanism was
    readable straight off the diff.

STRUCTURAL MATCHING

Within a mechanism every tier emits the SAME construct -- `ip route <P>
blackhole`, `ip ospf cost <N>`, `shutdown` -- differing only in which target.
chg_devices_touched, chg_lines and chg_touches_ospf are therefore identical
across severities, so severity cannot be read from the shape of the diff. The
only signal left is the relation between the changed element and the topology,
which is what the graph features encode. That is the anti-shortcut mechanism,
and it is structural rather than cosmetic.

WHAT THIS DOES NOT FIX

A `correct` repair never breaks a flow, so r_broken = 0 remains implied by the
class. That is a true property of the world, not an artifact: a repair that
breaks reachability is not correct. It is recorded rather than engineered away,
and it is why r is always reported split into broken and rerouted.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .model import Scenario, StaticRoute
from .severity import Fabric

Repair = Tuple[str, str, str, Scenario]      # rid, class, description, scenario

COST_MULTIPLIER = 20

#: Mechanisms in the PRIMARY corpus. Measured, not chosen by taste -- the
#: construct is visible in the diff, so any mechanism whose severity range is
#: distinctive hands the model a shortcut. R^2 of mechanism on severity:
#:
#:     all four (cost, shutdown, blackhole, exact)   0.569
#:     drop blackhole                                0.274
#:     cost + shutdown                               0.001
#:
#: blackhole is structurally capped near 0.12 (it breaks flows to ONE endpoint,
#: which is 1/N of destinations) and `exact` is an empty diff that always scores
#: 0, so both are readable off the diff. cost and shutdown overlap almost
#: completely -- 0.029-0.571 against 0.105-0.571 -- so neither construct says
#: anything about severity. Both remain available for a labelled auxiliary arm;
#: they are kept out of the headline corpus, not out of the study.
PRIMARY_MECHANISMS = ("cost", "blackhole")

#: Topologies in the PRIMARY corpus. The other eight have no peripheral links --
#: in a 4-router chain every link carries about half the flows -- so their
#: achievable severity starts at 0.33-0.48 and they can emit only high-severity
#: repairs. That made network size a severity proxy by construction:
#:
#:     topology R^2 on severity   all 20: 0.5521    wide 12: 0.0884
#:     per-topology mean spread   all 20: 0.192-0.530   wide 12: 0.192-0.325
#:     severity median            all 20: 0.389     wide 12: 0.262
#:
#: Restricting the set fixes the identity shortcut and the high-severity skew
#: together. The excluded eight remain valid networks and are kept for the
#: generalisation arm, where transfer to unseen SHAPES is the question.
PRIMARY_TOPOLOGIES = ("t03_dual8", "t05_ring6", "t06_mesh6", "t09_twin6",
                      "t13_bowtie7", "t14_ladder8", "t15_campus12",
                      "t16_pop14", "t17_metro13", "t18_grid12",
                      "t19_dualcore16", "t20_leafspine12")
AUXILIARY_MECHANISMS = ("shutdown", "exact")

#: The SPEC gate, which DEFINES the modelling population. P01/P02/P05
#: (hosta<->hostb reachability), P07 (no loops) and P08 (every OSPF adjacency
#: established). P03/P04, P06 and P09-P12 are oracle-only: Batfish is never
#: asked, so a repair can break them and still pass.
#:
#: This is checked here because an earlier version of this module chose
#: cost+shutdown on anti-shortcut grounds and never tested it against the gate:
#:
#:     cost       SPEC-PASS 100%   severity 0.000-0.455
#:     blackhole  SPEC-PASS  91%   severity 0.003-0.097
#:     shutdown   SPEC-PASS   0%   -- every one fails P08
#:
#: 42% of that corpus could not have entered the population at all, while
#: blackhole -- excluded to flatten a mechanism R^2 -- is the canonical
#: false-pass case: it breaks hosta->hostc, which is oracle-only, so the gate
#: never asks. Selecting mechanisms to improve a shortcut metric, without
#: checking the gate, optimised the study's own subject out of the corpus.
#: quantiles each class samples. Identical across classes ON PURPOSE -- that is
#: what makes the severity bands overlap instead of partitioning by class.
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)


# ---------------------------------------------------------------------------
# scenario edits. One construct per mechanism, so the diff shape is constant.
# ---------------------------------------------------------------------------

def _iface(spec, a: str, b: str) -> Tuple[Optional[str], Optional[int]]:
    for (n, i, aa, peer, pi, pa, label, cost) in spec.transit:
        if n == a and peer == b:
            return i, cost
    return None, None


def _set_cost(sc: Scenario, spec, link: Tuple[str, str], mult: int) -> bool:
    a, b = link
    ok = False
    for x, y in ((a, b), (b, a)):
        i, c = _iface(spec, x, y)
        if i is None:
            continue
        for f in sc.devices[x].ifaces:
            if f.name == i:
                f.ospf_cost = (c or 10) * mult
                ok = True
    return ok


def _shutdown(sc: Scenario, spec, link: Tuple[str, str]) -> bool:
    a, b = link
    i, _ = _iface(spec, a, b)
    if i is None:
        return False
    for f in sc.devices[a].ifaces:
        if f.name == i:
            f.up = False
            return True
    return False


def _blackhole(sc: Scenario, node: str, prefix: str) -> bool:
    if node not in sc.devices:
        return False
    sc.devices[node].statics.append(
        StaticRoute(prefix=prefix, nexthop="blackhole"))
    return True


def endpoint_prefix(spec, endpoint: str) -> Optional[str]:
    """The prefix that endpoint owns: a host's LAN, a router's loopback /32."""
    hosts = dict(getattr(spec, "hosts", {}) or {})
    if endpoint in hosts:
        for (a, ai, aa, b, bi, ba, sub, label, cost) in spec.links:
            if b == endpoint:
                return sub
            if a == endpoint:
                return sub
        return None
    lo = spec.routers.get(endpoint)
    return f"{lo}/32" if lo else None


# ---------------------------------------------------------------------------
# enumeration: every (mechanism, target) with its predicted severity
# ---------------------------------------------------------------------------

def spec_pass(fab: Fabric, spec, d: Dict) -> bool:
    """Would Batfish's SPEC gate pass this change? Predicted, not guessed.

    A repair that fails the gate never reaches the modelling population, so it
    must not be selectable. Shutting a link drops an adjacency and fails P08
    unconditionally; cost changes and blackholes leave adjacencies intact and
    pass unless they break hosta<->hostb, which the gate does ask about.
    """
    if d["mech"] == "shutdown":
        return False                       # P08: an adjacency goes down
    if d["mech"] == "cost":
        lk = d["target"]
        paths = fab.paths(cost_override={lk: fab.cost[lk] * COST_MULTIPLIER})
        bh = set()
    else:
        paths = fab.paths()
        bh = {(d["target"][0], d["target"][1])}

    def reaches(src, dst):
        p = paths.get((src, dst))
        return p is not None and not any((n, dst) in bh for n in p)

    return reaches("hosta", "hostb") and reaches("hostb", "hosta")


def catalogue(spec, fab: Optional[Fabric] = None) -> List[Dict]:
    """Every candidate intervention, with predicted r AND predicted SPEC verdict.

    No labs, no guessing.
    """
    fab = fab or Fabric(spec)
    origin = {e: r for e, r in fab.endpoints}
    out: List[Dict] = []
    for lk in sorted(fab.cost):
        c = fab.cost[lk]
        p = fab.predict(cost_override={lk: c * COST_MULTIPLIER})
        if p["r"] is not None:
            out.append({"mech": "cost", "target": lk, **p})
        q = fab.predict(removed=[lk])
        if q["r"] is not None:
            out.append({"mech": "shutdown", "target": lk, **q})
    for e, _ in fab.endpoints:
        pfx = endpoint_prefix(spec, e)
        if not pfx:
            continue
        for n in fab.routers:
            if origin.get(e) == n:
                continue            # connected route beats the static; no-op
            p = fab.predict(blackholes=[(n, e)])
            if p["r"]:
                    out.append({"mech": "blackhole", "target": (n, e, pfx), **p})
    for d in out:
        d["spec_pass"] = spec_pass(fab, spec, d)
    return out


def _relabel(picks: List[Dict]) -> List[Dict]:
    """Order picks by TARGET, not by severity.

    The selector walks severity quantiles, so emitting ids in pick order made
    `RC-reroute_q0` the lowest-severity repair and `_q4` the highest. The audit
    measured repair_id at R^2 = 0.84 on severity for that reason alone. It is
    banned from X by ANALYSIS-PLAN 3 so it never reached a model, but an
    identifier that encodes the answer is one accidental include away from
    being a leak, and it looks indefensible in a paper. Sorting by target makes
    the index arbitrary with respect to severity.
    """
    return sorted(picks, key=lambda d: (d["mech"], str(d["target"])))


def _pick(cands: Sequence[Dict], quantiles=QUANTILES) -> List[Dict]:
    """Targets nearest evenly spaced points of the achievable SEVERITY RANGE.

    Not quantiles of the candidate LIST. The catalogue is dominated by
    blackholes -- every (node, endpoint) pair is one candidate, and all of them
    are low-severity because a blackhole breaks flows to a single endpoint --
    so list-position quantiles put four of five picks in blackhole territory and
    produced a strongly bimodal corpus: 183 of 378 repairs under r=0.06 and 86
    above 0.42, with a hole through the middle. Sampling the value range instead
    gives a severity distribution set by the topology's reach rather than by how
    many candidates each mechanism happens to contribute.
    Mechanisms are rotated as the quantiles advance. Without that, the
    construct alone explained R^2 = 0.577 of severity: blackholes are capped
    near 0.12 because they break flows to a single endpoint, shutdowns that
    break anything start around 0.20, so `static` meant low and `shutdown` meant
    high and the model could read the band straight off the diff. Rotating
    forces each mechanism to appear wherever its own range allows. Where a
    mechanism physically cannot reach a band it is simply absent, and that is a
    structural fact about the mechanism, reported rather than engineered away.
    """
    if not cands:
        return []
    rs = [d["r"] for d in cands]
    lo, hi = min(rs), max(rs)
    mechs = sorted({d["mech"] for d in cands})
    out, seen = [], set()
    for i, q in enumerate(quantiles):
        target = lo + q * (hi - lo)
        # try the rotated mechanism first, then any, so a band is never skipped
        for pool in ([c for c in cands if c["mech"] == mechs[i % len(mechs)]],
                     cands):
            if not pool:
                continue
            d = min(pool, key=lambda c: (abs(c["r"] - target), str(c["target"])))
            key = (d["mech"], str(d["target"]))
            if key not in seen:
                seen.add(key)
                out.append(d)
                break
    return out


# ---------------------------------------------------------------------------
# the operator set
# ---------------------------------------------------------------------------

def generate(golden: Scenario, spec, fab: Optional[Fabric] = None,
             cat: Optional[List[Dict]] = None,
             mechanisms: Sequence[str] = PRIMARY_MECHANISMS) -> List[Repair]:
    """Repairs for one topology, spanning severity within every class.

    Built from GOLDEN, as v2's were: a repair is the configuration you end up
    with after repairing, not a patch applied to the faulted state.
    """
    fab = fab or Fabric(spec)
    cat = cat if cat is not None else catalogue(spec, fab)
    # SPEC-PASS only: the population is defined by the gate, so a repair that
    # cannot pass it is not a candidate at all.
    cat = [d for d in cat if d["mech"] in mechanisms and d.get("spec_pass", True)]
    clean = [d for d in cat if d["r_broken"] == 0 and d["r"] > 0]
    breaks = [d for d in cat if d["r_broken"] > 0]
    small = [d for d in cat if 0 < d["r"] <= 0.05]
    out: List[Repair] = []

    def emit(rid: str, cls: str, desc: str, d: Optional[Dict]) -> None:
        sc = golden.clone()
        if d is None:
            out.append((rid, cls, desc, sc))
            return
        ok = (_set_cost(sc, spec, d["target"], COST_MULTIPLIER)
              if d["mech"] == "cost" else
              _shutdown(sc, spec, d["target"]) if d["mech"] == "shutdown" else
              _blackhole(sc, d["target"][0], d["target"][2]))
        if ok:
            out.append((rid, cls, f"{desc} [predicted r={d['r']:.4f}]", sc))

    # CORRECT -- service restored. One exact restoration, the rest reroute onto
    # a different working path, which is what kills the v2 zero-tag.
    if "exact" in mechanisms:
        emit("RC-exact", "correct", "restore golden forwarding", None)
    for i, d in enumerate(_relabel(_pick(clean))):
        emit(f"RC-reroute_q{i}", "correct",
             f"restore via an alternate path ({d['mech']})", d)

    # CORRECT, zero severity, NOT an empty diff. Raising the cost of a link
    # that has no alternative path is a real configuration change that moves no
    # traffic at all. It restores the zeros that the corpus otherwise lacks
    # without reintroducing RC-exact, whose empty diff made `exact` worth
    # R^2 = 0.27 on severity all by itself. These are also the hardest rows in
    # the set: a change that looks substantial and does nothing, which is
    # exactly where a model reading the size of the diff will be wrong.
    zeros = sorted((d for d in cat if d["r"] == 0),
                   key=lambda d: (d["mech"], str(d["target"])))
    for i, d in enumerate(zeros[:2]):
        emit(f"RC-noop_q{i}", "correct",
             f"restores service, moves no traffic ({d['mech']})", d)

    # INCOMPLETE -- the fault's service is not fully restored. Severity here is
    # set by WHERE THE FAULT LANDED, and faults land anywhere, so this draws
    # from the whole catalogue rather than only from interventions that break a
    # flow. Restricting it to `breaks` capped the class at 0.119, because that
    # pool is dominated by blackholes and blackholes have a structural ceiling
    # (they break flows to ONE endpoint, which is 1/N of destinations). It also
    # made the mechanism a perfect tag for the class: 100% of incomplete repairs
    # were damage-type, 0% of correct ones were.
    nonzero = [d for d in cat if d["r"] > 0]
    for i, d in enumerate(_relabel(_pick(nonzero))):
        emit(f"RI-partial_q{i}", "incomplete",
             f"partial restoration ({d['mech']})", d)

    # REGRESSIVE -- fault fixed, something else degraded. Draws from the SAME
    # quantile range and the same mechanisms, including near-zero damage to
    # something nothing routes through, so neither class nor mechanism predicts
    # the severity band.
    for i, d in enumerate(_relabel(_pick(breaks, (0.15, 0.50, 0.85)))):
        emit(f"RR-damage_q{i}", "regressive",
             f"fixed, but broke something else ({d['mech']})", d)
    for i, d in enumerate(_relabel(_pick(small, (0.1, 0.6)))):
        emit(f"RR-minor_q{i}", "regressive",
             f"fixed, but degraded a lightly used path ({d['mech']})", d)
    for i, d in enumerate(_relabel(_pick(clean, (0.2, 0.5, 0.8)))):
        emit(f"RR-shift_q{i}", "regressive",
             f"fixed, but shifted traffic to a worse path ({d['mech']})", d)
    return out
