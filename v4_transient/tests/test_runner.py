"""Offline tests of the runner's refusal logic: Batfish gate, D1-D9 pilot approval gate, INCOMPLETE attempt detection.
No lab is touched and no pilot run can start (every approval used here lives in a temporary directory).
    ./.venv/Scripts/python.exe v4_transient/tests/test_runner.py
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4)); sys.path.insert(0, str(HERE.parent))
spec = importlib.util.spec_from_file_location("run_pilot", V4 / "pilot" / "run_pilot.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

from v4lib import decisions as DEC                                   # noqa: E402
from _fixtures import fixture_decisions                              # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


# ---- Batfish gate ---------------------------------------------------------------------------------------------
pop = {"change_id": "X1", "kind": "population"}
pos = {"change_id": "X2", "kind": "control_positive"}
ok_bfc = {"verdict": "OK", "changes": {"X1": {"spec_pass": True, "r_match": True},
                                       "X2": {"spec_pass": False, "r_match": True}}}
check("population PASS allowed", rp.batfish_gate(ok_bfc, pop)[0])
check("positive control FAIL allowed", rp.batfish_gate(ok_bfc, pos)[0])
bad = json.loads(json.dumps(ok_bfc)); bad["changes"]["X1"]["spec_pass"] = False
check("population SPEC FAIL refused", not rp.batfish_gate(bad, pop)[0])
bad2 = json.loads(json.dumps(ok_bfc)); bad2["changes"]["X2"]["spec_pass"] = True
check("positive control SPEC PASS refused", not rp.batfish_gate(bad2, pos)[0])
check("non-OK Batfish verdict refused", not rp.batfish_gate({**ok_bfc, "verdict": "PROBLEMS"}, pop)[0])
check("missing Batfish record refused", not rp.batfish_gate(ok_bfc, {"change_id": "X9", "kind": "population"})[0])
bad3 = json.loads(json.dumps(ok_bfc)); bad3["changes"]["X1"]["r_match"] = False
check("Batfish r mismatch refused", not rp.batfish_gate(bad3, pop)[0])
real_bfc = json.loads((V4 / "manifests" / "batfish_check.json").read_text())
man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
allowed = [rp.batfish_gate(real_bfc, c)[0] for c in man["changes"]]
check("real Batfish check admits all 36 manifest changes (34 + 2 A4 replacement controls; retired controls still "
      "SPEC-FAIL)", all(allowed) and len(allowed) == 36, sum(allowed))
retired = {"change_id": "X3", "kind": "control_positive_retired"}
check("A4-retired positive control must still be SPEC-FAIL",
      rp.batfish_gate({"verdict": "OK", "changes": {"X3": {"spec_pass": False, "r_match": True}}}, retired)[0]
      and not rp.batfish_gate({"verdict": "OK", "changes": {"X3": {"spec_pass": True, "r_match": True}}}, retired)[0])

# ---- D1-D9 approval gate (synthetic repository in a temp dir) ---------------------------------------------------
LEGEND = f"# pre-registration\n## 0. Status labels\n| **{DEC.UNFROZEN_MARKER}** | legend only |\n"
DECIDED = LEGEND + "## 6. Noise floor — decided\ntext\n## 12. Exclusions\ntext\n"


def make_repo(td: Path, doc, prereg_text=DECIDED, approval_over=None, write_decisions=True):
    (td / "docs").mkdir(parents=True, exist_ok=True)
    (td / "config").mkdir(parents=True, exist_ok=True)
    (td / "manifests").mkdir(parents=True, exist_ok=True)
    pre = td / "docs" / "PILOT-PREREGISTRATION.md"
    pre.write_text(prereg_text, encoding="utf-8")
    dfile = td / "config" / "pilot_decisions.json"
    if write_decisions:
        dfile.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    appr = {"approved": True, "approved_by": "test", "approved_utc": "1970-01-01T00:00:00Z",
            "prereg_file": DEC.PREREG_REL, "prereg_sha256": hashlib.sha256(pre.read_bytes()).hexdigest(),
            "decisions_file": DEC.DECISIONS_REL,
            "decisions_sha256": hashlib.sha256(dfile.read_bytes()).hexdigest() if dfile.exists() else "0" * 64}
    appr.update(approval_over or {})
    a = td / "manifests" / "PREREG-APPROVAL.json"
    a.write_text(json.dumps(appr), encoding="utf-8")
    return pre, a


def approval(td, pre, a):
    return rp.pilot_approval(pre, a, v4_root=td)


with tempfile.TemporaryDirectory() as t:
    td = Path(t) / "v4"
    pre, a = make_repo(td, fixture_decisions())
    ok, why = approval(td, pre, a)
    check("synthetic repo with a complete, approved decisions document is admitted", ok, why)

    for key in DEC.DECISION_KEYS:
        doc = fixture_decisions(); del doc["decisions"][key]
        pre, a = make_repo(td, doc)
        ok, why = approval(td, pre, a)
        check(f"runner BLOCKED when {key} is absent", not ok and key in why, why)

        doc = fixture_decisions(); doc["decisions"][key]["status"] = DEC.UNFROZEN_MARKER
        pre, a = make_repo(td, doc)
        ok, why = approval(td, pre, a)
        check(f"runner BLOCKED when {key} is marked UNFROZEN", not ok and key in why, why)

        doc = fixture_decisions()
        first = next(f for f, fs in DEC.SPEC[key]["fields"].items() if not fs.get("required_if"))
        doc["decisions"][key][first] = None
        pre, a = make_repo(td, doc)
        ok, why = approval(td, pre, a)
        check(f"runner BLOCKED when {key}.{first} has no value", not ok and f"{key}.{first}" in why, why)

    pre, a = make_repo(td, DEC.template())
    check("runner BLOCKED with the blank template as decisions", not approval(td, pre, a)[0])
    pre, a = make_repo(td, fixture_decisions(), write_decisions=False)
    (td / "config" / "pilot_decisions.json").unlink(missing_ok=True)
    check("runner BLOCKED when the decisions file is missing", "missing" in approval(td, pre, a)[1])
    pre, a = make_repo(td, fixture_decisions())
    doc = fixture_decisions(); doc["decisions"]["D6_G5_cost"]["kill_if_median_wall_s_above"] = 151.0
    (td / "config" / "pilot_decisions.json").write_text(json.dumps(doc), encoding="utf-8")
    check("runner BLOCKED when decisions change after approval", "decisions_sha256" in approval(td, pre, a)[1])
    pre, a = make_repo(td, fixture_decisions(), prereg_text=DECIDED + f"## 9. G4 — {DEC.UNFROZEN_MARKER}\n")
    check("runner BLOCKED while a pre-registration section heading is UNFROZEN", "UNFROZEN" in approval(td, pre, a)[1])
    pre, a = make_repo(td, fixture_decisions(), prereg_text=DECIDED + f"## 12. more\n- guard — {DEC.UNFROZEN_MARKER}.\n")
    check("runner BLOCKED while an inline UNFROZEN marker remains outside §0", "UNFROZEN" in approval(td, pre, a)[1])
    pre, a = make_repo(td, fixture_decisions())
    pre.write_text(DECIDED + "edited\n", encoding="utf-8")
    check("runner BLOCKED when the pre-registration changes after approval", "prereg_sha256" in approval(td, pre, a)[1])
    for over, needle in (({"approved": False}, "approved"), ({"approved_by": ""}, "approved_by"),
                         ({"decisions_file": None}, "decisions_file"), ({"decisions_file": "../outside.json"}, "inside")):
        pre, a = make_repo(td, fixture_decisions(), approval_over=over)
        ok, why = approval(td, pre, a)
        check(f"runner BLOCKED on approval {over}", not ok and needle in why, why)
    (td / "manifests" / "PREREG-APPROVAL.json").unlink()
    check("runner BLOCKED without an approval file", "missing" in approval(td, pre, a)[1])

    out = Path(t) / "results"
    (out / "raw" / "R1" / "attempt1").mkdir(parents=True)
    (out / "raw" / "R1" / "attempt2").mkdir(parents=True)
    (out / "raw" / "R1" / "attempt2" / "run.json").write_text(json.dumps({"status": "OK"}))
    at = rp.attempts(out, "R1")
    check("attempt without run.json is INCOMPLETE", at[0]["status"] == "INCOMPLETE" and at[1]["status"] == "OK", at)
    check("INCOMPLETE is retryable", "INCOMPLETE" in rp.RETRYABLE and rp.retryable(at[0]))
    (out / "raw" / "R3" / "attempt1").mkdir(parents=True)
    (out / "raw" / "R3" / "attempt1" / "change_applied.json").write_text("{}")
    at3 = rp.attempts(out, "R3")
    check("attempt that died after the change was applied is INCOMPLETE_AFTER_CHANGE and NOT retried",
          at3[0]["status"] == "INCOMPLETE_AFTER_CHANGE" and not rp.retryable(at3[0]), at3)

# ---- retry rule (§12, amendment A3) -------------------------------------------------------------------------------
for st in ("STAGING_FAILED", "DEPLOY_FAILED", "CONTAINERS_MISSING", "NO_CONVERGENCE", "LAB_INVALID", "ERROR"):
    check(f"{st} before the change is retried", rp.retryable({"status": st}))
for st in ("ERROR", "PUSH_FAILED"):
    check(f"{st} after the change was applied is NOT retried", not rp.retryable({"status": st, "change_applied": True}))
for st in ("OK", "NOT_SETTLED", "POST_CONFIG_MISMATCH"):
    check(f"{st} is never retried", not rp.retryable({"status": st}))
src = (V4 / "pilot" / "run_pilot.py").read_text(encoding="utf-8")
check("runner marks change_applied before the push", src.index('rec["change_applied"] = True') < src.index("L.push_change("))

# ---- the real repository ----------------------------------------------------------------------------------------
ok, why = rp.pilot_approval()
check("REAL repository: D1-D9 approval layer passes (approval only; not launch readiness)", ok, why)
ok, why = rp.pilot_preflight()
from v4lib import freeze as FREEZE                                   # noqa: E402
ready = FREEZE.open_blocking_issues(V4) == [] and (V4 / FREEZE.FREEZE_REL).exists()
check("REAL repository: full pilot preflight passes only with an empty launch-audit register AND a verified freeze",
      ok == (ready and FREEZE.verify(V4.parent)[0]), (ok, why))
print("   real preflight:", ok, why)

# ---- host cleanliness guard (fake docker listing; nothing is executed) ------------------------------------------
seen = []


def fake(stdout="", status="OK"):
    def run(argv, timeout=30):
        seen.append(argv)
        return {"status": status, "stdout": stdout, "stderr": "docker unavailable" if status != "OK" else ""}
    return run


check("host_clean passes when no containerlab container exists", rp.host_clean(fake(""))[0])
check("host_clean lists running AND stopped containers by the containerlab label",
      seen and seen[-1][:3] == ["docker", "ps", "-a"] and "label=containerlab" in seen[-1], seen[-1:])
ok, why = rp.host_clean(fake("clab-nrlv4-t05-corea\nclab-nrlv4-t05-wan1\n"))
check("host_clean refuses when a leftover lab exists", not ok and "clab-nrlv4-t05-corea" in why, why)
check("host_clean refuses when docker cannot be queried", not rp.host_clean(fake(status="ERROR"))[0])
# NEVER pass the correct confirmation token here: that would start the real 100-run pilot.
for extra, label in (([], "without --confirm-pilot"), (["--confirm-pilot", "yes"], "with a wrong confirmation token"),
                     (["--confirm-pilot", rp.PILOT_CONFIRM_TOKEN.lower()], "with a lower-cased token")):
    argv, sys.argv = sys.argv, ["run_pilot.py", "--plan", "pilot"] + extra
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = rp.main()
    finally:
        sys.argv = argv
    check(f"REAL repository: `run_pilot.py --plan pilot` {label} returns 2 before touching any lab",
          rc == 2 and "explicit start confirmation missing" in buf.getvalue(), buf.getvalue())
check("REAL repository: refusals created no pilot results", not (V4 / "results" / "pilot").exists())
check("the confirmation token is not a default argument", rp.PILOT_CONFIRM_TOKEN == "START-20x5-PILOT")
print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
