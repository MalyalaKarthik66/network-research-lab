"""Randomised execution environments -- the manipulation Gate 0 tests.

WHY THIS EXISTS

The Stage 3 corpus contains no irreducible risk. Three measurements say so:

  * at Tier C, 283 distinct feature vectors over 299 rows and ZERO of the
    duplicated groups disagree on the outcome;
  * the pre-registered transient label v1.2.0 found 0 transient-only harm and
    0 adjacency flaps in 299 runs, so it is identical to v1.1.0;
  * the 10 Stage 1 replicate pairs agree 10/10.

Together those say the map (topology, fault, repair) -> outcome is
deterministic. P(harm | X) is therefore 0 or 1 and there is nothing to
calibrate: a "calibrated risk model" is a category error on such an artifact.

docs/HARM-DEFINITION.md v1.2.0 pre-registered the disqualifying condition in
advance -- "if the measured false-pass rate turns out to be entirely gap (a),
the honest conclusion is 'write more properties' ... there is no irreducible
component and no argument for a risk layer."

This module supplies the only thing that can make the target exist: variance in
the OUTCOME that is not a function of the CONFIGURATION. It perturbs the
environment the candidate is deployed into, never the candidate. The artifact
is still byte-verified against pilot.lock.json by the unmodified staging path;
what changes is what else is happening on the network while it converges.

WHAT IS RANDOMISED

One churn event per run: a transit link somewhere in the topology goes down at
a random moment during convergence and comes back up a few seconds later. That
is the most ordinary thing that happens in a real network, and it is exactly
the class of event a steady-state model-based verifier is designed not to
reason about.

The link is drawn uniformly from ALL transit links, including ones the repair
touched. Excluding those would be a judgement about which perturbations
"count", made before seeing any data. Instead the choice is recorded per run so
the analysis can condition on it afterwards.

WHAT IS NOT RANDOMISED

No measurement parameter. MIN_SETTLE_S, CONVERGE_TIMEOUT, CONVERGE_POLL_S,
CONVERGE_STABLE_POLLS and PING_COUNT keep their frozen values, so every outcome
stays comparable with the frozen corpus. The perturbation window is bounded
below MIN_SETTLE_S (45 s) by construction -- max delay 25 s plus max down 12 s
is 37 s -- so the link is always restored before the earliest possible
convergence decision. A run whose perturbation had not finished would be
measuring a network that was never deployed as specified, which is the S-020
mistake in a new costume.

SEEDING

The environment for (candidate, replicate) is drawn from a seed derived from
those two values only, so the whole experiment replays exactly. The seed is
recorded in the run record and is BANNED from X -- it is an execution fact, not
pre-deployment evidence.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Dict, List, Optional, Tuple

from . import clab

#: Bounds. The invariant MAX_DELAY_S + MAX_DOWN_S < clab.MIN_SETTLE_S is what
#: guarantees the perturbation is over before convergence can be declared.
MIN_DELAY_S, MAX_DELAY_S = 2, 25
MIN_DOWN_S, MAX_DOWN_S = 3, 12

assert MAX_DELAY_S + MAX_DOWN_S < clab.MIN_SETTLE_S, (
    "perturbation window must close before the earliest convergence decision")


def seed_for(candidate_id: str, replicate: int) -> int:
    """Deterministic per (candidate, replicate). Independent of wall clock,
    machine and run order, so the experiment is replayable."""
    h = hashlib.sha256(f"gate0|{candidate_id}|{replicate}".encode()).digest()
    return int.from_bytes(h[:8], "big")


def _uniform(seed: int, k: int, lo: int, hi: int) -> int:
    """Draw k-th independent uniform integer in [lo, hi] from `seed`."""
    h = hashlib.sha256(f"{seed}|{k}".encode()).digest()
    return lo + int.from_bytes(h[:4], "big") % (hi - lo + 1)


def sample_environment(candidate_id: str, replicate: int, spec,
                       scenario=None, before_scenario=None) -> Dict:
    """Draw one execution environment. Pure: no side effects, no clock."""
    seed = seed_for(candidate_id, replicate)
    transit = list(spec.transit)
    if not transit:
        return {"kind": "none", "reason": "topology has no transit links",
                "seed": seed, "candidate_id": candidate_id,
                "replicate": replicate}
    node, iface = transit[_uniform(seed, 0, 0, len(transit) - 1)][:2]
    env = {
        "kind": "link_churn",
        "seed": seed,
        "candidate_id": candidate_id,
        "replicate": replicate,
        "node": node,
        "iface": iface,
        "delay_s": _uniform(seed, 1, MIN_DELAY_S, MAX_DELAY_S),
        "down_s": _uniform(seed, 2, MIN_DOWN_S, MAX_DOWN_S),
        "n_transit_links": len(transit),
    }
    env["touched_by_repair"] = _touches(scenario, before_scenario, node, iface)
    return env


def _iface(scenario, node: str, iface: str):
    if scenario is None:
        return None
    dev = getattr(scenario, "devices", {}).get(node)
    if dev is None:
        return None
    for i in dev.ifaces:
        if getattr(i, "name", None) == iface:
            return i
    return None


def _touches(scenario, before_scenario, node: str, iface: str) -> Optional[bool]:
    """Did the REPAIR modify this interface, relative to the faulted state?

    Compares the candidate's Iface against the incident's. `Iface` is a
    dataclass, so equality is a true field-wise diff of address, admin state,
    OSPF area, cost, passive and network type.

    An earlier version asked only whether the interface EXISTS on the device,
    which is true of every transit interface and would have recorded
    "touched_by_repair": true for all 400 runs -- a column that looks like
    evidence and carries none.

    Returns None when it cannot be determined. Guessing False here would
    silently become "the perturbation was independent of the repair" in the
    analysis, which is exactly the claim this column exists to test.
    """
    if scenario is None or before_scenario is None:
        return None
    try:
        a, b = _iface(scenario, node, iface), _iface(before_scenario, node, iface)
        if a is None and b is None:
            return None
        if (a is None) != (b is None):
            return True
        return a != b
    except Exception:                                              # noqa: BLE001
        return None


class Perturbation:
    """Runs one churn event on a background thread, and records what happened.

    Every step is recorded including failures. A perturbation that did not
    actually take the link down produced an UNPERTURBED run, and calling it
    perturbed would silently contaminate the control/treatment contrast.
    """

    def __init__(self, lab: str, env: Dict):
        self.lab = lab
        self.env = env
        self.log: List[Dict] = []
        self.completed = False
        self.restored: Optional[bool] = None
        self._thread: Optional[threading.Thread] = None
        self._t0 = None

    def _link(self, state: str) -> Dict:
        r = clab.dexec(self.lab, self.env["node"],
                       ["ip", "link", "set", self.env["iface"], state])
        rec = {"action": state, "node": self.env["node"],
               "iface": self.env["iface"],
               "at_s": round(time.time() - self._t0, 2),
               "status": r.get("status"), "rc": r.get("rc"),
               "stderr": (r.get("stderr") or "")[-200:]}
        self.log.append(rec)
        return rec

    def _run(self) -> None:
        try:
            time.sleep(self.env["delay_s"])
            down = self._link("down")
            time.sleep(self.env["down_s"])
            up = self._link("up")
            self.restored = up.get("status") == "OK" and up.get("rc") == 0
            self.completed = (down.get("status") == "OK"
                              and down.get("rc") == 0 and self.restored)
        except Exception as exc:                                   # noqa: BLE001
            self.log.append({"action": "ERROR",
                             "error": f"{type(exc).__name__}: {exc}"})
            self.completed = False

    def start(self) -> "Perturbation":
        if self.env.get("kind") != "link_churn":
            self.completed = False
            return self
        self._t0 = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def join(self, timeout: float = 60.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def record(self) -> Dict:
        return {"environment": self.env, "events": self.log,
                "completed": self.completed, "link_restored": self.restored}


def install(get_env, sink: Dict) -> None:
    """Wrap clab.wait_for_convergence into CONVERGE -> CHURN -> RECONVERGE.

    Wrapping rather than forking run_one is deliberate: staging, byte
    verification against pilot.lock.json, deploy, the S-020 OSPF binding check,
    measurement, the LAB_INVALID retry policy and teardown all stay on the
    frozen code path, so a Gate 0 outcome and a Stage 3 outcome are produced by
    the same instrument. The only difference is what the network was doing.

    WHY TWO PHASES

    The first version churned during the initial convergence, and the smoke
    test showed why that measures nothing. First reachability is around t=27 s;
    a churn drawn from [2, 25] s therefore lands while the network is still
    coming up, so a probe failure cannot be distinguished from a network that
    has simply not converged yet. `transient_outage_after_reachable` was False
    for exactly the right reason -- traffic had never flowed, so nothing had
    been interrupted.

    An operator does not apply a change to a network that is already down. The
    question is what a disturbance does to a RUNNING network carrying traffic.
    So: converge fully, then perturb, then instrument the re-convergence. The
    returned record is the SECOND window, which is the one where a transient
    outage is both meaningful and detectable. The first window is preserved
    under `phase1` so nothing is discarded.

    A lab that never converged in phase 1 is not perturbed. Disturbing a
    network that was already broken would produce an uninterpretable label, and
    NO_CONVERGENCE is already a harm outcome on its own terms.
    """
    if getattr(clab.wait_for_convergence, "_gate0_wrapped", False):
        return
    original = clab.wait_for_convergence

    def wrapped(lab, routers, *a, **kw):
        env = get_env()
        first = original(lab, routers, *a, **kw)
        if env is None or env.get("kind") != "link_churn":
            sink["perturbation"] = {"environment": env, "events": [],
                                    "completed": False, "link_restored": None,
                                    "phase": "none"}
            return first
        if not first.get("converged"):
            sink["perturbation"] = {
                "environment": env, "events": [], "completed": False,
                "link_restored": None, "phase": "skipped_no_phase1_convergence",
                "reason": "phase 1 did not converge; perturbing an already "
                          "broken network yields an uninterpretable label"}
            return first
        p = Perturbation(lab, env).start()
        try:
            second = original(lab, routers, *a, **kw)
        finally:
            p.join()
        rec = p.record()
        rec["phase"] = "post_convergence"
        sink["perturbation"] = rec
        # the second window is the label-bearing one; keep the first verbatim
        second = dict(second)
        second["phase1"] = first
        second["seconds_phase1"] = first.get("seconds")
        second["converged_phase1"] = first.get("converged")
        return second

    wrapped._gate0_wrapped = True                                  # noqa: SLF001
    wrapped._original = original                                   # noqa: SLF001
    clab.wait_for_convergence = wrapped


def neighbour_flaps(conv: Dict) -> Dict:
    """Per-NEIGHBOUR adjacency flaps from a convergence history.

    clab.transient_summary counts flaps per ROUTER: `"Full" in join(states)`.
    A router with two neighbours where one drops still has "Full" somewhere in
    its state list, so the flap is invisible. The smoke test hit this exactly
    -- corea read `Full/-Init/-` while an adjacency was re-forming and scored
    0 flaps.

    clab.py is the frozen measurement path and is not edited. This computes the
    finer metric alongside it, from the same recorded history.
    """
    hist = conv.get("history") or []
    seen_full, flaps, per_router = set(), 0, {}
    for h in hist:
        for r, states in (h.get("neighbor_states") or {}).items():
            for idx, st in enumerate(states or []):
                key = (r, idx)
                if "Full" in str(st):
                    seen_full.add(key)
                elif key in seen_full:
                    flaps += 1
                    per_router[r] = per_router.get(r, 0) + 1
                    seen_full.discard(key)
    return {"neighbour_flaps_total": flaps, "neighbour_flaps_by_router": per_router,
            "flapped_any_neighbour": flaps > 0}


def uninstall() -> None:
    fn = clab.wait_for_convergence
    if getattr(fn, "_gate0_wrapped", False):
        clab.wait_for_convergence = fn._original                   # noqa: SLF001
