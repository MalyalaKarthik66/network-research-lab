"""Phase 2: turn each frozen property into a Batfish query, and serialise
everything Batfish says about it.

Two rules govern this module.

RULE 1 -- a harness error is never a FAIL.
    Every evaluation returns status OK or ERROR. A verdict of PASS/FAIL is only
    produced when status == OK. If Batfish throws, times out, or returns a shape
    we did not expect, that is status=ERROR with the exception text preserved,
    and verdict=None. Conflating the two would silently turn infrastructure
    flakiness into evidence about the network, which is the single easiest way
    to poison a dataset.

RULE 2 -- nothing is discarded.
    Every question's full DataFrame is written to disk as JSON records, traces
    included. Phase 4 decides what matters. This module decides nothing.

The SPEC/ORACLE split from nrl/properties.py is respected but NOT enforced here:
we evaluate all twelve properties in Batfish and record both verdicts. The gate
is SPEC-only, and that is applied by the runner. Recording Batfish's opinion on
the oracle-only properties costs nothing and buys a real analysis later --
it separates "the verifier could not have known" from "nobody asked it".
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

try:                                              # keep importable without pybatfish
    from pybatfish.datamodel import HeaderConstraints, PathConstraints
except ImportError:                               # pragma: no cover
    HeaderConstraints = PathConstraints = None

from .properties import PROPERTIES, properties_for
from .topologies import expected_ospf_pairs, host_attach

SUCCESS_DISPOSITIONS = {"ACCEPTED", "DELIVERED_TO_SUBNET", "EXITS_NETWORK"}

# HOST_ATTACH and EXPECTED_OSPF_PAIRS used to live here as module constants
# holding pilot-v1's addresses and router set -- including
# "10.255.0.6": ("edgeb", None), which is edgeb's loopback in pilot-v1 ONLY.
# Both were dead (start_location goes through host_attach(spec), and the
# adjacency check through expected_ospf_pairs(spec)) but a dead constant
# carrying one network's addresses is a loaded gun: reading it again is exactly
# how P11 came to target wan3/wan4/coreb. They are deleted rather than policed.
# Everything topology-dependent comes from the spec.


def start_location(src_ip: str, spec) -> str:
    """`spec` is required. It used to default to T2V1, so a caller that forgot
    to thread the topology silently probed pilot-v1's network."""
    node, iface = host_attach(spec)[src_ip]
    return f"@enter({node}[{iface}])" if iface else node


def headers(src: str, dst: str, app: str):
    """ICMP is expressed as protocol + type/code rather than an application
    name, because Batfish's application list is TCP/UDP-oriented."""
    if app == "ICMP":
        return HeaderConstraints(srcIps=src, dstIps=dst, ipProtocols=["ICMP"],
                                 icmpTypes=[8], icmpCodes=[0])
    return HeaderConstraints(srcIps=src, dstIps=dst, applications=app)


# ---------------------------------------------------------------------------
# serialisation -- everything Batfish returns must survive to disk
# ---------------------------------------------------------------------------

def jsonable(obj: Any) -> Any:
    """Best-effort recursive conversion. Falls back to str() rather than
    dropping a field: an unreadable string beats a missing column."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    for attr in ("__dict__",):
        d = getattr(obj, attr, None)
        if isinstance(d, dict) and d:
            return {"_type": type(obj).__name__,
                    **{k: jsonable(v) for k, v in d.items()}}
    return str(obj)


def frame_to_records(frame) -> List[Dict]:
    if frame is None:
        return []
    return [ {str(k): jsonable(v) for k, v in row.items()}
             for row in frame.to_dict(orient="records") ]


def serialise_traces(frame) -> List[Dict]:
    """Full hop-by-hop evidence. This is the most valuable single artefact in
    Phase 2 -- the verdict is one bit, the trace explains it."""
    out = []
    if frame is None or len(frame) == 0:
        return out
    for _, row in frame.iterrows():
        traces = row.get("Traces")
        if traces is None:
            continue
        for ti, tr in enumerate(traces):
            hops = []
            for hop in getattr(tr, "hops", []):
                hops.append({
                    "node": getattr(hop, "node", None),
                    "steps": [{"type": type(s).__name__,
                               "action": str(getattr(s, "action", "")),
                               "detail": jsonable(getattr(s, "detail", None))}
                              for s in getattr(hop, "steps", [])],
                })
            out.append({
                "flow": jsonable(row.get("Flow")),
                "trace_index": ti,
                "disposition": str(getattr(tr, "disposition", "")),
                "hop_count": len(hops),
                "path": [h["node"] for h in hops],
                "hops": hops,
            })
    return out


# ---------------------------------------------------------------------------
# per-property evaluation
# ---------------------------------------------------------------------------

def _result(pid, kind, in_spec, text, status, verdict=None, error=None,
            evidence=None, counterexamples=0, extra=None, seconds=0.0):
    return {
        "property_id": pid, "kind": kind, "in_spec": in_spec, "text": text,
        "status": status,                 # OK | ERROR
        "verdict": verdict,               # PASS | FAIL | None (None iff ERROR)
        "error": error,
        "counterexample_count": counterexamples,
        "evidence": evidence or {},
        "extra": extra or {},
        "seconds": round(seconds, 3),
    }


def evaluate_property(bf, prop: Dict, spec) -> Dict:
    pid, kind = prop["pid"], prop["kind"]
    t0 = time.time()
    try:
        if kind == "reachability":
            hc = headers(prop["src"], prop["dst"], prop["app"])
            pc = PathConstraints(startLocation=start_location(prop["src"], spec))
            fail = bf.q.reachability(pathConstraints=pc, headers=hc,
                                     actions="FAILURE").answer().frame()
            tr = bf.q.traceroute(startLocation=start_location(prop["src"], spec),
                                 headers=hc).answer().frame()
            traces = serialise_traces(tr)
            disps = [t["disposition"] for t in traces]
            verdict = "PASS" if (len(fail) == 0 and disps and
                                 all(d in SUCCESS_DISPOSITIONS for d in disps)) \
                      else "FAIL"
            return _result(pid, kind, prop["in_spec"], prop["text"], "OK",
                           verdict, counterexamples=len(fail),
                           evidence={"failure_flows": frame_to_records(fail),
                                     "traces": traces},
                           extra={"dispositions": disps,
                                  "n_paths": len(traces)},
                           seconds=time.time() - t0)

        if kind == "path_contains":
            hc = headers(prop["src"], prop["dst"], "ICMP")
            tr = bf.q.traceroute(startLocation=start_location(prop["src"], spec),
                                 headers=hc).answer().frame()
            traces = serialise_traces(tr)
            need = set(prop["must_traverse"])
            ok = bool(traces) and all(need.issubset(set(t["path"]))
                                      for t in traces)
            return _result(pid, kind, prop["in_spec"], prop["text"], "OK",
                           "PASS" if ok else "FAIL",
                           evidence={"traces": traces},
                           extra={"paths": [t["path"] for t in traces],
                                  "must_traverse": sorted(need)},
                           seconds=time.time() - t0)

        if kind == "no_loops":
            f = bf.q.detectLoops().answer().frame()
            return _result(pid, kind, prop["in_spec"], prop["text"], "OK",
                           "PASS" if len(f) == 0 else "FAIL",
                           counterexamples=len(f),
                           evidence={"loops": frame_to_records(f)},
                           seconds=time.time() - t0)

        if kind == "ospf_adjacencies":
            f = bf.q.ospfSessionCompatibility().answer().frame()
            pairs = {frozenset((str(r["Interface"]).split("[")[0],
                                str(r["Remote_Interface"]).split("[")[0]))
                     for _, r in f.iterrows()} if len(f) else set()
            want_pairs = expected_ospf_pairs(spec)
            established = (len(f) > 0 and
                           all(str(s) == "ESTABLISHED"
                               for s in f["Session_Status"]))
            # The COUNT is checked as well as the set, for two reasons.
            #
            # 1. prop["expected"] was not read at all here. properties_for()
            #    carefully resolves it per topology and as_yaml() records it in
            #    the frozen document, and the Batfish evaluator ignored it --
            #    so the negative control that asks for n+1 adjacencies returned
            #    PASS on all 20 goldens. A parameter nothing reads is not a
            #    parameter.
            # 2. p3_eval's version of P08 compares the COUNT
            #    (full_adjacency_pairs == prop["expected"]) while this one
            #    compared the SET. Same property id, two different functions,
            #    across the two phases whose disagreement is the entire
            #    measurement. That is the fourth instance of the pattern behind
            #    S-010, S-012 and S-013.
            count_ok = len(pairs) == int(prop["expected"])
            ok = pairs == want_pairs and established and count_ok
            return _result(pid, kind, prop["in_spec"], prop["text"], "OK",
                           "PASS" if ok else "FAIL",
                           evidence={"sessions": frame_to_records(f)},
                           extra={"observed_pairs":
                                  sorted(tuple(sorted(p)) for p in pairs),
                                  "expected_pairs":
                                  sorted(tuple(sorted(p)) for p in want_pairs),
                                  "n_sessions": len(f),
                                  "n_pairs": len(pairs),
                                  "expected_count": int(prop["expected"]),
                                  "count_matches": count_ok,
                                  "all_established": established},
                           seconds=time.time() - t0)

        if kind == "route_present":
            missing, per_node = [], {}
            for n in sorted(spec.routers):
                f = bf.q.routes(nodes=n, network=prop["prefix"]).answer().frame()
                per_node[n] = frame_to_records(f)
                if len(f) == 0:
                    missing.append(n)
            return _result(pid, kind, prop["in_spec"], prop["text"], "OK",
                           "PASS" if not missing else "FAIL",
                           counterexamples=len(missing),
                           evidence={"routes_by_node": per_node},
                           extra={"nodes_missing_route": missing,
                                  "prefix": prop["prefix"]},
                           seconds=time.time() - t0)

        if kind == "no_iface_down":
            f = bf.q.interfaceProperties(properties="Active").answer().frame()
            down = [str(r["Interface"]) for _, r in f.iterrows()
                    if not r["Active"]]
            return _result(pid, kind, prop["in_spec"], prop["text"], "OK",
                           "PASS" if not down else "FAIL",
                           counterexamples=len(down),
                           evidence={"interfaces": frame_to_records(f)},
                           extra={"down_interfaces": down},
                           seconds=time.time() - t0)

        return _result(pid, kind, prop["in_spec"], prop["text"], "ERROR",
                       error=f"no evaluator for kind={kind}",
                       seconds=time.time() - t0)

    except Exception as exc:                                    # noqa: BLE001
        return _result(pid, kind, prop["in_spec"], prop["text"], "ERROR",
                       error=f"{type(exc).__name__}: {exc}",
                       seconds=time.time() - t0)


def evaluate_all(bf, spec) -> List[Dict]:
    return [evaluate_property(bf, p, spec) for p in properties_for(spec)]


# ---------------------------------------------------------------------------
# the raw question sweep -- run on every candidate, nothing filtered
# ---------------------------------------------------------------------------

RAW_QUESTIONS = [
    ("initIssues",           lambda bf: bf.q.initIssues()),
    ("fileParseStatus",      lambda bf: bf.q.fileParseStatus()),
    ("parseWarning",         lambda bf: bf.q.parseWarning()),
    ("undefinedReferences",  lambda bf: bf.q.undefinedReferences()),
    ("unusedStructures",     lambda bf: bf.q.unusedStructures()),
    ("definedStructures",    lambda bf: bf.q.definedStructures()),
    ("nodeProperties",       lambda bf: bf.q.nodeProperties()),
    ("interfaceProperties",  lambda bf: bf.q.interfaceProperties()),
    ("ipOwners",             lambda bf: bf.q.ipOwners()),
    ("layer3Edges",          lambda bf: bf.q.layer3Edges()),
    ("ospfSessionCompatibility", lambda bf: bf.q.ospfSessionCompatibility()),
    ("ospfInterfaceConfiguration",
     lambda bf: bf.q.ospfInterfaceConfiguration()),
    ("ospfProcessConfiguration", lambda bf: bf.q.ospfProcessConfiguration()),
    ("routes",               lambda bf: bf.q.routes()),
    ("detectLoops",          lambda bf: bf.q.detectLoops()),
    ("multipathConsistency", lambda bf: bf.q.multipathConsistency()),
    ("subnetMultipathConsistency",
     lambda bf: bf.q.subnetMultipathConsistency()),
]


def run_raw_questions(bf) -> Dict[str, Dict]:
    out = {}
    for name, mk in RAW_QUESTIONS:
        t0 = time.time()
        try:
            frame = mk(bf).answer().frame()
            out[name] = {"status": "OK", "error": None,
                         "row_count": int(len(frame)),
                         "columns": [str(c) for c in frame.columns],
                         "records": frame_to_records(frame),
                         "seconds": round(time.time() - t0, 3)}
        except Exception as exc:                                # noqa: BLE001
            out[name] = {"status": "ERROR",
                         "error": f"{type(exc).__name__}: {exc}",
                         "row_count": None, "columns": [], "records": [],
                         "seconds": round(time.time() - t0, 3)}
    return out


def differential_reachability(bf, snapshot: str, reference: str,
                              src: str, dst: str, spec) -> Dict:
    """Flows whose fate differs between two snapshots.

    Run twice per candidate:
      vs the INCIDENT snapshot  -- feature-eligible; you have the broken config
                                   and the proposed change at inference time
      vs the GOLDEN snapshot    -- BANNED from X (see docs/LEAKAGE.md); if you
                                   had the healthy config you would deploy it.
                                   Collected anyway, for analysis only.
    """
    t0 = time.time()
    try:
        f = bf.q.differentialReachability(
            headers=HeaderConstraints(srcIps=src, dstIps=dst),
            pathConstraints=PathConstraints(
                startLocation=start_location(src, spec)),
        ).answer(snapshot=snapshot, reference_snapshot=reference).frame()
        return {"status": "OK", "error": None, "row_count": int(len(f)),
                "records": frame_to_records(f),
                "seconds": round(time.time() - t0, 3)}
    except Exception as exc:                                    # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
                "row_count": None, "records": [],
                "seconds": round(time.time() - t0, 3)}
