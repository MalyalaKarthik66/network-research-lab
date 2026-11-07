"""Engineering smoke 3 plan (amendments A4 and A5). ENGINEERING VALIDATION ONLY -- never pilot data, never a gate input.

    ./.venv/Scripts/python.exe v4_transient/pilot/build_smoke3.py

The run list and its purpose were fixed before implementation in docs/V4-LAUNCH-AUDIT-2.md §4 (Git commit b165c23):
  * the two A4 replacement positive controls (single revalidation; hard stop) and the two unchanged ones;
  * the two A4-retired controls, descriptively (predicted T1 = 0 by construction);
  * one no-op on the smallest and one on the largest topology (engineering floor, instrument null);
  * the four smoke-2 population scenarios again (old serial vs A5 runner on the same scenarios);
  * cost-mid on every topology, so the runtime sample has two population runs per topology like the pilot.
Selection is by fixed change id, cross-checked against topology and role; no measured value is used.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]

SELECTION = [("V4P-05", "t05_ring6", "shutdown"), ("V4P-06", "t15_campus12", "shutdown"),
             ("V4P-02", "t13_bowtie7", "shutdown"), ("V4P-03", "t14_ladder8", "shutdown"),
             ("V4P-01", "t05_ring6", "shutdown"), ("V4P-04", "t15_campus12", "shutdown"),
             ("V4N-01", "t05_ring6", "noop"), ("V4N-09", "t15_campus12", "noop"),
             ("V4C-05", "t05_ring6", "bh"), ("V4C-10", "t13_bowtie7", "bh"),
             ("V4C-11", "t14_ladder8", "cost-hi"), ("V4C-18", "t15_campus12", "drain-hi"),
             ("V4C-02", "t05_ring6", "cost-mid"), ("V4C-07", "t13_bowtie7", "cost-mid"),
             ("V4C-12", "t14_ladder8", "cost-mid"), ("V4C-17", "t15_campus12", "cost-mid")]


def main() -> int:
    man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
    changes = {c["change_id"]: c for c in man["changes"]}
    runs = []
    for i, (cid, topo, role) in enumerate(SELECTION):
        c = changes[cid]
        if (c["topology"], c["role"]) != (topo, role):
            raise SystemExit(f"{cid} is {c['topology']}/{c['role']}, expected {topo}/{role}")
        runs.append({"run_id": f"SMOKE3-{cid}.rep1", "change_id": cid, "replicate": 1, "order": i})
    doc = {"plan": "smoke3",
           "purpose": "engineering validation of amendments A4 (positive controls) and A5 (runner); not pilot data",
           "acceptance_criteria": "docs/V4-LAUNCH-AUDIT-2.md §4 (fixed in Git commit b165c23 before smoke 3)",
           "selection": [list(x) for x in SELECTION], "runs": runs}
    (V4 / "manifests" / "run_plan_smoke3.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(runs, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
