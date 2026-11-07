"""Lab operations for the transient protocol. Runs inside WSL.

Reuses nrl.clab read-only for docker exec, vtysh, convergence polling, state capture and the runtime
same-artifact checks. Two deliberate differences, both because nrl/clab.py must not be modified:
  * containerlab is invoked WITHOUT `sudo -n`: the WSL user is in `clab_admins`, which containerlab
    0.79 honours for non-root operation (verified in the smoke test, recorded per run);
  * artifacts are staged with our own lock file under v4_transient/manifests.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

from nrl import clab

from . import PROTOCOL_VERSION
from .fib import POLL_ROUTES, SNAP_LINKS, SNAP_NEXTHOPS, parse_lines, parse_link_lines, split_state

# ---- frozen protocol parameters (docs/PILOT-PREREGISTRATION.md §3-§5) --------------------------------
PRE_CHANGE_BASELINE_S = 10.0     # instruments running, nothing pushed
MIN_OBS_S = 20.0                 # never stop observing earlier than this after t0
QUIET_S = 10.0                   # FIB silent this long after the last event / push end
MAX_OBS_S = 90.0                 # hard cap; exceeding it marks the run NOT_SETTLED
POLL_S = 2.0                     # FIB-log and OSPF-neighbour polling cadence (low to limit observer load)
PROBE_INTERVAL_S = 0.05          # busybox ping -i for host-pair packet probes (secondary instrument)
PROBE_COUNT = int(math.ceil((PRE_CHANGE_BASELINE_S + MAX_OBS_S + 30.0) / PROBE_INTERVAL_S))
MON_FILE = "/tmp/v4mon.log"
MON_CMD = "ip -ts monitor link route nexthop"      # amendment A3: link and nexthop-object events too
SNAPSHOT_SH = (f"ip -4 route show table main; echo {SNAP_LINKS}; ip -o link show; echo {SNAP_NEXTHOPS}; "
               "ip nexthop show 2>/dev/null; true")
POLL_SH = f"cat {MON_FILE}; echo; echo {POLL_ROUTES}; {SNAPSHOT_SH}"
#: amendment A5 (engineering, 2026-09-15): recorded in every run.json
RUNNER_EXEC_MODE = "A5-parallel-docker-exec-outside-observation-window"


def parallel_map(fn, items) -> list:
    """fn over items concurrently; results in input order; an exception propagates as in a serial loop.

    Amendment A5: used ONLY for docker exec phases outside [t_baseline_start, t_end] -- pre-change OSPF-binding
    check, monitor start, initial snapshot, probe start; post-window monitor and probe reads, final snapshot, state
    capture. Each phase completes before the next begins, and the commands sent to one container keep their A3 order.
    The observation window (push, 2 s FIB polls, OSPF poller) and stop_instruments keep the A3 serial code, pinned by
    hash in tests/test_runner_parallel.py."""
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=len(items)) as ex:
        return list(ex.map(fn, items))


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def wj(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8", newline="\n")
    tmp.replace(path)


def deploy(topo_dir: Path) -> Dict:
    destroy(topo_dir)
    return clab.run(["containerlab", "deploy", "-t", "topology.clab.yml", "--reconfigure"],
                    timeout=clab.DEPLOY_TIMEOUT, cwd=str(topo_dir))


def destroy(topo_dir: Path) -> Dict:
    return clab.run(["containerlab", "destroy", "-t", "topology.clab.yml", "--cleanup"],
                    timeout=clab.DESTROY_TIMEOUT, cwd=str(topo_dir))


def stage(src: Path, dst: Path, lock: Dict[str, str], rel_prefix: str) -> Dict:
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    bad, n = [], 0
    for f in sorted(dst.rglob("*")):
        if not f.is_file():
            continue
        rel = f"{rel_prefix}/artifact/{f.relative_to(dst).as_posix()}"
        want = lock.get(rel)
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        n += 1
        if want is None or got != want:
            bad.append(rel)
        f.chmod(0o644)
    return {"status": "OK" if not bad else "ERROR", "files_verified": n, "problems": bad}


def environment() -> Dict:
    def rd(p):
        try:
            return Path(p).read_text().strip()
        except OSError:
            return None
    mem = {}
    for line in (rd("/proc/meminfo") or "").splitlines()[:3]:
        k, v = line.split(":", 1)
        mem[k] = v.strip()
    ps = clab.run(["docker", "ps", "-q"], timeout=30)
    return {"utc": now_utc(), "epoch": time.time(), "loadavg": rd("/proc/loadavg"), "meminfo": mem,
            "uptime_s": rd("/proc/uptime"), "nproc": os.cpu_count(), "kernel": platform.release(),
            "python": platform.python_version(),
            "running_containers": len(ps["stdout"].split()) if ps["status"] == "OK" else None}


def static_environment() -> Dict:
    out = {"protocol_version": PROTOCOL_VERSION, "platform": platform.platform(), "hostname": platform.node()}
    for label, argv in (("containerlab", ["containerlab", "version"]),
                        ("docker", ["docker", "version", "--format", "{{.Server.Version}}"]),
                        ("frr_image", ["docker", "image", "inspect", "frrouting/frr:v8.4.1",
                                       "--format", "{{index .RepoDigests 0}}"]),
                        ("host_image", ["docker", "image", "inspect", "alpine:3.19",
                                        "--format", "{{index .RepoDigests 0}}"]),
                        ("cpu", ["sh", "-c", "grep -m1 'model name' /proc/cpuinfo"])):
        r = clab.run(argv, timeout=30)
        out[label] = (r["stdout"] or r["stderr"]).strip()[:400]
    out["euid"] = os.geteuid()
    return out


# ---- instrumentation --------------------------------------------------------------------------------

def start_fib_monitors(lab: str, routers: List[str]) -> Dict:
    """Pre-change (A5: routers in parallel; per router: truncate the log, then start the monitor)."""
    def one(r):
        clab.dexec(lab, r, ["sh", "-c", f": > {MON_FILE}"], timeout=15)
        res = clab.run(["docker", "exec", "-d", clab.container(lab, r), "sh", "-c",
                        f"exec {MON_CMD} >> {MON_FILE} 2>&1"], timeout=15)
        return {"status": res["status"], "stderr": res["stderr"][-300:]}
    return dict(zip(routers, parallel_map(one, routers)))


def _state_entry(t_a: float, res: Dict, state_text: str) -> Dict:
    parts = split_state(state_text)
    return {"t_before": t_a, "t_after": time.time(), "status": res["status"],
            "text": "\n".join(parts["routes"]) + "\n", "links": "\n".join(parts["links"]) + "\n",
            "nexthops": "\n".join(parts["nexthops"]) + "\n", "error": res.get("error")}


def fib_snapshot(lab: str, routers: List[str]) -> Dict:
    """Routes, link states and nexthop objects of every router, one docker exec per router, each with its own
    t_before/t_after. Called only outside the observation window (initial and final snapshot): routers in parallel (A5)."""
    def one(r):
        t_a = time.time()
        res = clab.dexec(lab, r, ["sh", "-c", SNAPSHOT_SH], timeout=20)
        return _state_entry(t_a, res, res.get("stdout") or "")
    return dict(zip(routers, parallel_map(one, routers)))


def poll_routers(lab: str, routers: List[str]) -> Dict:
    """Settle polling (§3/§5): the monitor log plus a full state dump per router in ONE docker exec, so the replay can
    be checked against the real FIB during the transient at no extra exec cost."""
    out = {}
    for r in routers:
        t_a = time.time()
        res = clab.dexec(lab, r, ["sh", "-c", POLL_SH], timeout=20)
        mon, _, state = (res.get("stdout") or "").partition(POLL_ROUTES)
        e = _state_entry(t_a, res, state.lstrip("\n"))
        e["monitor"] = mon
        out[r] = e
    return out


def read_monitors(lab: str, routers: List[str]) -> Dict[str, str]:
    """After every monitor is stopped (A5: routers in parallel)."""
    return dict(zip(routers, parallel_map(lambda r: clab.dexec(lab, r, ["cat", MON_FILE], timeout=20).get("stdout", ""),
                                          routers)))


def last_event_ts(texts: Dict[str, str]):
    """Latest FIB-relevant activity: IPv4 main-table route events and link events."""
    ts = [rec["ts"] for t in texts.values() for rec in parse_lines(t.splitlines(), with_ts=True)
          if rec.get("table", "main") == "main"]
    ts += [rec["ts"] for t in texts.values() for rec in parse_link_lines(t.splitlines(), with_ts=True)]
    return max(ts) if ts else None


def start_probes(lab: str, spec) -> Dict:
    from nrl import flowmatrix as fm
    hosts = [e for e in fm.endpoints(spec) if e["kind"] == "host"]

    def one_source(s):                            # pre-change (A5: source hosts in parallel; one host's pairs in A3 order)
        out = []
        for d in hosts:
            if s["addr"] == d["addr"]:
                continue
            fname = f"/tmp/v4ping_{d['name']}.log"
            clab.dexec(lab, s["container"], ["sh", "-c", f": > {fname}"], timeout=15)
            t_a = time.time()
            res = clab.run(["docker", "exec", "-d", clab.container(lab, s["container"]), "sh", "-c",
                            f"exec ping -i {PROBE_INTERVAL_S} -W 1 -c {PROBE_COUNT} {d['addr']} >> {fname} 2>&1"],
                           timeout=15)
            out.append((f"{s['name']}->{d['name']}", {"container": s["container"], "file": fname, "dst": d["addr"],
                                                     "t_start_before": t_a, "t_start_after": time.time(),
                                                     "status": res["status"]}))
        return out
    return dict(x for group in parallel_map(one_source, hosts) for x in group)


def stop_instruments(lab: str, routers: List[str], hosts: List[str]) -> None:
    for r in routers:
        clab.dexec(lab, r, ["sh", "-c", "pkill -f 'ip -ts monitor' || true"], timeout=15)
    for h in hosts:
        clab.dexec(lab, h, ["sh", "-c", "pkill ping || true"], timeout=15)


def collect_probes(lab: str, probes: Dict) -> Dict[str, str]:
    """After every ping is stopped (A5: containers in parallel; one container's reads in A3 order)."""
    by_container: Dict[str, List[str]] = {}
    for k in probes:
        by_container.setdefault(probes[k]["container"], []).append(k)

    def one(c):
        return [(k, clab.dexec(lab, c, ["cat", probes[k]["file"]], timeout=20).get("stdout", "")) for k in by_container[c]]
    got = dict(x for group in parallel_map(one, list(by_container)) for x in group)
    return {k: got[k] for k in probes}


def ospf_binding_state(lab: str, routers: List[str]) -> Dict:
    """Pre-change OSPF-binding inputs: the same two vtysh commands per router, in the A3 order; routers in parallel (A5)."""
    def one(n):
        return {"interface": clab.vtysh(lab, n, "show interface json"),
                "ospf_interface": clab.vtysh(lab, n, "show ip ospf interface json")}
    return dict(zip(routers, parallel_map(one, routers)))


def capture_state(lab: str, routers: List[str]) -> Dict:
    """Post-window state capture: the frozen, unmodified nrl.clab.capture_state called once per router (its per-router
    command order unchanged); routers in parallel (A5)."""
    return dict(zip(routers, parallel_map(lambda n: clab.capture_state(lab, [n])[n], routers)))


class NeighbourPoller(threading.Thread):
    """OSPF neighbour states every POLL_S, timestamped host-side (same kernel clock)."""

    def __init__(self, lab: str, routers: List[str]):
        super().__init__(daemon=True)
        self.lab, self.routers = lab, routers
        self.samples: List[Dict] = []
        # NOT `_stop`: threading.Thread uses self._stop() internally (join/is_alive). Shadowing it with an
        # Event crashed smoke run 1 in join() -- found by the smoke test, 2026-09-14.
        self._halt = threading.Event()

    def run(self):
        while not self._halt.is_set():
            t_a = time.time()
            try:
                nbr = clab.ospf_neighbor_states(self.lab, self.routers)
                self.samples.append({"t_before": t_a, "t_after": time.time(),
                                     "states": {n: v.get("states", []) for n, v in nbr.items()},
                                     "transitional": clab.transitional_neighbors(nbr)})
            except Exception as exc:                                    # noqa: BLE001
                self.samples.append({"t_before": t_a, "t_after": time.time(), "error": f"{type(exc).__name__}: {exc}",
                                     "states": {}, "transitional": []})
            self._halt.wait(max(0.0, POLL_S - (time.time() - t_a)))

    def stop(self):
        self._halt.set()


def push_change(lab: str, plan: Dict[str, List[str]]) -> List[Dict]:
    """Apply per device, sorted by node name, one vtysh invocation per device."""
    out = []
    for node in sorted(plan):
        argv = ["vtysh", "-c", "configure terminal"]
        for c in plan[node]:
            argv += ["-c", c]
        t_a = time.time()
        res = clab.dexec(lab, node, argv, timeout=30)
        out.append({"node": node, "commands": plan[node], "t_start": t_a, "t_end": time.time(),
                    "status": res["status"], "rc": res.get("rc"), "stdout": res["stdout"][-500:],
                    "stderr": res["stderr"][-500:]})
    return out
