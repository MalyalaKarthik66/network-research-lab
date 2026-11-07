"""Feed a3_frr_check.sh output through the PRODUCTION A3 replay-consistency code (extract_runs.router_consistency)."""
import importlib.util
import json
import sys
from pathlib import Path

V4 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))
spec = importlib.util.spec_from_file_location("extract_runs", V4 / "analysis" / "extract_runs.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)
from v4lib import fib  # noqa: E402

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
sec, cur = {}, None
for line in text:
    if line.startswith("== END_"):
        name, t = line[7:].split()
        sec[name]["t_after"] = float(t)
        cur = None
    elif line.startswith("== "):
        name, t = line[3:].split()
        sec[name] = {"t_before": float(t), "lines": []}
        cur = name
    elif cur:
        sec[cur]["lines"].append(line)


def entry(name, poll=False):
    body = "\n".join(sec[name]["lines"])
    if poll:
        body = body.partition(fib.POLL_ROUTES)[2].lstrip("\n")
    parts = fib.split_state(body)
    return {"t_before": sec[name]["t_before"], "t_after": sec[name]["t_after"], "status": "OK",
            "text": "\n".join(parts["routes"]) + "\n", "links": "\n".join(parts["links"]) + "\n",
            "nexthops": "\n".join(parts["nexthops"]) + "\n"}


mon = sec["MONITOR"]["lines"]
t_snap = sec["SNAP0"]["t_before"]
items = [(e["ts"], "r", e) for e in fib.parse_lines(mon, True) + fib.parse_link_lines(mon, True)
         if e["ts"] >= t_snap and (e.get("type") == "link" or e.get("table", "main") == "main")]
items += [(e["ts"], "r", e) for e in fib.parse_nexthop_lines(mon, True) if e["ts"] >= t_snap]
c = ex.router_consistency([], ex.state_of(entry("SNAP0")), ex.state_of(entry("FINAL")), items,
                          [entry(p, poll=True) for p in ("POLL1", "POLL2", "POLL3")])
out = {"monitor_error_lines": fib.monitor_error_lines(mon),
       "n_route_events": sum(1 for e in items if e[2].get("type") is None),
       "n_link_events": sum(1 for e in items if e[2].get("type") == "link"),
       "n_nexthop_events": sum(1 for e in items if e[2].get("type") == "nexthop"),
       **{k: v for k, v in c.items() if k not in ("replayed", "final_snapshot")},
       "final_view_prefixes": {p: [x.get("protocol") for x in v] for p, v in c["final_snapshot"].items()}}
if not c["final_match"]:
    out["replayed"], out["final_snapshot"] = c["replayed"], c["final_snapshot"]
print(json.dumps(out, indent=1, default=str))
ok = c["final_match"] and not c["intermediate_mismatches"] and c["intermediate_checks"] >= 1 and not out["monitor_error_lines"]
print("A3 INSTRUMENT CHECK:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
