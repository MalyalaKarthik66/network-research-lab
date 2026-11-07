"""Amendment A4 regression tests (positive-control selection). Offline and read-only.
    ./.venv/Scripts/python.exe v4_transient/tests/test_controls_a4.py

Proves: the frozen rule's picks on t05/t15 are cut edges (T1 = 0 by construction, confirmed on the preserved smoke-2
evidence); the A4 rule uses only the frozen topology/analytic model, is deterministic, and gives the selections stated in
docs/V4-LAUNCH-AUDIT-2.md before implementation; everything else in the design is byte-identical to the pre-A4 commit
(digests taken from Git commit d2c0cf0); Batfish confirms the replacements are SPEC-FAIL with r_match.
"""
import hashlib
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
REPO = V4.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(V4)); sys.path.insert(0, str(V4 / "analysis"))

from nrl import topologies_v3 as T3                                  # noqa: E402
from nrl.severity import Fabric                                      # noqa: E402

spec_ = importlib.util.spec_from_file_location("build_pilot", V4 / "pilot" / "build_pilot.py")
bp = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(bp)
import extract_runs as X                                             # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


def H(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True).encode()).hexdigest()


# digests of the pre-A4 design, computed from Git commit d2c0cf0 before any A4 edit
PRE_A4 = {"pop_noop_entries": "7387b0b97b0a1cad2408f5235a53273e5e7d36441afd0b59ca183a5e877ea704",
          "positive_entries": "067c6855c688fef428fb1527343b0b9dceff2507c4d645745c8427c81ff74ebe",
          "non_positive_run_order": "1eb48aaef969c72e23417a9bf14a1f0b924ca2d9e9c6d29b262b6eaf8daf45fd",
          "positive_run_orders": {"V4P-04": 39, "V4P-02": 45, "V4P-01": 88, "V4P-03": 109},
          "retired_lock_entries": "237f0f144ddf9422dcf39e85c46fca2ac1ecaadd52eb6c1cda4f15884900d232",
          "lock_entries_all": "d84a96295565e645942ceef95c6d99a075ddb76aa5042604a104f223c0905f17",
          "batfish_34_verdicts": "df28fb5a40ff863ad2c525cc6e4954e9a769415d1579fef80b8f80a39561bc5a"}
STATED_BEFORE_IMPLEMENTATION = {"t05_ring6": ("corea", "wan1"), "t13_bowtie7": ("b1", "mid"),
                                "t14_ladder8": ("l2", "l3"), "t15_campus12": ("coreb", "distb1")}

man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
changes = {c["change_id"]: c for c in man["changes"]}
lock = json.loads((V4 / "manifests" / "artifact_lock.json").read_text())
plan = json.loads((V4 / "manifests" / "run_plan_pilot.json").read_text())["runs"]

# ---- 1. the rule and the structural argument, per topology -------------------------------------------------------
for t in bp.TOPOLOGIES:
    spec = T3.resolve(t)
    fab = Fabric(spec)
    bet = fab.link_betweenness()
    frozen = max(sorted(bet), key=lambda k: bet[k])
    a4 = bp.positive_control_link(fab)
    check(f"{t}: A4 selection deterministic (repeat and fresh model agree)",
          a4 == bp.positive_control_link(fab) == bp.positive_control_link(Fabric(T3.resolve(t))))
    check(f"{t}: A4 selection {a4} equals the one stated before implementation", a4 == STATED_BEFORE_IMPLEMENTATION[t])
    after = fab.predict(removed=[a4])
    check(f"{t}: A4 control keeps every carried flow deliverable and reroutes some (transient loss possible)",
          after["r_broken"] == 0 and after["r_rerouted"] > 0, after)
    ties = [k for k in sorted(bet) if bet[k] == bet[a4] and fab.predict(removed=[k])["r_broken"] == 0]
    check(f"{t}: tie-break is the first maximum in sorted link order ({ties})", ties[0] == a4)
    pos = [c for c in man["changes"] if c["kind"] == "control_positive" and c["topology"] == t]
    ret = [c for c in man["changes"] if c["kind"] == "control_positive_retired" and c["topology"] == t]
    check(f"{t}: exactly one pilot positive control, targeting the A4 link", len(pos) == 1 and tuple(pos[0]["target"]) == a4)
    if frozen != a4:
        gold = fab.golden
        new = fab.paths(removed=[frozen])
        broken = {k for k, p in gold.items() if p is not None and new.get(k) is None}
        moved = {k for k, p in gold.items() if p is not None and new.get(k) != p}
        cut = fab.predict(removed=[frozen])
        check(f"{t}: frozen pick {frozen} is a cut edge: every flow whose path changes is broken permanently "
              f"(r_broken {cut['r_broken']}, r_rerouted {cut['r_rerouted']})",
              cut["r_rerouted"] == 0 and cut["r_broken"] > 0 and broken == moved and broken)
        check(f"{t}: frozen control kept as retired, with replacement link", len(ret) == 1 and tuple(ret[0]["target"]) == frozen
              and ret[0]["replaced_by"] == pos[0]["change_id"] and pos[0].get("replaces") == ret[0]["change_id"]
              and pos[0].get("amendment") == "A4" and ret[0].get("retired_by") == "A4")
    else:
        check(f"{t}: frozen pick is not a cut edge, control unchanged and not retired",
              not ret and "amendment" not in pos[0] and fab.predict(removed=[frozen])["r_broken"] == 0)

src = inspect.getsource(bp.positive_control_link)
body = src.split('"""', 2)[2]
check("A4 rule body reads no file, result, smoke value, Batfish output or target",
      not any(w in body for w in ("open(", "read_text", "json", "results", "smoke", "T1", "batfish", "Session")), body)

# ---- 2. everything else is the pre-A4 design ------------------------------------------------------------------------
check("population and no-op entries byte-identical to pre-A4",
      H([c for c in man["changes"] if c["kind"] in ("population", "control_noop")]) == PRE_A4["pop_noop_entries"])
restored = []
for c in man["changes"]:
    if c["kind"] == "control_positive" and "amendment" not in c:
        restored.append(c)
    elif c["kind"] == "control_positive_retired":
        restored.append({k: (("control_positive") if k == "kind" else v) for k, v in c.items()
                         if k not in ("retired_by", "replaced_by", "retired_reason")})
check("retired entries = the pre-A4 controls, unchanged except kind and the three retirement fields",
      H(restored) == PRE_A4["positive_entries"])
check("pilot run plan: 114 runs, no retired control", len(plan) == 114
      and not any(changes[r["change_id"]]["kind"] == "control_positive_retired" for r in plan))
check("pilot run plan: order of every non-positive run identical to pre-A4",
      H(sorted((r["order"], r["run_id"]) for r in plan if not r["change_id"].startswith("V4P-"))) == PRE_A4["non_positive_run_order"])
orders = {r["change_id"]: r["order"] for r in plan if r["change_id"].startswith("V4P-")}
check("pilot run plan: each replacement takes its retired control's slot, unchanged controls keep theirs",
      orders == {"V4P-02": 45, "V4P-03": 109, "V4P-05": PRE_A4["positive_run_orders"]["V4P-01"],
                 "V4P-06": PRE_A4["positive_run_orders"]["V4P-04"]}, orders)
check("artifact lock: every pre-A4 entry unchanged (only V4P-05/V4P-06 added)",
      H({k: v for k, v in lock["sha256"].items() if not k.startswith(("V4P-05/", "V4P-06/"))}) == PRE_A4["lock_entries_all"])
check("artifact lock: retired controls' artifacts unchanged",
      H({k: v for k, v in lock["sha256"].items() if k.startswith(("V4P-01/", "V4P-04/"))}) == PRE_A4["retired_lock_entries"])
check("artifact lock digest recorded in the manifest", lock["digest"] == man["artifact_lock_digest"] == H(lock["sha256"]))

# ---- 3. Batfish ---------------------------------------------------------------------------------------------------
bfc = json.loads((V4 / "manifests" / "batfish_check.json").read_text())
keep = ("spec_pass", "verdicts", "r_batfish", "r_exact", "r_match", "undetermined_flows")
check("Batfish check verdict OK over all 36 manifest changes", bfc.get("verdict") == "OK" and set(bfc["changes"]) == set(changes))
check("Batfish: the 34 pre-A4 verdicts reproduce exactly",
      H({k: {x: v[x] for x in keep} for k, v in bfc["changes"].items() if k not in ("V4P-05", "V4P-06")}) == PRE_A4["batfish_34_verdicts"])
for cid in ("V4P-05", "V4P-06"):
    r = bfc["changes"].get(cid, {})
    check(f"Batfish: {cid} is SPEC-FAIL (P08), with Batfish r equal to r_exact",
          r.get("spec_pass") is False and r.get("verdicts", {}).get("P08") == "FAIL" and r.get("r_match") is True, r)

# ---- 4. the preserved smoke-2 evidence of the retired controls -----------------------------------------------------
diff = subprocess.run(["git", "diff", "--quiet", "d2c0cf0", "--", "v4_transient/results/smoke2"], cwd=REPO)
check("results/smoke2 identical to the pre-A4 commit (evidence not overwritten)", diff.returncode == 0)
for cid in ("V4P-01", "V4P-04"):
    ad = V4 / "results" / "smoke2" / "raw" / f"SMOKE2-{cid}.rep1" / "attempt1"
    rec = json.loads((ad / "run.json").read_text())
    s, m, diag = X.extract(ad, rec, changes[cid])
    peak = max(r["broken_total"] for r in s["rows"])
    check(f"smoke 2 {cid}: valid, T1 = 0 and peak broken_total {peak:.6f} = r_broken_exact "
          f"(disruption seen, all of it steady-state)",
          all(X.validity_checks(s, m, diag, rec, changes[cid]).values()) and m["T1_disruption_area"] == 0
          and abs(peak - changes[cid]["features"]["r_broken_exact"]) < 1e-6)

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
