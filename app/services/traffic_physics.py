"""Traffic delay, turning-flow, signal-timing, and capacity warning models.

All traffic volume and capacity values must use the same time unit (the
starter GeoJSON uses vehicles/hour). Travel time is reported in seconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

try:
    from .flow_solver import FlowSolution, TrafficMatrixSolver
except ImportError:  # Supports direct execution: python app/services/traffic_physics.py
    from flow_solver import FlowSolution, TrafficMatrixSolver


FloatArray = NDArray[np.float64]


def _finite_float(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return result


def _haversine_length_m(coordinates: Sequence[Sequence[float]]) -> float:
    """Calculate LineString length on a spherical Earth from lon/lat points."""
    if len(coordinates) < 2:
        raise ValueError("LineString must contain at least two coordinates")
    earth_radius_m = 6_371_008.8
    length = 0.0
    for first, second in zip(coordinates, coordinates[1:]):
        if len(first) < 2 or len(second) < 2:
            raise ValueError("Each coordinate must contain longitude and latitude")
        lon1 = math.radians(_finite_float(first[0], "longitude"))
        lat1 = math.radians(_finite_float(first[1], "latitude"))
        lon2 = math.radians(_finite_float(second[0], "longitude"))
        lat2 = math.radians(_finite_float(second[1], "latitude"))
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        length += 2.0 * earth_radius_m * math.asin(min(1.0, math.sqrt(a)))
    if length <= 0:
        raise ValueError("Road geometry must have positive length")
    return length


@dataclass(frozen=True)
class RoadTravelMetrics:
    """BPR travel-time diagnostics for one directed road segment."""

    edge_id: str
    name: str
    flow: float
    capacity: float
    saturation_ratio: float
    free_flow_time_sec: float
    travel_time_sec: float
    congestion_delay_sec: float
    length_m: float
    effective_speed_kmh: float

    def as_dict(self) -> dict[str, str | float]:
        return {
            "edge_id": self.edge_id,
            "name": self.name,
            "flow": self.flow,
            "capacity": self.capacity,
            "saturation_ratio": self.saturation_ratio,
            "free_flow_time_sec": self.free_flow_time_sec,
            "travel_time_sec": self.travel_time_sec,
            "congestion_delay_sec": self.congestion_delay_sec,
            "length_m": self.length_m,
            "effective_speed_kmh": self.effective_speed_kmh,
        }


class BPRCalculator:
    """Calculate BPR travel time, delay, and effective speed by edge."""

    def __init__(self, alpha: float = 0.15, beta: float = 4.0) -> None:
        self.alpha = _finite_float(alpha, "alpha", minimum=0.0)
        self.beta = _finite_float(beta, "beta", minimum=0.0)

    def calculate_segment(
        self,
        *,
        edge_id: str,
        name: str,
        flow: float,
        capacity: float,
        free_flow_time_sec: float,
        length_m: float,
    ) -> RoadTravelMetrics:
        """Calculate metrics for one edge, rejecting impossible inputs."""
        x = _finite_float(flow, f"{edge_id} flow", minimum=0.0)
        cap = _finite_float(capacity, f"{edge_id} capacity", minimum=0.0)
        t0 = _finite_float(free_flow_time_sec, f"{edge_id} free-flow time", minimum=0.0)
        length = _finite_float(length_m, f"{edge_id} length", minimum=0.0)
        if cap == 0:
            raise ValueError(f"{edge_id} capacity must be greater than zero")
        if t0 == 0:
            raise ValueError(f"{edge_id} free-flow time must be greater than zero")
        if length == 0:
            raise ValueError(f"{edge_id} length must be greater than zero")
        rho = x / cap
        travel_time = t0 * (1.0 + self.alpha * rho**self.beta)
        delay = travel_time - t0
        speed = length / travel_time * 3.6
        return RoadTravelMetrics(
            edge_id=edge_id,
            name=name,
            flow=x,
            capacity=cap,
            saturation_ratio=rho,
            free_flow_time_sec=t0,
            travel_time_sec=travel_time,
            congestion_delay_sec=delay,
            length_m=length,
            effective_speed_kmh=speed,
        )

    def calculate_network(
        self,
        edges: Sequence[Mapping[str, Any]],
        edge_flows: Mapping[str, float] | FlowSolution | Mapping[str, Any],
    ) -> dict[str, RoadTravelMetrics]:
        """Compute metrics for edge records and a solver result or flow map."""
        flows = _extract_edge_flows(edge_flows)
        output: dict[str, RoadTravelMetrics] = {}
        for edge in edges:
            edge_id = str(edge["id"])
            if edge_id not in flows:
                raise KeyError(f"Solved flows are missing edge {edge_id}")
            geometry = edge.get("geometry")
            if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
                raise ValueError(f"Edge {edge_id} must include LineString geometry")
            properties = edge.get("properties", edge)
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, Sequence):
                raise ValueError(f"Edge {edge_id} has no valid coordinates")
            length_m = _haversine_length_m(coordinates)
            output[edge_id] = self.calculate_segment(
                edge_id=edge_id,
                name=str(properties.get("name", edge_id)),
                flow=flows[edge_id],
                capacity=properties["capacity"],
                free_flow_time_sec=properties["free_flow_time_sec"],
                length_m=length_m,
            )
        return output

    def calculate_from_solver(
        self,
        solver: TrafficMatrixSolver,
        solution: FlowSolution | Mapping[str, Any] | None = None,
    ) -> dict[str, RoadTravelMetrics]:
        """Accept a TrafficMatrixSolver and its most recent (or supplied) result."""
        selected = solution if solution is not None else solver.solution
        if selected is None:
            raise ValueError("The traffic solver has no solution; solve boundary flows first")
        return self.calculate_network(solver.edges, selected)


def _extract_edge_flows(
    flow_result: Mapping[str, Any] | FlowSolution,
) -> Mapping[str, float]:
    if isinstance(flow_result, FlowSolution):
        return flow_result.edge_flows
    if not isinstance(flow_result, Mapping):
        raise TypeError("edge_flows must be a mapping or FlowSolution")
    if "X" in flow_result and isinstance(flow_result["X"], Mapping):
        return flow_result["X"]
    if "edge_flows" in flow_result and isinstance(flow_result["edge_flows"], Mapping):
        return flow_result["edge_flows"]
    return flow_result  # A direct {edge_id: flow} map.


class MarkovTurnModel:
    """Validate row-stochastic turning matrices and propagate expected flow."""

    @staticmethod
    def validate_transition_matrix(transition_matrix: NDArray[np.float64]) -> FloatArray:
        matrix = np.asarray(transition_matrix, dtype=float)
        if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
            raise ValueError("transition_matrix must be a non-empty 2D matrix")
        if not np.all(np.isfinite(matrix)):
            raise ValueError("transition_matrix values must be finite")
        if np.any(matrix < 0.0):
            raise ValueError("transition probabilities cannot be negative")
        row_sums = matrix.sum(axis=1)
        if not np.allclose(row_sums, 1.0, rtol=0.0, atol=1e-9):
            raise ValueError("each transition matrix row must sum to 1.0")
        return matrix

    @classmethod
    def predict_turning_flows(
        cls,
        incoming_flows: Mapping[str, float],
        transition_matrix: NDArray[np.float64],
        outgoing_directions: Sequence[str] | None = None,
    ) -> dict[str, float]:
        """Return expected outgoing volume by direction.

        Matrix rows correspond to incoming_flows iteration order. Columns
        correspond to outgoing_directions order. If direction labels are
        omitted, deterministic names ``outgoing_1`` ... are generated.
        """
        if not isinstance(incoming_flows, Mapping) or not incoming_flows:
            raise ValueError("incoming_flows must be a non-empty mapping")
        incoming = np.asarray(
            [_finite_float(value, f"incoming flow {key}", minimum=0.0) for key, value in incoming_flows.items()],
            dtype=float,
        )
        matrix = cls.validate_transition_matrix(transition_matrix)
        if matrix.shape[0] != incoming.size:
            raise ValueError(
                f"transition matrix has {matrix.shape[0]} rows for {incoming.size} incoming flows"
            )
        if outgoing_directions is None:
            labels = [f"outgoing_{index + 1}" for index in range(matrix.shape[1])]
        else:
            labels = list(outgoing_directions)
            if len(labels) != matrix.shape[1]:
                raise ValueError("outgoing_directions count must equal transition matrix columns")
            if any(not isinstance(label, str) or not label for label in labels):
                raise ValueError("outgoing direction labels must be non-empty strings")
            if len(set(labels)) != len(labels):
                raise ValueError("outgoing direction labels must be unique")
        outgoing = incoming @ matrix
        return {label: float(outgoing[index]) for index, label in enumerate(labels)}


def predict_turning_flows(
    incoming_flows: Mapping[str, float],
    transition_matrix: NDArray[np.float64],
    outgoing_directions: Sequence[str] | None = None,
) -> dict[str, float]:
    """Convenience wrapper around :class:`MarkovTurnModel`."""
    return MarkovTurnModel.predict_turning_flows(
        incoming_flows, transition_matrix, outgoing_directions
    )


@dataclass(frozen=True)
class SignalTimingPlan:
    """Green splits and fixed clearance allocation for one signal cycle."""

    green_times_sec: dict[str, float]
    amber_clearance_sec: float
    cycle_time_sec: float
    phase_saturation_ratios: dict[str, float]
    extended_phases: tuple[str, ...]

    @property
    def total_green_sec(self) -> float:
        return float(sum(self.green_times_sec.values()))

    @property
    def total_allocated_sec(self) -> float:
        return self.total_green_sec + self.amber_clearance_sec

    def as_dict(self) -> dict[str, Any]:
        return {
            "green_times_sec": self.green_times_sec.copy(),
            "amber_clearance_sec": self.amber_clearance_sec,
            "cycle_time_sec": self.cycle_time_sec,
            "phase_saturation_ratios": self.phase_saturation_ratios.copy(),
            "extended_phases": list(self.extended_phases),
            "total_green_sec": self.total_green_sec,
            "total_allocated_sec": self.total_allocated_sec,
        }


class SignalOptimizer:
    """Allocate cycle green time proportionally to non-negative saturation."""

    def __init__(
        self,
        cycle_time_sec: float = 90.0,
        minimum_green_sec: float = 10.0,
        amber_clearance_sec: float = 0.0,
        warning_threshold: float = 0.75,
    ) -> None:
        self.cycle_time_sec = _finite_float(cycle_time_sec, "cycle_time_sec", minimum=0.0)
        self.minimum_green_sec = _finite_float(minimum_green_sec, "minimum_green_sec", minimum=0.0)
        self.amber_clearance_sec = _finite_float(
            amber_clearance_sec, "amber_clearance_sec", minimum=0.0
        )
        self.warning_threshold = _finite_float(warning_threshold, "warning_threshold", minimum=0.0)
        if self.warning_threshold > 1.0:
            raise ValueError("warning_threshold cannot exceed 1.0")
        if self.amber_clearance_sec >= self.cycle_time_sec:
            raise ValueError("amber clearance must be less than the cycle time")

    def allocate_green_times(
        self,
        phase_saturations: Mapping[str, float],
        *,
        cycle_time_sec: float | None = None,
        minimum_green_sec: float | None = None,
        amber_clearance_sec: float | None = None,
    ) -> SignalTimingPlan:
        """Allocate greens using the specified ratio formula.

        Amber clearance is reserved inside the stated cycle. The remaining
        usable time is distributed as minimum greens plus saturation-weighted
        excess green. All phase names are retained, including zero-demand phases.
        """
        if not isinstance(phase_saturations, Mapping) or not phase_saturations:
            raise ValueError("phase_saturations must be a non-empty mapping")
        cycle = self.cycle_time_sec if cycle_time_sec is None else _finite_float(
            cycle_time_sec, "cycle_time_sec", minimum=0.0
        )
        minimum = self.minimum_green_sec if minimum_green_sec is None else _finite_float(
            minimum_green_sec, "minimum_green_sec", minimum=0.0
        )
        amber = self.amber_clearance_sec if amber_clearance_sec is None else _finite_float(
            amber_clearance_sec, "amber_clearance_sec", minimum=0.0
        )
        if cycle <= 0:
            raise ValueError("cycle_time_sec must be greater than zero")
        if amber >= cycle:
            raise ValueError("amber clearance must be less than cycle time")
        if any(not isinstance(name, str) or not name for name in phase_saturations):
            raise ValueError("phase names must be non-empty strings")
        ratios = {
            name: _finite_float(value, f"saturation for {name}", minimum=0.0)
            for name, value in phase_saturations.items()
        }
        count = len(ratios)
        usable_green = cycle - amber
        if count * minimum > usable_green + 1e-9:
            raise ValueError(
                f"minimum green requirements ({count * minimum:g}s) exceed "
                f"available green time ({usable_green:g}s)"
            )
        distributable = usable_green - count * minimum
        ratio_total = sum(ratios.values())
        if ratio_total > 0:
            greens = {
                name: minimum + distributable * ratio / ratio_total
                for name, ratio in ratios.items()
            }
        else:
            # No measured demand: divide excess green evenly for deterministic,
            # non-starving operation while respecting each minimum.
            share = distributable / count
            greens = {name: minimum + share for name in ratios}
        # Correct floating point accumulation so green + amber equals cycle.
        last = next(reversed(greens))
        greens[last] += usable_green - sum(greens.values())
        extended = tuple(name for name, ratio in ratios.items() if ratio >= self.warning_threshold)
        return SignalTimingPlan(
            green_times_sec=greens,
            amber_clearance_sec=amber,
            cycle_time_sec=cycle,
            phase_saturation_ratios=ratios,
            extended_phases=extended,
        )

    def allocate_from_solver(
        self,
        solver: TrafficMatrixSolver,
        phase_edges: Mapping[str, str | Sequence[str]],
        solution: FlowSolution | Mapping[str, Any] | None = None,
        **timing_overrides: float,
    ) -> SignalTimingPlan:
        """Aggregate solver edge saturation into named approach phases."""
        selected = solution if solution is not None else solver.solution
        if selected is None:
            raise ValueError("The traffic solver has no solution; solve boundary flows first")
        if isinstance(selected, FlowSolution):
            edge_ratios = selected.saturation_ratios
        else:
            edge_ratios = selected.get("saturation_ratios")
            if not isinstance(edge_ratios, Mapping):
                raise ValueError("solver result must contain saturation_ratios")
        phase_ratios: dict[str, float] = {}
        for phase, edges in phase_edges.items():
            edge_list = [edges] if isinstance(edges, str) else list(edges)
            if not edge_list:
                raise ValueError(f"phase {phase} must include at least one edge")
            missing = [edge for edge in edge_list if edge not in edge_ratios]
            if missing:
                raise KeyError(f"phase {phase} references unknown edges: {', '.join(missing)}")
            phase_ratios[phase] = max(float(edge_ratios[edge]) for edge in edge_list)
        return self.allocate_green_times(phase_ratios, **timing_overrides)

    def capacity_warnings(
        self,
        saturation_ratios: Mapping[str, float] | FlowSolution | Mapping[str, Any],
        threshold: float | None = None,
    ) -> dict[str, dict[str, float | bool | str]]:
        """Return edge warnings at or above the configured buffer threshold."""
        limit = self.warning_threshold if threshold is None else _finite_float(
            threshold, "threshold", minimum=0.0
        )
        if limit > 1.0:
            raise ValueError("threshold cannot exceed 1.0")
        ratios: Mapping[str, float]
        if isinstance(saturation_ratios, FlowSolution):
            ratios = saturation_ratios.saturation_ratios
        elif "saturation_ratios" in saturation_ratios and isinstance(
            saturation_ratios["saturation_ratios"], Mapping
        ):
            ratios = saturation_ratios["saturation_ratios"]
        else:
            ratios = saturation_ratios
        warnings: dict[str, dict[str, float | bool | str]] = {}
        for edge_id, raw_ratio in ratios.items():
            ratio = _finite_float(raw_ratio, f"saturation ratio {edge_id}", minimum=0.0)
            if ratio >= limit:
                warnings[edge_id] = {
                    "saturation_ratio": ratio,
                    "threshold": limit,
                    "warning": True,
                    "severity": "capacity_buffer" if ratio < 1.0 else "at_or_over_capacity",
                    "recommended_action": "consider_preemptive_signal_phase_extension",
                }
        return warnings


def _default_network_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "mit_wpu_roads.geojson"


def _print_diagnostics(
    travel_metrics: Mapping[str, RoadTravelMetrics],
    timings: SignalTimingPlan,
    warnings: Mapping[str, Mapping[str, Any]],
) -> None:
    print("ASTraM traffic physics diagnostics")
    print("\nBPR road segment metrics")
    print(
        f"{'Edge':<8} {'Travel time (s)':>16} {'Delay (s)':>12} "
        f"{'Speed (km/h)':>14} {'Saturation':>12}"
    )
    print("-" * 67)
    for edge_id, item in travel_metrics.items():
        print(
            f"{edge_id:<8} {item.travel_time_sec:>16.3f} "
            f"{item.congestion_delay_sec:>12.3f} {item.effective_speed_kmh:>14.3f} "
            f"{item.saturation_ratio * 100:>11.2f}%"
        )
    print("\nFour-way signal timing")
    print(f"{'Approach':<16} {'Green (s)':>12} {'Saturation':>12}")
    print("-" * 42)
    for phase, green in timings.green_times_sec.items():
        print(f"{phase:<16} {green:>12.2f} {timings.phase_saturation_ratios[phase] * 100:>11.2f}%")
    print(
        f"Amber clearance: {timings.amber_clearance_sec:.2f}s; "
        f"total allocated: {timings.total_allocated_sec:.2f}s / "
        f"{timings.cycle_time_sec:.2f}s cycle"
    )
    print("\nCapacity buffer warnings (>= 75%)")
    if not warnings:
        print("No road segments at or above the warning threshold.")
    else:
        for edge_id, warning in warnings.items():
            print(f"{edge_id}: {warning['saturation_ratio'] * 100:.2f}% ({warning['severity']})")


if __name__ == "__main__":
    path = _default_network_path()
    traffic_solver = TrafficMatrixSolver(path)
    flow_solution = traffic_solver.solve(
        {"node_1": 40.0, "node_7": 20.0, "node_8": -60.0}
    )

    calculator = BPRCalculator()
    road_metrics = calculator.calculate_from_solver(traffic_solver, flow_solution)

    signal_optimizer = SignalOptimizer(
        cycle_time_sec=90.0,
        minimum_green_sec=10.0,
        amber_clearance_sec=8.0,
        warning_threshold=0.75,
    )
    # Four approaches to the central campus junction, represented by the
    # incident directed links in the starter road network.
    four_way_phases = {
        "north_approach": ("e13",),
        "east_approach": ("e5",),
        "south_approach": ("e8",),
        "west_approach": ("e14",),
    }
    timing_plan = signal_optimizer.allocate_from_solver(
        traffic_solver, four_way_phases, flow_solution
    )
    capacity_alerts = signal_optimizer.capacity_warnings(flow_solution)
    _print_diagnostics(road_metrics, timing_plan, capacity_alerts)

    turns = MarkovTurnModel.predict_turning_flows(
        {"north_in": 40.0, "south_in": 35.0, "east_in": 25.0, "west_in": 20.0},
        np.asarray(
            [
                [0.10, 0.70, 0.20],
                [0.15, 0.65, 0.20],
                [0.30, 0.40, 0.30],
                [0.25, 0.50, 0.25],
            ],
            dtype=float,
        ),
        ("left", "through", "right"),
    )
    print("\nExpected turning flows")
    for movement, volume in turns.items():
        print(f"{movement:<12} {volume:>10.2f} vehicles/hour")
