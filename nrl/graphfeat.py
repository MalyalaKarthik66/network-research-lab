"""Tier A+ : graph-structural features of a configuration change.

WHY THESE EXIST
---------------
The pilot found no signal in Tier A -- counts of added/removed lines, which
devices were touched, which config sections. That is unsurprising: "three lines
changed on coreb" says nothing about whether coreb was the only path.

What plausibly predicts residual risk is structural: did the change touch a cut
edge, is the changed device on the specified path, did the number of equal-cost
paths between the two hosts drop from two to one. Those are graph-theoretic
scalars, and a model can use them at ~700 training rows. Learning them from an
adjacency matrix instead -- a CNN or a GNN -- needs orders of magnitude more
data, because it first has to learn permutation invariance that these features
have by construction.

Every feature here is:
  * permutation invariant  -- renaming or reordering routers cannot change it
  * computable at inference time from the proposed config plus the topology,
    which is exactly what an operator has before deploying
  * computed on BEFORE (the faulted network) and AFTER (the candidate), with
    the delta reported, because risk lives in what the change did

No third-party dependency. Brandes betweenness, Tarjan bridges, Dijkstra and
power iteration are ~40 lines each and these graphs have under twenty nodes;
adding networkx to the venv for that would be a worse trade.

SCOPE, stated so it is not mistaken for more than it is: the graph modelled
here is the OSPF adjacency graph. Static routes, redistribution and filtering
affect reachability and are NOT in this graph. A feature saying "the graph is
still connected" therefore means "OSPF still has a path", not "traffic flows".
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import Dict, List, Set, Tuple

DEFAULT_COST = 10


# ---------------------------------------------------------------------------
# graph extraction
# ---------------------------------------------------------------------------

def ospf_graph(scn) -> Dict[str, Dict[str, int]]:
    """Router adjacency graph implied by the configuration.

    An edge exists only where OSPF would actually form an adjacency: both ends
    up, both in OSPF, in the SAME area, neither passive. That is the point of
    computing it from the model rather than from the topology spec -- a fault
    that shuts an interface or changes an area must remove the edge.
    """
    routers = set(scn.routers)
    g: Dict[str, Dict[str, int]] = {r: {} for r in routers}
    for ln in scn.links:
        a, b = ln.a_node, ln.b_node
        if a not in routers or b not in routers:
            continue
        try:
            ia = scn.devices[a].iface(ln.a_iface)
            ib = scn.devices[b].iface(ln.b_iface)
        except KeyError:
            continue
        if not (ia.up and ib.up):
            continue
        if ia.ospf_area is None or ib.ospf_area is None:
            continue
        if str(ia.ospf_area) != str(ib.ospf_area):
            continue
        if ia.ospf_passive or ib.ospf_passive:
            continue
        cost = max(int(ia.ospf_cost or DEFAULT_COST),
                   int(ib.ospf_cost or DEFAULT_COST))
        g[a][b] = cost
        g[b][a] = cost
    return g


def edges_of(g) -> Set[Tuple[str, str]]:
    return {tuple(sorted((a, b))) for a in g for b in g[a]}


# ---------------------------------------------------------------------------
# algorithms
# ---------------------------------------------------------------------------

def dijkstra(g, src):
    """(dist, n_shortest_paths) from src, weighted by OSPF cost."""
    dist = {n: float("inf") for n in g}
    paths = {n: 0 for n in g}
    dist[src], paths[src] = 0, 1
    pq, seen = [(0, src)], set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        for v, w in g[u].items():
            nd = d + w
            if nd < dist[v]:
                dist[v], paths[v] = nd, paths[u]
                heapq.heappush(pq, (nd, v))
            elif nd == dist[v]:
                paths[v] += paths[u]
    return dist, paths


def bfs_hops(g, src):
    dist = {src: 0}
    q = deque([src])
    while q:
        u = q.popleft()
        for v in g[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def betweenness(g) -> Dict[str, float]:
    """Brandes, on hop counts. Normalised to [0,1] over ordered pairs."""
    bc = {n: 0.0 for n in g}
    for s in g:
        stack, pred = [], {n: [] for n in g}
        sigma = {n: 0 for n in g}; sigma[s] = 1
        dist = {n: -1 for n in g}; dist[s] = 0
        q = deque([s])
        while q:
            v = q.popleft(); stack.append(v)
            for w in g[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = {n: 0.0 for n in g}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w]) if sigma[w] else 0
            if w != s:
                bc[w] += delta[w]
    n = len(g)
    scale = 1.0 / ((n - 1) * (n - 2)) if n > 2 else 1.0
    return {k: v * scale for k, v in bc.items()}


def eigenvector_centrality(g, iters=200, tol=1e-9) -> Dict[str, float]:
    n = len(g)
    if n == 0:
        return {}
    x = {k: 1.0 / n for k in g}
    for _ in range(iters):
        nx = {k: 0.0 for k in g}
        for u in g:
            for v in g[u]:
                nx[v] += x[u]
        norm = sum(v * v for v in nx.values()) ** 0.5
        if norm == 0:
            return x
        nx = {k: v / norm for k, v in nx.items()}
        if sum(abs(nx[k] - x[k]) for k in g) < tol:
            return nx
        x = nx
    return x


def bridges(g) -> Set[Tuple[str, str]]:
    """Tarjan. A bridge is an edge whose removal disconnects the graph -- the
    single most direct structural statement of 'there is no other way round'."""
    out, disc, low, timer = set(), {}, {}, [0]

    def dfs(u, parent):
        disc[u] = low[u] = timer[0]; timer[0] += 1
        skipped_parent = False
        for v in g[u]:
            if v == parent and not skipped_parent:
                skipped_parent = True
                continue
            if v not in disc:
                dfs(v, u)
                low[u] = min(low[u], low[v])
                if low[v] > disc[u]:
                    out.add(tuple(sorted((u, v))))
            else:
                low[u] = min(low[u], disc[v])

    for n in g:
        if n not in disc:
            dfs(n, None)
    return out


def weighted_diameter(g) -> float:
    """Longest finite shortest path, by OSPF cost. inf if disconnected."""
    best = 0.0
    for s in g:
        dist, _ = dijkstra(g, s)
        for v, d in dist.items():
            if d == float("inf"):
                return float("inf")
            best = max(best, d)
    return best


def connected(g) -> bool:
    if not g:
        return True
    start = next(iter(g))
    return len(bfs_hops(g, start)) == len(g)


# ---------------------------------------------------------------------------
# the feature block
# ---------------------------------------------------------------------------

def _safe(v):
    """inf is not JSON, and a disconnected graph is a real state we must record
    rather than drop. -1 is the sentinel and it is documented in the data
    dictionary."""
    return -1.0 if v == float("inf") else round(float(v), 6)


def graph_features(spec, before, after, touched: List[str]) -> Dict:
    """Structural features of the change from `before` to `after`.

    `spec` supplies the ingress/egress routers and the specified path;
    `touched` is change_stats.devices_touched_list.
    """
    gb, ga = ospf_graph(before), ospf_graph(after)
    eb, ea = edges_of(gb), edges_of(ga)
    endpoints = sorted(set(spec.hosts.values()))
    ingress = endpoints[0] if endpoints else None
    egress = endpoints[-1] if len(endpoints) > 1 else ingress
    spec_path = set(spec.primary_path) | set(endpoints)
    touched = [t for t in (touched or []) if t in ga]

    bc_a = betweenness(ga)
    ev_a = eigenvector_centrality(ga)
    br_b, br_a = bridges(gb), bridges(ga)
    changed_edges = (eb - ea) | (ea - eb)

    # distance in hops from the nearest changed device to the specified path
    dist_to_spec = -1
    if touched and spec_path & set(ga):
        best = float("inf")
        for t in touched:
            hops = bfs_hops(ga, t)
            for s in spec_path:
                if s in hops:
                    best = min(best, hops[s])
        dist_to_spec = -1 if best == float("inf") else int(best)

    def _paths(g):
        if not ingress or not egress or ingress not in g or egress not in g:
            return -1.0, -1
        d, p = dijkstra(g, ingress)
        return _safe(d.get(egress, float("inf"))), int(p.get(egress, 0))

    spl_b, npaths_b = _paths(gb)
    spl_a, npaths_a = _paths(ga)

    deg_a = {n: len(ga[n]) for n in ga}
    t_deg = [deg_a[t] for t in touched] or [0]
    t_bc = [bc_a[t] for t in touched] or [0.0]
    t_ev = [ev_a[t] for t in touched] or [0.0]

    return {
        # --- size and shape -------------------------------------------------
        "g_n_routers": len(ga),
        "g_n_edges_before": len(eb),
        "g_n_edges_after": len(ea),
        "g_d_edges": len(ea) - len(eb),
        "g_min_degree_after": min(deg_a.values()) if deg_a else 0,
        "g_connected_after": bool(connected(ga)),
        "g_connected_before": bool(connected(gb)),
        # --- where the change landed ---------------------------------------
        "g_touched_max_degree": max(t_deg),
        "g_touched_mean_degree": round(sum(t_deg) / len(t_deg), 4),
        "g_touched_max_betweenness": round(max(t_bc), 6),
        "g_touched_sum_betweenness": round(sum(t_bc), 6),
        "g_touched_max_eigenvector": round(max(t_ev), 6),
        "g_touched_on_spec_path": bool(set(touched) & spec_path),
        "g_touched_hops_to_spec_path": dist_to_spec,
        # --- redundancy -----------------------------------------------------
        "g_n_bridges_before": len(br_b),
        "g_n_bridges_after": len(br_a),
        "g_d_bridges": len(br_a) - len(br_b),
        "g_change_touches_bridge": bool(changed_edges & (br_b | br_a)),
        "g_touched_incident_to_bridge":
            bool({n for e in br_a for n in e} & set(touched)),
        # --- the specified path itself --------------------------------------
        "g_spl_ingress_egress_before": spl_b,
        "g_spl_ingress_egress_after": spl_a,
        "g_d_spl_ingress_egress": _safe(spl_a - spl_b)
            if (spl_a >= 0 and spl_b >= 0) else -1.0,
        "g_n_shortest_paths_before": npaths_b,
        "g_n_shortest_paths_after": npaths_a,
        "g_d_n_shortest_paths": npaths_a - npaths_b,
        "g_lost_last_alternate_path": bool(npaths_b > 1 and npaths_a == 1),
        # --- global cost ----------------------------------------------------
        "g_weighted_diameter_before": _safe(weighted_diameter(gb)),
        "g_weighted_diameter_after": _safe(weighted_diameter(ga)),
    }
