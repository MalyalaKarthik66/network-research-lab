"""Offline leakage audit of the proposed v3 corpus. No labs, no corpus build.

THE QUESTION

The v3 design reported repair_class R^2 = 0.001 and mechanism R^2 = 0.003 on
predicted severity. Two features is not an audit. This asks whether severity is
predictable from anything that has no business carrying it.

WHAT COUNTS AS A LEAK HERE

Only features that actually reach the model. The banned list in
ANALYSIS-PLAN 3 keeps repair_class, repair_id, incident_id and candidate_id out
of X, so the quantile index embedded in a repair_id is provenance, not leakage --
it is measured below and then excluded from the model tests, rather than being
quietly counted as either.

The features that DO reach X are the ones the frozen build writes:

    chg_*  16 of them: devices_touched, lines_added/removed/changed_total, and
           eleven touches_<construct> booleans. NO raw cost values -- an earlier
           version of this audit invented chg_cost_new/chg_cost_old, measured
           R^2 = 0.208 on them, and was measuring a feature that does not exist.
    g_*    28 graph features, including g_n_routers, g_n_edges_*,
           g_weighted_diameter_* and g_touched_*_betweenness.

That distinction matters because `g_touched_max_betweenness` IS the legitimate
signal -- severity genuinely is a function of where the change lands -- while
`g_n_routers` is a size proxy that correlates with severity for a structural
reason, and topology identity is recoverable from the graph features whether we
like it or not.

THE TEST THAT SEPARATES THEM

Leave-one-topology-out. Memorising "t15 -> 0.4" cannot transfer to a topology
never seen in training; a rule about betweenness can. Random CV minus LOTO is
the size of the memorisation.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np                                                # noqa: E402
from nrl import repairs_v3 as R3                                  # noqa: E402
from nrl import topologies_v3 as T3                               # noqa: E402
from nrl.graphfeat import graph_features                          # noqa: E402
from nrl.severity import Fabric                                   # noqa: E402
from nrl.topologies import build_golden                           # noqa: E402

OUT = Path(__file__).resolve().parent / "v3_leakage_audit.json"

#: topologies whose achievable severity range spans low AND high. The other
#: eight have no peripheral links -- in a 4-router chain every link carries
#: about half the flows -- so they can only emit high-severity repairs, which
#: is what makes network size correlate with severity by construction.
WIDE_RANGE = R3.PRIMARY_TOPOLOGIES

_CONSTRUCTS = ("cost", "static", "shutdown", "ospf", "address", "area",
               "passive", "interface", "access_list", "prefix_list",
               "route_map", "description_only")


def chg_features(g, sc) -> dict:
    """The frozen chg_ set, recomputed from the scenario pair."""
    devs, added, removed, touches = set(), 0, 0, set()
    for n, d in sc.devices.items():
        gd = g.devices.get(n)
        if gd is None:
            continue
        for f in d.ifaces:
            gf = next((x for x in gd.ifaces if x.name == f.name), None)
            if gf is None or f == gf:
                continue
            devs.add(n)
            added += 1
            removed += 1
            touches.add("interface")
            if f.ospf_cost != gf.ospf_cost:
                touches.update(("cost", "ospf"))
            if f.up != gf.up:
                touches.add("shutdown")
            if f.ospf_area != gf.ospf_area:
                touches.update(("area", "ospf"))
            if f.addresses != gf.addresses:
                touches.add("address")
            if f.ospf_passive != gf.ospf_passive:
                touches.update(("passive", "ospf"))
        ns = len(d.statics or []) - len(gd.statics or [])
        if ns:
            devs.add(n)
            added += ns
            touches.add("static")
    out = {"chg_devices_touched": len(devs), "chg_lines_added": added,
           "chg_lines_removed": removed,
           "chg_lines_changed_total": added + removed}
    for c in _CONSTRUCTS:
        out[f"chg_touches_{c}"] = c in touches
    return out


def build_table(mechanisms, topologies):
    rows = []
    for tn in topologies:
        spec = T3.resolve(tn)
        fab = Fabric(spec)
        cat = R3.catalogue(spec, fab)
        g = build_golden(spec)
        for order, (rid, cls, desc, sc) in enumerate(
                R3.generate(g, spec, fab, cat, mechanisms=mechanisms)):
            m = re.search(r"predicted r=([0-9.]+)", desc)
            r = float(m.group(1)) if m else 0.0
            mech = ("exact" if "exact" in rid
                    else re.search(r"\((\w+)\)", desc).group(1))
            cf = chg_features(g, sc)
            touched = sorted({n for n, d in sc.devices.items()
                              if g.devices.get(n) is not None
                              and (d.ifaces != g.devices[n].ifaces
                                   or len(d.statics or [])
                                   != len(g.devices[n].statics or []))})
            try:
                gf = graph_features(spec, g, sc, touched)
            except Exception:                                      # noqa: BLE001
                gf = {}
            rows.append({"topology": tn, "repair_class": cls, "repair_id": rid,
                         "mechanism": mech, "severity": r, "order": order,
                         "quantile_idx": int(re.search(r"q(\d+)", rid).group(1))
                                          if re.search(r"q(\d+)", rid) else -1,
                         **cf, **gf})
    return rows


def r2_cat(rows, key):
    y = np.array([r["severity"] for r in rows], float)
    tot = float(((y - y.mean()) ** 2).sum())
    if not tot:
        return 0.0
    by = defaultdict(list)
    for r in rows:
        by[r[key]].append(r["severity"])
    w = sum(float(((np.array(v) - np.mean(v)) ** 2).sum()) for v in by.values())
    return round(1.0 - w / tot, 4)


def r2_num(rows, key):
    x = np.array([float(r.get(key, 0) or 0) for r in rows])
    y = np.array([r["severity"] for r in rows], float)
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return round(float(np.corrcoef(x, y)[0, 1] ** 2), 4)


def forest(rows, feats, group_by=None, seed=0):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import GroupKFold, KFold, cross_val_predict
    cols = []
    for f in feats:
        vals = [r.get(f, 0) for r in rows]
        if isinstance(vals[0], str):
            u = sorted(set(vals))
            cols.append([u.index(v) for v in vals])
        else:
            cols.append([float(v or 0) for v in vals])
    X = np.array(cols, float).T
    y = np.array([r["severity"] for r in rows], float)
    groups = [r[group_by] for r in rows] if group_by else None
    cv = (GroupKFold(n_splits=min(5, len(set(groups)))) if group_by
          else KFold(n_splits=5, shuffle=True, random_state=seed))
    p = cross_val_predict(
        RandomForestRegressor(n_estimators=300, min_samples_leaf=2,
                              random_state=seed, n_jobs=-1),
        X, y, cv=cv, groups=groups)
    return round(1.0 - float(((y - p) ** 2).sum())
                 / float(((y - y.mean()) ** 2).sum()), 4)


def audit(rows, label):
    y = np.array([r["severity"] for r in rows])
    chg = sorted(k for k in rows[0] if k.startswith("chg_"))
    gph = sorted(k for k in rows[0] if k.startswith("g_"))
    # CHANGE-EFFECT features are legitimate: they describe what the edit did.
    # An earlier pass classified g_d_spl_ingress_egress, g_d_edges and
    # g_lost_last_alternate_path as "size/identity" purely because their names
    # lack "touched", and then reported the legitimate signal as a shortcut.
    legit = [k for k in gph if k.startswith(("g_d_", "g_touched_", "g_change_",
                                             "g_lost_"))]
    size = [k for k in gph if k not in legit]
    print(f"\n{'=' * 78}\n{label}: n={len(rows)}, {len(set(r['topology'] for r in rows))} topologies")
    print(f"  severity {y.min():.3f}-{y.max():.3f} mean {y.mean():.3f} "
          f"median {np.median(y):.3f} distinct {len(set(np.round(y,3)))}")
    print("  -- provenance, BANNED from X (measured, then excluded) --")
    prov = {k: r2_cat(rows, k) for k in ("repair_class", "repair_id", "topology")}
    prov["quantile_idx"] = r2_num(rows, "quantile_idx")
    prov["order"] = r2_num(rows, "order")
    for k, v in prov.items():
        print(f"     {k:26s} {v:.4f}")
    print("  -- chg_ features, IN X --")
    top_chg = sorted(((r2_num(rows, k), k) for k in chg), reverse=True)[:5]
    for v, k in top_chg:
        print(f"     {k:26s} {v:.4f}")
    print("  -- g_ size/identity features, IN X --")
    for v, k in sorted(((r2_num(rows, k), k) for k in size), reverse=True)[:4]:
        print(f"     {k:26s} {v:.4f}")
    print("  -- g_ 'where it landed' features, IN X (the legitimate signal) --")
    for v, k in sorted(((r2_num(rows, k), k) for k in legit), reverse=True)[:4]:
        print(f"     {k:26s} {v:.4f}")
    res = {
        "n": len(rows), "provenance_r2": prov,
        "rf_chg_only_loto": forest(rows, chg, "topology"),
        "rf_chg_plus_size_loto": forest(rows, chg + size, "topology"),
        "rf_all_X_random": forest(rows, chg + gph),
        "rf_all_X_loto": forest(rows, chg + gph, "topology"),
        "rf_legit_only_loto": forest(rows, legit + chg, "topology"),
        "severity": {"min": float(y.min()), "max": float(y.max()),
                     "mean": float(y.mean()), "median": float(np.median(y)),
                     "zeros": int((y == 0).sum())},
    }
    print("  -- RANDOM FOREST, leave-one-topology-out unless stated --")
    print(f"     chg_ only                  {res['rf_chg_only_loto']:.4f}")
    print(f"     chg_ + size/identity g_    {res['rf_chg_plus_size_loto']:.4f}")
    print(f"     all X (chg_ + g_) random   {res['rf_all_X_random']:.4f}")
    print(f"     all X (chg_ + g_) LOTO     {res['rf_all_X_loto']:.4f}")
    print(f"     chg_ + 'where it landed'   {res['rf_legit_only_loto']:.4f}")
    print(f"     memorisation (random-LOTO) {res['rf_all_X_random'] - res['rf_all_X_loto']:+.4f}")
    return res


def main() -> int:
    wide = build_table(R3.PRIMARY_MECHANISMS, WIDE_RANGE)
    a = b = audit(wide, "REVISED PRIMARY CORPUS (SPEC-PASS, cost+blackhole, 12 topologies)")
    full = wide
    print("\n" + "=" * 78)
    print("PER-TOPOLOGY MEAN SEVERITY SPREAD")
    for lbl, rows in (("all 20", full), ("wide 12", wide)):
        by = defaultdict(list)
        for r in rows:
            by[r["topology"]].append(r["severity"])
        mu = [np.mean(v) for v in by.values()]
        print(f"  {lbl:8s} {min(mu):.3f} - {max(mu):.3f}   (topology R^2 "
              f"{r2_cat(rows, 'topology'):.4f})")
    OUT.write_text(json.dumps({"all20": a, "wide12": b}, indent=2),
                   encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
