"""D1-D9 decisions for the V4 transient pilot: the schema that receives them, a blank template, strict validation,
and the approval check that gates the 20x5 pilot.

NOTHING IN THIS MODULE CHOOSES A SCIENTIFIC VALUE.
  * The template is entirely null / UNFROZEN.
  * No plan proposal (G1 30 %, G2 0.90, G3 80 %, G5 180 s, 90 %/80 % validity guard, ...) is encoded as a default.
  * Option lists mirror docs/PILOT-PREREGISTRATION.md §6-§12 and §16; docs/D1-D9-DECISION-SCHEMA.md explains every field.

The pilot is refused unless (check_approval):
  1. manifests/PREREG-APPROVAL.json exists, approved is true, approved_by / approved_utc are set;
  2. its prereg_sha256 equals the SHA-256 of docs/PILOT-PREREGISTRATION.md;
  3. its decisions_file (inside v4_transient) exists and its decisions_sha256 matches;
  4. the decisions document passes validate(): every D1-D9 block present, status FROZEN, rationale given, every
     applicable field explicitly set and in range, no inapplicable field set, no UNFROZEN marker anywhere;
  5. no section of the pre-registration other than the §0 legend still contains the UNFROZEN marker.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "v4-pilot-decisions-1"
UNFROZEN_MARKER = "UNFROZEN — REQUIRES DECISION BEFORE PILOT"
PREREG_REL = "docs/PILOT-PREREGISTRATION.md"
DECISIONS_REL = "config/pilot_decisions.json"
TEMPLATE_REL = "config/pilot_decisions.TEMPLATE.json"
SCHEMA_REL = "config/pilot_decisions.schema.json"
APPROVAL_REL = "manifests/PREREG-APPROVAL.json"
BASELINE_IDS = ("B2_r_exact", "B3_fib_entries_changed", "B4_microloop_potential", "B5_combined_analytic",
                "B6_graph_analytic")
HOST_PROXY_STATISTICS = ("resid_vs_order", "resid_vs_loadavg1", "resid_vs_wallclock")
BLOCK_META = ("status", "rationale", "prereg_section")


def _enum(*values):
    return {"kind": "enum", "values": list(values)}


def _num(lo=None, hi=None, lo_open=False, hi_open=False):
    return {"kind": "number", "lo": lo, "hi": hi, "lo_open": lo_open, "hi_open": hi_open}


def _int(values=None, lo=None, hi=None):
    return {"kind": "integer", "values": list(values) if values else None, "lo": lo, "hi": hi}


def _bool():
    return {"kind": "boolean"}


def _subset(values):
    return {"kind": "subset", "values": list(values)}


def _when(spec, *conds):
    """The field applies (and is then required) only when every (field, value) condition holds; otherwise it must be null."""
    return dict(spec, required_if=[{"field": f, "equals": v} for f, v in conds])


SPEC: Dict[str, Dict[str, Any]] = {
    "D1_noise_floor": {"prereg_section": "§6", "fields": {
        "floor_statistic": _enum("max_all_noop", "max_per_topology_noop", "mean_plus_k_sd_all_noop"),
        "k_sd": _when(_num(lo=0, lo_open=True), ("floor_statistic", "mean_plus_k_sd_all_noop")),
        "per_change_comparator": _enum("replicate_median", "replicate_mean"),
        "metrics": _enum("T1_only", "T1_and_probe_loss"),
        "probe_metric": _when(_enum("probe_loss_frac_window", "probe_lost_packet_s_window"),
                              ("metrics", "T1_and_probe_loss")),
        "probe_combination": _when(_enum("both_above_required", "either_above_sufficient"),
                                   ("metrics", "T1_and_probe_loss")),
        "all_noop_zero_handling": _enum("floor_is_zero", "minimum_resolution_floor"),
        "minimum_resolution_floor": _when(_num(lo=0), ("all_noop_zero_handling", "minimum_resolution_floor")),
        "probe_minimum_resolution_floor": _when(_num(lo=0), ("all_noop_zero_handling", "minimum_resolution_floor"),
                                                ("metrics", "T1_and_probe_loss")),
        # whether the resolution floor applies only in the all-zero case (§6 draft wording) or always as a lower bound
        "minimum_resolution_floor_scope": _when(_enum("only_when_all_noop_zero", "lower_bound_always"),
                                                ("all_noop_zero_handling", "minimum_resolution_floor")),
    }},
    "D2_G1_measurable": {"prereg_section": "§7", "fields": {
        "kill_if_share_above_floor_below": _num(lo=0, hi=1, lo_open=True),
        "denominator": _enum("all_population_changes", "changes_meeting_D7"),
    }},
    "D3_G3_repeatable": {"prereg_section": "§8", "fields": {
        "kill_if_within_share_above": _num(lo=0, hi=1, hi_open=True),
        "zero_within_share_clause": _enum("kills_only_if_G2_kills", "kills_independently", "report_only"),
        "zero_total_variance_handling": _enum("kill", "no_kill_report_undefined", "apply_zero_within_share_clause"),
    }},
    "D4_G4_host_invariance": {"prereg_section": "§9", "fields": {
        "metric": _enum("median_abs_diff_change_mean_T1", "median_abs_diff_change_mean_T1_over_pooled_within_sd"),
        "tolerance": _num(lo=0),
        "n_changes_on_second_host": _int(lo=1, hi=20),
        "second_host_available_for_this_pilot": _bool(),
        "untested_handling": _enum("cap_at_GO_WITH_FIXES", "NO_GO_until_tested", "single_host_proxy"),
        "proxy_statistics": _when(_subset(HOST_PROXY_STATISTICS), ("untested_handling", "single_host_proxy")),
        "proxy_kill_if_abs_rho_above": _when(_num(lo=0, hi=1, hi_open=True), ("untested_handling", "single_host_proxy")),
        "proxy_kill_requires_p_below": _when(_num(lo=0, hi=1, lo_open=True), ("untested_handling", "single_host_proxy")),
        "proxy_fail_handling": _when(_enum("NO_GO", "GO_WITH_FIXES"), ("untested_handling", "single_host_proxy")),
        "proxy_pass_counts_as_tested": _when(_bool(), ("untested_handling", "single_host_proxy")),
    }},
    "D5_G2_analytic_reducibility": {"prereg_section": "§10", "fields": {
        "unit": _enum("change_means", "runs"),
        "aggregator": _enum("max_over_B2_B6", "single_named_baseline"),
        "named_baseline": _when(_enum(*BASELINE_IDS), ("aggregator", "single_named_baseline")),
        "cross_validation": _enum("leave_one_topology_out"),
        "kill_if_r2_at_least": _num(hi=1),
        "ci_rule": _enum("point_estimate", "lower_95_bootstrap_bound"),
    }},
    "D6_G5_cost": {"prereg_section": "§11", "fields": {
        "kill_if_median_wall_s_above": _num(lo=0, lo_open=True),
    }},
    "D7_min_valid_replicates": {"prereg_section": "§12", "fields": {
        "min_valid_replicates_per_change": _int(values=(3, 4, 5)),
    }},
    "D8_validity_guard": {"prereg_section": "§12", "fields": {
        "min_valid_population_run_share": _num(lo=0, hi=1, lo_open=True),
    }},
    "D9_positive_control_sensitivity": {"prereg_section": "§16", "fields": {
        "min_positive_controls_above_floor": _int(values=(3, 4)),
        "invalid_positive_control_handling": _enum("counts_as_not_above", "excluded_from_count"),
    }},
}
DECISION_KEYS = tuple(SPEC)
#: pre-registration §6 option table: (a) max+median, (b) max+mean, (c) per-topology max+median, (d) mean+k*sd with median or mean
D1_ALLOWED_COMBINATIONS = {("max_all_noop", "replicate_median"), ("max_all_noop", "replicate_mean"),
                           ("max_per_topology_noop", "replicate_median"),
                           ("mean_plus_k_sd_all_noop", "replicate_median"),
                           ("mean_plus_k_sd_all_noop", "replicate_mean")}


def _check_value(spec: Dict[str, Any], v: Any) -> Optional[str]:
    kind = spec["kind"]
    if kind == "enum":
        return None if v in spec["values"] else f"must be one of {spec['values']}"
    if kind == "boolean":
        return None if isinstance(v, bool) else "must be true or false"
    if kind == "integer":
        if isinstance(v, bool) or not isinstance(v, int):
            return "must be an integer"
        if spec["values"] is not None and v not in spec["values"]:
            return f"must be one of {spec['values']}"
        if spec["lo"] is not None and v < spec["lo"]:
            return f"must be >= {spec['lo']}"
        if spec["hi"] is not None and v > spec["hi"]:
            return f"must be <= {spec['hi']}"
        return None
    if kind == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return "must be a finite number"
        lo, hi = spec["lo"], spec["hi"]
        if lo is not None and (v <= lo if spec["lo_open"] else v < lo):
            return f"must be {'>' if spec['lo_open'] else '>='} {lo}"
        if hi is not None and (v >= hi if spec["hi_open"] else v > hi):
            return f"must be {'<' if spec['hi_open'] else '<='} {hi}"
        return None
    if kind == "subset":
        if not isinstance(v, list) or not v:
            return f"must be a non-empty list drawn from {spec['values']}"
        if len(set(v)) != len(v) or any(x not in spec["values"] for x in v):
            return f"must contain distinct items from {spec['values']}"
        return None
    return f"unknown field kind {kind!r}"


def _marker_hits(obj: Any, path: str = "$") -> List[str]:
    hits: List[str] = []
    if isinstance(obj, str):
        if "UNFROZEN" in obj.upper():
            hits.append(path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits += _marker_hits(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _marker_hits(v, f"{path}[{i}]")
    return hits


def validate(doc: Any) -> List[str]:
    """Every problem that blocks the pilot. An empty list means the document is complete and schema-valid."""
    if not isinstance(doc, dict):
        return ["decisions document is not a JSON object"]
    problems = [f"{p}: contains an UNFROZEN marker" for p in _marker_hits(doc)]
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if doc.get("status") != "FROZEN":
        problems.append("top-level status must be 'FROZEN'")
    for f in ("decided_by", "decided_utc"):
        if not isinstance(doc.get(f), str) or not doc[f].strip():
            problems.append(f"{f} requires an explicit non-empty value")
    decs = doc.get("decisions")
    if not isinstance(decs, dict):
        return problems + ["decisions must be an object containing " + ", ".join(DECISION_KEYS)]
    for extra in sorted(set(decs) - set(DECISION_KEYS)):
        problems.append(f"decisions.{extra}: unknown decision key")
    for key, spec in SPEC.items():
        block = decs.get(key)
        if block is None:
            problems.append(f"{key}: missing (requires an explicit decision, pre-registration {spec['prereg_section']})")
            continue
        if not isinstance(block, dict):
            problems.append(f"{key}: must be an object")
            continue
        if block.get("status") != "FROZEN":
            problems.append(f"{key}.status must be 'FROZEN' (found {block.get('status')!r})")
        if not isinstance(block.get("rationale"), str) or not block["rationale"].strip():
            problems.append(f"{key}.rationale requires an explicit non-empty value")
        for extra in sorted(set(block) - set(spec["fields"]) - set(BLOCK_META)):
            problems.append(f"{key}.{extra}: unknown field")
        for fname, fspec in spec["fields"].items():
            v = block.get(fname)
            conds = fspec.get("required_if") or []
            applies = all(block.get(c["field"]) == c["equals"] for c in conds)
            where = f"{key}.{fname}"
            if not applies:
                if v is not None:
                    problems.append(f"{where}: must be null because " +
                                    " or ".join(f"{c['field']} != {c['equals']!r}" for c in conds))
                continue
            if v is None:
                problems.append(f"{where}: missing (requires an explicit scientific value)")
                continue
            msg = _check_value(fspec, v)
            if msg:
                problems.append(f"{where}: {msg}")
    d1 = decs.get("D1_noise_floor") if isinstance(decs.get("D1_noise_floor"), dict) else {}
    combo = (d1.get("floor_statistic"), d1.get("per_change_comparator"))
    if None not in combo and combo[0] in SPEC["D1_noise_floor"]["fields"]["floor_statistic"]["values"] \
            and combo not in D1_ALLOWED_COMBINATIONS:
        problems.append(f"D1_noise_floor: combination {combo} is not an option in pre-registration §6")
    d4 = decs.get("D4_G4_host_invariance") if isinstance(decs.get("D4_G4_host_invariance"), dict) else {}
    if d4.get("second_host_available_for_this_pilot") is True:
        problems.append("D4_G4_host_invariance.second_host_available_for_this_pilot: a two-host G4 measurement is "
                        "not implemented in v4_transient; it needs a pre-registration amendment and new code")
    return problems


def template() -> Dict[str, Any]:
    """Blank decisions document: every value null, every status UNFROZEN. Never valid."""
    return {"schema_version": SCHEMA_VERSION, "status": UNFROZEN_MARKER, "decided_by": None, "decided_utc": None,
            "decisions": {k: {"status": UNFROZEN_MARKER, "prereg_section": s["prereg_section"], "rationale": None,
                              **{f: None for f in s["fields"]}} for k, s in SPEC.items()}}


def _field_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    kind = spec["kind"]
    if kind == "enum":
        base: Dict[str, Any] = {"enum": spec["values"]}
    elif kind == "boolean":
        base = {"type": "boolean"}
    elif kind == "integer":
        base = {"type": "integer"}
        if spec["values"]:
            base["enum"] = spec["values"]
        if spec["lo"] is not None:
            base["minimum"] = spec["lo"]
        if spec["hi"] is not None:
            base["maximum"] = spec["hi"]
    elif kind == "number":
        base = {"type": "number"}
        if spec["lo"] is not None:
            base["exclusiveMinimum" if spec["lo_open"] else "minimum"] = spec["lo"]
        if spec["hi"] is not None:
            base["exclusiveMaximum" if spec["hi_open"] else "maximum"] = spec["hi"]
    else:
        base = {"type": "array", "items": {"enum": spec["values"]}, "minItems": 1, "uniqueItems": True}
    conds = spec.get("required_if")
    if not conds:
        return base
    return {"oneOf": [base, {"type": "null"}],
            "description": "non-null and required iff " + " and ".join(f"{c['field']} == {c['equals']!r}" for c in conds)
                           + "; otherwise must be null"}


def json_schema() -> Dict[str, Any]:
    props = {}
    for key, spec in SPEC.items():
        props[key] = {"type": "object", "description": f"pre-registration {spec['prereg_section']}",
                      "additionalProperties": False,
                      "required": ["status", "rationale"] + list(spec["fields"]),
                      "properties": {"status": {"const": "FROZEN"},
                                     "prereg_section": {"type": "string"},
                                     "rationale": {"type": "string", "minLength": 1},
                                     **{f: _field_schema(fs) for f, fs in spec["fields"].items()}}}
    return {"$schema": "http://json-schema.org/draft-07/schema#",
            "title": "V4 transient pilot decisions D1-D9",
            "description": ("Receives the approved D1-D9 values. Structural schema only: conditional requirements, the "
                            "§6 option combinations, the single-host restriction and UNFROZEN-marker rejection are "
                            "enforced by v4_transient/v4lib/decisions.py validate()."),
            "type": "object", "additionalProperties": False,
            "required": ["schema_version", "status", "decided_by", "decided_utc", "decisions"],
            "properties": {"schema_version": {"const": SCHEMA_VERSION}, "status": {"const": "FROZEN"},
                           "decided_by": {"type": "string", "minLength": 1},
                           "decided_utc": {"type": "string", "minLength": 1},
                           "decisions": {"type": "object", "additionalProperties": False,
                                         "required": list(DECISION_KEYS), "properties": props}}}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prereg_unfrozen_sections(text: str) -> List[str]:
    """Headings of pre-registration sections that still contain the UNFROZEN marker. The §0 legend is exempt."""
    bad: List[str] = []
    heading, legend = "(preamble)", False
    for line in text.splitlines():
        if line.startswith("## "):
            heading, legend = line.strip(), line.startswith("## 0.")
        if not legend and UNFROZEN_MARKER in line and heading not in bad:
            bad.append(heading)
    return bad


def check_approval(v4_root: Path, prereg: Optional[Path] = None,
                   approval: Optional[Path] = None) -> Tuple[bool, str]:
    """(ok, reason). Pure check with no side effects. See the module docstring for the five conditions."""
    v4_root = Path(v4_root)
    prereg = Path(prereg) if prereg else v4_root / PREREG_REL
    approval = Path(approval) if approval else v4_root / APPROVAL_REL
    if not approval.exists():
        return False, f"{APPROVAL_REL} missing"
    try:
        a = json.loads(approval.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"approval unreadable: {exc}"
    if not isinstance(a, dict) or a.get("approved") is not True:
        return False, "approval.approved is not true"
    for f in ("approved_by", "approved_utc"):
        if not isinstance(a.get(f), str) or not a[f].strip():
            return False, f"approval.{f} missing"
    if not prereg.exists():
        return False, "pre-registration file missing"
    if a.get("prereg_sha256") != sha256_file(prereg):
        return False, "pre-registration changed after approval (prereg_sha256 mismatch)"
    rel = a.get("decisions_file")
    if not isinstance(rel, str) or not rel.strip():
        return False, "approval.decisions_file missing"
    dpath = (v4_root / rel).resolve()
    try:
        dpath.relative_to(v4_root.resolve())
    except ValueError:
        return False, "approval.decisions_file must be inside v4_transient"
    if not dpath.exists():
        return False, f"decisions file {rel} missing"
    if a.get("decisions_sha256") != sha256_file(dpath):
        return False, "decisions file changed after approval (decisions_sha256 mismatch)"
    try:
        doc = json.loads(dpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"decisions file unreadable: {exc}"
    problems = validate(doc)
    if problems:
        return False, f"decisions invalid ({len(problems)} problem(s)): " + "; ".join(problems)
    bad = prereg_unfrozen_sections(prereg.read_text(encoding="utf-8"))
    if bad:
        return False, f"pre-registration still UNFROZEN in: {bad}"
    return True, "ok"


def load_approved(v4_root: Path) -> Tuple[bool, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(ok, reason, decisions_doc, approval_doc) for the real repository layout; documents only when ok."""
    ok, why = check_approval(v4_root)
    if not ok:
        return False, why, None, None
    appr = json.loads((Path(v4_root) / APPROVAL_REL).read_text(encoding="utf-8"))
    doc = json.loads((Path(v4_root) / appr["decisions_file"]).read_text(encoding="utf-8"))
    return True, "ok", doc, appr
