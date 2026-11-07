"""Offline tests of the execution freeze (v4lib/freeze.py) on a SYNTHETIC repository in a temp dir, plus the real
repository's refusal state. No lab, no pilot.
    ./.venv/Scripts/python.exe v4_transient/tests/test_freeze.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
REPO = V4.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(V4))

from v4lib import freeze as FREEZE                                   # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


def make_repo(root: Path, open_issues=()):
    v4 = root / FREEZE.V4_DIR
    for rel in ["v4lib/__init__.py", "v4lib/fib.py"] + list(FREEZE.V4_FIXED_FILES):
        p = v4 / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"content of {rel}\n", encoding="utf-8")
    (v4 / FREEZE.BLOCKING_REL).write_text(json.dumps({"open": list(open_issues), "resolved": []}), encoding="utf-8")
    for rel in FREEZE.REQUIRED_NRL + ("nrl/severity.py",):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"nrl {rel}\n", encoding="utf-8")
    art = v4 / "pilot" / "artifacts" / "golden-x" / "artifact"
    art.mkdir(parents=True, exist_ok=True)
    (art / "frr.conf").write_text("router ospf\n", encoding="utf-8")
    return v4


def freeze(root: Path, nrl=None):
    doc = FREEZE.build(root, list(nrl if nrl is not None else FREEZE.REQUIRED_NRL + ("nrl/severity.py",)),
                       "0123456789abcdef", "test", "1970-01-01T00:00:00Z")
    (root / FREEZE.V4_DIR / FREEZE.FREEZE_REL).write_text(json.dumps(doc), encoding="utf-8")
    return doc


with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    v4 = make_repo(root)
    ok, why = FREEZE.verify(root)
    check("no freeze file -> refused", not ok and "missing" in why, why)
    doc = freeze(root)
    ok, why = FREEZE.verify(root)
    check("complete freeze of an unchanged tree verifies", ok, why)
    check("freeze covers V4 code, config, manifests and nrl dependencies",
          {"v4_transient/pilot/run_pilot.py", "v4_transient/config/pilot_decisions.json",
           "v4_transient/manifests/run_plan_pilot.json", "nrl/clab.py", "nrl/severity.py"} <= set(doc["files"]))

    for rel in ("v4_transient/v4lib/fib.py", "v4_transient/pilot/run_pilot.py", "v4_transient/analysis/analyze_pilot.py",
                "v4_transient/manifests/run_plan_pilot.json", "v4_transient/config/pilot_decisions.json", "nrl/severity.py"):
        p = root / rel
        orig = p.read_bytes()
        p.write_bytes(orig + b"# edit\n")
        ok, why = FREEZE.verify(root)
        check(f"edit of {rel} after freeze -> refused", not ok and rel in why, why)
        p.write_bytes(orig)
    check("restored tree verifies again", FREEZE.verify(root)[0])

    extra = v4 / "v4lib" / "sneaky.py"
    extra.write_text("x = 1\n", encoding="utf-8")
    ok, why = FREEZE.verify(root)
    check("new v4lib module added after freeze -> refused", not ok and "sneaky.py" in why, why)
    extra.unlink()

    a = v4 / "pilot" / "artifacts" / "golden-x" / "artifact" / "frr.conf"
    a.write_text("router ospf\n passive-interface eth1\n", encoding="utf-8")
    check("artifact changed after freeze -> refused", "artifacts" in FREEZE.verify(root)[1])
    check("artifact check can be skipped only explicitly", FREEZE.verify(root, check_artifacts=False)[0])
    a.write_text("router ospf\n", encoding="utf-8")
    (a.parent / "new.conf").write_text("x\n", encoding="utf-8")
    check("artifact file added after freeze -> refused", "artifacts" in FREEZE.verify(root)[1])
    (a.parent / "new.conf").unlink()

    # platform independence: the digest orders files by relative POSIX path string (case-sensitive), not Path objects
    import hashlib                                                   # noqa: E402
    for name in ("B.conf", "a.conf", "Z/x.txt", "b/y.txt"):
        q = v4 / "pilot" / "artifacts" / name
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text(name + "\n", encoding="utf-8")
    base = v4 / "pilot" / "artifacts"
    rels = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
    h = hashlib.sha256()
    for rel in rels:
        h.update(f"{rel}\t{hashlib.sha256((base / rel).read_bytes()).hexdigest()}\n".encode())
    check("artifact digest uses case-sensitive string order (same digest on Windows and POSIX)",
          FREEZE.artifact_digest(v4) == (h.hexdigest(), len(rels)), (FREEZE.artifact_digest(v4), h.hexdigest()))
    for name in ("B.conf", "a.conf", "Z/x.txt", "b/y.txt"):
        (base / name).unlink()
    (base / "Z").rmdir(); (base / "b").rmdir()

    freeze(root, nrl=["nrl/severity.py"])
    ok, why = FREEZE.verify(root)
    check("freeze omitting a required nrl module -> refused", not ok and "not covered" in why, why)
    doc = freeze(root)
    for mut, needle in ((lambda d: d.update(git_commit=""), "Git"), (lambda d: d.update(status="DRAFT"), "status"),
                        (lambda d: d.update(files={}), "no files")):
        d = json.loads(json.dumps(doc)); mut(d)
        (v4 / FREEZE.FREEZE_REL).write_text(json.dumps(d), encoding="utf-8")
        ok, why = FREEZE.verify(root)
        check(f"malformed freeze ({needle}) -> refused", not ok and needle in why, why)
    freeze(root)

    (v4 / FREEZE.BLOCKING_REL).write_text(json.dumps({"open": [{"id": "B9-test"}]}), encoding="utf-8")
    ok, why = FREEZE.verify(root)
    check("open launch-audit issue -> refused even with an otherwise valid freeze", not ok and "B9-test" in why, why)
    (v4 / FREEZE.BLOCKING_REL).unlink()
    check("missing launch-audit register -> refused", "missing" in FREEZE.verify(root)[1])

# real repository ------------------------------------------------------------------------------------------------
reg = json.loads((V4 / FREEZE.BLOCKING_REL).read_text(encoding="utf-8"))
issues = FREEZE.open_blocking_issues(V4)
check("REAL repository: launch-audit register is well-formed", isinstance(issues, list) and isinstance(reg.get("resolved"), list))
b1 = [i for i in issues + reg["resolved"] if str(i.get("id", "")).startswith("B1-")]
check("REAL repository: issue B1 is recorded (open, or resolved with amendment and evidence references)",
      len(b1) == 1 and (b1[0] in issues or (b1[0].get("resolution") and b1[0].get("resolution_evidence"))), b1)
ok, why = FREEZE.verify(REPO)
print("   real freeze verification:", ok, why)
if issues:
    check("REAL repository: open blocking issue -> execution freeze refuses", not ok and "blocking" in why, why)
    import importlib.util                                            # noqa: E402
    import contextlib                                                # noqa: E402
    import io                                                        # noqa: E402
    before = (V4 / FREEZE.FREEZE_REL).read_bytes() if (V4 / FREEZE.FREEZE_REL).exists() else None
    spec = importlib.util.spec_from_file_location("write_pilot_freeze", V4 / "tools" / "write_pilot_freeze.py")
    wpf = importlib.util.module_from_spec(spec); spec.loader.exec_module(wpf)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = wpf.main()
    after = (V4 / FREEZE.FREEZE_REL).read_bytes() if (V4 / FREEZE.FREEZE_REL).exists() else None
    check("REAL repository: write_pilot_freeze refuses and writes nothing", rc == 2 and "REFUSED" in buf.getvalue()
          and before == after, buf.getvalue())
else:
    exists = (V4 / FREEZE.FREEZE_REL).exists()
    check("REAL repository: no open issue -> freeze verification passes iff the freeze file exists and matches",
          ok == exists or (exists and not ok and "changed" in why), why)
    if exists:
        check("REAL repository: execution freeze verifies against the tree on disk", ok, why)

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
