"""Offline tests: FIB parser, replay, targets and analytic features on synthetic data. No lab needed.
    ./.venv/Scripts/python.exe v4_transient/tests/test_core.py
"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2])); sys.path.insert(0, str(HERE.parents[1]))
from v4lib import fib, targets, analytic
from nrl import topologies_v3 as T3
from nrl.severity import Fabric

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)

# 1. parser: static, connected, blackhole, multipath, deleted, ipv6, mgmt, timestamps
snap = """default via 172.20.20.1 dev eth0
10.10.0.0/24 dev eth1 proto kernel scope link src 10.10.0.1
10.20.0.0/24 via 10.13.1.2 dev eth2 proto ospf metric 20
10.255.0.3 proto ospf metric 20
\tnexthop via 10.13.1.2 dev eth2 weight 1
\tnexthop via 10.13.2.2 dev eth3 weight 1
blackhole 10.255.0.9 proto static metric 20
172.20.20.0/24 dev eth0 proto kernel scope link src 172.20.20.3
""".splitlines()
recs = fib.parse_lines(snap, with_ts=False)
by = {r["dst"]: r for r in recs}
check("parse count", len(recs) == 6, [r["dst"] for r in recs])
check("multipath folded", sorted(by["10.255.0.3/32"]["nexthops"]) == [("10.13.1.2", "eth2"), ("10.13.2.2", "eth3")], by["10.255.0.3/32"])
check("blackhole kind", by["10.255.0.9/32"]["kind"] == "blackhole")
mon = """[2026-09-14T12:00:00.100000] Deleted 10.20.0.0/24 via 10.13.1.2 dev eth2 proto ospf metric 20
[2026-09-14T12:00:00.100500] 10.20.0.0/24 via 10.13.2.2 dev eth3 proto ospf metric 20
[2026-09-14T12:00:00.200000] fe80::/64 dev eth1 proto kernel metric 256 pref medium
""".splitlines()
ev = fib.parse_lines(mon, with_ts=True)
check("monitor parse (ipv6 dropped)", len(ev) == 2 and ev[0]["deleted"] and not ev[1]["deleted"], ev)
check("timestamp epoch", abs(ev[1]["ts"] - ev[0]["ts"] - 0.0005) < 1e-6)
f = fib.RouterFib(["10.255.0.1/32"])
for r in recs: f.apply(r)
fm = f.to_flowmatrix()
check("mgmt + default dropped", "0.0.0.0/0" not in fm and "172.20.20.0/24" not in fm)
check("own loopback connected", fm["10.255.0.1/32"][0]["protocol"] == "connected")
check("blackhole nexthop", fm["10.255.0.9/32"][0]["nexthops"][0].get("blackhole") is True)

# 2. replay + targets on a real v3 topology: golden FIB synthesised from the analytic model,
#    then a transient microloop state, then the final state.
spec = T3.resolve("t05_ring6")
fab = Fabric(spec)
from nrl import flowmatrix as flowm
owner = flowm.owner_map(spec)
def synth_fib(cost_override=None, removed=None):
    """Kernel-style records for every router from the analytic next-hop table (+ connected host LANs)."""
    nh = analytic.nexthop_table(fab, cost_override, removed)
    out = {}
    for r in spec.routers:
        lines = []
        for (a, ai, aa, b, bi, ba, sub, label, cost) in spec.links:
            if r == a: lines.append(f"{sub} dev {ai} proto kernel scope link src {aa.split('/')[0]}")
            if r == b: lines.append(f"{sub} dev {bi} proto kernel scope link src {ba.split('/')[0]}")
        for dr in spec.routers:
            if dr == r: continue
            hops = sorted(nh[(r, dr)], key=lambda v: fab._nh_key(r, v))
            if not hops: continue
            v = hops[0]
            lines.append(f"{spec.routers[dr]} via {fab.nh_addr[(r, v)]} dev x proto ospf metric 20")
            for h, hr in spec.hosts.items():
                if hr == dr:
                    pfx = next(l[6] for l in spec.links if h in (l[0], l[3]))
                    lines.append(f"{pfx} via {fab.nh_addr[(r, v)]} dev x proto ospf metric 20")
        out[r] = fib.parse_lines(lines, with_ts=False)
    return out
gold = synth_fib()
lk = max(sorted(fab.cost), key=lambda l: fab.predict(cost_override={l: fab.cost[l] * 20})["r"])
assert fab.predict(cost_override={lk: fab.cost[lk] * 20})["r"] > 0
fin = synth_fib(cost_override={lk: fab.cost[lk] * 20})
t0 = 1000.0
events = []
# at t0+0.5 every router jumps to its final FIB (deletes + adds), creating no transient
for r in spec.routers:
    for rec in gold[r]:
        if rec["proto"] == "ospf": events.append((t0 + 0.5, r, dict(rec, deleted=True)))
    for rec in fin[r]:
        if rec["proto"] == "ospf": events.append((t0 + 0.5, r, dict(rec, deleted=False)))
s = targets.series(gold, events, spec, t0, t0 + 20)
m = targets.summarize(s)
pred = fab.predict(cost_override={lk: fab.cost[lk] * 20})
check("golden undetermined 0", s["rows"][0]["undetermined"] == 0, s["rows"][0])
check("final r equals analytic r_exact", abs(m["r_final"] - pred["r"]) < 1e-6, (m["r_final"], pred["r"]))
check("atomic switch => T1 == 0", m["T1_disruption_area"] == 0.0, m)
# now insert a transient: one router on the golden path loses its route to hostb's router for 0.3 s
victim_dst = spec.routers[spec.hosts["hostb"]]
gp = fab.golden[("hosta", "hostb")]
mid = gp[1] if len(gp) > 2 else gp[0]
drop = [rec for rec in gold[mid] if rec["dst"].startswith("10.20.0.")]
ev2 = [(t0 + 0.1, mid, dict(rec, deleted=True)) for rec in drop] + [(t0 + 0.4, mid, dict(rec, deleted=False)) for rec in drop] + events
s2 = targets.series(gold, ev2, spec, t0, t0 + 20)
m2 = targets.summarize(s2)
check("transient blackhole => T1 > 0", m2["T1_disruption_area"] > 0, m2)
check("T3 duration ~0.4", abs(m2["T3_disruption_duration"] - 0.4) < 1e-6, m2["T3_disruption_duration"])
check("T1 == peak x 0.3", abs(m2["T1_disruption_area"] - m2["T2_peak_disruption"] * 0.3) < 1e-9, m2)
ev3 = [(t0 - 1.0, mid, dict(drop[0], deleted=True)), (t0 - 0.5, mid, dict(drop[0], deleted=False))] + events
check("pre-change FIB activity detected", targets.series(gold, ev3, spec, t0, t0 + 20)["pre_change_fib_events"] == 2)

# 3. analytic features
ft = analytic.features(spec, {"mechanism": "cost", "cost_override": {lk: fab.cost[lk] * 20}}, {"x": ["interface e", "ip ospf cost 1", "exit"]})
check("analytic r_exact", abs(ft["r_exact"] - pred["r"]) < 1e-6)
check("fib entries changed > 0", ft["n_fib_entries_changed"] > 0, ft)
check("pml in [0,1]", 0 <= ft["pml_flow_frac"] <= 1, ft)
check("no-op change => zero features", analytic.features(spec, {"mechanism": "noop"}, {})["n_fib_entries_changed"] == 0)
g = {"a": ["b"], "b": ["a"]}
check("cycle detection", analytic._cycle_reachable(g, "a") and not analytic._cycle_reachable({"a": ["b"], "b": []}, "a"))
# 4. transiently UNDETERMINED flows: excluded from T1, counted in T1_upper (pre-registration §13)
undet = [dict(rec, nexthops=[("192.0.2.99", "eth9")]) for rec in drop]
ev4 = [(t0 + 0.1, mid, u_) for u_ in undet] + [(t0 + 0.4, mid, dict(rec, deleted=False)) for rec in drop] + events
m4 = targets.summarize(targets.series(gold, ev4, spec, t0, t0 + 20))
check("undetermined transient not in T1", m4["T1_disruption_area"] == 0.0, m4)
check("undetermined transient in T1_upper",
      m4["undetermined_peak"] > 0 and abs(m4["T1_upper_undetermined_as_broken"] - m4["undetermined_peak"] * 0.3) < 1e-9, m4)

# 5. amendment A3: kernel link-state semantics, flags, nexthop objects, monitor errors, windows, 10 ms merge
import json
AUD = HERE.parents[1] / "audit" / "2026-09-15-instrument-unit-checks"
p = fib.parse_lines(["10.6.0.0/24 via 10.9.1.2 dev w0 proto ospf metric 20 linkdown",
                     "10.7.0.0/24 proto ospf metric 20", "\tnexthop via 10.9.0.2 dev v0 weight 1 dead linkdown",
                     "\tnexthop via 10.9.1.2 dev w0 weight 1", "10.255.0.3 nhid 35 via 10.15.5.2 dev eth3 proto ospf metric 20"],
                    with_ts=False)
check("route flags parsed", p[0]["nh_flags"] == [["linkdown"]] and p[1]["nh_flags"] == [["dead", "linkdown"], []], p[:2])
check("nhid parsed", p[2]["nhid"] == "35" and p[2]["nexthops"] == [("10.15.5.2", "eth3")], p[2])
lk = fib.parse_link_lines(["[2026-09-15T09:12:23.008312] 3: v0@v1: <BROADCAST,MULTICAST> mtu 1500 state DOWN",
                           "    link/ether 3e:f7:f1:12:eb:8e brd ff:ff:ff:ff:ff:ff",
                           "[2026-09-15T09:12:23.009454] 2: v1@v0: <NO-CARRIER,BROADCAST,MULTICAST,UP,M-DOWN> mtu 1500"], with_ts=True)
check("link events parsed (admin down; carrier loss)", [(l["dev"], l["admin_up"], l["carrier"]) for l in lk]
      == [("v0", False, False), ("v1", True, False)], lk)
check("ip -o link parsed", fib.links_from("7: eth2@if8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9500 qdisc noqueue") == {"eth2": (True, True)})
nh = fib.parse_nexthop_lines(["[2026-09-15T09:00:00.100000] id 40 group 34/35 proto zebra", "[2026-09-15T09:00:00.200000] Deleted id 34 via 10.0.0.1 dev eth1 scope link proto zebra"], True)
check("nexthop objects parsed", nh[0]["members"] == ["34", "35"] and nh[1]["deleted"] and nh[1]["id"] == "34", nh)
check("route parser ignores link and nexthop lines", fib.parse_lines(["[2026-09-15T09:00:00.100000] id 40 group 34/35 proto zebra",
      "[2026-09-15T09:12:23.008312] 3: v0@v1: <BROADCAST,MULTICAST> mtu 1500"], True) == [])
t = fib.NexthopTable(fib.parse_nexthop_lines(["id 34 via 10.0.0.1 dev eth1 scope link proto zebra", "id 40 group 34/35 proto zebra"], False))
check("in-place replacement of a referenced nexthop object detected",
      t.apply({"deleted": False, "id": "34", "content": "via 10.0.0.9 dev eth2 scope link proto zebra", "members": []}, {"40"}) is not None)
check("deletion of an unreferenced nexthop object is not a problem",
      fib.NexthopTable(t.by_id.values()).apply({"deleted": True, "id": "99", "content": "", "members": []}, {"40"}) is None)
check("monitor error lines detected", fib.monitor_error_lines(["[2026-09-15T09:00:00.100000] 10.0.0.0/24 dev e", "  link/ether x",
                                                                 "netlink receive error No buffer space available (105)"]) ==
      ["netlink receive error No buffer space available (105)"])
st = fib.split_state("10.0.0.0/24 dev e1 proto kernel\n@@LINKS@@\n2: e1: <UP,LOWER_UP> mtu 1\n@@NEXTHOPS@@\nid 3 dev e1\n")
check("combined snapshot split", len(st["routes"]) == 1 and len(st["links"]) == 1 and len(st["nexthops"]) == 1, st)

# real kernel output (audit unit check): replay of the monitored link events reproduces what the kernel shows
sec, cur = {}, None
for line in (AUD / "kernel_flush_out.txt").read_text().splitlines():
    if line.startswith("== "):
        cur = line[3:].split(" (")[0].strip(); sec[cur] = []
    elif cur:
        sec[cur].append(line)
links_ev = fib.parse_link_lines(sec["MONITOR OUTPUT"], with_ts=True)
t_w1 = next(e["ts"] for e in links_ev if e["dev"] == "w1")
def kernel_view(route_lines, links):
    g = fib.RouterFib([], links)
    for r_ in fib.parse_lines(route_lines, with_ts=False): g.apply(r_)
    return g.to_flowmatrix()
rf = fib.RouterFib([])
for r_ in fib.parse_lines(sec["BEFORE"], with_ts=False): rf.apply(r_)
for e in links_ev:
    if e["ts"] < t_w1: rf.apply(e)
check("REAL kernel: admin-down replay == kernel FIB (flag-driven view, no link data)",
      rf.to_flowmatrix() == kernel_view(sec["AFTER admin down v0"], {}), (rf.to_flowmatrix(), kernel_view(sec["AFTER admin down v0"], {})))
check("REAL kernel: route via the downed device and its connected route are gone",
      "10.8.0.0/24" not in rf.to_flowmatrix() and "10.9.0.0/30" not in rf.to_flowmatrix())
for e in links_ev:
    if e["ts"] >= t_w1: rf.apply(e)
kv = kernel_view(sec["AFTER carrier loss on w0"], {})
check("REAL kernel: carrier-loss replay == kernel FIB; linkdown routes discard traffic",
      rf.to_flowmatrix() == kv and kv["10.6.0.0/24"][0]["nexthops"] == [{"blackhole": True}], (rf.to_flowmatrix(), kv))
check("REAL kernel: route monitor emitted no IPv4 route event for the silent flush",
      fib.parse_lines(sec["MONITOR OUTPUT"], with_ts=True) == [])

# multipath member flush and partial linkdown
mp = fib.RouterFib([], {})
for r_ in fib.parse_lines(["10.7.0.0/24 proto ospf metric 20", "\tnexthop via 10.9.0.2 dev v0 weight 1", "\tnexthop via 10.9.1.2 dev w0 weight 1"], False):
    mp.apply(r_)
mp.apply({"type": "link", "dev": "w0", "admin_up": True, "carrier": False, "deleted": False})
check("ECMP with one carrier-down member keeps only the usable member",
      mp.to_flowmatrix()["10.7.0.0/24"][0]["nexthops"] == [{"ip": "10.9.0.2", "interfaceName": "v0"}])
mp.apply({"type": "link", "dev": "v0", "admin_up": False, "carrier": False, "deleted": False})
check("ECMP: admin-down member flushed, remaining member carrier-down -> discards",
      mp.to_flowmatrix()["10.7.0.0/24"][0]["nexthops"] == [{"blackhole": True}] and len(mp.routes[("10.7.0.0/24", 20)]["nexthops"]) == 1)

# carrier loss: routes installed through a nexthop object are flushed; nexthop-less routes stay and discard
cl = fib.RouterFib([], {})
for r_ in fib.parse_lines(["10.8.0.0/24 nhid 16 via 10.9.1.2 dev w0 proto 196 metric 20",
                           "10.9.1.0/30 dev w0 proto kernel scope link src 10.9.1.1",
                           "10.6.0.0/24 via 10.9.1.2 dev w0 proto static metric 20"], False):
    cl.apply(r_)
cl.apply({"type": "link", "dev": "w0", "admin_up": True, "carrier": False, "deleted": False})
cv = cl.to_flowmatrix()
check("carrier loss: nexthop-object route flushed, legacy routes kept but discarding",
      "10.8.0.0/24" not in cv and cv["10.9.1.0/30"][0]["nexthops"] == [{"blackhole": True}]
      and cv["10.6.0.0/24"][0]["nexthops"] == [{"blackhole": True}], cv)
check("flush rule: admin down and carrier loss flush nexthop objects; carrier restore does not",
      fib.flushes_nexthop_objects((True, True), (False, False)) and fib.flushes_nexthop_objects((True, True), (True, False))
      and not fib.flushes_nexthop_objects((True, False), (True, True)))
import subprocess
rr = subprocess.run([sys.executable, str(AUD / "a3_frr_replay.py"), str(AUD / "a3_frr_out.txt")], capture_output=True, text=True)
check("REAL FRR 8.4.1 (ECMP group, blackhole, shutdown, carrier loss): production replay == every poll and final FIB",
      rr.returncode == 0 and "A3 INSTRUMENT CHECK: PASS" in rr.stdout, rr.stdout[-1500:] + rr.stderr[-500:])

# shutdown transient on the synthetic ring: admin-down of the victim's device flushes its routes until re-install
xdev = [(t0 + 0.1, mid, {"type": "link", "dev": "x", "admin_up": False, "carrier": False, "deleted": False}),
        (t0 + 0.4, mid, {"type": "link", "dev": "x", "admin_up": True, "carrier": True, "deleted": False})]
xdev += [(t0 + 0.4, mid, dict(rec, deleted=False)) for rec in gold[mid] if rec["proto"] == "ospf"]
m5 = targets.summarize(targets.series(gold, xdev + events, spec, t0, t0 + 20))
check("link-down flush => transient broken flows (T1 > 0) ending at re-install", m5["T1_disruption_area"] > 0
      and abs(m5["T3_disruption_duration"] - 0.4) < 1e-6, m5)
cdev = [(t0 + 0.1, mid, {"type": "link", "dev": "x", "admin_up": True, "carrier": False, "deleted": False}),
        (t0 + 0.4, mid, {"type": "link", "dev": "x", "admin_up": True, "carrier": True, "deleted": False})]
m6 = targets.summarize(targets.series(gold, cdev + events, spec, t0, t0 + 20))
check("carrier loss (routes kept, not forwarding) => T1 > 0 without any route event", m6["T1_disruption_area"] > 0, m6)
check("no link data => identical to the pre-A3 computation", targets.summarize(targets.series(gold, ev2, spec, t0, t0 + 20, {}))
      == targets.summarize(targets.series(gold, ev2, spec, t0, t0 + 20)))
late = events + [(t0 + 25, mid, dict(drop[0], deleted=True))]
check("event after the observation window counted", targets.series(gold, late, spec, t0, t0 + 20)["post_window_fib_events"] == 1)
fast = [(t0 + 0.101, mid, dict(rec, deleted=True)) for rec in drop] + [(t0 + 0.104, mid, dict(rec, deleted=False)) for rec in drop] + events
check("3 ms transient: T1 > 0, removed by the 10 ms merge", targets.summarize(targets.series(gold, fast, spec, t0, t0 + 20))["T1_disruption_area"] > 0
      and targets.summarize(targets.series(gold, fast, spec, t0, t0 + 20, bin_s=0.01))["T1_disruption_area"] == 0.0)

# 6. mechanism is a function of the configuration diff (no generation provenance in X)
man = json.loads((HERE.parents[1] / "manifests" / "pilot_manifest.json").read_text())
def mechanism_from_diff(c):
    cmds = [x for v in c["push_plan"].values() for x in v]
    if any("blackhole" in x for x in cmds): return "blackhole"
    if "shutdown" in cmds: return "shutdown"
    n = sum(1 for x in cmds if x.startswith("ip ospf cost"))
    return {1: "noop", 2: "cost"}.get(n, "drain" if n >= 4 else "?")
bad = [(c["change_id"], c["mechanism"], mechanism_from_diff(c)) for c in man["changes"] if mechanism_from_diff(c) != c["mechanism"]]
check(f"manifest mechanism == mechanism derived from the configuration diff (all {len(man['changes'])} changes, "
      "including A4-retired controls)", not bad and len(man["changes"]) == 36, bad)
check("feature columns contain no identifier/role/order/telemetry", not any(
    w in c for c in analytic.FEATURE_COLUMNS for w in ("id", "role", "order", "topology", "seed", "T1", "wall", "conv")))

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
