"""Offline staged directed-cost cycle model for six existing V4 cases.

Model inputs are limited to predeployment topology definitions and candidate
push plans. Runtime T1/FIB artifacts are deliberately not read here.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from nrl.topologies_v3 import resolve
from nrl.severity import Fabric

OUT = ROOT / "v4_transient" / "analysis" / "mechanistic"
CASES = [
    ("V4C-04", ROOT / "v4_transient" / "manifests" / "pilot_manifest.json"),
    ("EX-V4-01", Path(r"C:\Users\karth\v4_exploratory\manifest.json")),
    ("EX-V4-02", Path(r"C:\Users\karth\v4_exploratory\manifest.json")),
    ("EX-V4-03", Path(r"C:\Users\karth\v4_exploratory2\manifest.json")),
    ("EX-V4-04", Path(r"C:\Users\karth\v4_exploratory2\manifest.json")),
    ("EX-V4-05", Path(r"C:\Users\karth\v4_exploratory2\manifest.json")),
]


def load_case(case_id: str, manifest_path: Path) -> dict:
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    for candidate in doc["changes"]:
        cid = candidate.get("candidate_id", candidate.get("change_id"))
        if cid == case_id:
            return candidate
    raise KeyError(case_id)


def interface_neighbor(spec, node: str, interface: str) -> str:
    for a, ai, aa, b, bi, ba, subnet, label, cost in spec.links:
        if a == node and ai == interface:
            return b
        if b == node and bi == interface:
            return a
    raise KeyError(f"{node}:{interface}")


def interface_operations(spec, push_plan: dict) -> list[dict]:
    """Extract cost operations in the exact dict/device/interface command order."""
    operations = []
    for node, commands in push_plan.items():
        current_interface = None
        for command in commands:
            if command.startswith("interface "):
                current_interface = command.split(maxsplit=1)[1]
            elif command.startswith("ip ospf cost "):
                if current_interface is None:
                    raise ValueError(f"cost command without interface: {command}")
                neighbor = interface_neighbor(spec, node, current_interface)
                operations.append({
                    "node": node,
                    "interface": current_interface,
                    "neighbor": neighbor,
                    "new_cost": int(command.split()[-1]),
                    "command": command,
                })
    return operations


def directed_costs(spec) -> dict[tuple[str, str], float]:
    costs = {}
    for a, ai, aa, b, bi, ba, subnet, label, cost in spec.links:
        if a in spec.routers and b in spec.routers:
            costs[(a, b)] = cost
            costs[(b, a)] = cost
    return costs


def directed_next_hops(spec, costs: dict[tuple[str, str], float], destination: str) -> dict[str, list[str]]:
    """Compute all shortest next hops toward a destination under directed costs."""
    routers = sorted(spec.routers)
    distances = {destination: 0.0}
    for _ in range(len(routers)):
        changed = False
        for (source, target), cost in costs.items():
            if target in distances:
                value = cost + distances[target]
                if source not in distances or value < distances[source]:
                    distances[source] = value
                    changed = True
        if not changed:
            break
    return {
        source: sorted(
            target for (src, target), cost in costs.items()
            if src == source and target in distances
            and math.isclose(distances[source], cost + distances[target], rel_tol=0.0, abs_tol=1e-9)
        )
        for source in routers
        if source != destination
    }


def flow_cycle(next_hops: dict[str, list[str]], source: str, destination: str) -> tuple[bool, list[str]]:
    sequence = []
    seen = set()
    current = source
    for _ in range(len(next_hops) + 2):
        if current == destination:
            return False, sequence + [current]
        if current in seen:
            start = sequence.index(current)
            return True, sequence[start:] + [current]
        seen.add(current)
        sequence.append(current)
        choices = next_hops.get(current, [])
        if not choices:
            return False, sequence
        current = choices[0]
    return True, sequence


def stage_features(spec, push_plan: dict) -> dict:
    endpoints = [(router, router) for router in sorted(spec.routers)]
    endpoints += [(host, router) for host, router in sorted(spec.hosts.items())]
    flow_count = sum(1 for source, destination in endpoints for dst_name, dst_router in endpoints
                     if source != dst_name and router_for_source(spec, source) != dst_router)
    costs = directed_costs(spec)
    operations = interface_operations(spec, push_plan)
    stages = []
    for index, operation in enumerate(operations, 1):
        costs[(operation["node"], operation["neighbor"])] = operation["new_cost"]
        cycle_flows = []
        cycle_lengths = []
        no_path_flows = []
        for source_name, _ in endpoints:
            source_router = router_for_source(spec, source_name)
            for destination_name, destination_router in endpoints:
                if source_name == destination_name or source_router == destination_router:
                    continue
                next_hops = directed_next_hops(spec, costs, destination_router)
                has_cycle, sequence = flow_cycle(next_hops, source_router, destination_router)
                flow_id = f"{source_name}->{destination_name}"
                if has_cycle:
                    cycle_flows.append(flow_id)
                    cycle_lengths.append(len(sequence) - 1)
                elif not sequence or sequence[-1] != destination_router:
                    no_path_flows.append(flow_id)
        stages.append({
            "index": index,
            "operation": operation,
            "cycle_flow_count": len(cycle_flows),
            "cycle_flow_fraction": len(cycle_flows) / flow_count if flow_count else 0.0,
            "distinct_cycle_lengths": sorted(set(cycle_lengths)),
            "max_cycle_length": max(cycle_lengths) if cycle_lengths else 0,
            "no_path_flow_count": len(no_path_flows),
            "cycle_flows": cycle_flows,
        })
    cycle_stages = [stage for stage in stages if stage["cycle_flow_count"]]
    return {
        "operations": operations,
        "n_operations": len(operations),
        "n_intermediate_states": len(stages),
        "cycle_state_count": len(cycle_stages),
        "max_cycle_flow_fraction": max((stage["cycle_flow_fraction"] for stage in stages), default=0.0),
        "max_cycle_flow_count": max((stage["cycle_flow_count"] for stage in stages), default=0),
        "max_cycle_length": max((stage["max_cycle_length"] for stage in stages), default=0),
        "total_cycle_flow_state_exposure": sum(stage["cycle_flow_count"] for stage in stages),
        "max_no_path_flow_count": max((stage["no_path_flow_count"] for stage in stages), default=0),
        "stages": stages,
    }


def hybrid_state_features(spec, push_plan: dict) -> dict:
    """Mixed old/new per-router forwarding maps under serial device updates.

    This is a predeployment dependency model: a router is switched from its
    golden next-hop map to its final next-hop map when its serialized push
    begins. It deliberately models susceptibility, not runtime duration.
    """
    fabric = Fabric(spec)
    old = fabric.paths()
    cost_override = {}
    for node, commands in push_plan.items():
        interface = None
        for command in commands:
            if command.startswith("interface "):
                interface = command.split(maxsplit=1)[1]
            elif command.startswith("ip ospf cost "):
                new_cost = int(command.split()[-1])
                neighbor = interface_neighbor(spec, node, interface)
                for a, ai, aa, b, bi, ba, subnet, label, old_cost in spec.links:
                    if a == node and ai == interface or b == node and bi == interface:
                        cost_override[tuple(sorted((a, b)))] = new_cost
    final = fabric.paths(cost_override=cost_override)
    changed_routers = list(push_plan)
    endpoints = [(r, r) for r in sorted(spec.routers)]
    endpoints += [(h, r) for h, r in sorted(spec.hosts.items())]
    flow_count = sum(1 for source, source_router in endpoints for destination, destination_router in endpoints
                     if source != destination and source_router != destination_router)
    stages = []
    for stage_index in range(len(changed_routers) + 1):
        active = set(changed_routers[:stage_index])
        cycles = []
        for source, source_router in endpoints:
            for destination, destination_router in endpoints:
                if source == destination or source_router == destination_router:
                    continue
                current = source_router
                sequence = []
                for _ in range(len(spec.routers) + 2):
                    if current == destination_router:
                        break
                    if current in sequence:
                        cycles.append({"flow_id": f"{source}->{destination}", "cycle": sequence[sequence.index(current):] + [current]})
                        break
                    sequence.append(current)
                    path_map = final if current in active else old
                    path = path_map.get((current, destination))
                    if not path or len(path) < 2:
                        break
                    current = path[1]
        stages.append({"stage": stage_index, "active_routers": sorted(active), "cycle_flows": cycles})
    return {
        "hybrid_cycle_state_count": sum(bool(stage["cycle_flows"]) for stage in stages),
        "hybrid_max_cycle_flow_count": max((len(stage["cycle_flows"]) for stage in stages), default=0),
        "hybrid_max_cycle_flow_fraction": max((len(stage["cycle_flows"]) / flow_count for stage in stages), default=0.0),
        "hybrid_stages": stages,
    }


def router_for_source(spec, source: str) -> str:
    return dict(spec.hosts).get(source, source)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for case_id, manifest_path in CASES:
        candidate = load_case(case_id, manifest_path)
        spec = resolve(candidate["topology"])
        features = stage_features(spec, candidate["push_plan"])
        hybrid = hybrid_state_features(spec, candidate["push_plan"])
        result = {
            "candidate_id": case_id,
            "topology": candidate["topology"],
            "role": candidate.get("role"),
            "mechanism": candidate.get("mechanism"),
            "target": candidate.get("target"),
            "predeployment_features": candidate.get("features", {}),
            "mechanistic_features": features,
            "hybrid_features": hybrid,
            "model_input_sources": [str(manifest_path), "nrl/topologies_v3.py"],
            "runtime_artifacts_used_as_model_input": False,
        }
        results.append(result)
    (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    fields = ["candidate_id", "topology", "mechanism", "n_operations", "n_intermediate_states",
              "cycle_state_count", "max_cycle_flow_fraction", "max_cycle_flow_count",
              "max_cycle_length", "total_cycle_flow_state_exposure", "max_no_path_flow_count",
              "hybrid_cycle_state_count", "hybrid_max_cycle_flow_count", "hybrid_max_cycle_flow_fraction"]
    with (OUT / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = {field: result["mechanistic_features"].get(field, result.get(field)) for field in fields}
            row.update({field: result["hybrid_features"].get(field) for field in fields
                        if field.startswith("hybrid_")})
            row.update({"candidate_id": result["candidate_id"], "topology": result["topology"],
                        "mechanism": result["mechanism"]})
            writer.writerow(row)
    for result in results:
        print(result["candidate_id"], json.dumps(result["mechanistic_features"], separators=(",", ":")))


if __name__ == "__main__":
    import csv
    main()
