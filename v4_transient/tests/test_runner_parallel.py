"""Amendment A5 regression tests: parallel docker exec outside the observation window changes nothing the protocol
measures. Offline (a fake nrl.clab transport; no lab, no Docker).
    ./.venv/Scripts/python.exe v4_transient/tests/test_runner_parallel.py

1. Code pins against the A3 commit 4056099 (read with `git show`): the observation-window block of run_pilot.py, every
   in-window lab operation and stop_instruments, the frozen protocol parameters, the extraction/replay/target code, and
   nrl/ are unchanged.
2. Behaviour: each parallelized operation sends exactly the A3 commands (same per-container order) and returns exactly
   the A3 result structure, apart from wall-clock timestamps; timestamps still bracket each router's own exec; the work
   really runs concurrently; a phase returns only after all of its tasks; errors propagate.
3. Phase order in one_run: monitors before the reference snapshot before probes before the baseline; after t_end the
   poller stops and joins, instruments stop (serially, as A3), then reads, final snapshot, state capture.
"""
import ast
import hashlib
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
REPO = V4.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(V4))

from nrl import clab                                                 # noqa: E402

from v4lib import labops as L                                        # noqa: E402

A3 = "4056099"
fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def git_show(rel: str) -> str:
    r = subprocess.run(["git", "show", f"{A3}:{rel}"], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"FAIL cannot read {rel} at {A3}: {r.stderr}")
    return r.stdout


def defs(src: str):
    return {n.name: ast.get_source_segment(src, n) for n in ast.parse(src).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def window(src: str) -> str:
    a = src.index('        rec["t_baseline_start"] = time.time()')
    b = src.index('        rec["observation_s"] = rec["t_end"] - rec["t0"]')
    return src[a:b]


# ---- 1. code pins ---------------------------------------------------------------------------------------------------
rp_now, rp_a3 = (V4 / "pilot" / "run_pilot.py").read_text(encoding="utf-8"), git_show("v4_transient/pilot/run_pilot.py")
check("run_pilot observation window (baseline start .. t_end) identical to A3",
      window(rp_now) == window(rp_a3) and sha(window(rp_now)) == "df4d32392a13d43f1139f2d5779e5206b061e2e4b4b4e8515ecb15c19cdd7a81")
lab_now, lab_a3 = (V4 / "v4lib" / "labops.py").read_text(encoding="utf-8"), git_show("v4_transient/v4lib/labops.py")
dn, da = defs(lab_now), defs(lab_a3)
for name in ("poll_routers", "push_change", "NeighbourPoller", "last_event_ts", "_state_entry", "stop_instruments",
             "deploy", "destroy", "stage", "environment", "static_environment"):
    check(f"labops.{name} identical to A3", dn.get(name) == da.get(name))
params = ("PRE_CHANGE_BASELINE_S", "MIN_OBS_S", "QUIET_S", "MAX_OBS_S", "POLL_S", "PROBE_INTERVAL_S", "PROBE_COUNT",
          "MON_FILE", "MON_CMD", "SNAPSHOT_SH", "POLL_SH")
a3_mod = types.ModuleType("v4lib._labops_a3")
a3_mod.__package__ = "v4lib"
exec(compile(lab_a3, "labops@A3", "exec"), a3_mod.__dict__)
check("frozen protocol parameters identical to A3 (values)", all(getattr(L, p) == getattr(a3_mod, p) for p in params),
      [p for p in params if getattr(L, p) != getattr(a3_mod, p)])
for rel in ("v4lib/fib.py", "v4lib/targets.py", "v4lib/analytic.py", "v4lib/gates.py", "analysis/analyze_pilot.py"):
    check(f"{rel} identical to A3", (V4 / rel).read_text(encoding="utf-8") == git_show(f"v4_transient/{rel}"))
ex_now = (V4 / "analysis" / "extract_runs.py").read_text(encoding="utf-8")
check("extract_runs.py identical to A3 except the added 'smoke3' plan choice",
      ex_now.replace(', "smoke3"', "") == git_show("v4_transient/analysis/extract_runs.py"))
nrl_diff = subprocess.run(["git", "diff", "--quiet", A3, "--", "nrl"], cwd=REPO)
check("nrl/ unchanged since A3 (read-only)", nrl_diff.returncode == 0)
check("pre-change convergence still the frozen nrl.clab.wait_for_convergence", "clab.wait_for_convergence(lab, routers)" in rp_now)
PAR = ("start_fib_monitors", "fib_snapshot", "read_monitors", "start_probes", "collect_probes", "ospf_binding_state",
       "capture_state", "parallel_map")
w = window(rp_now)
check("no parallelized operation is called inside the observation window", not any(f"L.{p}(" in w for p in PAR))
for name in ("poll_routers", "push_change", "NeighbourPoller", "stop_instruments"):
    check(f"labops.{name} does not use parallel_map", "parallel_map" not in dn[name])
check("run_pilot does not call nrl.clab.capture_state directly any more (per-router wrapper)",
      "clab.capture_state(" not in rp_now)

# ---- 2. behaviour against the A3 functions, with a fake transport ---------------------------------------------------
calls, lock = [], threading.Lock()
active, peak = [0], [0]


def _enter():
    with lock:
        active[0] += 1
        peak[0] = max(peak[0], active[0])


def _leave():
    with lock:
        active[0] -= 1


def fake_run(argv, timeout=60, cwd=None):
    _enter()
    t = time.time()
    time.sleep(0.02)
    with lock:
        calls.append({"t": t, "argv": list(argv)})
    _leave()
    return {"status": "OK", "rc": 0, "stdout": f"out {' '.join(argv)}\n", "stderr": "", "seconds": 0.02, "error": None}


def fake_dexec(lab, node, argv, timeout=60):
    return fake_run(["docker", "exec", clab.container(lab, node)] + list(argv), timeout)


def fake_vtysh(lab, node, cmd, timeout=60):
    r = fake_dexec(lab, node, ["vtysh", "-c", cmd], timeout)
    return dict(r, json={"node": node, "cmd": cmd})


clab.run, clab.dexec, clab.vtysh = fake_run, fake_dexec, fake_vtysh
LAB, ROUTERS = "nrlv4-t15", ["r%02d" % i for i in range(12)]
TS_KEYS = {"t_before", "t_after", "t_start_before", "t_start_after", "seconds"}


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in TS_KEYS}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o


def per_container(cs):
    out = {}
    for c in cs:
        key = c["argv"][2] if c["argv"][:2] == ["docker", "exec"] and c["argv"][2] != "-d" else c["argv"][3]
        out.setdefault(key, []).append(c["argv"])
    return out


def compare(label, new_fn, old_fn):
    del calls[:]
    peak[0] = 0
    old = old_fn()
    old_calls, old_peak = list(calls), peak[0]
    del calls[:]
    peak[0] = 0
    t_a = time.time()
    new = new_fn()
    new_calls, new_peak, dt = list(calls), peak[0], time.time() - t_a
    check(f"{label}: identical result (timestamps excluded)", strip(new) == strip(old))
    check(f"{label}: identical commands, identical order per container",
          per_container(new_calls) == per_container(old_calls) and len(new_calls) == len(old_calls))
    check(f"{label}: A3 ran serially, A5 runs concurrently (peak {old_peak} -> {new_peak})", old_peak == 1 and new_peak > 1)
    return new, new_calls


spec = types.SimpleNamespace()
hosts = [{"kind": "host", "name": f"host{c}", "container": f"host{c}", "addr": f"10.2{i}.0.10"} for i, c in enumerate("abc")]
import nrl.flowmatrix as fm                                          # noqa: E402
fm.endpoints = lambda s: hosts + [{"kind": "router", "name": r, "container": r, "addr": f"10.255.0.{i}"}
                                  for i, r in enumerate(ROUTERS)]
compare("start_fib_monitors", lambda: L.start_fib_monitors(LAB, ROUTERS), lambda: a3_mod.start_fib_monitors(LAB, ROUTERS))
snap, snap_calls = compare("fib_snapshot", lambda: L.fib_snapshot(LAB, ROUTERS), lambda: a3_mod.fib_snapshot(LAB, ROUTERS))
starts = {c["argv"][2]: c["t"] for c in snap_calls}
check("fib_snapshot: each router's t_before/t_after bracket its own exec",
      all(snap[r]["t_before"] <= starts[clab.container(LAB, r)] <= snap[r]["t_after"] for r in ROUTERS))
check("fib_snapshot: result keys in router order", list(snap) == ROUTERS)
compare("read_monitors", lambda: L.read_monitors(LAB, ROUTERS), lambda: a3_mod.read_monitors(LAB, ROUTERS))
probes, _ = compare("start_probes", lambda: L.start_probes(LAB, spec), lambda: a3_mod.start_probes(LAB, spec))
check("start_probes: 6 host pairs in A3 key order", list(probes) == [f"{s['name']}->{d['name']}" for s in hosts for d in hosts if s != d])
compare("collect_probes", lambda: L.collect_probes(LAB, probes), lambda: a3_mod.collect_probes(LAB, probes))
compare("ospf_binding_state vs the A3 inline binding capture", lambda: L.ospf_binding_state(LAB, ROUTERS),
        lambda: {n: {"interface": clab.vtysh(LAB, n, "show interface json"),
                     "ospf_interface": clab.vtysh(LAB, n, "show ip ospf interface json")} for n in ROUTERS})
compare("capture_state vs nrl.clab.capture_state (unmodified)", lambda: L.capture_state(LAB, ROUTERS),
        lambda: clab.capture_state(LAB, ROUTERS))

done = []
res = L.parallel_map(lambda x: (time.sleep(0.05 if x == 0 else 0.0), done.append(x), x * 2)[2], list(range(8)))
check("parallel_map: results in input order and returns only after every task", res == [x * 2 for x in range(8)] and len(done) == 8)
try:
    L.parallel_map(lambda x: 1 / (x - 3), range(6))
    check("parallel_map: an exception propagates", False)
except ZeroDivisionError:
    check("parallel_map: an exception propagates", True)

# ---- 3. phase order in one_run --------------------------------------------------------------------------------------
one_run = defs(rp_now)["one_run"]


def order(*needles):
    idx = [one_run.find(n) for n in needles]
    return all(i >= 0 for i in idx) and idx == sorted(idx), dict(zip(needles, idx))


ok, d = order("clab.wait_for_convergence(", "L.ospf_binding_state(", "L.start_fib_monitors(", "time.sleep(0.5)",
              'L.wj(rdir / "fib_initial.json", L.fib_snapshot(', "L.start_probes(", "poller.start()",
              'rec["t_baseline_start"] = time.time()')
check("pre-change phase order: convergence, binding, monitors, 0.5 s, reference snapshot, probes, poller, baseline", ok, d)
ok, d = order('rec["observation_s"]', "poller.stop()", "poller.join(timeout=30)", "L.stop_instruments(", "L.read_monitors(",
              "L.collect_probes(", 'L.wj(rdir / "fib_final.json", L.fib_snapshot(', "L.capture_state(", 'rec["post_checks"]')
check("post-window phase order: poller stop+join, instruments stopped (serial, A3), reads, final snapshot, state", ok, d)
check("RUNNER_EXEC_MODE recorded in run.json", '"runner_exec_mode": L.RUNNER_EXEC_MODE' in rp_now)

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
