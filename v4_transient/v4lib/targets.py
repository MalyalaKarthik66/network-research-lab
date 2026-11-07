"""Transient time series and the three pre-registered target candidates.

Flow set: every ordered endpoint pair (router loopbacks and hosts), the same set v3 used for r, restricted
to flows the golden state carries. Each flow at time t is classified against the golden (pre-change) path
and the final (post-convergence) path, both reconstructed from the same monitored FIB (fib.replay, which since
amendment A3 includes kernel link-state semantics):

  BROKEN          terminal NO_ROUTE / LOOP / BLACKHOLE
  broken_excess   BROKEN now and NOT broken in the final state  -> traffic lost only while converging
  detour          delivered, on a path that is neither the golden nor the final path
  rerouted        delivered, path differs from golden (includes the steady-state reroute)
  undetermined    NO_RIB / UNKNOWN_NH / MAX_HOPS (measurement validity; expected 0)

Targets (per run, t measured from t0 = start of the first configuration push):
  T1 disruption area      integral of broken_excess(t) dt       [flow-fraction x seconds]   PRIMARY
  T2 peak disruption      max broken_excess(t)                  [flow fraction]
  T3 disruption duration  end of the last interval with broken_excess(t) > THETA  [seconds]
THETA = 0: the only threshold that needs no tuning. Steady-state (Batfish-computable) damage is excluded
from all three by construction, because broken_excess subtracts the final state.
T1_merge10ms (descriptive sensitivity, A3): T1 with event timestamps rounded up to a 10 ms grid, so cross-router
orderings finer than 10 ms (monitor scheduling) cannot create or remove transient states.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from nrl import flowmatrix as fm

from .fib import replay

BROKEN = ("NO_ROUTE", "LOOP", "BLACKHOLE")
UNDET = ("NO_RIB", "UNKNOWN_NH", "MAX_HOPS")
THETA = 0.0
MERGE_BIN_S = 0.01


def flows(spec) -> List[Dict]:
    e = fm.endpoints(spec)
    return [{"flow_id": f"{s['name']}->{d['name']}", "src_name": s["name"], "dst_addr": d["addr"]}
            for s in e for d in e if s["addr"] != d["addr"]]


def eval_state(ribs: Dict[str, Dict], spec, fl: List[Dict]) -> Dict[str, Tuple[tuple, str]]:
    owner = fm.owner_map(spec)
    attach = dict(getattr(spec, "hosts", {}) or {})
    out = {}
    for f in fl:
        src = attach.get(f["src_name"], f["src_name"])
        path, term = fm.forwarding_path(ribs, src, f["dst_addr"], owner)
        out[f["flow_id"]] = (tuple(path), term)
    return out


def binned(events, bin_s: float):
    return [(math.ceil(t / bin_s - 1e-9) * bin_s, r, rec) for t, r, rec in events]


def series(initial, events, spec, t0: float, t_end: float, initial_links=None, bin_s: Optional[float] = None) -> Dict:
    """Reconstruct the time series. Returns rows (t_rel, counts) plus golden/final states and validity."""
    fl = flows(spec)
    evs = binned(events, bin_s) if bin_s else events
    states: List[Tuple[Optional[float], Dict]] = [(t, eval_state(ribs, spec, fl))
                                                  for t, ribs in replay(initial, evs, spec, initial_links)]
    golden = states[0][1]
    final = states[-1][1]
    carried = [k for k, (p, term) in golden.items() if term not in BROKEN + UNDET]
    n = len(carried)
    pre_change_events = sum(1 for t, _ in states[1:] if t is not None and t < t0)
    post_window_events = sum(1 for t, _ in states[1:] if t is not None and t > t_end)
    rows = []
    for t, st in states:
        t_rel = 0.0 if t is None else t - t0
        be = bue = det = rer = brk = und = 0
        for k in carried:
            p, term = st[k]
            gp, _ = golden[k]
            fp_, fterm = final[k]
            if term in UNDET:
                und += 1
                if fterm not in BROKEN:
                    bue += 1                      # pre-registration §13: T1_upper counts these as broken
                continue
            if term in BROKEN:
                brk += 1
                if fterm not in BROKEN:
                    be += 1
                    bue += 1
                continue
            if p != gp:
                rer += 1
                if p != fp_:
                    det += 1
        rows.append({"t_rel": round(max(t_rel, 0.0) if t is None else t_rel, 6),
                     "broken_excess": be / n if n else None,
                     "broken_or_undet_excess": bue / n if n else None, "detour": det / n if n else None,
                     "rerouted_vs_golden": rer / n if n else None, "broken_total": brk / n if n else None,
                     "undetermined": und / n if n else None})
    f_brk = sum(1 for k in carried if final[k][1] in BROKEN)
    f_rer = sum(1 for k in carried if final[k][1] not in BROKEN + UNDET and final[k][0] != golden[k][0])
    return {"rows": rows, "n_flows_carried": n, "t_end_rel": t_end - t0,
            "pre_change_fib_events": pre_change_events, "post_window_fib_events": post_window_events,
            "r_final": (f_brk + f_rer) / n if n else None,
            "r_final_broken": f_brk / n if n else None, "r_final_rerouted": f_rer / n if n else None,
            "final_undetermined": sum(1 for k in carried if final[k][1] in UNDET)}


def _integral(rows: List[Dict], key: str, t_end_rel: float) -> float:
    """Piecewise-constant integral over [0, t_end_rel]; a value holds until the next row."""
    pts = [(max(r["t_rel"], 0.0), r[key] or 0.0) for r in rows]
    area = 0.0
    for i, (t, v) in enumerate(pts):
        t_next = pts[i + 1][0] if i + 1 < len(pts) else t_end_rel
        t_next = min(max(t_next, 0.0), t_end_rel)
        if t_next > t:
            area += v * (t_next - t)
    return area


def summarize(s: Dict) -> Dict:
    rows, t_end = s["rows"], s["t_end_rel"]
    post = [r for r in rows if r["t_rel"] >= 0]
    last_on = 0.0
    for i, r in enumerate(rows):
        if (r["broken_excess"] or 0.0) > THETA:
            nxt = rows[i + 1]["t_rel"] if i + 1 < len(rows) else t_end
            last_on = max(last_on, nxt)
    fib_times = [r["t_rel"] for r in rows[1:]]
    return {
        "T1_disruption_area": _integral(rows, "broken_excess", t_end),
        "T2_peak_disruption": max((r["broken_excess"] or 0.0) for r in post) if post else 0.0,
        "T3_disruption_duration": last_on,
        "T1_upper_undetermined_as_broken": _integral(rows, "broken_or_undet_excess", t_end),
        "detour_area": _integral(rows, "detour", t_end),
        "detour_peak": max((r["detour"] or 0.0) for r in post) if post else 0.0,
        "undetermined_peak": max((r["undetermined"] or 0.0) for r in rows),
        "n_fib_state_changes": len(rows) - 1,
        "fib_settle_s": max(fib_times) if fib_times else 0.0,
        "first_fib_change_s": min(fib_times) if fib_times else None,
        "r_final": s["r_final"], "r_final_broken": s["r_final_broken"],
        "r_final_rerouted": s["r_final_rerouted"], "n_flows_carried": s["n_flows_carried"],
        "pre_change_fib_events": s["pre_change_fib_events"],
        "post_window_fib_events": s.get("post_window_fib_events", 0), "observation_s": t_end,
    }
