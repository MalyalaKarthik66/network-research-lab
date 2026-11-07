"""PHASE 3 -- Containerlab ground truth. Deploy, converge, measure, tear down.

    python3 pipeline/run_phase3.py --preflight-only     # check the box first
    python3 pipeline/run_phase3.py --only golden        # one lab, ~3 min
    python3 pipeline/run_phase3.py                      # all 61 labs
    python3 pipeline/run_phase3.py --resume             # after any interruption
    python3 pipeline/run_phase3.py --datasets-only      # rebuild CSVs, no labs

MUST RUN INSIDE WSL (or any Linux host). Containerlab needs real network
namespaces. See docs/PHASE3-SETUP.md.

61 labs: golden + 10 incidents + 50 candidates. Budget ~2.5-4 hours. It is
resumable at run granularity, so an interruption costs one lab, not the run.

Nothing here decides whether a candidate is safe. It measures. The harm
definition is frozen in docs/HARM-DEFINITION.md and applied mechanically to the
stored per-property outcomes; `label` stays null for Phase 4.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import sys
import re
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nrl.batching import (append_ledger, ledger_integrity,      # noqa: E402
                          now as bnow, plan_batch, print_batch_summary)
from nrl import GENERATOR_VERSION, clab                            # noqa: E402
from nrl.faults import FAULTS                                      # noqa: E402
from nrl.p3_eval import measure_all                                # noqa: E402
from nrl.properties import PROPERTIES, SUITE_VERSION               # noqa: E402
from nrl.repairs import APPLICABLE, REPAIRS                        # noqa: E402
from nrl.scenario_io import read as read_scenario                  # noqa: E402
from nrl.topologies import resolve as resolve_topology, src_node             # noqa: E402
from nrl.topology import ROUTERS, build_golden                     # noqa: E402

IMAGE_DIGESTS: dict = {}
PIDS = [p["pid"] for p in PROPERTIES]
# The transient probe follows P01 (hostA can ping hostB): the same pair the
# specification's first property names, so the transient measurement and the
# steady-state one are about the same flow.
P01_SRC = next(p["src"] for p in PROPERTIES if p["pid"] == "P01")
P01_DST = next(p["dst"] for p in PROPERTIES if p["pid"] == "P01")
SPEC_PIDS = [p["pid"] for p in PROPERTIES if p["in_spec"]]
# Deliberately NOT defined here any more. Router and host lists are per
# topology and come from the spec inside run_one(). A module-level list is how
# t1 labs aborted with CONTAINERS_MISSING and t3 silently went unmeasured.




def resolve_pilot(raw: str) -> Path:
    """Resolve --pilot and REFUSE a directory that is not a pilot.

    A mistyped path (`data\\pilot-v` for `data\\pilot-v2` -- a shell wrapping
    the last character) used to get several steps in: the header printed
    "pilot.lock.json: UNREADABLE", a Batfish network `nrl-spike-pilot-v` was
    created, and only then did it die on a missing manifest. Half-executing
    against a target that does not exist is the wrong-target failure this
    project has already been bitten by; the run must stop at the first step.
    """
    p = Path(raw)
    if not p.is_absolute():
        p = (REPO / p).resolve()
    if not p.is_dir():
        raise SystemExit(f"BLOCKED: no such pilot directory: {p}\n"
                         f"         (check for a truncated or wrapped path)")
    missing = [f for f in ("manifest.json", "pilot.lock.json")
               if not (p / f).exists()]
    if missing:
        raise SystemExit(f"BLOCKED: {p} is not a pilot directory -- missing "
                         f"{', '.join(missing)}.\n"
                         f"         Run build_pilot_v2.py first.")
    return p

def placeholder_measurements(error: str) -> list:
    """Twelve ERROR rows for a run that never got far enough to measure.

    A lab that failed to deploy must still occupy twelve rows. Left empty it
    would not appear in any per-run count and would look like no run at all
    rather than a failed one -- the same trap that hid a broken candidate in
    Phase 2 (notes/surprises.md S-002). Absence must never be mistakable for
    success.
    """
    return [{"property_id": p["pid"], "kind": p["kind"],
             "in_spec": p["in_spec"], "text": p["text"],
             "status": "ERROR", "holds": None,
             "error": error or "run aborted before measurement",
             "evidence": {}, "extra": {}, "seconds": 0.0}
            for p in PROPERTIES]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wj(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n",
                    newline="\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# gates and sampling helpers
# ---------------------------------------------------------------------------

def golden_gate(out: Path, topologies) -> dict:
    """Return {topology: reason} for every topology whose golden is not healthy.

    G is the set of ORACLE properties that HOLD on the golden lab. The frozen
    harm definition requires |G| == every property; a candidate is HARMFUL iff
    it breaks something in G, so a property missing from G is a property whose
    breakage can never be observed for that topology.

    A topology whose golden has not been run yet is NOT blocked -- it is simply
    not yet gated, and the ordering in main() runs goldens first.
    """
    bad = {}
    for tn in (topologies or ["__single__"]):
        rid = f"golden-{tn}" if tn != "__single__" else "golden"
        mj = out / "runs" / rid / "measurements.json"
        if not mj.exists():
            continue                      # not run yet; gate applies next batch
        try:
            ms = json.loads(mj.read_text())
        except Exception as exc:                                   # noqa: BLE001
            bad[tn] = f"measurements.json unreadable: {exc}"
            continue
        by = {m["property_id"]: m for m in ms}
        missing = [pid for pid in PIDS
                   if by.get(pid, {}).get("holds") is not True]
        if missing:
            detail = ", ".join(
                f"{pid}({by.get(pid, {}).get('status', 'ABSENT')}"
                f"/{by.get(pid, {}).get('holds')})" for pid in missing)
            bad[tn] = f"|G|={len(PIDS) - len(missing)}/{len(PIDS)}  not holding: {detail}"
    return bad


def stratified_sample(items, n, key, seed=20260902):
    """Round-robin over strata, so a sample of N spans the design rather than
    taking a contiguous slice of one topology and one fault family.

    `--limit N` takes the first N of a topology-ordered manifest, which is one
    topology and one repair class. That is why it is not used for sampling.
    """
    import random
    if n <= 0 or not items:
        return []
    rng = random.Random(seed)
    buckets = {}
    for it in items:
        buckets.setdefault(key(it), []).append(it)
    for b in buckets.values():
        rng.shuffle(b)
    # Shuffled with the fixed seed, not left alphabetical: when n is smaller
    # than the number of strata the round-robin only reaches the first n of
    # them, so sorted order silently truncated a 150-candidate sample to
    # topologies t01..t15. Deterministic either way.
    order = sorted(buckets)
    rng.shuffle(order)
    out, i = [], 0
    while len(out) < min(n, len(items)):
        progressed = False
        for k in order:
            if buckets[k][i:i + 1]:
                out.append(buckets[k][i]["candidate_id"]
                           if isinstance(buckets[k][i], dict)
                           else buckets[k][i])
                progressed = True
                if len(out) >= min(n, len(items)):
                    break
        if not progressed:
            break
        i += 1
    return sorted(out)


def boundary_score(run_rec: dict) -> float:
    """How close a completed run sat to flipping its own label.

    Random replicates mostly resample easy candidates. The label-noise floor
    that matters is measured on candidates whose measurement was marginal:
    partial packet loss, slow convergence, or a property that changed between
    polls. Higher is closer to the boundary.
    """
    score = 0.0
    for m in run_rec.get("measurements", []):
        ex = m.get("extra") or {}
        loss = ex.get("loss_pct")
        if isinstance(loss, (int, float)) and 0.0 < loss < 100.0:
            score += 2.0                       # partial loss: the clearest sign
        if m.get("status") == "ERROR":
            score += 1.0
    conv = (run_rec.get("convergence") or {}).get("seconds")
    if isinstance(conv, (int, float)):
        score += min(conv / 180.0, 1.0)        # slow convergence
    return score


def preflight(root: Path, workdir: Path) -> bool:
    print("PREFLIGHT")
    ok = True

    def c(label, good, detail=""):
        nonlocal ok
        print(f"  [{'PASS' if good else 'FAIL'}] {label}")
        if not good and detail:
            print(f"         {detail}")
        ok = ok and bool(good)

    c("running on Linux (Containerlab needs real netns)",
      platform.system() == "Linux",
      f"got {platform.system()} -- run this inside WSL, not Windows Python")
    c("docker on PATH", shutil.which("docker") is not None)
    c("containerlab on PATH", shutil.which("containerlab") is not None,
      "install: bash -c \"$(curl -sL https://get.containerlab.dev)\"  "
      "(.dev, not .net)")

    import os as _os
    # os.geteuid() does not exist on Windows. Preflight had already FAILED the
    # "running on Linux" check by this point and then crashed with an
    # AttributeError instead of returning the clean refusal it had earlier
    # decided on -- so the operator saw a traceback rather than the two lines
    # telling them to use WSL. A gate that has made its decision must deliver
    # it.
    if platform.system() != "Linux":
        print("\n  Phase 3 cannot run here. Containerlab creates veth pairs "
              "and network")
        print("  namespaces, which needs a real Linux kernel. See "
              "docs/PHASE3-SETUP.md.")
        print("  Phases 1 and 2 stay on the Windows side; only Phase 3 moves.")
        return False
    if _os.geteuid() == 0:
        print("  [INFO] running as root -- containerlab invoked directly")
    else:
        v = clab.run(["sudo", "-n", "containerlab", "version"], timeout=60)
        c("passwordless sudo works for containerlab", v["status"] == "OK",
          "containerlab needs root to create veths and netns. Either run\n"
          "         the orchestrator as root:\n"
          "           sudo -E python3 pipeline/run_phase3.py --workdir "
          "/root/nrl-run\n"
          "         or grant passwordless sudo for it:\n"
          "           echo \"$USER ALL=(ALL) NOPASSWD: $(which containerlab)\""
          " | sudo tee /etc/sudoers.d/nrl-clab")

    d = clab.run(["docker", "info"], timeout=60)
    c("docker daemon reachable", d["status"] == "OK",
      (d.get("stderr") or "")[:200])

    if d["status"] == "OK":
        wsl_dd = "Docker Desktop" in d["stdout"]
        print(f"  [{'WARN' if wsl_dd else 'INFO'}] docker provider: "
              f"{'Docker Desktop (see docs/PHASE3-SETUP.md)' if wsl_dd else 'native docker-ce'}")
        if wsl_dd:
            print("         Docker Desktop's WSL backend does not create "
                  "docker0 in the distro;")
            print("         Containerlab typically fails with 'Link not "
                  "found'. Use docker-ce.")

    imgs = clab.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    have = imgs["stdout"] if imgs["status"] == "OK" else ""
    from nrl.emit import FRR_IMAGE, HOST_IMAGE
    for img in (FRR_IMAGE, HOST_IMAGE):
        c(f"image present: {img}", img in have, f"docker pull {img}")

    c("pilot lock present", (root / "pilot.lock.json").exists())
    sp = root / "phase2" / "spike_result.json"
    if sp.exists():
        spike = json.loads(sp.read_text())
        lock = json.loads((root / "pilot.lock.json").read_text())
        c("spike verdict is GO", spike.get("verdict") == "GO")
        c("spike artifact digest matches the pilot on disk",
          spike.get("artifact_digest") == lock.get("artifact_digest"),
          "the pilot was rebuilt after the spike -- re-run the spike")
    else:
        c("spike result present", False, "run pipeline/spike_frr_batfish.py")

    global IMAGE_DIGESTS
    IMAGE_DIGESTS = {}
    for img in (FRR_IMAGE, HOST_IMAGE):
        d = clab.run(["docker", "inspect", "--format",
                      "{{index .RepoDigests 0}}", img], timeout=60)
        IMAGE_DIGESTS[img] = (d["stdout"].strip()
                              if d["status"] == "OK" else None)
        print(f"  [INFO] {img} -> {IMAGE_DIGESTS[img] or 'digest unresolved'}")

    try:
        workdir.mkdir(parents=True, exist_ok=True)
        t = workdir / ".probe"
        t.write_text("x")
        t.unlink()
        c(f"workdir writable ({workdir})", True)
    except Exception as exc:                                       # noqa: BLE001
        c(f"workdir writable ({workdir})", False, str(exc))

    if str(workdir).startswith("/mnt/"):
        print("  [WARN] workdir is on the Windows share. Bind mounts from "
              "/mnt/c into")
        print("         containers are slow and permission-quirky. Prefer "
              "~/nrl-run.")
    return ok


# ---------------------------------------------------------------------------
# one lab
# ---------------------------------------------------------------------------

def scenario_for(run_id: str):
    g = build_golden()
    if run_id == "golden":
        return g
    if run_id.startswith("I-"):
        return FAULTS[int(run_id.split("-")[1]) - 1].apply(g)
    return None                      # candidates rebuilt by the caller


def scenario_for(src_dir: Path, run_id: str, fallback: dict):
    """Prefer the scenario.json written beside the artifact. Falls back to the
    regenerated pilot-v1 map so v1 keeps working unchanged."""
    p = src_dir / "scenario.json"
    if p.exists():
        return read_scenario(p)
    key = "golden" if run_id.startswith("golden") else run_id
    return fallback[key]


def build_scenarios():
    """Rebuild every scenario from the model, so runtime checks compare against
    the same source of truth Phase 1 rendered from."""
    g = build_golden()
    out = {"golden": g}
    cnum = 0
    for idx, fault in enumerate(FAULTS, start=1):
        iid = f"I-{idx:02d}"
        faulted = fault.apply(g)
        out[iid] = faulted
        for rid in APPLICABLE[fault.family]:
            cnum += 1
            out[f"C-{cnum:04d}"] = REPAIRS[rid].apply(g, faulted, fault)
    return out


def golden_control(rows) -> tuple:
    """Oracle-stability control over the golden rows of containerlab_summary.

    A control that cannot fail is not a control. This used to compare the
    property vectors of ALL golden rows, including rows whose lab never came
    up: three identical FAILURES reported "3 golden run(s), ALL IDENTICAL".
    Only runs that actually executed can witness stability, and one run
    witnesses nothing -- both cases now report VACUOUS.
    """
    pids = [f"holds_P{i:02d}" for i in range(1, 13)]
    g_all = [r for r in rows if r["run_id"].startswith("golden")]
    ok = [r for r in g_all if r.get("run_status") == "OK"]
    bad = [r["run_id"] for r in g_all if r.get("run_status") != "OK"]
    vecs = {r["run_id"]: tuple(r[p] for p in pids if p in r) for r in ok}
    uniq = set(vecs.values())
    if not vecs:
        msg = (f"VACUOUS: 0 golden run(s) completed ({len(g_all)} attempted) "
               f"-- control did not run")
    elif len(vecs) == 1:
        msg = ("VACUOUS: 1 golden run completed -- a single run cannot "
               "witness oracle stability")
    else:
        msg = (f"{len(vecs)} golden run(s) OK, "
               f"{'ALL IDENTICAL' if len(uniq) <= 1 else 'DISAGREEMENT'}")
    if len(uniq) > 1:
        msg += f"  <-- ORACLE UNSTABLE: {vecs}"
    if bad:
        msg += f"  [{len(bad)} golden run(s) did not complete: {bad}]"
    return sorted(vecs), msg


def lab_name_from_artifact(art: Path) -> str:
    """Read the containerlab lab name out of the artifact itself.

    It used to be re-derived as f"nrl-{run_id}". The v2 builder emits
    `name: nrlv2-<candidate_id>`, so every deploy succeeded and every
    subsequent `docker ps` lookup searched for `clab-nrl-...` containers that
    do not exist: 29/29 labs reported CONTAINERS_MISSING. Same class of defect
    as B5/B6 -- reconstructing an identity that the artifact already states.
    Read it, never rebuild it, and fail loudly if it is not there.
    """
    f = art / "topology.clab.yml"
    if not f.exists():
        raise FileNotFoundError(f"no topology.clab.yml in {art}")
    for line in f.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^name:\s*(\S+)\s*$", line)
        if m:
            return m.group(1)
    raise ValueError(f"{f} has no top-level `name:` line; refusing to guess "
                     f"the lab name")


def run_one(run_id: str, src_dir: Path, workdir: Path, lock: dict,
            scenario, out_dir: Path, keep: bool, spec=None,
            kind: str = None, attempt: int = 1) -> dict:
    """`kind` is now passed in by the caller, which knows what it enqueued.

    It used to be inferred from the run_id string:
        "golden" if run_id == "golden" else
        "golden_replicate" if run_id.startswith("golden-r") else ...
    Under pilot-v2 the goldens are named `golden-t01_chain4`, which matches
    none of those, so every golden run was classified as a CANDIDATE. The
    summary then reported N+topologies candidates and no goldens, and nothing
    downstream noticed. Inferring identity from a name is how that happened;
    the caller is told to state it instead.
    """
    if spec is None:
        raise ValueError(f"run_one({run_id}) requires a topology spec; it used "
                         f"to fall back to pilot-v1's network, which would "
                         f"have probed the wrong addresses on every v2 lab")
    routers = sorted(spec.routers)
    hosts = sorted(spec.hosts)
    lab = lab_name_from_artifact(src_dir / "artifact")
    rdir = out_dir / "runs" / run_id
    t0 = time.time()
    rec = {"run_id": run_id, "lab": lab, "kind": kind or "candidate",
           "attempt": attempt,
           "started_utc": now(), "status": "OK", "error": None}

    rel_prefix = (f"reference/{src_dir.name}" if src_dir.parent.name == "reference"
                  else f"incidents/{src_dir.name}"
                  if src_dir.parent.name == "incidents"
                  else f"candidates/{src_dir.name}")
    staged = workdir / run_id
    stage = clab.stage_artifact(src_dir / "artifact", staged,
                                lock["sha256"], rel_prefix)
    rec["staging"] = stage
    if stage["status"] != "OK":
        rec["status"] = "STAGING_FAILED"
        rec["error"] = stage["error"]
        rec["measurements"] = placeholder_measurements(stage["error"])
        wj(rdir / "run.json", rec)
        return rec

    dep = des = None
    try:
        dep = clab.deploy(staged, lab)
        wj(rdir / "clab_deploy.json", dep)
        if dep["status"] != "OK":
            rec["status"] = "DEPLOY_FAILED"
            rec["error"] = (dep.get("error")
                            or (dep.get("stderr") or "")[-600:])
            rec["measurements"] = placeholder_measurements(rec["error"])
            return rec

        up = clab.containers_up(lab, routers + hosts)
        rec["containers"] = up
        if up["status"] != "OK":
            rec["status"] = "CONTAINERS_MISSING"
            rec["error"] = up["error"]
            rec["measurements"] = placeholder_measurements(up["error"])
            return rec

        listeners = clab.start_listeners(
            lab, [h for h in hosts if h != "hosta"])
        wj(rdir / "listeners.json", listeners)

        # One cheap reachability probe per convergence poll. This is the only
        # instrument in the harness that can see gap (b) -- harm that exists
        # during reconvergence and is gone by the time steady state is
        # measured. Batfish is designed not to model it, so if the false-pass
        # rate turns out to be entirely gap (a), the honest conclusion is
        # "write more properties" and there is no irreducible component to
        # report. hostA -> hostB, one packet, one second.
        def _transient_probe():
            try:
                node, src_if = src_node(spec)[P01_SRC]
                r = clab.probe_ping(lab, node, P01_DST, src=src_if, count=1)
                return {"src": P01_SRC, "dst": P01_DST,
                        "reachable": (r.get("loss_pct") is not None
                                      and r["loss_pct"] < 100.0),
                        "loss_pct": r.get("loss_pct"),
                        "rtt_avg_ms": r.get("rtt_avg_ms"),
                        "status": r.get("status")}
            except Exception as exc:                               # noqa: BLE001
                return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

        conv = clab.wait_for_convergence(lab, routers,
                                         transient_probe=_transient_probe)
        rec["convergence"] = {k: v for k, v in conv.items() if k != "history"}
        rec["transient"] = clab.transient_summary(conv)
        wj(rdir / "convergence.json", conv)
        wj(rdir / "transient.json", rec["transient"])

        state = clab.capture_state(lab, routers)
        for node, s in state.items():
            for label, payload in s.items():
                wj(rdir / "state" / f"{node}.{label}.json", payload)

        rec["artifact_runtime_check"] = {
            "running_config": clab.verify_running_config(state, scenario),
            "addresses": clab.verify_addresses(state, scenario),
            "ospf_binding": clab.verify_ospf_binding(state, scenario),
        }
        wj(rdir / "artifact_runtime_check.json", rec["artifact_runtime_check"])

        # S-020. A containerlab interface-rename race can leave ospfd with
        # nothing bound to an interface the artifact puts in OSPF. The config
        # is right, the addresses are right, and one adjacency never forms --
        # which flipped C-01361 SAFE -> HARMFUL between two identical runs.
        # The lab was not measured, so it must not be labelled: LAB_INVALID
        # becomes EXECUTION_FAILED downstream and is excluded from y.
        ob = rec["artifact_runtime_check"]["ospf_binding"]
        if ob["status"] != "OK":
            rec["status"] = "LAB_INVALID"
            rec["error"] = ("OSPF binding incomplete: "
                            + "; ".join(ob["problems"][:4]))
            rec["measurements"] = placeholder_measurements(rec["error"])
            wj(rdir / "measurements.json", rec["measurements"])
            wj(rdir / "run.json", rec)
            if not keep:
                des = clab.destroy(staged, lab)
                rec["teardown_ok"] = des["status"] == "OK"
                wj(rdir / "clab_destroy.json", des)
                wj(rdir / "run.json", rec)
            return rec

        meas = measure_all(lab, state, scenario, spec)
        rec["measurements"] = meas
        wj(rdir / "measurements.json", meas)

        adj = clab.ospf_full_adjacencies(state)
        rec["ospf_full_adjacency_pairs"] = adj["full_adjacency_pairs"]
        rec["interfaces_down"] = clab.interfaces_down(state, scenario)
        rec["non_artifact_interfaces_ignored"] = getattr(
            clab.interfaces_down, "last_ignored", [])
        rec["route_counts"] = {
            n: (len(state[n]["route"]["json"])
                if state[n]["route"].get("json") else None)
            for n in routers}

        if not conv["converged"]:
            rec["status"] = "NO_CONVERGENCE"
            rec["error"] = conv["error"]

    except Exception as exc:                                       # noqa: BLE001
        rec["status"] = "ERROR"
        rec["error"] = f"{type(exc).__name__}: {exc}"
        if not rec.get("measurements"):
            rec["measurements"] = placeholder_measurements(rec["error"])
    finally:
        if not keep:
            des = clab.destroy(staged, lab)
            wj(rdir / "clab_destroy.json", des)
            rec["teardown_ok"] = des["status"] == "OK"
            clab.rm_tree(staged)
        rec["wall_seconds"] = round(time.time() - t0, 1)
        rec["finished_utc"] = now()
        wj(rdir / "run.json", rec)
    return rec


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------

def wcsv(path: Path, rows):
    if not rows:
        return 0, 0
    cols = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows), len(cols)


def build_datasets(out: Path, manifest: dict) -> dict:
    # `<run_id>.attempt1/` holds the archived first attempt of a lab that was
    # retried under ANALYSIS-PLAN 14.1. Its run.json carries the SAME run_id,
    # so globbing everything would let the invalid attempt overwrite the valid
    # one -- sorted order puts "C-x/" before "C-x.attempt1/", so the LAB_INVALID
    # record would win. Archived attempts are evidence, not data.
    runs, archived = {}, []
    for rj in sorted((out / "runs").rglob("run.json")):
        if rj.parent.name.endswith(".attempt1"):
            archived.append(rj.parent.name)
            continue
        r = json.loads(rj.read_text())
        runs[r["run_id"]] = r

    summary, measurements = [], []
    for rid, r in sorted(runs.items()):
        by = {m["property_id"]: m for m in r.get("measurements", [])}
        arc = r.get("artifact_runtime_check", {})
        row = {
            "run_id": rid, "kind": r["kind"], "lab": r["lab"],
            "run_status": r["status"], "run_error": r.get("error"),
            "wall_seconds": r.get("wall_seconds"),
            "converged": r.get("convergence", {}).get("converged"),
            "convergence_seconds": r.get("convergence", {}).get("seconds"),
            "convergence_polls": r.get("convergence", {}).get("polls"),
            "staging_files_verified": r.get("staging", {}).get("files_verified"),
            "staging_status": r.get("staging", {}).get("status"),
            "runtime_config_match":
                arc.get("running_config", {}).get("status"),
            "runtime_config_problems":
                len(arc.get("running_config", {}).get("problems", []) or []),
            "runtime_address_match": arc.get("addresses", {}).get("status"),
            "runtime_ospf_binding": arc.get("ospf_binding", {}).get("status"),
            "ospf_full_adjacency_pairs": r.get("ospf_full_adjacency_pairs"),
            "interfaces_down_count": len(r.get("interfaces_down", []) or []),
            "teardown_ok": r.get("teardown_ok"),
            **{f"holds_{p}": by.get(p, {}).get("holds") for p in PIDS},
            **{f"status_{p}": by.get(p, {}).get("status") for p in PIDS},
        }
        tr = r.get("transient") or {}
        row.update({
            # harm definition v1.2.0 signals, recorded alongside the v1.1.0
            # primary label. Never used to compute outcome_harm_v1.
            "transient_flapped": tr.get("flapped"),
            "transient_adjacency_flaps": tr.get("adjacency_flaps_after_full"),
            "transient_rib_changes": tr.get("rib_changes_total"),
            "transient_probe_polls": tr.get("probe_polls"),
            "transient_unreachable_polls": tr.get("probe_unreachable_polls"),
            "transient_outage_after_reachable":
                tr.get("transient_outage_after_reachable"),
        })
        row["properties_measured"] = sum(
            1 for p in PIDS if by.get(p, {}).get("status") == "OK")
        row["properties_errored"] = sum(
            1 for p in PIDS if by.get(p, {}).get("status") == "ERROR")
        summary.append(row)
        for p in PIDS:
            m = by.get(p) or {
                "kind": "unknown", "in_spec": p in SPEC_PIDS, "status": "ERROR",
                "holds": None,
                "error": f"no measurement recorded (run_status={r['status']})",
                "seconds": 0.0, "extra": {}}
            measurements.append({
                "run_id": rid, "kind": r["kind"], "property_id": p,
                "property_kind": m["kind"], "in_spec": m["in_spec"],
                "status": m["status"], "holds": m["holds"], "error": m["error"],
                "seconds": m["seconds"],
                "extra_json": json.dumps(m.get("extra", {}), default=str),
            })

    # ---- deltas: golden vs BEFORE vs AFTER, per candidate per property ----
    # DEFECT B6. This used to be `g = runs.get("golden")`, a single pilot-v1
    # golden. pilot-v2 has one golden PER TOPOLOGY named `golden-<topology>`,
    # so the lookup returned None, `if not g: continue` skipped every candidate,
    # and Phase 3 produced ZERO deltas and ZERO outcomes while reporting all
    # labs completed. Absence looked exactly like success.
    def _golden_run(cand):
        tn = cand.get("topology")
        return runs.get(f"golden-{tn}") if tn else runs.get("golden")

    deltas = []
    for c in manifest["candidates"]:
        cid, iid = c["candidate_id"], c["incident_id"]
        g = _golden_run(c)
        gby = {m["property_id"]: m for m in (g or {}).get("measurements", [])}
        after, before = runs.get(cid), runs.get(iid)
        if not after or not before or not g:
            continue
        aby = {m["property_id"]: m for m in after.get("measurements", [])}
        bby = {m["property_id"]: m for m in before.get("measurements", [])}
        for p in PIDS:
            gm, bm, am = gby.get(p, {}), bby.get(p, {}), aby.get(p, {})
            deltas.append({
                "candidate_id": cid, "incident_id": iid, "property_id": p,
                "in_spec": am.get("in_spec"),
                "golden_holds": gm.get("holds"), "golden_status": gm.get("status"),
                "before_holds": bm.get("holds"), "before_status": bm.get("status"),
                "after_holds": am.get("holds"), "after_status": am.get("status"),
                "repaired_by_candidate":
                    (bm.get("holds") is False and am.get("holds") is True),
                "regressed_vs_golden":
                    (gm.get("holds") is True and am.get("holds") is False),
                "regressed_vs_before":
                    (bm.get("holds") is True and am.get("holds") is False),
                "undetermined":
                    any(x.get("status") == "ERROR" for x in (gm, bm, am)),
            })

    # ---- outcome per the FROZEN harm definition (mechanical, recomputable) --
    outcomes = []
    for c in manifest["candidates"]:
        cid, iid = c["candidate_id"], c["incident_id"]
        g = _golden_run(c)
        after = runs.get(cid)
        if not after or not g:
            continue
        rows = [d for d in deltas if d["candidate_id"] == cid]
        in_G = [d for d in rows if d["golden_holds"] is True]
        violations = [d["property_id"] for d in in_G if d["regressed_vs_golden"]]
        undet = [d["property_id"] for d in in_G if d["undetermined"]]
        if after["status"] == "NO_CONVERGENCE":
            outcome = "NO_CONVERGENCE"
        elif after["status"] not in ("OK",):
            outcome = "EXECUTION_FAILED"
        elif violations:
            outcome = "HARMFUL"
        elif undet:
            outcome = "UNDETERMINED"
        else:
            outcome = "SAFE"
        outcomes.append({
            "candidate_id": cid, "incident_id": iid,
            "run_status": after["status"],
            "golden_properties_in_G": len(in_G),
            "violations_vs_golden": ";".join(violations),
            "violation_count": len(violations),
            "spec_violations_vs_golden": ";".join(
                v for v in violations if v in SPEC_PIDS),
            "undetermined_properties": ";".join(undet),
            "outcome_harm_v1": outcome,
            "harm_definition_version": "1.1.0",
            "label": None,
        })

    # ---- REPLICATE AGREEMENT: the label-noise floor -----------------------
    # Both loops above iterate manifest["candidates"], so a `<base>~r1` run
    # never produced a delta or an outcome row: the replicate arm burned ~15
    # minutes of emulator time per batch and computed NOTHING. The arm exists
    # to measure how often an identical config re-labels differently, which is
    # the ceiling on any model's achievable accuracy -- so compute it here, by
    # the same mechanical rule, and write it down.
    def _outcome_of(run, before, g):
        gby = {m["property_id"]: m for m in (g or {}).get("measurements", [])}
        bby = {m["property_id"]: m for m in (before or {}).get("measurements", [])}
        aby = {m["property_id"]: m for m in (run or {}).get("measurements", [])}
        in_G, viol, undet = [], [], []
        for pid in PIDS:
            gm, bm, am = gby.get(pid, {}), bby.get(pid, {}), aby.get(pid, {})
            if gm.get("holds") is not True:
                continue
            in_G.append(pid)
            if any(x.get("status") == "ERROR" for x in (gm, bm, am)):
                undet.append(pid)
            elif am.get("holds") is False:
                viol.append(pid)
        if run["status"] == "NO_CONVERGENCE":
            oc = "NO_CONVERGENCE"
        elif run["status"] != "OK":
            oc = "EXECUTION_FAILED"
        elif viol:
            oc = "HARMFUL"
        elif undet:
            oc = "UNDETERMINED"
        else:
            oc = "SAFE"
        return oc, in_G, viol

    cand_by_id = {c["candidate_id"]: c for c in manifest["candidates"]}
    replicates = []
    for rid, run in sorted(runs.items()):
        if "~" not in rid:
            continue
        base = rid.split("~", 1)[0]
        c = cand_by_id.get(base)
        base_run = runs.get(base)
        if not c or not base_run:
            continue
        g = _golden_run(c)
        before = runs.get(c["incident_id"])
        b_oc, b_G, b_v = _outcome_of(base_run, before, g)
        r_oc, r_G, r_v = _outcome_of(run, before, g)
        b_by = {m["property_id"]: (m["status"], m["holds"])
                for m in base_run.get("measurements", [])}
        r_by = {m["property_id"]: (m["status"], m["holds"])
                for m in run.get("measurements", [])}
        differing = [pid for pid in PIDS if b_by.get(pid) != r_by.get(pid)]
        replicates.append({
            "replicate_run_id": rid, "candidate_id": base,
            "incident_id": c["incident_id"], "topology": c.get("topology"),
            "base_run_status": base_run["status"],
            "replicate_run_status": run["status"],
            "base_outcome": b_oc, "replicate_outcome": r_oc,
            "outcome_agrees": b_oc == r_oc,
            "differing_properties": ";".join(differing),
            "n_differing_properties": len(differing),
            "base_violations": ";".join(b_v),
            "replicate_violations": ";".join(r_v),
            "base_adjacency_pairs": base_run.get("ospf_full_adjacency_pairs"),
            "replicate_adjacency_pairs": run.get("ospf_full_adjacency_pairs"),
            "harm_definition_version": "1.1.0",
        })

    n1 = wcsv(out / "containerlab_summary.csv", summary)
    n2 = wcsv(out / "containerlab_measurements.csv", measurements)
    n3 = wcsv(out / "containerlab_deltas.csv", deltas)
    n4 = wcsv(out / "containerlab_outcomes.csv", outcomes)
    n5 = wcsv(out / "containerlab_replicates.csv", replicates)
    terminal = sorted(rid for rid, r in runs.items()
                      if r.get("status") == "LAB_INVALID")
    return {"summary": n1, "measurements": n2, "deltas": n3, "outcomes": n4,
            "replicates": n5, "runs": len(runs), "outcome_rows": outcomes,
            "replicate_rows": replicates,
            "lab_invalid_attempts": sorted(archived),
            "lab_invalid_terminal": terminal}


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True,
                    help="pilot directory, e.g. data/pilot-v2. There is deliberately "
                         "NO default: a default silently pointed every run at the old "
                         "pilot, whose ledger was already complete, so the run executed "
                         "nothing and reported ALL ITEMS COMPLETE.")
    ap.add_argument("--workdir", default=str(Path.home() / "nrl-run"))
    ap.add_argument("--only", choices=["all", "golden", "incidents",
                                       "candidates"], default="all")
    ap.add_argument("--limit", type=int, default=0,
                    help="TAKES THE FIRST N of a topology-ordered list. Use it "
                         "only for smoke tests -- for a real sample use "
                         "--sample, which spans the design.")
    ap.add_argument("--sample", type=int, default=0, metavar="N",
                    help="run N candidates stratified over (topology, fault "
                         "family) instead of all eligible ones. Deterministic: "
                         "the same N is chosen on every invocation, so a "
                         "batched collection resumes inside the SAME sample. "
                         "The chosen ids are recorded in run_metadata so "
                         "verify_phase3 recomputes the expected set from them.")
    ap.add_argument("--incidents", default="",
                    help="comma-separated incident ids to restrict the run to, "
                         "e.g. I-0001,I-0002. Use this for a stratified "
                         "validation batch: --limit takes a contiguous slice "
                         "of a topology-ordered manifest, which is one "
                         "topology, and a batch that never produces a FAIL has "
                         "not shown that the checks discriminate.")
    ap.add_argument("--batch-size", type=int, default=0,
                    help="run only the next N pending labs, then stop cleanly. "
                         "0 = all remaining.")
    ap.add_argument("--only-passing", action="store_true",
                    help="run Containerlab only on candidates that PASSED the "
                         "Batfish spec gate. P(harm|FAIL) was 100%% in the "
                         "pilot, so FAIL candidates carry no information for "
                         "the risk model and cost half the lab time.")
    ap.add_argument("--no-control", action="store_true",
                    help="skip the per-batch golden replicate (not advised)")
    ap.add_argument("--fail-controls", type=int, default=0, metavar="N",
                    help="also run N candidates that FAILED the Batfish SPEC "
                         "gate, stratified over topology and fault family. "
                         "Bounds the Batfish-PESSIMISTIC rate: observing 0 "
                         "harmful-free FAILs in 150 gives a 95%% Clopper-Pearson "
                         "upper bound of about 2%%. Without this arm the 2x2 "
                         "table has only one row and the 'never pessimistic' "
                         "claim rests on pilot-v1's 26 candidates.")
    ap.add_argument("--replicate", type=int, default=0, metavar="N",
                    help="re-run N already-completed candidate labs a second "
                         "time under a `<id>~r1` run id and report label "
                         "agreement. This is the LABEL NOISE FLOOR: calibration "
                         "cannot be better than the rate at which the same "
                         "candidate reproduces its own label. Half the sample "
                         "is drawn at random and half from boundary cases "
                         "(partial loss, slow convergence, properties that "
                         "flipped between polls), because random replicates "
                         "mostly resample easy candidates.")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--keep-lab", action="store_true",
                    help="do not destroy the lab (debugging, one run only)")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--datasets-only", action="store_true")
    args = ap.parse_args()

    root = resolve_pilot(args.pilot)
    out = root / "phase3"
    workdir = Path(args.workdir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "manifest.json").read_text())

    if args.datasets_only:
        got = build_datasets(out, manifest)
        print(f"datasets rebuilt from {got['runs']} runs: "
              f"summary={got['summary']} measurements={got['measurements']} "
              f"deltas={got['deltas']} outcomes={got['outcomes']}")
        return 0

    if not preflight(root, workdir):
        print("\nPREFLIGHT FAILED -- fix the above before deploying anything.")
        print("See docs/PHASE3-SETUP.md")
        return 2
    print("\npreflight OK")
    if args.preflight_only:
        return 0

    lock = json.loads((root / "pilot.lock.json").read_text())

    # DEFECT B5. `man_topos` was read here and assigned ~20 lines further down,
    # so every invocation of main() raised UnboundLocalError. Phase 3 has not
    # been executed since the edit that introduced it, which is why nothing
    # caught it. The topology map is now built before anything reads it.
    topo_of = {c["candidate_id"]: c.get("topology")
               for c in manifest.get("candidates", [])}
    topo_of.update({i["incident_id"]: i.get("topology")
                    for i in manifest.get("incidents", [])})
    man_topos = sorted({t for t in topo_of.values() if t})

    scenarios = {} if man_topos else build_scenarios()

    cand_list = manifest["candidates"]
    incident_filter = sorted(i.strip() for i in args.incidents.split(",")
                             if i.strip())
    if incident_filter:
        known = {i["incident_id"] for i in manifest.get("incidents", [])}
        unknown = [i for i in incident_filter if known and i not in known]
        if unknown:
            print(f"BLOCKED: not in manifest: {unknown}")
            return 2
        cand_list = [c for c in cand_list
                     if c["incident_id"] in set(incident_filter)]
        print(f"--incidents: {len(incident_filter)} incidents, "
              f"{len(cand_list)} candidates")
    if args.only_passing:
        p2 = root / "phase2" / "batfish_summary.csv"
        if not p2.exists():
            print("BLOCKED: --only-passing needs phase2/batfish_summary.csv")
            return 2
        import csv as _csv
        with p2.open(newline="", encoding="utf-8") as f:
            keep = {r["candidate_id"] for r in _csv.DictReader(f)
                    if r["batfish_spec_verdict"] == "PASS"}
        cand_list = [c for c in cand_list if c["candidate_id"] in keep]
        print(f"--only-passing: {len(cand_list)} of "
              f"{len(manifest['candidates'])} candidates passed the spec gate")

    # ---- FAIL control arm ------------------------------------------------
    fail_control_ids = []
    if args.fail_controls:
        p2 = root / "phase2" / "batfish_summary.csv"
        if not p2.exists():
            print("BLOCKED: --fail-controls needs phase2/batfish_summary.csv")
            return 2
        import csv as _csv
        with p2.open(newline="", encoding="utf-8") as f:
            failed_ids = {r["candidate_id"] for r in _csv.DictReader(f)
                          if r["batfish_spec_verdict"] == "FAIL"}
        pool = [c for c in manifest["candidates"]
                if c["candidate_id"] in failed_ids]
        fail_control_ids = stratified_sample(
            pool, args.fail_controls,
            key=lambda c: (c.get("topology"), c.get("fault_family")))
        by_id = {c["candidate_id"]: c for c in manifest["candidates"]}
        cand_list = cand_list + [by_id[i] for i in fail_control_ids
                                 if i not in {c["candidate_id"]
                                              for c in cand_list}]
        print(f"--fail-controls: {len(fail_control_ids)} of {len(pool)} "
              f"SPEC-FAIL candidates sampled over "
              f"{len({(c.get('topology'), c.get('fault_family')) for c in pool})} "
              f"(topology, family) strata")

    # ---- STRATIFIED SAMPLE ----------------------------------------------
    # `--limit` slices the first N of a topology-ordered list: 150 candidates
    # from the first two topologies, which is exactly the per-topology spread
    # the Stage 2 gate is supposed to read. --sample spans the design instead,
    # deterministically, so a batched collection resumes inside one sample.
    sample_ids = []
    if args.sample:
        sample_ids = stratified_sample(
            cand_list, args.sample,
            key=lambda c: (c.get("topology"), c.get("fault_family")))
        keep = set(sample_ids)
        cand_list = [c for c in cand_list if c["candidate_id"] in keep]
        strata = {(c.get("topology"), c.get("fault_family")) for c in cand_list}
        print(f"--sample: {len(cand_list)} candidates spanning "
              f"{len({c.get('topology') for c in cand_list})} topologies and "
              f"{len(strata)} (topology, family) strata")

    ids = []
    kind_by_id = {}
    # Only the goldens of topologies actually under test. Harm is defined
    # against the golden of the candidate's OWN topology, so a restricted run
    # needs those goldens and no others -- running all twenty for a two-topology
    # validation batch is twenty labs and about thirty-five minutes of nothing.
    needed_topos = (sorted({topo_of[c["candidate_id"]] for c in cand_list
                            if topo_of.get(c["candidate_id"])})
                    if (incident_filter or args.only_passing or args.fail_controls)
                    else man_topos)
    if args.only in ("all", "golden"):
        if man_topos:
            for tn in needed_topos:
                ids.append((f"golden-{tn}", root / "reference" / f"golden-{tn}"))
                topo_of[f"golden-{tn}"] = tn
                kind_by_id[f"golden-{tn}"] = "golden"
        else:
            ids.append(("golden", root / "reference" / "golden"))
            kind_by_id["golden"] = "golden"
    if args.only in ("all", "incidents"):
        needed = sorted({c["incident_id"] for c in cand_list}) \
            if (args.only_passing or args.fail_controls) else \
            sorted({i["incident_id"] for i in manifest.get(
                "incidents", [{"incident_id": c["incident_id"]}
                              for c in manifest["candidates"]])})
        ids += [(i, root / "incidents" / i) for i in needed]
        for i in needed:
            kind_by_id[i] = "incident"
    if args.only in ("all", "candidates"):
        ids += [(c["candidate_id"], root / "candidates" / c["candidate_id"])
                for c in cand_list]
        for c in cand_list:
            kind_by_id[c["candidate_id"]] = "candidate"
    if args.limit and args.sample:
        print("BLOCKED: --limit and --sample together would slice the sample. "
              "Use one.")
        return 2
    if args.limit:
        ids = ids[:args.limit]

    # DONE iff the run record exists. Disk is the state.
    src_by_id = dict(ids)
    spec_by_id = {rid: resolve_topology(topo_of.get(rid)) for rid, _ in ids}
    all_ids = [i for i, _ in ids]

    # ---- GATE B2: the harm definition must not be silently narrowed ------
    # docs/HARM-DEFINITION.md defines G as the ORACLE properties that hold on
    # the golden AS MEASURED IN CONTAINERLAB, and says: "Expected to be all 12;
    # if it is not, the pilot is broken and must be fixed before any candidate
    # is run." Nothing enforced that. run_phase3 computed `in_G` per candidate
    # and looked for regressions only inside it, so one property failing on a
    # topology's golden lab removed that property from the harm definition for
    # every candidate of that topology -- no error, no warning, and a lower
    # false-pass rate. This gate makes that state refuse to proceed.
    blocked_topos = golden_gate(out, needed_topos)
    if blocked_topos:
        print("\n" + "=" * 70)
        print("BLOCKED by the golden-property gate (|G| must equal "
              f"{len(PIDS)})")
        for tn, detail in sorted(blocked_topos.items()):
            print(f"  {tn:16s} {detail}")
        print("A property that does not hold on a HEALTHY golden is measuring")
        print("something other than what its text claims. Every candidate of")
        print("that topology would be judged against a narrowed definition of")
        print("harm and the false-pass rate would come out too low.")
        print("Fix the property or the golden. Do not proceed.")
        print("=" * 70)
        keep_ids = [i for i in all_ids
                    if topo_of.get(i) not in blocked_topos]
        dropped = len(all_ids) - len(keep_ids)
        if dropped:
            print(f"{dropped} runs belonging to blocked topologies will not "
                  f"be executed.")
        all_ids = keep_ids
        if not all_ids:
            return 2
    # ANALYSIS-PLAN.md 14.1, pre-registered 2026-09-04: a run whose lab was
    # invalid gets exactly one retry. Encoding it here rather than in the loop
    # means an interrupted collection resumes with the retry still owed -- the
    # ledger cannot forget it. A second LAB_INVALID is terminal and IS done.
    RETRY_STATUSES = ("LAB_INVALID",)
    MAX_ATTEMPTS = 2

    def _read_rec(rid):
        f = out / "runs" / rid / "run.json"
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"status": "UNREADABLE", "attempt": MAX_ATTEMPTS}

    def _retry_owed(rid):
        r = _read_rec(rid)
        return bool(r and r.get("status") in RETRY_STATUSES
                    and int(r.get("attempt", 1)) < MAX_ATTEMPTS)

    def _done(rid):
        return _read_rec(rid) is not None and not _retry_owed(rid)
    plan = plan_batch(all_ids, _done, args.batch_size)
    todo = list(plan["this_batch"])
    batch_no = ledger_integrity(out / "batch_log.jsonl")["batches"] + 1

    # CONTROL: one extra golden replicate per batch. pilot-v2 has no
    # exact_revert operator by design, so golden replicates are the standing
    # oracle-stability check -- an identical config measured repeatedly must
    # give an identical property vector every time.
    if todo and not args.no_control:
        cid = f"golden-r{batch_no:02d}"
        base_g = (f"golden-{needed_topos[0]}" if needed_topos else "golden")
        if not _done(cid):
            todo.insert(0, cid)
            src_by_id[cid] = src_by_id[base_g]
            spec_by_id[cid] = spec_by_id[base_g]
            kind_by_id[cid] = "golden_replicate"

    # ---- REPLICATE ARM: the label-noise floor ---------------------------
    # Calibration cannot be better than the rate at which the same candidate
    # reproduces its own label. The per-batch golden replicate above tests
    # reproducibility on the HEALTHY network, which is the easy case; this
    # arm tests it on real candidates, half of them chosen because their first
    # measurement sat near a boundary (partial loss, slow convergence, errored
    # property). A run id is `<candidate>~r1`; replicates are not manifest
    # candidates, so they never enter the deltas, outcomes or the dataset.
    replicate_ids = []
    if args.replicate:
        completed = []
        for rid in all_ids:
            if not kind_by_id.get(rid) == "candidate":
                continue
            rj = out / "runs" / rid / "run.json"
            if rj.exists():
                try:
                    completed.append((rid, json.loads(rj.read_text())))
                except Exception:                                  # noqa: BLE001
                    pass
        if not completed:
            print("--replicate: no completed candidate runs yet -- SKIPPING.")
            print("  Replicates re-run labs that already have a run.json, so")
            print("  they cannot be produced by the same invocation that")
            print("  creates them. Run this command again, unchanged, once the")
            print("  main batch has finished; the second pass will find the")
            print("  completed runs and replicate them.")
        else:
            half = max(1, args.replicate // 2)
            ranked = sorted(completed, key=lambda x: -boundary_score(x[1]))
            boundary = [r for r, _ in ranked[:half]]
            rest = [r for r, _ in completed if r not in set(boundary)]
            random_part = stratified_sample(
                rest, args.replicate - len(boundary),
                key=lambda rid: topo_of.get(rid))
            for base in sorted(set(boundary) | set(random_part)):
                rep = f"{base}~r1"
                if _done(rep):
                    continue
                replicate_ids.append(rep)
                src_by_id[rep] = src_by_id[base]
                spec_by_id[rep] = spec_by_id[base]
                kind_by_id[rep] = "candidate_replicate"
                topo_of[rep] = topo_of.get(base)
            todo += replicate_ids
            print(f"--replicate: {len(replicate_ids)} replicate labs "
                  f"({len(boundary)} boundary, "
                  f"{len(replicate_ids) - len(boundary)} random)")
    print(f"batch {batch_no}: {plan['already_done']} done, "
          f"{plan['pending']} pending, {len(todo)} this batch "
          f"(incl. control), {plan['remaining_after']} after")

    print(f"\n{len(ids)} labs to run. workdir={workdir}")
    t_start = time.time()
    done, failed = 0, []
    for n, rid in enumerate(todo, start=1):
        src = src_by_id[rid]
        eta = ""
        if done:
            per = (time.time() - t_start) / done
            eta = f"  eta {int(per * (len(todo) - n + 1) / 60)}m"
        print(f"[{n:3d}/{len(todo)}] {rid}{eta}", flush=True)
        sc = scenario_for(src, rid, scenarios)
        attempt = 1
        if _retry_owed(rid):
            attempt = 2
            arch = out / "runs" / f"{rid}.attempt1"
            if arch.exists():
                shutil.rmtree(arch)
            (out / "runs" / rid).rename(arch)
            print(f"        RETRY (attempt 2 of {MAX_ATTEMPTS}) -- attempt 1 "
                  f"was LAB_INVALID, archived to {arch.name}")
        rec = run_one(rid, src, workdir, lock, sc, out, args.keep_lab,
                      spec_by_id.get(rid), kind=kind_by_id.get(rid),
                      attempt=attempt)
        if rec["status"] == "LAB_INVALID" and attempt < MAX_ATTEMPTS:
            arch = out / "runs" / f"{rid}.attempt1"
            if arch.exists():
                shutil.rmtree(arch)
            (out / "runs" / rid).rename(arch)
            print(f"        LAB_INVALID -- retrying once "
                  f"(ANALYSIS-PLAN 14.1)")
            rec = run_one(rid, src, workdir, lock, sc, out, args.keep_lab,
                          spec_by_id.get(rid), kind=kind_by_id.get(rid),
                          attempt=2)
        done += 1
        mark = rec["status"]
        conv = rec.get("convergence", {}).get("seconds")
        print(f"        {mark}  converge={conv}s  "
              f"adj={rec.get('ospf_full_adjacency_pairs')}  "
              f"{rec.get('wall_seconds')}s")
        if mark not in ("OK", "NO_CONVERGENCE"):
            failed.append((rid, rec.get("error")))

    got = build_datasets(out, manifest)
    wj(out / "run_metadata.json", {
        "phase": 3, "run_utc": now(),
        "generator_version": GENERATOR_VERSION,
        "suite_version": SUITE_VERSION,
        "harm_definition_version": "1.1.0",
        "artifact_digest": lock.get("artifact_digest"),
        "snapshot_digest": lock.get("snapshot_digest"),
        "image_digests": IMAGE_DIGESTS,
        "platform": platform.platform(),
        "workdir": str(workdir),
        "labs_requested": len(all_ids), "labs_completed": done,
        "batch_size": args.batch_size, "batch_number": batch_no,
        "only_passing": bool(args.only_passing),
        # verify_phase3.py recomputes the expected run set from these plus the
        # manifest and the lock, rather than from whatever happened to run.
        "incident_filter": incident_filter or None,
        "candidate_filter": sorted(c["candidate_id"] for c in cand_list) if (
            incident_filter or args.sample) else None,
        "sample_size": args.sample or None,
        "fail_control_ids": fail_control_ids,
        # ANALYSIS-PLAN 14.1: reported as two numbers, never one.
        "lab_invalid_attempts": got.get("lab_invalid_attempts", []),
        "lab_invalid_terminal": got.get("lab_invalid_terminal", []),
        "lab_invalid_retry_policy": "ANALYSIS-PLAN.md 14.1 (max 1 retry)",
        "replicate_ids": replicate_ids,
        "harm_definition_secondary": "1.2.0",
        "labs_failed": [f[0] for f in failed],
        "convergence_timeout_s": clab.CONVERGE_TIMEOUT,
        "convergence_min_settle_s": clab.MIN_SETTLE_S,
        "convergence_poll_s": clab.CONVERGE_POLL_S,
        "convergence_stable_polls": clab.CONVERGE_STABLE_POLLS,
        "ping_count": clab.PING_COUNT,
        "wall_seconds": round(time.time() - t_start, 1),
        "note": "Measurement only. `label` is null; outcome_harm_v1 is a "
                "mechanical application of docs/HARM-DEFINITION.md v1.1.0 and "
                "is recomputable from containerlab_deltas.csv.",
    })

    dd = REPO / "docs" / "PHASE3-DATA-DICTIONARY.md"
    if dd.exists():
        shutil.copyfile(dd, out / "DATA-DICTIONARY.md")

    from collections import Counter
    import csv as _csv
    oc = Counter(o["outcome_harm_v1"] for o in got["outcome_rows"])
    batch_oc = Counter(o["outcome_harm_v1"] for o in got["outcome_rows"]
                       if o["candidate_id"] in todo)

    # CONTROL: every golden replicate must produce an identical property vector.
    ctrl, ctrl_msg = [], "no replicates yet"
    sp = out / "containerlab_summary.csv"
    if sp.exists():
        with sp.open(newline="", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        ctrl, ctrl_msg = golden_control(rows)

    reps = got.get("replicate_rows") or []
    if not reps:
        rep_msg = "no replicates run"
    else:
        ag = sum(1 for r in reps if r["outcome_agrees"])
        flips = [r for r in reps if not r["outcome_agrees"]]
        rep_msg = f"{ag}/{len(reps)} identical outcome on re-run"
        if flips:
            rep_msg += ("  <-- LABEL NOISE: " + ", ".join(
                f"{r['candidate_id']} {r['base_outcome']}->"
                f"{r['replicate_outcome']} on {r['differing_properties']}"
                for r in flips[:4]))

    ledger = out / "batch_log.jsonl"
    append_ledger(ledger, {
        "batch": batch_no, "utc": bnow(), "phase": 3, "ids": sorted(todo),
        "n": len(todo), "seconds": round(time.time() - t_start, 1),
        "safe": batch_oc.get("SAFE", 0), "harmful": batch_oc.get("HARMFUL", 0),
        "failed": [f[0] for f in failed], "control": ctrl_msg,
        "replicate_agreement": rep_msg})

    print_batch_summary(
        "PHASE 3 BATCH COMPLETE", plan,
        {"labs run (incl. control)": len(todo),
         "containerlab SAFE": batch_oc.get("SAFE", 0),
         "containerlab HARMFUL": batch_oc.get("HARMFUL", 0),
         "NO_CONVERGENCE": batch_oc.get("NO_CONVERGENCE", 0),
         "UNDETERMINED": batch_oc.get("UNDETERMINED", 0),
         "errors": len(failed)},
        {"labs completed": got["runs"],
         "cumulative SAFE": oc.get("SAFE", 0),
         "cumulative HARMFUL": oc.get("HARMFUL", 0),
         "golden control": ctrl_msg,
         "ledger duplicates (must be 0)":
             len(ledger_integrity(ledger)["duplicates"]),
         "replicate agreement": rep_msg,
         "labs retried / terminal invalid":
             f"{len(got.get('lab_invalid_attempts', []))} retried, "
             f"{len(got.get('lab_invalid_terminal', []))} still invalid "
             f"(excluded, counted)"},
        time.time() - t_start)
    for k, v in got.items():
        if k in ("summary", "measurements", "deltas", "outcomes",
                 "replicates"):
            print(f"  containerlab_{k}.csv  {v[0]} rows x {v[1]} cols")
    if failed:
        print(f"  {len(failed)} lab(s) failed:")
        for rid, e in failed[:10]:
            print(f"    {rid}: {str(e)[:120]}")
    print("next:  python3 pipeline/verify_phase3.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
