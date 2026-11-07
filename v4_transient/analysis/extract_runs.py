"""Extract per-run transient time series, targets and validity from raw run directories.

    ./.venv/Scripts/python.exe v4_transient/analysis/extract_runs.py --plan smoke2|pilot

Writes results/<plan>/timeseries/<run_id>.csv, results/<plan>/run_metrics.csv, results/<plan>/validity.json.
Uses the last attempt of each run; every attempt's status is listed in validity.json (nothing dropped
silently). No thresholds or gates here. Validity checks: pre-registration §12 (amendment A3).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from nrl import topologies_v3 as T3                                # noqa: E402

from v4lib import targets                                          # noqa: E402
from v4lib.fib import (UP, NexthopTable, RouterFib, event_order, flushes_nexthop_objects,  # noqa: E402
                       links_equal, monitor_error_lines, own_prefixes, parse_link_lines, parse_lines,
                       parse_nexthop_lines)

MEASURABLE = {"OK", "NOT_SETTLED"}
POLL_MARGIN_BEFORE_S, POLL_MARGIN_AFTER_S = 0.01, 0.25       # events this close to a poll dump make it ambiguous


def load_run(adir: Path):
    rec = json.loads((adir / "run.json").read_text())
    return rec


def state_of(entry: dict):
    """(route records, link states, nexthop objects, status OK) of one snapshot entry (old smoke format: routes only)."""
    routes = parse_lines((entry.get("text") or "").splitlines(), with_ts=False)
    links = {l["dev"]: (l["admin_up"], l["carrier"])
             for l in parse_link_lines((entry.get("links") or "").splitlines(), with_ts=False)}
    nhs = parse_nexthop_lines((entry.get("nexthops") or "").splitlines(), with_ts=False)
    return routes, links, nhs, entry.get("status") == "OK"


def probe_metrics(adir: Path, rec: dict) -> dict:
    meta_p = adir / "probes_meta.json"
    if not meta_p.exists():
        return {}
    meta = json.loads(meta_p.read_text())
    interval = rec["params"]["PROBE_INTERVAL_S"]
    t0, t_end, t_base = rec["t0"], rec["t_end"], rec["t_baseline_start"]
    lost_pre = sent_pre = lost_win = sent_win = 0
    per_pair = {}
    for k, v in meta.items():
        f = adir / "probes" / f"{k.replace('->', '__')}.log"
        text = f.read_text() if f.exists() else ""
        got = {int(m.group(1)) for m in re.finditer(r"seq=(\d+)", text)}
        t_start = (v["t_start_before"] + v["t_start_after"]) / 2
        horizon = int((t_end - t_start) / interval)
        lp = sp = lw = sw = 0
        for seq in range(max(horizon, 0)):
            ts = t_start + seq * interval
            if t_base <= ts < t0:
                sp += 1
                lp += seq not in got
            elif t0 <= ts < t_end:
                sw += 1
                lw += seq not in got
        per_pair[k] = {"lost_pre": lp, "sent_pre": sp, "lost_window": lw, "sent_window": sw}
        lost_pre += lp; sent_pre += sp; lost_win += lw; sent_win += sw
    return {"probe_loss_frac_pre": lost_pre / sent_pre if sent_pre else None,
            "probe_loss_frac_window": lost_win / sent_win if sent_win else None,
            "probe_lost_packet_s_window": lost_win * interval, "probe_pairs": per_pair}


def router_consistency(own_r, init_state, fin_state, items, polls_r) -> dict:
    """Replay one router's FIB (snapshot + route/link/nexthop events) and check it against every unambiguous
    in-transient poll dump and the final snapshot, in forwarding semantics; report silent nexthop-object changes."""
    fr = RouterFib(own_r, init_state[1])
    for x in init_state[0]:
        fr.apply(x)
    nht = NexthopTable(init_state[2])
    items = sorted(items, key=event_order)
    all_ts = [e[0] for e in items]
    out = {"intermediate_checks": 0, "intermediate_skipped": 0, "intermediate_mismatches": [], "nhg_silent_changes": []}
    i = 0

    def advance(upto):
        nonlocal i
        while i < len(items) and items[i][0] < upto:
            ev = items[i][2]
            if ev.get("type") == "nexthop":
                p = nht.apply(ev, fr.referenced_nhids())
                if p:
                    out["nhg_silent_changes"].append(f"{items[i][0]:.6f} {p}")
            else:
                if ev.get("type") == "link" and not ev.get("deleted") and flushes_nexthop_objects(
                        fr.links.get(ev["dev"], UP), (bool(ev["admin_up"]), bool(ev["carrier"]))):
                    nht.flush_dev(ev["dev"])
                fr.apply(ev)
            i += 1

    def view(state):
        g = RouterFib(own_r, state[1])
        for x in state[0]:
            g.apply(x)
        return g.to_flowmatrix()

    for entry in sorted(polls_r, key=lambda e: e["t_before"]):
        tb, ta = entry["t_before"], entry["t_after"]
        advance(tb)
        if entry.get("status") != "OK" or any(tb - POLL_MARGIN_BEFORE_S <= t <= ta + POLL_MARGIN_AFTER_S for t in all_ts):
            out["intermediate_skipped"] += 1
            continue
        st = state_of(entry)
        if fr.to_flowmatrix() != view(st) or not links_equal(fr.links, st[1]):
            out["intermediate_mismatches"].append(tb)
        else:
            out["intermediate_checks"] += 1
    advance(float("inf"))
    out["final_match"] = fr.to_flowmatrix() == view(fin_state) and links_equal(fr.links, fin_state[1])
    out["replayed"], out["final_snapshot"] = fr.to_flowmatrix(), view(fin_state)
    return out


def extract(adir: Path, rec: dict, change: dict) -> tuple:
    """(series, metrics, diagnostics). Diagnostics feed validity_checks()."""
    spec = T3.resolve(change["topology"])
    snap0 = json.loads((adir / "fib_initial.json").read_text())
    snap1 = json.loads((adir / "fib_final.json").read_text())
    init = {r: state_of(snap0.get(r, {})) for r in spec.routers}
    fin = {r: state_of(snap1.get(r, {})) for r in spec.routers}
    initial = {r: init[r][0] for r in spec.routers}
    initial_links = {r: init[r][1] for r in spec.routers}
    events, nh_events, pre_snapshot, mon_err, n_link = [], {r: [] for r in spec.routers}, 0, 0, 0
    for r in spec.routers:
        f = adir / "fib_monitor" / f"{r}.log"
        lines = f.read_text().splitlines() if f.exists() else []
        mon_err += len(monitor_error_lines(lines))
        t_snap = snap0.get(r, {}).get("t_before", float("-inf"))
        for ev in parse_lines(lines, with_ts=True) + parse_link_lines(lines, with_ts=True):
            if ev.get("type") != "link" and ev.get("table", "main") != "main":
                continue
            if ev["ts"] < t_snap:
                pre_snapshot += 1                         # already reflected in the snapshot
                continue
            n_link += ev.get("type") == "link"
            events.append((ev["ts"], r, ev))
        nh_events[r] = [ev for ev in parse_nexthop_lines(lines, with_ts=True) if ev["ts"] >= t_snap]
    s = targets.series(initial, events, spec, rec["t0"], rec["t_end"], initial_links)
    m = targets.summarize(s)
    m["T1_merge10ms"] = targets.summarize(targets.series(initial, events, spec, rec["t0"], rec["t_end"], initial_links,
                                                         bin_s=targets.MERGE_BIN_S))["T1_disruption_area"]

    # replay consistency, router by router: intermediate FIB polls, silent nexthop-object changes, final snapshot
    own = own_prefixes(spec)
    polls_p = adir / "fib_polls.json"
    polls = json.loads(polls_p.read_text()) if polls_p.exists() else []
    mismatched, inter_mism, nhg_silent = [], [], []
    inter_checked = inter_skipped = 0
    for r in spec.routers:
        items = [e for e in events if e[1] == r] + [(ev["ts"], r, ev) for ev in nh_events[r]]
        polls_r = [p["routers"][r] for p in polls if r in (p.get("routers") or {})]
        c = router_consistency(own[r], init[r], fin[r], items, polls_r)
        mismatched += [r] if not c["final_match"] else []
        inter_mism += [f"{r}@{tb:.3f}" for tb in c["intermediate_mismatches"]]
        nhg_silent += [f"{r}: {x}" for x in c["nhg_silent_changes"]]
        inter_checked += c["intermediate_checks"]
        inter_skipped += c["intermediate_skipped"]
    nb = json.loads((adir / "ospf_neighbours.json").read_text()) if (adir / "ospf_neighbours.json").exists() else []
    diag = {"snapshots_complete": all(init[r][3] and fin[r][3] for r in spec.routers),
            "replay_mismatch_routers": mismatched, "intermediate_mismatches": inter_mism,
            "nhg_silent_changes": nhg_silent, "monitor_error_lines": mon_err}
    m.update({"events_before_snapshot": pre_snapshot, "replay_mismatch_routers": len(mismatched),
              "intermediate_checks": inter_checked, "intermediate_skipped": inter_skipped,
              "intermediate_mismatches": len(inter_mism), "nhg_silent_changes": len(nhg_silent),
              "monitor_error_lines": mon_err, "n_link_events": n_link,
              "ospf_polls": len(nb), "ospf_transitional_polls": sum(1 for x in nb if x.get("transitional")),
              "push_duration_s": rec["t_push_end"] - rec["t0"]})
    m.update({k: v for k, v in probe_metrics(adir, rec).items() if k != "probe_pairs"})
    return s, m, diag


def validity_checks(s: dict, m: dict, diag: dict, rec: dict, change: dict) -> dict:
    """Pre-registration §12 run validity (amendment A3). Every check must be True for a valid run."""
    return {
        "snapshots_complete": bool(diag["snapshots_complete"]),
        "pre_change_fib_events_zero": m["pre_change_fib_events"] == 0,
        "post_window_fib_events_zero": m["post_window_fib_events"] == 0,
        "final_undetermined_zero": s["final_undetermined"] == 0,
        "golden_carried_equals_analytic": s["n_flows_carried"] == change["features"]["n_flows_carried_pred"],
        # Fabric.predict rounds r to 6 dp, hence 1e-6 rather than exact equality
        "r_final_equals_r_exact": abs((m["r_final"] or 0) - change["features"]["r_exact"]) < 1e-6,
        "replay_matches_final_snapshot": not diag["replay_mismatch_routers"],
        "intermediate_replay_consistent": not diag["intermediate_mismatches"],
        "no_silent_nexthop_object_change": not diag["nhg_silent_changes"],
        "monitor_errors_zero": diag["monitor_error_lines"] == 0,
        "container_clock_utc": "UTC" in (rec.get("container_date") or ""),
        "post_running_config_ok": (rec.get("post_checks") or {}).get("running_config", {}).get("status") == "OK",
        "settled": bool(rec.get("settled")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", choices=["smoke", "smoke2", "smoke3", "pilot"], required=True)
    a = ap.parse_args()
    if a.plan == "smoke":
        print("REFUSED: results/smoke is preserved evidence extracted with the smoke-era library; it is not re-extracted "
              "(tests/test_smoke_regression.py recomputes it in memory)")
        return 2
    man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
    changes = {c["change_id"]: c for c in man["changes"]}
    plan = json.loads((V4 / "manifests" / f"run_plan_{a.plan}.json").read_text())["runs"]
    root = V4 / "results" / a.plan
    rows, validity = [], {"runs": {}}
    for run in sorted(plan, key=lambda r: r["order"]):
        rid = run["run_id"]
        adirs = sorted((root / "raw" / rid).glob("attempt*")) if (root / "raw" / rid).exists() else []
        statuses = []
        for ad in adirs:
            try:
                r_ = load_run(ad)
                statuses.append({"attempt": ad.name, "status": r_.get("status"), "error": r_.get("error"),
                                 "change_applied": bool(r_.get("change_applied")),
                                 "cleanup_errors": r_.get("cleanup_errors"), "injected_failure": r_.get("injected_failure")})
            except (OSError, json.JSONDecodeError):
                # no run.json: the attempt died before writing its record (pre-registration §12: INCOMPLETE)
                statuses.append({"attempt": ad.name,
                                 "status": "INCOMPLETE_AFTER_CHANGE" if (ad / "change_applied.json").exists() else "INCOMPLETE",
                                 "files": sorted(p.name for p in ad.iterdir())})
        v = {"attempts": statuses, "used": None, "measurable": False}
        validity["runs"][rid] = v
        if not adirs:
            v["status"] = "NOT_RUN"
            continue
        ad = adirs[-1]
        ch = changes[run["change_id"]]
        if not (ad / "run.json").exists():
            v["status"] = statuses[-1]["status"]
            rows.append({"run_id": rid, "change_id": run["change_id"], "replicate": run["replicate"],
                         "order": run["order"], "kind": ch["kind"], "topology": ch["topology"], "role": ch["role"],
                         "mechanism": ch["mechanism"], "status": v["status"], "attempt": ad.name, "valid": False})
            continue
        rec = load_run(ad)
        base = {"run_id": rid, "change_id": run["change_id"], "replicate": run["replicate"], "order": run["order"],
                "kind": ch["kind"], "topology": ch["topology"], "role": ch["role"], "mechanism": ch["mechanism"],
                "status": rec.get("status"), "attempt": rec.get("attempt"), "wall_s": rec.get("wall_s"),
                "convergence_s": (rec.get("convergence") or {}).get("seconds"),
                "loadavg1_before": float(((rec.get("env_before") or {}).get("loadavg") or "nan nan").split()[0]),
                "t_wall_start": rec.get("t_wall_start"), "settled": rec.get("settled"),
                "injected_failure": (rec.get("injected_failure") or {}).get("kind"), "valid": False}
        base.update({f"feat_{k}": val for k, val in ch["features"].items()})
        if rec.get("status") not in MEASURABLE:
            v["status"] = rec.get("status")
            rows.append(base)
            continue
        try:
            s, m, diag = extract(ad, rec, ch)
        except Exception as exc:                                     # noqa: BLE001
            v.update(status="EXTRACT_ERROR", error=f"{type(exc).__name__}: {exc}")
            rows.append(base)
            continue
        ts_dir = root / "timeseries"
        ts_dir.mkdir(parents=True, exist_ok=True)
        with (ts_dir / f"{rid}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(s["rows"][0]))
            w.writeheader()
            w.writerows(s["rows"])
        checks = validity_checks(s, m, diag, rec, ch)
        v.update(used=ad.name, status=rec.get("status"), checks=checks, measurable=all(checks.values()),
                 diagnostics={k: diag[k] for k in ("replay_mismatch_routers", "intermediate_mismatches",
                                                   "nhg_silent_changes")})
        base.update(m)
        base["valid"] = all(checks.values())
        rows.append(base)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "run_metrics.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    validity["summary"] = {"planned": len(plan), "with_record": sum(1 for x in validity["runs"].values() if x["attempts"]),
                           "measurable_and_valid": sum(1 for x in validity["runs"].values() if x["measurable"])}
    (root / "validity.json").write_text(json.dumps(validity, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(validity["summary"]))
    for rid, x in validity["runs"].items():
        if not x["measurable"]:
            print(f"  NOT VALID {rid}: {x.get('status')} {x.get('checks', '')} {x.get('error', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
