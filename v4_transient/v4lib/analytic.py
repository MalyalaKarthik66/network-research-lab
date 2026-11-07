"""Pre-deployment features and deterministic baselines. Everything here is computed from the golden and
candidate CONFIGURATIONS only -- no lab, no measurement, no identifiers.

Baseline families (pre-registered):
  steady-state exact    r_exact, r_broken_exact, r_rerouted_exact  (== Batfish, validated 151/151 in v3)
  FIB-change counts     n_fib_entries_changed, n_routers_changed   (routers whose next-hop set to some
                        destination changes; blackholes count one entry at the discarding router)
  microloop potential   pml_flow_frac: fraction of carried flows whose source can reach a cycle in the
                        union of old and new next-hop graphs toward the flow's destination (RFC 5715: a
                        transient loop requires such a cycle). Upper bound, not a prediction of timing.
  change shape          n_devices_pushed, n_config_commands
  graph                 n_routers, n_endpoints, changed_link_betweenness, golden_mean_path_len
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from nrl.severity import Fabric


def nexthop_table(fab: Fabric, cost_override=None, removed=None) -> Dict[Tuple[str, str], frozenset]:
    cost = dict(fab.cost)
    if cost_override:
        cost.update({tuple(sorted(k)): v for k, v in cost_override.items()})
    rem = {tuple(sorted(x)) for x in (removed or ())}
    out = {}
    for root in fab.routers:
        dist = fab._dist_to(root, cost, rem)
        for node in fab.routers:
            if node == root:
                continue
            out[(node, root)] = frozenset(fab._nexthops(dist, node, cost, rem))
    return out


def _cycle_reachable(graph: Dict[str, Iterable[str]], start: str) -> bool:
    color: Dict[str, int] = {}
    stack = [(start, iter(graph.get(start, ())))]
    color[start] = 1
    while stack:
        node, it = stack[-1]
        nxt = next(it, None)
        if nxt is None:
            color[node] = 2
            stack.pop()
            continue
        c = color.get(nxt, 0)
        if c == 1:
            return True
        if c == 0:
            color[nxt] = 1
            stack.append((nxt, iter(graph.get(nxt, ()))))
    return False


def features(spec, change: Dict, push_plan: Dict[str, List[str]]) -> Dict:
    """change: {"mechanism", "cost_override": {(a,b): cost}, "removed": [(a,b)], "blackholes": [(node, endpoint)]}"""
    fab = Fabric(spec)
    co = {tuple(sorted(k)): v for k, v in (change.get("cost_override") or {}).items()} or None
    removed = [tuple(sorted(x)) for x in (change.get("removed") or [])] or None
    bh = [tuple(x) for x in (change.get("blackholes") or [])] or None
    pred = fab.predict(cost_override=co, removed=removed, blackholes=bh)
    old = nexthop_table(fab)
    new = nexthop_table(fab, co, removed)
    changed = [k for k in old if old[k] != new.get(k)]
    origin = {e: r for e, r in fab.endpoints}
    bh_eff = [(n, e) for n, e in (bh or []) if origin.get(e) != n]
    routers_changed = {r for r, _ in changed} | {n for n, _ in bh_eff}

    at_risk = carried = 0
    cache: Dict[Tuple[str, str], bool] = {}
    for (sn, dn), gp in fab.golden.items():
        if gp is None:
            continue
        carried += 1
        sr, dr = origin[sn], origin[dn]
        if sr == dr:
            continue
        key = (sr, dr)
        if key not in cache:
            g = {u: set(old.get((u, dr), ())) | set(new.get((u, dr), ())) for u in fab.routers if u != dr}
            cache[key] = _cycle_reachable(g, sr)
        at_risk += cache[key]

    bet = fab.link_betweenness()
    changed_links = set((co or {}).keys()) | set(removed or [])
    lens = [len(p) - 1 for p in fab.golden.values() if p]
    return {
        "r_exact": pred["r"], "r_broken_exact": pred["r_broken"], "r_rerouted_exact": pred["r_rerouted"],
        "n_fib_entries_changed": len(changed) + len(bh_eff),
        "n_routers_changed": len(routers_changed),
        "pml_flow_frac": at_risk / carried if carried else 0.0,
        "n_devices_pushed": len(push_plan),
        "n_config_commands": sum(len([c for c in v if c != "exit"]) for v in push_plan.values()),
        "n_routers": len(fab.routers), "n_endpoints": len(fab.endpoints),
        "changed_link_betweenness": sum(bet.get(l, 0.0) for l in changed_links),
        "golden_mean_path_len": sum(lens) / len(lens) if lens else 0.0,
        "n_flows_carried_pred": pred["n_pairs"],
    }


FEATURE_COLUMNS = ["r_exact", "r_broken_exact", "r_rerouted_exact", "n_fib_entries_changed",
                   "n_routers_changed", "pml_flow_frac", "n_devices_pushed", "n_config_commands",
                   "n_routers", "n_endpoints", "changed_link_betweenness", "golden_mean_path_len"]
