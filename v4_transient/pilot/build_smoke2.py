"""Engineering smoke 2 plan (amendment A3). ENGINEERING VALIDATION ONLY -- never pilot data, never a gate input.

    ./.venv/Scripts/python.exe v4_transient/pilot/build_smoke2.py

Validates the amended instrument on exactly the mechanisms and topologies the first smoke never ran in a lab:
the positive control (shutdown) of every topology, one no-op control, the blackhole mechanism on two topologies,
and one cost and one drain change on the two larger topologies (ECMP-rich ladder and campus). One run each.
Selection is by kind/role from the frozen manifest; no measured value is used.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]

SELECTION = [("t05_ring6", "shutdown"), ("t13_bowtie7", "shutdown"), ("t14_ladder8", "shutdown"),
             ("t15_campus12", "shutdown"), ("t05_ring6", "noop"), ("t05_ring6", "bh"), ("t13_bowtie7", "bh"),
             ("t14_ladder8", "cost-hi"), ("t15_campus12", "drain-hi")]


def main() -> int:
    man = json.loads((V4 / "manifests" / "pilot_manifest.json").read_text())
    runs = []
    for i, (topo, role) in enumerate(SELECTION):
        c = next(c for c in man["changes"] if c["topology"] == topo and c["role"] == role)
        runs.append({"run_id": f"SMOKE2-{c['change_id']}.rep1", "change_id": c["change_id"], "replicate": 1, "order": i})
    doc = {"plan": "smoke2", "purpose": "engineering validation of amendment A3 instrument; not pilot data",
           "selection": [list(x) for x in SELECTION], "runs": runs}
    (V4 / "manifests" / "run_plan_smoke2.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(runs, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
