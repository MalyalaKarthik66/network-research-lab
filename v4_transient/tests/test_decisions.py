"""Offline tests of the D1-D9 schema and validation. No lab, no smoke or pilot data.
    ./.venv/Scripts/python.exe v4_transient/tests/test_decisions.py
"""
import io
import json
import sys
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4)); sys.path.insert(0, str(HERE.parent))

from v4lib import decisions as DEC                                   # noqa: E402
from _fixtures import fixture_decisions                              # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


def probs(doc):
    return DEC.validate(doc)


def mentions(problems, needle):
    return any(needle in p for p in problems)


# template is never valid, and reports every decision
tp = probs(DEC.template())
check("blank template is invalid", len(tp) > 0)
for k in DEC.DECISION_KEYS:
    check(f"template reports {k} unresolved", mentions(tp, k))
check("template carries the UNFROZEN marker", mentions(tp, "UNFROZEN"))

# fixture (synthetic, not a decision) is valid -> validation is not simply always-refuse
check("synthetic fixture validates cleanly", probs(fixture_decisions()) == [], probs(fixture_decisions()))


def non_null_example(fs):
    k = fs["kind"]
    return {"enum": fs.get("values", [None])[0] if k == "enum" else None, "boolean": True, "integer": 5,
            "number": 1.0, "subset": [fs["values"][0]] if k == "subset" else None}[k]


for key, spec in DEC.SPEC.items():
    doc = fixture_decisions(); del doc["decisions"][key]
    check(f"{key} absent -> refused", mentions(probs(doc), key))
    doc = fixture_decisions(); doc["decisions"][key]["status"] = DEC.UNFROZEN_MARKER
    check(f"{key} status UNFROZEN -> refused", mentions(probs(doc), f"{key}.status"))
    doc = fixture_decisions(); doc["decisions"][key]["rationale"] = None
    check(f"{key} rationale missing -> refused", mentions(probs(doc), f"{key}.rationale"))
    doc = fixture_decisions(); doc["decisions"][key]["surprise"] = 1
    check(f"{key} unknown field -> refused", mentions(probs(doc), f"{key}.surprise"))
    for fname, fs in spec["fields"].items():
        base = fixture_decisions()
        block = base["decisions"][key]
        applies = all(block.get(c["field"]) == c["equals"] for c in (fs.get("required_if") or []))
        if applies:
            doc = fixture_decisions(); doc["decisions"][key][fname] = None
            check(f"{key}.{fname} null -> refused", mentions(probs(doc), f"{key}.{fname}"))
            doc = fixture_decisions(); doc["decisions"][key].pop(fname)
            check(f"{key}.{fname} absent -> refused", mentions(probs(doc), f"{key}.{fname}"))
            doc = fixture_decisions(); doc["decisions"][key][fname] = DEC.UNFROZEN_MARKER
            check(f"{key}.{fname} = UNFROZEN marker -> refused", mentions(probs(doc), f"{key}.{fname}"))
        else:
            doc = fixture_decisions(); doc["decisions"][key][fname] = non_null_example(fs)
            check(f"{key}.{fname} set although not applicable -> refused", mentions(probs(doc), f"{key}.{fname}"))

# top level
for field, bad in (("status", DEC.UNFROZEN_MARKER), ("status", "DRAFT"), ("decided_by", ""), ("decided_utc", None),
                   ("schema_version", "other")):
    doc = fixture_decisions(); doc[field] = bad
    check(f"top-level {field}={bad!r} -> refused", probs(doc) != [])
doc = fixture_decisions(); doc["decisions"]["D10_extra"] = {}
check("unknown decision key -> refused", mentions(probs(doc), "D10_extra"))
doc = fixture_decisions(); doc["decisions"]["D6_G5_cost"]["rationale"] = "still unfrozen, decide later"
check("any string containing 'unfrozen' -> refused", mentions(probs(doc), "UNFROZEN marker"))
check("non-object document -> refused", probs([]) != [])

# types, ranges and option sets
cases = [
    ("D5_G2_analytic_reducibility", "unit", "folds"), ("D2_G1_measurable", "kill_if_share_above_floor_below", 0),
    ("D2_G1_measurable", "kill_if_share_above_floor_below", 1.5), ("D3_G3_repeatable", "kill_if_within_share_above", 1),
    ("D5_G2_analytic_reducibility", "kill_if_r2_at_least", 1.01), ("D6_G5_cost", "kill_if_median_wall_s_above", 0),
    ("D6_G5_cost", "kill_if_median_wall_s_above", True), ("D6_G5_cost", "kill_if_median_wall_s_above", float("nan")),
    ("D7_min_valid_replicates", "min_valid_replicates_per_change", 2), ("D7_min_valid_replicates", "min_valid_replicates_per_change", 4.0),
    ("D8_validity_guard", "min_valid_population_run_share", 0), ("D9_positive_control_sensitivity", "min_positive_controls_above_floor", 2),
    ("D4_G4_host_invariance", "tolerance", -0.1), ("D4_G4_host_invariance", "n_changes_on_second_host", 0),
    ("D5_G2_analytic_reducibility", "cross_validation", "random_5_fold"),
]
for key, f, v in cases:
    doc = fixture_decisions(); doc["decisions"][key][f] = v
    check(f"{key}.{f}={v!r} -> refused", mentions(probs(doc), f"{key}.{f}"))

# conditional requirements
doc = fixture_decisions(); doc["decisions"]["D1_noise_floor"]["floor_statistic"] = "mean_plus_k_sd_all_noop"
check("mean_plus_k_sd without k_sd -> refused", mentions(probs(doc), "D1_noise_floor.k_sd"))
doc["decisions"]["D1_noise_floor"]["k_sd"] = 1.5
check("mean_plus_k_sd with k_sd -> valid", probs(doc) == [], probs(doc))
doc = fixture_decisions(); doc["decisions"]["D1_noise_floor"].update(floor_statistic="max_per_topology_noop", per_change_comparator="replicate_mean")
check("§6 option combination not in pre-registration -> refused", mentions(probs(doc), "combination"))
doc = fixture_decisions(); doc["decisions"]["D1_noise_floor"]["metrics"] = "T1_and_probe_loss"
check("probe loss chosen without probe_metric/probe_combination -> refused",
      mentions(probs(doc), "D1_noise_floor.probe_metric") and mentions(probs(doc), "D1_noise_floor.probe_combination"))
doc["decisions"]["D1_noise_floor"].update(probe_metric="probe_loss_frac_window", probe_combination="either_above_sufficient")
check("probe loss fully specified -> valid", probs(doc) == [], probs(doc))
doc["decisions"]["D1_noise_floor"]["all_noop_zero_handling"] = "minimum_resolution_floor"
check("resolution floor chosen without values -> refused",
      mentions(probs(doc), "D1_noise_floor.minimum_resolution_floor") and mentions(probs(doc), "D1_noise_floor.probe_minimum_resolution_floor"))
doc = fixture_decisions(); doc["decisions"]["D4_G4_host_invariance"]["untested_handling"] = "single_host_proxy"
check("single-host proxy without its parameters -> refused", mentions(probs(doc), "D4_G4_host_invariance.proxy_statistics"))
doc["decisions"]["D4_G4_host_invariance"].update(proxy_statistics=["resid_vs_order"], proxy_kill_if_abs_rho_above=0.55,
                                                  proxy_kill_requires_p_below=0.01, proxy_fail_handling="GO_WITH_FIXES",
                                                  proxy_pass_counts_as_tested=False)
check("single-host proxy fully specified -> valid", probs(doc) == [], probs(doc))
doc["decisions"]["D4_G4_host_invariance"]["proxy_statistics"] = ["resid_vs_order", "resid_vs_order"]
check("duplicate proxy statistic -> refused", mentions(probs(doc), "proxy_statistics"))
doc = fixture_decisions(); doc["decisions"]["D4_G4_host_invariance"]["second_host_available_for_this_pilot"] = True
check("second host claimed (not implemented) -> refused", mentions(probs(doc), "two-host"))
doc = fixture_decisions(); doc["decisions"]["D5_G2_analytic_reducibility"]["aggregator"] = "single_named_baseline"
check("single named baseline without a name -> refused", mentions(probs(doc), "named_baseline"))

doc = fixture_decisions(); doc["decisions"]["D1_noise_floor"].update(all_noop_zero_handling="minimum_resolution_floor",
                                                                    minimum_resolution_floor=0.01)
check("resolution floor without its scope -> refused", mentions(probs(doc), "minimum_resolution_floor_scope"))
doc["decisions"]["D1_noise_floor"]["minimum_resolution_floor_scope"] = "lower_bound_always"
check("resolution floor with scope -> valid", probs(doc) == [], probs(doc))
doc = fixture_decisions(); doc["decisions"]["D1_noise_floor"]["minimum_resolution_floor_scope"] = "lower_bound_always"
check("scope set while floor_is_zero -> refused", mentions(probs(doc), "minimum_resolution_floor_scope"))

# generated files are exactly the generator output
tpl_p, sch_p = V4 / DEC.TEMPLATE_REL, V4 / DEC.SCHEMA_REL
check("template file matches generator", tpl_p.exists() and json.loads(tpl_p.read_text(encoding="utf-8")) == DEC.template())
check("schema file matches generator", sch_p.exists() and json.loads(sch_p.read_text(encoding="utf-8")) == DEC.json_schema())

# the frozen decisions on disk: valid, identical to the freeze tool, resolution floor derived from design constants
import importlib.util                                                # noqa: E402
fspec = importlib.util.spec_from_file_location("freeze", V4 / "tools" / "freeze_pilot_decisions.py")
freeze = importlib.util.module_from_spec(fspec); fspec.loader.exec_module(freeze)
dpath = V4 / DEC.DECISIONS_REL
frozen = json.loads(dpath.read_text(encoding="utf-8")) if dpath.exists() else None
check("frozen decisions file exists", frozen is not None)
check("frozen decisions validate", frozen is not None and probs(frozen) == [], frozen and probs(frozen))
check("frozen decisions equal the freeze tool's decisions (no hand edits)",
      frozen is not None and freeze.without_time(frozen) == freeze.without_time(freeze.build()))
check("frozen decisions: stricter-than-plan choices are recorded as stated in pre-registration §19",
      frozen is not None and frozen["decisions"]["D3_G3_repeatable"]["kill_if_within_share_above"] == 0.5
      and frozen["decisions"]["D5_G2_analytic_reducibility"]["kill_if_r2_at_least"] == 0.8
      and frozen["decisions"]["D2_G1_measurable"]["kill_if_share_above_floor_below"] == 0.3
      and frozen["decisions"]["D6_G5_cost"]["kill_if_median_wall_s_above"] == 180.0
      and frozen["decisions"]["D4_G4_host_invariance"]["untested_handling"] == "cap_at_GO_WITH_FIXES")
from v4lib.labops import PROBE_INTERVAL_S                            # noqa: E402
man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text(encoding="utf-8"))
nmin = min(c["features"]["n_flows_carried_pred"] for c in man["changes"] if c["kind"] == "population")
check("D1 resolution floor = probe interval / fewest carried flows (design constants only)",
      frozen is not None and frozen["decisions"]["D1_noise_floor"]["minimum_resolution_floor"] == PROBE_INTERVAL_S / nmin
      and nmin == 72, (nmin, frozen and frozen["decisions"]["D1_noise_floor"]["minimum_resolution_floor"]))
for key in DEC.DECISION_KEYS:
    check(f"{key}: rationale recorded", frozen is not None and len(frozen["decisions"][key]["rationale"]) > 80)
ok, why = DEC.check_approval(V4)
check("approval check passes on the real repository (hashes current)", ok, why)
appr = json.loads((V4 / DEC.APPROVAL_REL).read_text(encoding="utf-8")) if (V4 / DEC.APPROVAL_REL).exists() else {}
check("approval hashes equal files on disk",
      appr.get("prereg_sha256") == DEC.sha256_file(V4 / DEC.PREREG_REL)
      and appr.get("decisions_sha256") == DEC.sha256_file(dpath))
check("pre-registration contains no UNFROZEN marker outside §0",
      DEC.prereg_unfrozen_sections((V4 / DEC.PREREG_REL).read_text(encoding="utf-8")) == [])

# no plan proposal is hard-coded as a numeric literal in the decision/gate/runner code
forbidden = {0.3, 0.8, 0.9, 180.0}
for rel in ("v4lib/decisions.py", "v4lib/gates.py", "pilot/run_pilot.py"):
    src = (V4 / rel).read_text(encoding="utf-8")
    nums = [t.string for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.NUMBER]
    hits = [n for n in nums if float(n.replace("_", "")) in forbidden]
    check(f"{rel}: no numeric literal equal to a plan proposal (0.3, 0.8, 0.9, 180)", not hits, hits)

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
