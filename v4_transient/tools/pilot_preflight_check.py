"""WSL-side launch preflight for the exact pilot command. STARTS NOTHING.

    # on Windows, immediately before (same checkout; `git status` from WSL over /mnt/c takes > 10 min):
    git rev-parse HEAD + git status --porcelain --untracked-files=no  ->  {"head": ..., "porcelain": ...} JSON file
    wsl -d clab -- bash -lc "cd /mnt/c/Users/karth/network-research-lab && ./.venv-wsl/bin/python v4_transient/tools/pilot_preflight_check.py --windows-git-status /mnt/c/.../wingit_status.json"

Re-checks, in the environment the pilot command uses, everything
    ./.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan pilot --resume --confirm-pilot START-20x5-PILOT
verifies before its first lab (approval, execution freeze, artifact digest, empty launch-audit register, manifest/lock
digest, Batfish gate for every planned run, clean host), plus the facts the audit needs (Git state, containerlab,
Docker, images, Batfish service, Python environment, no pilot state, smoke-3 validation, runner refusal without the
token). run_pilot.main() is only ever invoked WITHOUT the token, in a subprocess, to prove it refuses.
Writes logs/preflight_<UTC>.json.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
REPO = V4.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(V4))

spec_ = importlib.util.spec_from_file_location("run_pilot", V4 / "pilot" / "run_pilot.py")
rp = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(rp)
from v4lib import freeze as FREEZE                                   # noqa: E402

EXACT_TOKEN = "START-20x5-PILOT"
results = []
_ap = argparse.ArgumentParser()
_ap.add_argument("--windows-git-status", default=None,
                 help="JSON {head, porcelain} from Windows-native git on this checkout, taken just before this run")
ARGS = _ap.parse_args()


def check(name, cond, detail=None):
    results.append({"check": name, "pass": bool(cond), "detail": detail})
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail not in (None, "") else ""))


def sh(argv, cwd=REPO, timeout=60):
    """(rc, stdout, stderr). A timeout (rc 124) or a failure to execute (rc 126) is recorded as a failed check, never a
    crash, so every later launch check still runs."""
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s: {' '.join(argv)}"
    except OSError as exc:
        return 126, "", f"cannot execute {argv[0]}: {exc!r}"
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


# ---- environment -----------------------------------------------------------------------------------------------------
check("running inside WSL (Linux kernel with microsoft in release)", "microsoft" in os.uname().release.lower(), os.uname().release)
check("interpreter is the pilot venv .venv-wsl", Path(sys.prefix).name == ".venv-wsl", sys.prefix)
check("not root (non-root containerlab as the protocol requires)", os.geteuid() != 0, os.geteuid())
rc, out, _ = sh(["id", "-nG"])
check("user in clab_admins and docker groups", "clab_admins" in out.split() and "docker" in out.split(), out)
for mod in ("pandas", "numpy", "pybatfish"):
    try:
        m = __import__(mod)
        check(f"python module {mod} importable", True, getattr(m, "__version__", ""))
    except Exception as exc:                                         # noqa: BLE001
        check(f"python module {mod} importable", False, repr(exc))
rc, out, err = sh(["containerlab", "version"])
check("containerlab available", rc == 0, next((l.strip() for l in out.splitlines() if "version" in l.lower()), err[-200:]))
rc, out, err = sh(["docker", "version", "--format", "{{.Server.Version}}"])
check("docker daemon reachable", rc == 0 and out, out or err[-200:])
for img in ("frrouting/frr:v8.4.1", "alpine:3.19"):
    rc, out, err = sh(["docker", "image", "inspect", img, "--format", "{{index .RepoDigests 0}}"])
    check(f"image {img} present", rc == 0, out or err[-200:])
try:
    with socket.create_connection(("localhost", 9996), timeout=5):
        check("Batfish service reachable on localhost:9996 (used for batfish_check.json; not used by the runner)", True)
except OSError as exc:
    check("Batfish service reachable on localhost:9996 (used for batfish_check.json; not used by the runner)", False, repr(exc))
wd = Path.home() / "nrl-v4"
wd.mkdir(parents=True, exist_ok=True)
check("runner workdir writable", os.access(wd, os.W_OK), str(wd))

# ---- Git and provenance ------------------------------------------------------------------------------------------------
# Only tree-level git commands run in WSL. `git status` from WSL over /mnt/c (DrvFs) re-stats and re-reads every tracked
# file (> 10 min on this checkout), and Windows interop is unavailable in this distro (git.exe: Exec format error). The
# working-tree status therefore comes from Windows-native git on the SAME checkout, taken immediately before this run
# and bound to it by HEAD equality; a missing, unreadable or mismatched record FAILS. Every launch-relevant file is
# additionally proven unchanged by freeze.verify (hashes) below.
rc, head, err = sh(["git", "rev-parse", "HEAD"])
check("WSL git reads HEAD (tree-level, no working-tree scan)", rc == 0 and len(head) == 40, head or err[-200:])
ws = None
if ARGS.windows_git_status:
    try:
        ws = json.loads(Path(ARGS.windows_git_status).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        ws = {"error": repr(exc)}
check("Windows-native git record of this checkout has the same HEAD as WSL git", isinstance(ws, dict) and ws.get("head") == head,
      {"wsl": head, "windows_record": ws})
check("Git tree has no modified tracked file (Windows-native `git status --porcelain --untracked-files=no`)",
      isinstance(ws, dict) and ws.get("head") == head and ws.get("porcelain") == "", (ws or {}).get("porcelain"))
frz = json.loads((V4 / FREEZE.FREEZE_REL).read_text(encoding="utf-8")) if (V4 / FREEZE.FREEZE_REL).exists() else {}
fc = frz.get("git_commit", "")
rc, _, _ = sh(["git", "merge-base", "--is-ancestor", fc, head]) if fc else (1, "", "")
check("freeze commit is an ancestor of HEAD", rc == 0, {"freeze_commit": fc, "head": head})
rc, changed, _ = sh(["git", "diff", "--name-only", fc, head]) if fc else (1, "", "")
check("commits after the freeze touch only the freeze file, audit docs, logs or preflight tooling",
      rc == 0 and all(p.startswith(("v4_transient/manifests/PILOT-FREEZE.json", "v4_transient/docs/", "v4_transient/logs/",
                                    "v4_transient/tools/pilot_preflight_check.py"))
                      for p in changed.splitlines() if p), changed.splitlines())

# ---- exactly what the pilot command checks, without starting it ---------------------------------------------------------
check("the command's token equals the runner's PILOT_CONFIRM_TOKEN", rp.PILOT_CONFIRM_TOKEN == EXACT_TOKEN)
ok, why = rp.pilot_approval()
check("D1-D9 approval (pre-registration and decisions hashes)", ok, why)
issues = FREEZE.open_blocking_issues(V4)
check("launch-audit register has no open issue", issues == [], issues)
ok, why = rp.pilot_preflight()
check("pilot_preflight: approval + execution freeze + artifact digest + register", ok, why)
ok, why = rp.host_clean()
check("clean host: no containerlab container present", ok, why)
man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
lock = json.loads((V4 / "manifests" / "artifact_lock.json").read_text())
check("artifact lock digest equals the manifest", lock["digest"] == man["artifact_lock_digest"], lock["digest"])
digest, n = FREEZE.artifact_digest(V4)
check("artifact tree digest equals the freeze", digest == frz.get("artifacts_digest") and n == frz.get("n_artifact_files"),
      {"digest": digest, "n": n})
bfc = json.loads((V4 / "manifests" / "batfish_check.json").read_text())
changes = {c["change_id"]: c for c in man["changes"]}
plan = json.loads((V4 / "manifests" / "run_plan_pilot.json").read_text())["runs"]
gate = [(r["run_id"], *rp.batfish_gate(bfc, changes[r["change_id"]])) for r in plan]
check("Batfish gate admits every planned pilot run", all(g[1] for g in gate), [g for g in gate if not g[1]][:5])
kinds = {}
for r in plan:
    kinds[changes[r["change_id"]]["kind"]] = kinds.get(changes[r["change_id"]]["kind"], 0) + 1
check("pilot plan: 114 runs = 100 population + 10 no-op + 4 positive; no injection, no retired control",
      len(plan) == 114 and kinds == {"population": 100, "control_noop": 10, "control_positive": 4}
      and not any(r.get("inject") for r in plan), kinds)
check("no pilot state: results/pilot, logs/pilot_ledger.jsonl, plots/pilot absent",
      not (V4 / "results" / "pilot").exists() and not (V4 / "logs" / "pilot_ledger.jsonl").exists()
      and not (V4 / "plots" / "pilot").exists())
sv = V4 / "results" / "smoke3" / "SMOKE3-VALIDATION.json"
s3 = json.loads(sv.read_text())["summary"] if sv.exists() else {}
check("engineering smoke 3 validated with no failed check", bool(s3) and s3.get("failed") == [],
      {k: s3.get(k) for k in ("checks", "passed", "failed", "population_median_wall_s")})

# ---- the runner refuses without the token (subprocess; cannot start the pilot) -----------------------------------------
for extra in ([], ["--resume"], ["--resume", "--confirm-pilot", "WRONG"]):
    r = subprocess.run([sys.executable, str(V4 / "pilot" / "run_pilot.py"), "--plan", "pilot", *extra], cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    check(f"run_pilot.py --plan pilot {' '.join(extra)} (no valid token) refuses with exit 2 and starts nothing",
          r.returncode == 2 and "REFUSED" in r.stdout and not (V4 / "results" / "pilot").exists(), r.stdout.strip()[-200:])

env = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "head": head, "python": sys.version.split()[0],
       "loadavg": Path("/proc/loadavg").read_text().strip(),
       "meminfo": Path("/proc/meminfo").read_text().splitlines()[:3], "nproc": os.cpu_count()}
summary = {"checks": len(results), "passed": sum(r["pass"] for r in results),
           "failed": [r["check"] for r in results if not r["pass"]], "environment": env,
           "exact_command": "./.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan pilot --resume --confirm-pilot "
                            + EXACT_TOKEN, "note": "preflight only; the pilot was not started"}
out = V4 / "logs" / f"preflight_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
out.write_text(json.dumps({"summary": summary, "results": results}, indent=2, default=str) + "\n", encoding="utf-8")
print(json.dumps({k: summary[k] for k in ("checks", "passed", "failed")}, indent=1), "->", out.name)
sys.exit(0 if not summary["failed"] else 1)
