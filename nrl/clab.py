"""Phase 3 execution layer: drive Containerlab and measure the running network.

Design rules, in order of importance.

RULE 1 -- an execution failure is never a property FAIL.
    Every measurement carries status OK or ERROR. A verdict of HOLDS/VIOLATED is
    produced only when status == OK. If a container is missing, vtysh times out,
    or output will not parse, that is ERROR with the text preserved. Letting
    infrastructure flakiness masquerade as network behaviour is the fastest way
    to fabricate a false-pass rate.

RULE 2 -- the artifact is never modified for measurement.
    Containerlab deploys exactly the bytes Phase 1 wrote and Phase 2 analysed.
    TCP listeners are started by `docker exec` AFTER deploy: instrumentation,
    not configuration. Nothing in artifact/ is touched.

RULE 3 -- poll for convergence, never sleep.
    Sleeping produces labels biased toward harm, which inflates the false-pass
    rate. Convergence here is RIB STABILITY, not adjacency count: a faulted
    network legitimately never brings all adjacencies up, and using adjacency
    count as the criterion would time out every incident lab by construction.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

DEPLOY_TIMEOUT = 420
DESTROY_TIMEOUT = 240
EXEC_TIMEOUT = 60
CONVERGE_TIMEOUT = 180
CONVERGE_POLL_S = 5
CONVERGE_STABLE_POLLS = 3
# Floor before convergence may be declared at all. OSPF defaults are hello 10s,
# dead 40s; an adjacency that is going to form needs that long to do it. Without
# a floor the RIB looks "stable" at t=0 simply because OSPF has not started
# changing it yet, and everything gets measured mid-convergence.
MIN_SETTLE_S = 45
PING_COUNT = 5
TCP_PORTS = (80, 443)


# ---------------------------------------------------------------------------
# process helpers
# ---------------------------------------------------------------------------

def run(argv: List[str], timeout: int = EXEC_TIMEOUT, cwd=None) -> Dict:
    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return {"status": "OK" if p.returncode == 0 else "NONZERO",
                "rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr,
                "argv": argv, "seconds": round(time.time() - t0, 2),
                "error": None}
    except subprocess.TimeoutExpired:
        return {"status": "ERROR", "rc": None, "stdout": "", "stderr": "",
                "argv": argv, "seconds": round(time.time() - t0, 2),
                "error": f"timeout after {timeout}s"}
    except Exception as exc:                                       # noqa: BLE001
        return {"status": "ERROR", "rc": None, "stdout": "", "stderr": "",
                "argv": argv, "seconds": round(time.time() - t0, 2),
                "error": f"{type(exc).__name__}: {exc}"}


def _priv() -> List[str]:
    """Containerlab requires root -- it creates veths and network namespaces.
    Docker does not, because the user is in the docker group.

    `sudo -n` is non-interactive on purpose: a password prompt inside an
    unattended 61-lab run would hang forever instead of failing. Preflight
    checks this works before anything is deployed.
    """
    return [] if os.geteuid() == 0 else ["sudo", "-n"]


def clab_cmd(*args: str) -> List[str]:
    return _priv() + ["containerlab", *args]


def rm_tree(path: Path) -> None:
    """Containerlab writes its clab-<lab>/ directory as root inside the
    topology dir, so a plain rmtree fails when we are not root."""
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        run(_priv() + ["rm", "-rf", str(path)], timeout=60)


def container(lab: str, node: str) -> str:
    return f"clab-{lab}-{node}"


def dexec(lab: str, node: str, argv: List[str], timeout: int = EXEC_TIMEOUT) -> Dict:
    return run(["docker", "exec", container(lab, node)] + argv, timeout=timeout)


def vtysh(lab: str, node: str, cmd: str, timeout: int = EXEC_TIMEOUT) -> Dict:
    r = dexec(lab, node, ["vtysh", "-c", cmd], timeout=timeout)
    r["command"] = cmd
    if r["status"] == "OK" and cmd.rstrip().endswith("json"):
        try:
            r["json"] = json.loads(r["stdout"])
        except json.JSONDecodeError as exc:
            r["status"] = "ERROR"
            r["error"] = f"JSONDecodeError: {exc}"
            r["json"] = None
    return r


# ---------------------------------------------------------------------------
# lab lifecycle
# ---------------------------------------------------------------------------

def deploy(topo_dir: Path, lab: str) -> Dict:
    destroy(topo_dir, lab, quiet=True)          # never inherit a stale lab
    r = run(clab_cmd("deploy", "-t", "topology.clab.yml", "--reconfigure"),
            timeout=DEPLOY_TIMEOUT, cwd=str(topo_dir))
    r["lab"] = lab
    return r


def destroy(topo_dir: Path, lab: str, quiet: bool = False) -> Dict:
    r = run(clab_cmd("destroy", "-t", "topology.clab.yml", "--cleanup"),
            timeout=DESTROY_TIMEOUT, cwd=str(topo_dir))
    r["lab"] = lab
    return r


def containers_up(lab: str, nodes: List[str]) -> Dict:
    r = run(["docker", "ps", "--format", "{{.Names}}"])
    names = set(r["stdout"].split()) if r["status"] == "OK" else set()
    missing = [n for n in nodes if container(lab, n) not in names]
    return {"status": "OK" if not missing else "ERROR",
            "missing": missing, "expected": len(nodes),
            "found": len(nodes) - len(missing),
            "error": None if not missing else f"containers missing: {missing}"}


# ---------------------------------------------------------------------------
# convergence
# ---------------------------------------------------------------------------

def rib_snapshot(lab: str, routers: List[str]) -> Dict:
    out = {}
    for n in routers:
        r = vtysh(lab, n, "show ip route json")
        out[n] = r.get("json") if r["status"] == "OK" else {"_error": r.get("error")}
    return out


def _rib_key(rib: Dict) -> str:
    """Comparable fingerprint. Strips uptime, which ticks every second and would
    make the RIB never look stable."""
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in sorted(o.items())
                    if k not in ("uptime", "duration", "installedNexthopGroupId")}
        if isinstance(o, list):
            return [clean(x) for x in o]
        return o
    return json.dumps(clean(rib), sort_keys=True)


def ospf_neighbor_states(lab: str, routers: List[str]) -> Dict:
    """Every OSPF neighbour's state, per router."""
    out = {}
    for n in routers:
        r = vtysh(lab, n, "show ip ospf neighbor json")
        states = []
        if r["status"] == "OK" and isinstance(r.get("json"), dict):
            neigh = r["json"].get("neighbors", r["json"])
            if isinstance(neigh, dict):
                for _, entries in neigh.items():
                    for e in (entries if isinstance(entries, list) else [entries]):
                        if isinstance(e, dict):
                            states.append(str(e.get("nbrState",
                                                    e.get("state", "?"))))
        out[n] = {"status": r["status"], "states": states}
    return out


def transitional_neighbors(nbr: Dict) -> List[str]:
    """Neighbours mid-handshake: Init, 2-Way, ExStart, Exchange, Loading.

    Every link in this topology is point-to-point, so Full is the only settled
    state -- there is no DR election and no legitimate 2-Way. A neighbour that
    never appears at all is NOT transitional: in a faulted lab an adjacency that
    cannot form is the thing being measured, and waiting for it would time out
    every incident by construction.
    """
    bad = []
    for node, v in nbr.items():
        for s in v.get("states", []):
            if not s.startswith("Full"):
                bad.append(f"{node}:{s}")
    return bad


def wait_for_convergence(lab: str, routers: List[str],
                         transient_probe=None) -> Dict:
    """Converged when ALL THREE hold:

      1. at least MIN_SETTLE_S has elapsed
      2. no OSPF neighbour is in a transitional state
      3. the RIB has been byte-identical for CONVERGE_STABLE_POLLS polls

    Condition 1 exists because conditions 2 and 3 are both trivially true at
    t=0, before OSPF has done anything -- an empty neighbour table has nothing
    transitional in it and a connected-only RIB is perfectly stable. Declaring
    convergence there measures the network mid-convergence, which biases every
    label toward harm.
    """
    t0 = time.time()
    history, stable, last = [], 0, None
    trans: List[str] = []
    while time.time() - t0 < CONVERGE_TIMEOUT:
        rib = rib_snapshot(lab, routers)
        nbr = ospf_neighbor_states(lab, routers)
        trans = transitional_neighbors(nbr)
        key = _rib_key(rib)
        elapsed = time.time() - t0
        changed = (last is not None and key != last)
        stable = stable + 1 if key == last else 1
        last = key
        # TRANSIENT SAMPLING (harm definition v1.2.0, pre-registered before any
        # v2 label existed). The harness measures at a quiescent point >= 45 s
        # after deploy, so a repair that restores connectivity while flapping
        # for forty seconds scores identically to one that never flapped. Most
        # real configuration-induced harm happens during the transition, and it
        # is the part of the gap Batfish is DESIGNED not to model. One probe per
        # poll is what makes that observable at all.
        probe = transient_probe() if transient_probe else None
        history.append({
            "t": round(elapsed, 1),
            "route_counts": {n: (len(v) if isinstance(v, dict)
                                 and "_error" not in v else None)
                             for n, v in rib.items()},
            # was `key != last if history else True`, which was ALWAYS False:
            # `last` had just been assigned `key` two lines above. A field that
            # can never be true is not a measurement.
            "rib_changed": changed,
            "rib_stable_polls": stable,
            "neighbor_states": {n: v.get("states", []) for n, v in nbr.items()},
            "transitional": trans,
            "probe": probe,
        })
        if (elapsed >= MIN_SETTLE_S and not trans
                and stable >= CONVERGE_STABLE_POLLS):
            return {"status": "OK", "converged": True,
                    "seconds": round(elapsed, 1), "polls": len(history),
                    "min_settle_s": MIN_SETTLE_S,
                    "history": history, "error": None}
        time.sleep(CONVERGE_POLL_S)
    why = []
    if trans:
        why.append(f"neighbours still transitional: {sorted(set(trans))[:6]}")
    if stable < CONVERGE_STABLE_POLLS:
        why.append(f"RIB changed within the last "
                   f"{CONVERGE_STABLE_POLLS} polls")
    return {"status": "OK", "converged": False,
            "seconds": round(time.time() - t0, 1), "polls": len(history),
            "min_settle_s": MIN_SETTLE_S, "history": history,
            "error": f"not converged within {CONVERGE_TIMEOUT}s: "
                     f"{'; '.join(why) or 'unknown'}"}


def transient_summary(conv: Dict) -> Dict:
    """Signals from the convergence window, for harm definition v1.2.0.

    v1.1.0 (binary, steady state) remains the PRIMARY label and is unchanged;
    these are recorded alongside it so the secondary analysis is possible
    without re-running a single lab. Declared before any pilot-v2 label exists,
    which is what makes adding them legitimate rather than post-hoc.
    """
    hist = conv.get("history") or []
    routers = sorted({n for h in hist for n in (h.get("route_counts") or {})})

    rib_changes = {r: 0 for r in routers}
    prev = {}
    for h in hist:
        for r, c in (h.get("route_counts") or {}).items():
            if r in prev and prev[r] != c:
                rib_changes[r] += 1
            prev[r] = c

    # adjacency flap: a neighbour that reached Full and later was not Full
    seen_full, flaps = set(), 0
    for h in hist:
        for r, states in (h.get("neighbor_states") or {}).items():
            full = "Full" in " ".join(states or [])
            if full:
                seen_full.add(r)
            elif r in seen_full:
                flaps += 1
                seen_full.discard(r)

    probes = [h.get("probe") for h in hist if h.get("probe") is not None]
    reach = [p.get("reachable") for p in probes if isinstance(p, dict)]
    blackhole_polls = sum(1 for r in reach if r is False)
    # a blackhole AFTER traffic was already flowing is a transient outage; one
    # before it ever flowed is just the network still coming up
    transient_outage = False
    seen_reachable = False
    for r in reach:
        if r:
            seen_reachable = True
        elif seen_reachable:
            transient_outage = True

    return {
        "harm_definition": "1.2.0-signals",
        "seconds_to_converge": conv.get("seconds"),
        "converged": conv.get("converged"),
        "polls": len(hist),
        "rib_changes_total": sum(rib_changes.values()),
        "rib_changes_max_router": max(rib_changes.values()) if rib_changes else 0,
        "adjacency_flaps_after_full": flaps,
        "probe_polls": len(reach),
        "probe_unreachable_polls": blackhole_polls,
        "transient_outage_after_reachable": transient_outage,
        "flapped": bool(flaps > 0),
    }


# ---------------------------------------------------------------------------
# instrumentation (post-deploy, never in the artifact)
# ---------------------------------------------------------------------------

def start_listeners(lab: str, hosts: List[str]) -> Dict:
    """busybox nc, one accept loop per port. Measurement only."""
    out = {}
    for h in hosts:
        for port in TCP_PORTS:
            cmd = (f"(while true; do nc -l -p {port} >/dev/null 2>&1; done) "
                   f">/dev/null 2>&1 &")
            out[f"{h}:{port}"] = dexec(lab, h, ["sh", "-c", cmd], timeout=15)
    return out


# ---------------------------------------------------------------------------
# probes
# ---------------------------------------------------------------------------

_PING_RE = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received"
                      r"(?:.*?(\d+(?:\.\d+)?)% packet loss)?", re.S)
_RTT_RE = re.compile(r"min/avg/max(?:/mdev)?\s*=\s*"
                     r"([\d.]+)/([\d.]+)/([\d.]+)")


def probe_ping(lab: str, node: str, dst: str, src: Optional[str] = None,
               count: Optional[int] = None) -> Dict:
    """`count` defaults to PING_COUNT. The transient sampler passes count=1 so
    that one probe per convergence poll costs about a second, not PING_COUNT
    seconds; the frozen property measurement always uses the default."""
    n = int(count or PING_COUNT)
    argv = ["ping", "-c", str(n), "-W", "1"]
    if src:
        argv += ["-I", src]
    argv.append(dst)
    r = dexec(lab, node, argv, timeout=n * 3 + 10)
    out = {"kind": "ping", "node": node, "dst": dst, "src": src,
           "raw": r["stdout"] + r["stderr"], "seconds": r["seconds"],
           "status": "OK", "error": None,
           "sent": None, "received": None, "loss_pct": None,
           "rtt_min_ms": None, "rtt_avg_ms": None, "rtt_max_ms": None}
    if r["status"] == "ERROR":
        out["status"] = "ERROR"
        out["error"] = r["error"]
        return out
    m = _PING_RE.search(out["raw"])
    if not m:
        out["status"] = "ERROR"
        out["error"] = "could not parse ping output"
        return out
    sent, recv = int(m.group(1)), int(m.group(2))
    out["sent"], out["received"] = sent, recv
    out["loss_pct"] = round(100.0 * (sent - recv) / sent, 1) if sent else None
    rm = _RTT_RE.search(out["raw"])
    if rm:
        out["rtt_min_ms"] = float(rm.group(1))
        out["rtt_avg_ms"] = float(rm.group(2))
        out["rtt_max_ms"] = float(rm.group(3))
    return out


def probe_tcp(lab: str, node: str, dst: str, port: int) -> Dict:
    r = dexec(lab, node, ["sh", "-c",
                          f"nc -w 3 {dst} {port} </dev/null >/dev/null 2>&1; "
                          f"echo rc=$?"], timeout=20)
    out = {"kind": "tcp", "node": node, "dst": dst, "port": port,
           "raw": r["stdout"] + r["stderr"], "seconds": r["seconds"],
           "status": "OK", "error": None, "connected": None}
    if r["status"] == "ERROR":
        out["status"] = "ERROR"
        out["error"] = r["error"]
        return out
    m = re.search(r"rc=(\d+)", out["raw"])
    if not m:
        out["status"] = "ERROR"
        out["error"] = "could not parse nc exit code"
        return out
    out["connected"] = int(m.group(1)) == 0
    return out


def probe_traceroute(lab: str, node: str, dst: str) -> Dict:
    r = dexec(lab, node, ["traceroute", "-n", "-m", "12", "-w", "1", dst],
              timeout=60)
    out = {"kind": "traceroute", "node": node, "dst": dst,
           "raw": r["stdout"] + r["stderr"], "seconds": r["seconds"],
           "status": "OK", "error": None, "hops": [], "loop_suspected": None,
           "max_hops_reached": None}
    if r["status"] == "ERROR":
        out["status"] = "ERROR"
        out["error"] = r["error"]
        return out
    hops = []
    for line in out["raw"].splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)", line)
        if m and m.group(2) != "traceroute":
            hops.append({"n": int(m.group(1)), "ip": m.group(2)})
    out["hops"] = hops
    ips = [h["ip"] for h in hops if h["ip"] != "*"]
    out["loop_suspected"] = any(ips.count(x) >= 3 for x in set(ips))
    out["max_hops_reached"] = bool(hops) and hops[-1]["n"] >= 12
    return out


# ---------------------------------------------------------------------------
# state capture
# ---------------------------------------------------------------------------

VTYSH_COMMANDS = [
    ("route", "show ip route json"),
    ("ospf_neighbor", "show ip ospf neighbor json"),
    ("ospf_interface", "show ip ospf interface json"),
    ("interface", "show interface json"),
    ("running_config", "show running-config"),
]


def capture_state(lab: str, routers: List[str]) -> Dict:
    out = {}
    for n in routers:
        out[n] = {}
        for label, cmd in VTYSH_COMMANDS:
            out[n][label] = vtysh(lab, n, cmd)
        out[n]["ip_addr_raw"] = dexec(lab, n, ["sh", "-c", "ip addr show"],
                                      timeout=20)
    return out


def ospf_full_adjacencies(state: Dict) -> Dict:
    """Count Full neighbours. Returns per-router detail plus the pair count."""
    per_router, pairs = {}, 0
    for node, s in state.items():
        j = s.get("ospf_neighbor", {}).get("json")
        if not isinstance(j, dict):
            per_router[node] = {"status": "ERROR", "full": None}
            continue
        full = 0
        neigh = j.get("neighbors", j)
        if isinstance(neigh, dict):
            for _, entries in neigh.items():
                for e in (entries if isinstance(entries, list) else [entries]):
                    if isinstance(e, dict) and \
                            str(e.get("nbrState", e.get("state", ""))).startswith("Full"):
                        full += 1
        per_router[node] = {"status": "OK", "full": full}
        pairs += full
    return {"per_router": per_router,
            "full_adjacency_pairs": pairs // 2 if pairs else 0}


def routes_for_prefix(state: Dict, prefix: str) -> Dict:
    out = {}
    for node, s in state.items():
        j = s.get("route", {}).get("json")
        out[node] = bool(isinstance(j, dict) and prefix in j)
    return out


def interfaces_down(state: Dict, scenario=None) -> List[str]:
    """Administratively-down interfaces, SCOPED TO THE ARTIFACT.

    FRR's `show interface json` reports every interface in the container's
    namespace: the four we configured, plus eth0 (Containerlab's management
    link), plus -- transiently -- Containerlab's veth staging stubs, which have
    random names like `clab-3afeb34c` and exist only while the lab is being
    wired.

    Counting those made P12 non-deterministic: across ten configs that are
    byte-identical to golden, it failed five times, each on a different
    random stub name. Worse, it broke comparability. Batfish evaluates P12 over
    the interfaces in the configuration and has no concept of eth0 or a veth
    stub, so the two phases were measuring different sets and their P12 columns
    could not legitimately be compared.

    Scoping to the artifact's own interfaces makes the two phases ask the same
    question, which is the whole premise of the experiment.
    """
    allowed = None
    if scenario is not None:
        allowed = {(n, i.name) for n, d in scenario.devices.items()
                   if d.kind == "frr" for i in d.ifaces}
    down, ignored = [], []
    for node, s in state.items():
        j = s.get("interface", {}).get("json")
        if not isinstance(j, dict):
            continue
        for name, d in j.items():
            if not isinstance(d, dict):
                continue
            if allowed is not None and (node, name) not in allowed:
                ignored.append(f"{node}:{name}")
                continue
            admin = str(d.get("administrativeStatus",
                              d.get("adminStatus", ""))).lower()
            if admin in ("down", "false"):
                down.append(f"{node}:{name}")
    interfaces_down.last_ignored = sorted(set(ignored))
    return sorted(down)


# ---------------------------------------------------------------------------
# same-artifact verification at RUNTIME
# ---------------------------------------------------------------------------

def verify_running_config(state: Dict, scenario) -> Dict:
    """Does the container actually run what Batfish analysed?

    FRR normalises its running-config, so this is not a byte comparison. It
    checks the load-bearing facts: hostname, per-interface OSPF area/cost,
    admin state, and every static route. If these drift, the emulator and the
    verifier are describing different networks and the whole measurement is
    void.
    """
    problems, checked = [], 0
    for node, dev in scenario.devices.items():
        if dev.kind != "frr":
            continue
        rc = state.get(node, {}).get("running_config", {})
        if rc.get("status") != "OK":
            problems.append(f"{node}: running-config unavailable "
                            f"({rc.get('error')})")
            continue
        text = rc["stdout"]
        checked += 1
        if f"hostname {node}" not in text:
            problems.append(f"{node}: hostname missing from running-config")
        for i in dev.ifaces:
            blk = re.search(rf"^interface {re.escape(i.name)}$(.*?)^(?:interface |!$)",
                            text, re.M | re.S)
            body = blk.group(1) if blk else ""
            if i.ospf_area is not None and f"ip ospf area {i.ospf_area}" not in body:
                problems.append(f"{node}:{i.name} ospf area not in running-config")
            if i.ospf_cost is not None and f"ip ospf cost {i.ospf_cost}" not in body:
                problems.append(f"{node}:{i.name} ospf cost {i.ospf_cost} missing")
            if not i.up and "shutdown" not in body:
                problems.append(f"{node}:{i.name} should be shutdown but is not")
        for s in dev.statics:
            if f"ip route {s.prefix} {s.nexthop}" not in text:
                problems.append(f"{node}: static {s.prefix} -> {s.nexthop} missing")

        # Config text present is NOT config in effect. I-01 shipped `shutdown`
        # into the container, FRR echoed it back in show running-config, and the
        # interface stayed up with a Full OSPF neighbour on it. Comparing text
        # proved delivery; only comparing STATE proves effect.
        j = state.get(node, {}).get("interface", {}).get("json")
        if isinstance(j, dict):
            for i in dev.ifaces:
                d = j.get(i.name)
                if not isinstance(d, dict):
                    continue
                admin = str(d.get("administrativeStatus",
                                  d.get("adminStatus", ""))).lower()
                running_up = admin not in ("down", "false")
                if running_up != i.up:
                    problems.append(
                        f"{node}:{i.name} artifact says up={i.up} but the "
                        f"container reports admin={admin!r} -- the two tools "
                        f"are running different networks")
    return {"status": "OK" if not problems else "MISMATCH",
            "routers_checked": checked, "problems": problems}


def verify_addresses(state: Dict, scenario) -> Dict:
    problems = []
    for node, dev in scenario.devices.items():
        if dev.kind != "frr":
            continue
        raw = state.get(node, {}).get("ip_addr_raw", {}).get("stdout", "")
        for i in dev.ifaces:
            for a in i.addresses:
                if a.split("/")[0] not in raw:
                    problems.append(f"{node}:{i.name} address {a} not on the "
                                    f"container interface")
    return {"status": "OK" if not problems else "MISMATCH",
            "problems": problems}


def verify_ospf_binding(state: Dict, scenario) -> Dict:
    """Every interface the artifact puts in OSPF must actually be in OSPF.

    S-020. Containerlab wires a node by creating the veth inside the container
    under a temporary name (`clab-fd812620`) and renaming it to `eth2` after.
    If FRR's ospfd reads its configuration during that window it binds nothing
    to `eth2`, keeps the stale down-state stub in its interface table, and
    never retries. The result is a lab whose configuration is byte-correct,
    whose addresses are all present and correct, and on which one OSPF
    adjacency simply never forms.

    Every existing check passed on such a lab: `verify_running_config` compares
    config text, `verify_addresses` compares addresses -- and both were right.
    `interfaces_down` deliberately ignores `clab-*` stubs because counting them
    made P12 non-deterministic. Nothing asked the question this asks.

    This is a MEASUREMENT-VALIDITY check, not a property. A lab that fails it
    has not been measured; it must not be labelled SAFE or HARMFUL.

    SCOPED TO OPERATIONALLY-UP INTERFACES. The first version of this check
    flagged three of 38 Stage 1 runs; two were the `iface_down` fault family
    doing exactly what it is supposed to do -- ospfd drops an interface from
    its OSPF table when the link goes down, and demanding it back is v1.0.0's
    mistake of requiring every expected adjacency to be Full, which fails every
    genuinely faulted lab by construction. The real defect looks different: the
    interface is administratively AND operationally up, carrying its correct
    address, and ospfd still does not have it. Only that is flagged.
    """
    problems = []
    for node, dev in scenario.devices.items():
        if dev.kind != "frr":
            continue
        oper = {}
        ij = state.get(node, {}).get("interface", {}).get("json")
        if isinstance(ij, dict):
            oper = {n: (v.get("administrativeStatus"),
                        v.get("operationalStatus"))
                    for n, v in ij.items() if isinstance(v, dict)}
        want = {i.name for i in dev.ifaces
                if i.ospf_area is not None and i.up and i.name != "lo"
                and oper.get(i.name, ("up", "up")) == ("up", "up")}
        if not want:
            continue
        j = state.get(node, {}).get("ospf_interface", {}).get("json")
        if not isinstance(j, dict):
            problems.append(f"{node}: no `show ip ospf interface json` output")
            continue
        ifs = j.get("interfaces", j)
        if not isinstance(ifs, dict):
            problems.append(f"{node}: unparseable ospf interface output")
            continue
        for name in sorted(want):
            v = ifs.get(name)
            if not isinstance(v, dict):
                problems.append(f"{node}:{name} is in area "
                                f"{next(i.ospf_area for i in dev.ifaces if i.name == name)} "
                                f"in the artifact but ospfd does not have it "
                                f"at all (containerlab rename race)")
            elif v.get("ospfEnabled") is False:
                problems.append(f"{node}:{name} present but ospfEnabled=false")
            elif v.get("ifUp") is False:
                problems.append(f"{node}:{name} in OSPF but the interface "
                                f"is down")
    return {"status": "OK" if not problems else "MISMATCH",
            "problems": problems}


# ---------------------------------------------------------------------------
# staging: cross from the Windows share into a native Linux path, provably
# ---------------------------------------------------------------------------

def stage_artifact(src: Path, dst: Path, expected_hashes: Dict[str, str],
                   rel_prefix: str) -> Dict:
    """Copy artifact/ to a native Linux path and prove it byte-for-byte.

    Bind-mounting straight off /mnt/c into containers is slow and has
    permission quirks, so we copy. A copy is only acceptable if it is verified,
    otherwise the same-artifact guarantee ends at the filesystem boundary --
    so every file is re-hashed against pilot.lock.json.
    """
    import hashlib
    if dst.exists():
        rm_tree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    checked, bad = 0, []
    for f in sorted(dst.rglob("*")):
        if not f.is_file():
            continue
        rel = f"{rel_prefix}/artifact/{f.relative_to(dst).as_posix()}"
        want = expected_hashes.get(rel)
        if want is None:
            bad.append(f"{rel}: not present in pilot.lock.json")
            continue
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        checked += 1
        if got != want:
            bad.append(f"{rel}: sha256 differs after staging")
    for f in dst.rglob("*"):
        if f.is_file():
            f.chmod(0o644)
    return {"status": "OK" if not bad else "ERROR",
            "files_verified": checked, "problems": bad,
            "staged_to": str(dst),
            "error": None if not bad else f"{len(bad)} staging problem(s)"}
