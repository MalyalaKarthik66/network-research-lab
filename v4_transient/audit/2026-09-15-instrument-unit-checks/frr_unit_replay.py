"""Feed the FRR unit-check output through the production v4lib.fib parser/replay, exactly as extract_runs does."""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\karth\network-research-lab\v4_transient")
from v4lib.fib import RouterFib, parse_lines  # noqa: E402

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
sec, cur = {}, None
for line in text.splitlines():
    if line.startswith("== "):
        cur = line[3:].strip()
        sec[cur] = []
    elif cur:
        sec[cur].append(line)
t_before = float(sec["T_BEFORE"][0])


def fib(lines):
    f = RouterFib()
    for r in parse_lines(lines, with_ts=False):
        f.apply(r)
    return f


def replay(upto_last_ts=None):
    f = fib(sec["SNAP0"])
    evs = [e for e in parse_lines(sec["MONITOR"], with_ts=True) if e["ts"] >= t_before]
    for e in sorted(evs, key=lambda e: e["ts"]):
        f.apply(e)
    return f, evs


def show(label, d):
    print(label)
    for p, es in sorted(d.items()):
        for e in es:
            print("   ", p, e["protocol"], e["nexthops"], "selected" if e["selected"] else "")


rep, evs = replay()
print("parsed monitor events:", len(evs))
for e in evs:
    print("   ", e["deleted"] and "DEL" or "ADD", e["kind"], e["dst"], e["nexthops"], e["proto"])
snap1 = fib(sec["SNAP1_AFTER_BLACKHOLE"]).to_flowmatrix()
snap2 = fib(sec["SNAP2_AFTER_SHUTDOWN"]).to_flowmatrix()
show("SNAPSHOT after blackhole, as the walker sees it:", {k: v for k, v in snap1.items() if k.startswith("10.255")})
final = rep.to_flowmatrix()
print("replayed final == final snapshot:", final == snap2)
for p in sorted(set(final) | set(snap2)):
    if final.get(p) != snap2.get(p):
        print("   MISMATCH", p, "replay:", final.get(p), "| snapshot:", snap2.get(p))
