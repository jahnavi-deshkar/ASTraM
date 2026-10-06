"""Run and report reproducible ASTraM campus traffic scenarios.

Execute from the repository root:
    python scripts/run_scenarios.py
    python scripts/run_scenarios.py --scenario morning
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.flow_solver import (  # noqa: E402
    BoundaryFlowError,
    NetworkDataError,
    OptimizationError,
    TrafficMatrixSolver,
)
from app.services.traffic_physics import BPRCalculator, SignalOptimizer  # noqa: E402


NETWORK_PATH = ROOT / "data" / "mit_wpu_roads.geojson"
LOGGER = logging.getLogger("astram.scenarios")
SIGNAL_PHASE_EDGES = {
    "north_approach": ("e13", "e11"),
    "east_approach": ("e5", "e15"),
    "south_approach": ("e8", "e10"),
    "west_approach": ("e7", "e17"),
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "morning": {
        "title": "Scenario 1 - Standard Morning Rush",
        "description": "Gate 1 supplies 120 veh/hr; Paud Road and West Parking are balancing exits.",
        "boundary_flows": {"node_1": 120.0, "node_7": -50.0, "node_8": -70.0},
        "closed_edges": (),
    },
    "evening": {
        "title": "Scenario 2 - Evening Mass Exit",
        "description": "Paud Road node_7 models the unrepresented Gate 3 exit at 140 veh/hr; Gate 1 supplies the balancing inflow.",
        "boundary_flows": {"node_1": 140.0, "node_7": -140.0},
        "closed_edges": (),
    },
    "closure": {
        "title": "Scenario 3 - Gate 1 Main Road Closure",
        "description": "Edge e1 is closed; Gate 1 demand is routed through the schematic Gate 1 North Bypass (e19).",
        "boundary_flows": {"node_1": 90.0, "node_7": -20.0, "node_8": -70.0},
        "closed_edges": ("e1",),
    },
}


def _print_scenario_header(config: dict[str, Any]) -> None:
    print("\n" + "=" * 112)
    print(config["title"])
    print(config["description"])
    boundary = config["boundary_flows"]
    print("Boundary vector B: " + ", ".join(f"{node}={flow:+.0f}" for node, flow in boundary.items()))
    if config["closed_edges"]:
        print("Closed links: " + ", ".join(config["closed_edges"]))
    print("=" * 112)


def run_scenario(name: str, config: dict[str, Any]) -> bool:
    _print_scenario_header(config)
    try:
        solver = TrafficMatrixSolver(NETWORK_PATH)
        for edge_id in config["closed_edges"]:
            if edge_id not in solver.edge_index:
                raise NetworkDataError(f"Cannot close unknown road edge {edge_id}")
            index = solver.edge_index[edge_id]
            solver.capacities[index] = 0.0
            solver.edges[index]["capacity"] = 0.0

        solution = solver.solve(config["boundary_flows"])
        bpr = BPRCalculator()
        open_edges = [edge for edge in solver.edges if edge["capacity"] > 0]
        travel_metrics = bpr.calculate_network(open_edges, solution)
        signal_optimizer = SignalOptimizer(
            cycle_time_sec=90.0,
            minimum_green_sec=10.0,
            amber_clearance_sec=8.0,
            warning_threshold=0.75,
        )
        timings = signal_optimizer.allocate_from_solver(solver, SIGNAL_PHASE_EDGES, solution)
        warnings = signal_optimizer.capacity_warnings(solution)

        print(f"Conservation residual: {solution.residual_error:.6g} vehicles/hr")
        print(f"Objective value:      {solution.objective_value:.6g}")
        print("\nDirected edge allocation")
        print(f"{'Edge':<8} {'Road segment':<42} {'Flow':>10} {'Capacity':>10} {'Sat.':>9} {'BPR delay':>12} {'Status':<18}")
        print("-" * 116)
        for edge in solver.edges:
            edge_id = edge["id"]
            flow = solution.edge_flows[edge_id]
            capacity = edge["capacity"]
            saturation = solution.saturation_ratios[edge_id]
            if capacity <= 0:
                delay_text = "CLOSED"
                status = "CLOSED"
            else:
                metric = travel_metrics[edge_id]
                delay_text = f"{metric.congestion_delay_sec:.3f}s"
                status = "WARNING" if edge_id in warnings else "OPEN"
            print(
                f"{edge_id:<8} {edge['name'][:42]:<42} {flow:>10.2f} "
                f"{capacity:>10.2f} {saturation * 100:>8.2f}% {delay_text:>12} {status:<18}"
            )

        print("\nCapacity warnings")
        if not warnings:
            print("  None; all open links are below the 75% buffer threshold.")
        else:
            for edge_id, warning in warnings.items():
                road_name = solver.edges[solver.edge_index[edge_id]]["name"]
                print(
                    f"  {edge_id} | {road_name}: "
                    f"{warning['saturation_ratio'] * 100:.1f}% - {warning['severity']}"
                )

        print("\nSignal timing allocation")
        print(f"{'Approach':<20} {'Green':>12} {'Max saturation':>18}")
        print("-" * 52)
        for phase, green in timings.green_times_sec.items():
            ratio = timings.phase_saturation_ratios[phase]
            print(f"{phase:<20} {green:>10.2f}s {ratio * 100:>16.2f}%")
        print(
            f"Amber clearance {timings.amber_clearance_sec:.2f}s + "
            f"green {timings.total_green_sec:.2f}s = "
            f"cycle {timings.total_allocated_sec:.2f}s"
        )
        return True
    except (BoundaryFlowError, NetworkDataError, OptimizationError, ValueError) as exc:
        LOGGER.error("Scenario %s could not be solved: %s", name, exc)
        print(f"SCENARIO INFEASIBLE: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate ASTraM campus traffic scenarios.")
    parser.add_argument(
        "--scenario",
        choices=tuple(SCENARIOS),
        help="Run one scenario instead of all three (morning, evening, or closure).",
    )
    parser.add_argument("--verbose", action="store_true", help="Show scenario runner diagnostics.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not NETWORK_PATH.is_file():
        parser.error(f"Campus network file not found: {NETWORK_PATH}")
    selected = {args.scenario: SCENARIOS[args.scenario]} if args.scenario else SCENARIOS
    results = [run_scenario(name, config) for name, config in selected.items()]
    successes = sum(results)
    print(f"\nCompleted {successes}/{len(results)} selected traffic scenario(s).")
    return 0 if successes == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
