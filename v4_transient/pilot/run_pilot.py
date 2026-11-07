"""Run the V4 transient protocol (smoke or pilot). Runs inside WSL, no sudo (clab_admins).

    /mnt/c/Users/karth/network-research-lab/.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan smoke
    /mnt/c/Users/karth/network-research-lab/.venv-wsl/bin/python v4_transient/pilot/run_pilot.py --plan pilot --resume

Protocol: docs/PILOT-PREREGISTRATION.md §3-§5, §12. Every attempt keeps its own directory; an attempt that dies
before writing run.json is detected as INCOMPLETE and is retryable. Teardown and run.json are written even if
cleanup itself fails (smoke run 1 showed a crash inside `finally` can otherwise leave a lab running and no
record).

Refusals (no lab is touched):
  * Batfish check missing or not OK; a change whose Batfish SPEC verdict differs from what its kind requires
    (population / no-op must PASS, positive controls must FAIL) or whose Batfish r differs from r_exact
  * --plan pilot unless v4lib.decisions.check_approval passes: manifests/PREREG-APPROVAL.json approved with the
    SHA-256 of the pre-registration and of config/pilot_decisions.json, every decision D1-D9 present, FROZEN and
    schema-valid, and no UNFROZEN marker left outside the pre-registration's §0 legend
  * --plan pilot without the explicit --confirm-pilot token
  * --plan pilot unless v4lib.freeze.verify passes: manifests/PILOT-FREEZE.json (Git-anchored) matches every
    executing/analysis file, nrl dependency, config, manifest and artifact, and the launch-audit register
    manifests/AUDIT-BLOCKING-ISSUES.json has no open issue. Approval and freeze are re-checked before every attempt.
  * any containerlab container (running or stopped) present before an attempt
  * failure injection outside the smoke plan

Amendment A5 (engineering, 2026-09-15): docker exec phases OUTSIDE [t_baseline_start, t_end] run across routers/pairs
in parallel (v4lib.labops.parallel_map), phase by phase. The observation window below, stop_instruments and the frozen
nrl.clab.wait_for_convergence are unchanged (tests/test_runner_parallel.py pins them by hash).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from nrl import clab                                               # noqa: E402
from nrl import topologies_v3 as T3                                # noqa: E402
from nrl.scenario_io import read as read_scenario                  # noqa: E402

from v4lib import EXPERIMENT_ID, PROTOCOL_VERSION                  # noqa: E402
from v4lib import decisions as DEC                                 # noqa: E402
from v4lib import freeze as FREEZE                                 # noqa: E402
from v4lib import labops as L                                      # noqa: E402

ART = V4 / "pilot" / "artifacts"
MAN = V4 / "manifests"
PREREG = V4 / "docs" / "PILOT-PREREGISTRATION.md"
APPROVAL = V4 / DEC.APPROVAL_REL
#: the 20x5 pilot never starts without this exact token on the command line (never a default, never used in tests)
PILOT_CONFIRM_TOKEN = "START-20x5-PILOT"
UNFROZEN_MARKER = DEC.UNFROZEN_MARKER
REQUIRED_DECISIONS = DEC.DECISION_KEYS
RETRYABLE = {"STAGING_FAILED", "DEPLOY_FAILED", "CONTAINERS_MISSING", "NO_CONVERGENCE", "LAB_INVALID",
             "ERROR", "PUSH_FAILED", "INCOMPLETE"}
MAX_ATTEMPTS = 2


def retryable(rec: dict) -> bool:
    """Pre-registration §12 (amendment A3): a failure is retried only if the change was never applied. Once the push
    has started, the attempt has observed (part of) the outcome, so re-running it could select on that outcome."""
    return rec.get("status") in RETRYABLE and not rec.get("change_applied")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_digest() -> dict:
    files = sorted((V4 / "v4lib").glob("*.py")) + [HERE]
    return {str(f.relative_to(V4)).replace("\\", "/"): sha(f) for f in files}


def lab_name(art: Path) -> str:
    for line in (art / "topology.clab.yml").read_text().splitlines():
        m = re.match(r"^name:\s*(\S+)\s*$", line)
        if m:
            return m.group(1)
    raise ValueError("no lab name")


def batfish_gate(bfc: dict, change: dict):
    """(allowed, reason). Population and no-op changes must be Batfish SPEC-PASS; positive controls must FAIL."""
    if not bfc or bfc.get("verdict") != "OK":
        return False, f"Batfish check verdict {bfc.get('verdict') if bfc else None}"
    rec = (bfc.get("changes") or {}).get(change["change_id"])
    if rec is None:
        return False, "no Batfish record for this change"
    expected = not change["kind"].startswith("control_positive")    # includes A4-retired controls (still SPEC-FAIL)
    if rec.get("spec_pass") is not expected:
        return False, f"Batfish SPEC pass={rec.get('spec_pass')}, required {expected} for kind {change['kind']}"
    if not rec.get("r_match"):
        return False, "Batfish steady-state r does not match r_exact"
    return True, "ok"


def pilot_approval(prereg: Path = PREREG, approval: Path = APPROVAL, v4_root: Path = V4):
    """(ok, reason). Pure check, no side effects. All D1-D9 rules live in v4lib/decisions.py."""
    return DEC.check_approval(v4_root, prereg, approval)


def pilot_preflight(check_artifacts: bool = True):
    """(ok, reason). Pure check: D1-D9 approval, then the execution freeze (code, nrl dependencies, config, manifests,
    artifacts, empty launch-audit register; v4lib/freeze.py)."""
    ok, why = pilot_approval()
    if not ok:
        return False, why
    return FREEZE.verify(V4.parent, check_artifacts=check_artifacts)


def host_clean(run=None):
    """(ok, reason). No containerlab container, running or stopped, may exist before an attempt: a lab left behind by a
    crash (smoke run 1) would load the host and perturb every later transient measurement."""
    r = (run or clab.run)(["docker", "ps", "-a", "--filter", "label=containerlab", "--format", "{{.Names}}"], timeout=30)
    if r.get("status") != "OK":
        return False, f"cannot list containers: {(r.get('error') or r.get('stderr') or '')[-200:]}"
    names = (r.get("stdout") or "").split()
    return (not names), ("ok" if not names else f"leftover containerlab containers present: {names[:6]}")


def attempts(out_root: Path, rid: str):
    d = out_root / "raw" / rid
    recs = []
    for ad in sorted(d.glob("attempt*")) if d.exists() else []:
        f = ad / "run.json"
        applied = (ad / "change_applied.json").exists()
        incomplete = {"status": "INCOMPLETE_AFTER_CHANGE" if applied else "INCOMPLETE", "attempt_dir": ad.name,
                      "change_applied": applied}
        if not f.exists():
            recs.append(incomplete)
            continue
        try:
            recs.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            recs.append(incomplete)
    return recs


def _guard(rec: dict, label: str, fn):
    try:
        return fn()
    except Exception as exc:                                        # noqa: BLE001
        rec.setdefault("cleanup_errors", []).append(f"{label}: {type(exc).__name__}: {exc}")
        return None


def one_run(run, change, out_root: Path, workdir: Path, lock: dict, attempt: int, provenance: dict = None) -> dict:
    rid = run["run_id"]
    rdir = out_root / "raw" / rid / f"attempt{attempt}"
    rdir.mkdir(parents=True, exist_ok=True)
    spec = T3.resolve(change["topology"])
    routers, hosts = sorted(spec.routers), sorted(spec.hosts)
    art_rel = change["lab_artifact"]
    src = ART / art_rel / "artifact"
    lab = lab_name(src)
    golden_sc = read_scenario(ART / art_rel / "scenario.json")
    cand_sc = read_scenario(ART / change["candidate_scenario"])
    rec = {"experiment_id": EXPERIMENT_ID, "protocol_version": PROTOCOL_VERSION, **run,
           "change_kind": change["kind"], "topology": change["topology"], "lab": lab, "attempt": attempt,
           "status": "OK", "error": None, "started_utc": L.now_utc(), "t_wall_start": time.time(),
           "code_sha256": code_digest(), "prereg_sha256": sha(PREREG), "runner_exec_mode": L.RUNNER_EXEC_MODE,
           "env_before": L.environment(),
           "params": {k: getattr(L, k) for k in ("PRE_CHANGE_BASELINE_S", "MIN_OBS_S", "QUIET_S", "MAX_OBS_S",
                                                  "POLL_S", "PROBE_INTERVAL_S", "PROBE_COUNT")}}
    rec.update(provenance or {})
    L.wj(rdir / "attempt_started.json", {k: rec[k] for k in ("run_id", "attempt", "started_utc", "code_sha256")})
    staged = workdir / f"{rid}.a{attempt}"
    poller = None
    deployed = False
    lock_used = lock
    if run.get("inject") == "staging":
        key = sorted(k for k in lock if k.startswith(f"{art_rel}/artifact/"))[0]
        lock_used = dict(lock)
        lock_used[key] = "0" * 64
        rec["injected_failure"] = {"kind": "staging", "corrupted_lock_key": key}
    try:
        st = L.stage(src, staged, lock_used, art_rel)
        rec["staging"] = st
        if st["status"] != "OK":
            rec.update(status="STAGING_FAILED", error=str(st["problems"][:5]))
            return rec
        dep = L.deploy(staged)
        deployed = True
        L.wj(rdir / "clab_deploy.json", dep)
        rec["deploy"] = {k: dep.get(k) for k in ("status", "rc", "seconds", "error")}
        if dep["status"] != "OK":
            rec.update(status="DEPLOY_FAILED", error=(dep.get("error") or dep.get("stderr", ""))[-800:])
            return rec
        up = clab.containers_up(lab, routers + hosts)
        rec["containers"] = up
        if up["status"] != "OK":
            rec.update(status="CONTAINERS_MISSING", error=up["error"])
            return rec
        t_c = time.time()
        conv = clab.wait_for_convergence(lab, routers)
        L.wj(rdir / "convergence.json", conv)
        rec["convergence"] = {k: v for k, v in conv.items() if k != "history"}
        rec["convergence_wall_s"] = round(time.time() - t_c, 2)
        if not conv["converged"]:
            rec.update(status="NO_CONVERGENCE", error=conv["error"])
            return rec
        pre = L.ospf_binding_state(lab, routers)                   # A5: routers in parallel, same commands
        rec["pre_ospf_binding"] = clab.verify_ospf_binding(pre, golden_sc)
        if rec["pre_ospf_binding"]["status"] != "OK":
            rec.update(status="LAB_INVALID", error="; ".join(rec["pre_ospf_binding"]["problems"][:4]))
            return rec

        rec["container_date"] = clab.dexec(lab, routers[0], ["date"])["stdout"].strip()
        rec["fib_monitors"] = L.start_fib_monitors(lab, routers)
        time.sleep(0.5)                                   # monitors attach before the reference snapshot
        L.wj(rdir / "fib_initial.json", L.fib_snapshot(lab, routers))
        probes = L.start_probes(lab, spec)
        L.wj(rdir / "probes_meta.json", probes)
        poller = L.NeighbourPoller(lab, routers)
        poller.start()
        rec["t_baseline_start"] = time.time()
        time.sleep(L.PRE_CHANGE_BASELINE_S)               # fixed pre-change observation window (§4)

        rec["change_applied"] = True                      # from here on a failure is never retried (§12, A3)
        L.wj(rdir / "change_applied.json", {"run_id": rid, "attempt": attempt, "t": time.time()})
        push = L.push_change(lab, change["push_plan"])
        L.wj(rdir / "push.json", push)
        rec["t0"] = push[0]["t_start"]
        rec["t_push_end"] = max(p["t_end"] for p in push)
        rec["push_status"] = [p["status"] for p in push]
        push_ok = all(p["status"] == "OK" for p in push)

        settled = False
        polls = []
        while True:
            pr = L.poll_routers(lab, routers)
            polls.append({"routers": {r: {k: v for k, v in e.items() if k != "monitor"} for r, e in pr.items()}})
            last = L.last_event_ts({r: e["monitor"] for r, e in pr.items()})
            last_act = max(rec["t_push_end"], last or 0.0)
            # the OSPF verdict must come from an error-free poll that started after the last activity (§5, A3)
            fresh = [x for x in list(poller.samples) if x["t_before"] >= last_act and not x.get("error")]
            now = time.time()
            if (now - rec["t0"] >= L.MIN_OBS_S and now - last_act >= L.QUIET_S
                    and fresh and not fresh[-1]["transitional"]):
                settled = True
                break
            if now - rec["t0"] >= L.MAX_OBS_S:
                break
            time.sleep(L.POLL_S)
        rec["t_end"] = time.time()
        rec["settled"] = settled
        rec["observation_s"] = rec["t_end"] - rec["t0"]
        L.wj(rdir / "fib_polls.json", polls)
        poller.stop()
        poller.join(timeout=30)
        L.stop_instruments(lab, routers, hosts)
        for r, text in L.read_monitors(lab, routers).items():
            p = rdir / "fib_monitor" / f"{r}.log"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        for k, text in L.collect_probes(lab, probes).items():
            p = rdir / "probes" / f"{k.replace('->', '__')}.log"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        L.wj(rdir / "ospf_neighbours.json", poller.samples)
        L.wj(rdir / "fib_final.json", L.fib_snapshot(lab, routers))
        state = L.capture_state(lab, routers)                      # A5: nrl.clab.capture_state per router, in parallel
        for node, s in state.items():
            for label, payload in s.items():
                L.wj(rdir / "state" / f"{node}.{label}.json", payload)
        rec["post_checks"] = {"running_config": clab.verify_running_config(state, cand_sc),
                              "addresses": clab.verify_addresses(state, cand_sc),
                              "ospf_binding": clab.verify_ospf_binding(state, cand_sc)}
        if not push_ok:
            rec.update(status="PUSH_FAILED", error=str([p["stderr"] for p in push if p["status"] != "OK"])[:800])
        elif rec["post_checks"]["running_config"]["status"] != "OK":
            rec.update(status="POST_CONFIG_MISMATCH",
                       error="; ".join(rec["post_checks"]["running_config"]["problems"][:4]))
        elif not settled:
            rec["status"] = "NOT_SETTLED"
    except Exception as exc:                                        # noqa: BLE001
        rec.update(status="ERROR", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-3000:])
    finally:
        if poller is not None:
            _guard(rec, "poller.stop", poller.stop)
            _guard(rec, "poller.join", lambda: poller.join(timeout=30))
        if deployed:
            des = _guard(rec, "destroy", lambda: L.destroy(staged))
            if des is not None:
                _guard(rec, "write clab_destroy.json", lambda: L.wj(rdir / "clab_destroy.json", des))
            rec["teardown_ok"] = bool(des and des.get("status") == "OK")
        _guard(rec, "rm staged", lambda: shutil.rmtree(staged, ignore_errors=True))
        rec["env_after"] = _guard(rec, "environment", L.environment)
        rec["finished_utc"] = L.now_utc()
        rec["wall_s"] = round(time.time() - rec["t_wall_start"], 2)
        L.wj(rdir / "run.json", rec)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", choices=["smoke", "smoke2", "smoke3", "pilot"], required=True)
    ap.add_argument("--workdir", default=str(Path.home() / "nrl-v4"))
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--confirm-pilot", default=None, metavar="TOKEN",
                    help=f"required with --plan pilot; must equal {PILOT_CONFIRM_TOKEN}")
    a = ap.parse_args()

    provenance = {}
    if a.plan == "pilot":
        if a.confirm_pilot != PILOT_CONFIRM_TOKEN:
            print(f"REFUSED (pilot): explicit start confirmation missing. The 100-run pilot starts only with "
                  f"--confirm-pilot {PILOT_CONFIRM_TOKEN}")
            return 2
        ok, why = pilot_preflight()
        if not ok:
            print(f"REFUSED (pilot): {why}. See docs/V4-LAUNCH-AUDIT.md and docs/PILOT-PREREGISTRATION.md §19.")
            return 2
        appr = json.loads(APPROVAL.read_text(encoding="utf-8"))
        frz = json.loads((V4 / FREEZE.FREEZE_REL).read_text(encoding="utf-8"))
        provenance = {"approval_sha256": sha(APPROVAL), "decisions_sha256": appr["decisions_sha256"],
                      "prereg_sha256_approved": appr["prereg_sha256"],
                      "freeze_sha256": sha(V4 / FREEZE.FREEZE_REL), "freeze_git_commit": frz["git_commit"]}

    man = json.loads((MAN / "pilot_manifest.json").read_text())
    lock_doc = json.loads((MAN / "artifact_lock.json").read_text())
    if lock_doc["digest"] != man["artifact_lock_digest"]:
        print("REFUSED: artifact lock digest differs from the manifest")
        return 2
    lock = lock_doc["sha256"]
    bfc_p = MAN / "batfish_check.json"
    bfc = json.loads(bfc_p.read_text()) if bfc_p.exists() else {}
    changes = {c["change_id"]: c for c in man["changes"]}
    plan = json.loads((MAN / f"run_plan_{a.plan}.json").read_text())["runs"]
    if a.plan != "smoke" and any(r.get("inject") for r in plan):
        print("REFUSED: failure injection is allowed only in the smoke plan")
        return 2
    for r in plan:
        ok, why = batfish_gate(bfc, changes[r["change_id"]])
        if not ok:
            print(f"REFUSED: Batfish gate for {r['run_id']} ({r['change_id']}): {why}")
            return 2

    out_root = V4 / "results" / a.plan
    out_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(a.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    L.wj(out_root / f"environment_{time.strftime('%Y%m%dT%H%M%S')}.json", L.static_environment())
    ledger = V4 / "logs" / f"{a.plan}_ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)

    def log(rec):
        line = {k: rec.get(k) for k in ("run_id", "attempt", "status", "error", "wall_s", "observation_s",
                                        "settled", "finished_utc", "cleanup_errors")}
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")

    done_now = 0
    for run in sorted(plan, key=lambda r: r["order"]):
        prev = attempts(out_root, run["run_id"])
        if prev and not a.resume:
            print(f"REFUSED: {run['run_id']} already has attempts; use --resume")
            return 2
        while True:
            prev = attempts(out_root, run["run_id"])
            if prev and (not retryable(prev[-1]) or len(prev) >= MAX_ATTEMPTS):
                break
            if a.limit and done_now >= a.limit:
                return 0
            if a.plan == "pilot":
                ok, why = pilot_preflight()
                if not ok:
                    print(f"REFUSED (pilot, before {run['run_id']}): {why}")
                    return 2
            ok, why = host_clean()
            if not ok:
                print(f"REFUSED (before {run['run_id']}): {why}. Destroy the leftover lab, then restart with --resume.")
                return 2
            attempt = len(prev) + 1
            ch = changes[run["change_id"]]
            print(f"[{run['order'] + 1}/{len(plan)}] {run['run_id']} {ch['topology']} {ch['role']} attempt {attempt}",
                  flush=True)
            rec = one_run(run, ch, out_root, workdir, lock, attempt, provenance)
            done_now += 1
            log(rec)
            print(f"      -> {rec['status']} wall {rec['wall_s']}s obs {rec.get('observation_s')} "
                  f"{'' if rec['status'] == 'OK' else rec.get('error')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
