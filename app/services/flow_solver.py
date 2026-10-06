"""Capacity-bounded traffic flow estimation for the ASTraM road network.

The incidence matrix uses +1 at an edge's source and -1 at its target, so
``A @ x`` is net outbound flow at each node. Boundary values represent
external supply or demand: positive entry supply and negative exit demand.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import OptimizeResult, minimize


FloatArray = NDArray[np.float64]


class NetworkDataError(ValueError):
    """Raised when the supplied network is malformed or incomplete."""


class BoundaryFlowError(ValueError):
    """Raised when boundary flows are invalid or infeasible under capacities."""


class OptimizationError(RuntimeError):
    """Raised when the bounded flow optimization cannot produce a solution."""


@dataclass(frozen=True)
class FlowSolution:
    """Immutable solution and diagnostics for one boundary-flow snapshot."""

    edge_flows: dict[str, float]
    saturation_ratios: dict[str, float]
    residual_error: float
    node_conservation: dict[str, dict[str, float]]
    requested_boundary_flows: dict[str, float]
    effective_boundary_flows: dict[str, float]
    objective_value: float
    optimizer_success: bool
    optimizer_message: str

    @property
    def X(self) -> dict[str, float]:
        """Solved vector indexed by edge ID."""
        return self.edge_flows

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this solution."""
        return {
            "X": self.edge_flows.copy(),
            "saturation_ratios": self.saturation_ratios.copy(),
            "residual_error": self.residual_error,
            "node_conservation": {
                node_id: metrics.copy()
                for node_id, metrics in self.node_conservation.items()
            },
            "requested_boundary_flows": self.requested_boundary_flows.copy(),
            "effective_boundary_flows": self.effective_boundary_flows.copy(),
            "objective_value": self.objective_value,
            "optimizer_success": self.optimizer_success,
            "optimizer_message": self.optimizer_message,
        }


class TrafficMatrixSolver:
    """Build and solve the ASTraM capacitated node-edge flow model.

    Args:
        network: A path to a GeoJSON FeatureCollection or an in-memory mapping
            with ``nodes`` and ``features`` arrays.
        gamma: Non-negative regularization weight for squared normalized flows.
        feasibility_tolerance: Maximum allowed L2 conservation residual before
            a boundary vector is classified as infeasible.

    Boundary values follow the requested data convention (positive entry
    supply, negative exit demand). With the specified incidence signs, entry
    supply equals net edge outflow at the entry node and exit demand is
    negative net edge outflow.
    """

    def __init__(
        self,
        network: str | Path | Mapping[str, Any],
        gamma: float = 1e-4,
        feasibility_tolerance: float = 1e-5,
    ) -> None:
        if not math.isfinite(gamma) or gamma < 0:
            raise ValueError("gamma must be a finite, non-negative number")
        if not math.isfinite(feasibility_tolerance) or feasibility_tolerance <= 0:
            raise ValueError("feasibility_tolerance must be finite and positive")

        self.gamma = float(gamma)
        self.feasibility_tolerance = float(feasibility_tolerance)
        payload = self._load_payload(network)
        self.nodes, self.edges = self._parse_network(payload)
        self.node_ids = tuple(self.nodes)
        self.edge_ids = tuple(edge["id"] for edge in self.edges)
        self.node_index = {node_id: index for index, node_id in enumerate(self.node_ids)}
        self.edge_index = {edge_id: index for index, edge_id in enumerate(self.edge_ids)}
        self.capacities = np.asarray([edge["capacity"] for edge in self.edges], dtype=float)
        self.incidence_matrix = self._build_incidence_matrix()
        self.A = self.incidence_matrix
        self._requested_boundary_flows: dict[str, float] = {}
        self._solution: FlowSolution | None = None

    @staticmethod
    def _load_payload(network: str | Path | Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(network, Mapping):
            return network
        path = Path(network)
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                payload = json.load(file)
        except OSError as exc:
            raise NetworkDataError(f"Unable to read GeoJSON file {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise NetworkDataError(f"Invalid JSON in {path}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise NetworkDataError("GeoJSON root must be an object")
        return payload

    @staticmethod
    def _finite_number(value: Any, label: str, *, positive: bool = False) -> float:
        if isinstance(value, bool):
            raise NetworkDataError(f"{label} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise NetworkDataError(f"{label} must be numeric") from exc
        if not math.isfinite(number) or (positive and number <= 0):
            qualifier = "finite and greater than zero" if positive else "finite"
            raise NetworkDataError(f"{label} must be {qualifier}")
        return number

    @classmethod
    def _parse_network(
        cls, payload: Mapping[str, Any]
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        if payload.get("type") != "FeatureCollection":
            raise NetworkDataError("Network must be a GeoJSON FeatureCollection")
        raw_nodes = payload.get("nodes")
        raw_features = payload.get("features")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise NetworkDataError("GeoJSON must contain a non-empty 'nodes' array")
        if not isinstance(raw_features, list) or not raw_features:
            raise NetworkDataError("GeoJSON must contain a non-empty 'features' array")

        nodes: dict[str, dict[str, Any]] = {}
        for position, raw_node in enumerate(raw_nodes):
            if not isinstance(raw_node, Mapping):
                raise NetworkDataError(f"Node at index {position} must be an object")
            node_id = raw_node.get("id")
            if not isinstance(node_id, str) or not node_id.strip():
                raise NetworkDataError(f"Node at index {position} has no valid id")
            if node_id in nodes:
                raise NetworkDataError(f"Duplicate node id: {node_id}")
            normalized = dict(raw_node)
            for coordinate in ("longitude", "latitude"):
                if coordinate in raw_node:
                    normalized[coordinate] = cls._finite_number(
                        raw_node[coordinate], f"node {node_id} {coordinate}"
                    )
            nodes[node_id] = normalized

        edges: list[dict[str, Any]] = []
        edge_ids: set[str] = set()
        for position, feature in enumerate(raw_features):
            if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
                raise NetworkDataError(f"Feature at index {position} is invalid")
            properties = feature.get("properties")
            geometry = feature.get("geometry")
            if not isinstance(properties, Mapping):
                raise NetworkDataError(f"Feature at index {position} has no properties")
            if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
                raise NetworkDataError(f"Feature at index {position} must be a LineString")
            required = ("id", "name", "source", "target", "capacity")
            missing = [key for key in required if key not in properties]
            if missing:
                raise NetworkDataError(
                    f"Feature at index {position} is missing properties: {', '.join(missing)}"
                )
            edge_id = properties["id"]
            if not isinstance(edge_id, str) or not edge_id.strip():
                raise NetworkDataError(f"Feature at index {position} has invalid edge id")
            if edge_id in edge_ids:
                raise NetworkDataError(f"Duplicate edge id: {edge_id}")
            source, target = properties["source"], properties["target"]
            if source not in nodes or target not in nodes:
                raise NetworkDataError(
                    f"Edge {edge_id} references unknown nodes {source!r} -> {target!r}"
                )
            if source == target:
                raise NetworkDataError(f"Edge {edge_id} cannot connect a node to itself")
            coords = geometry.get("coordinates")
            if not isinstance(coords, list) or len(coords) < 2:
                raise NetworkDataError(f"Edge {edge_id} LineString needs at least two points")
            capacity = cls._finite_number(
                properties["capacity"], f"edge {edge_id} capacity", positive=True
            )
            lanes = properties.get("lanes")
            if lanes is not None:
                lanes_value = cls._finite_number(lanes, f"edge {edge_id} lanes", positive=True)
                if not lanes_value.is_integer():
                    raise NetworkDataError(f"Edge {edge_id} lanes must be an integer")
                lanes = int(lanes_value)
            edge_ids.add(edge_id)
            edges.append(
                {
                    "id": edge_id,
                    "name": str(properties["name"]),
                    "source": source,
                    "target": target,
                    "capacity": capacity,
                    "lanes": lanes,
                    "free_flow_time_sec": properties.get("free_flow_time_sec"),
                    "geometry": geometry,
                }
            )
        return nodes, edges

    def _build_incidence_matrix(self) -> FloatArray:
        matrix = np.zeros((len(self.node_ids), len(self.edge_ids)), dtype=float)
        for column, edge in enumerate(self.edges):
            matrix[self.node_index[edge["source"]], column] = 1.0
            matrix[self.node_index[edge["target"]], column] = -1.0
        return matrix

    @property
    def boundary_flows(self) -> dict[str, float]:
        """Current public-convention boundary inputs (a defensive copy)."""
        return self._requested_boundary_flows.copy()

    @property
    def solution(self) -> FlowSolution | None:
        """Most recently calculated solution, if one is available."""
        return self._solution

    def _validate_boundary_flows(self, boundary_dict: Mapping[str, Any]) -> dict[str, float]:
        if not isinstance(boundary_dict, Mapping):
            raise BoundaryFlowError("boundary_dict must map node IDs to finite flow values")
        unknown = set(boundary_dict) - set(self.node_ids)
        if unknown:
            raise BoundaryFlowError(f"Unknown boundary node IDs: {', '.join(map(str, sorted(unknown)))}")
        result: dict[str, float] = {}
        for node_id, raw_value in boundary_dict.items():
            if node_id not in self.node_ids:
                raise BoundaryFlowError(f"Unknown boundary node ID: {node_id!r}")
            if isinstance(raw_value, bool):
                raise BoundaryFlowError(f"Boundary flow for {node_id} must be numeric")
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise BoundaryFlowError(f"Boundary flow for {node_id} must be numeric") from exc
            if not math.isfinite(value):
                raise BoundaryFlowError(f"Boundary flow for {node_id} must be finite")
            result[node_id] = value

        # A closed campus network cannot create or remove vehicles. Omitted
        # nodes are treated as zero, so net specified boundary flow must balance.
        net = sum(result.values())
        scale = max(1.0, sum(abs(value) for value in result.values()))
        if abs(net) > self.feasibility_tolerance * scale:
            raise BoundaryFlowError(
                f"Boundary flows do not balance globally (sum={net:.6g}); "
                "entry and exit totals must match"
            )
        return result

    def _solve(self, requested: dict[str, float]) -> FlowSolution:
        # Entry supply equals net edge outflow; exit demand is negative outflow.
        b = np.zeros(len(self.node_ids), dtype=float)
        for node_id, value in requested.items():
            b[self.node_index[node_id]] = value

        scale = np.maximum(self.capacities, 1.0)
        inv_capacity_sq = 1.0 / np.square(scale)

        def objective(x: FloatArray) -> float:
            residual = self.incidence_matrix @ x - b
            return float(residual @ residual + self.gamma * np.sum(np.square(x / scale)))

        def gradient(x: FloatArray) -> FloatArray:
            residual = self.incidence_matrix @ x - b
            return 2.0 * (self.incidence_matrix.T @ residual) + 2.0 * self.gamma * x * inv_capacity_sq

        initial = np.zeros(len(self.edge_ids), dtype=float)
        result: OptimizeResult = minimize(
            objective,
            initial,
            jac=gradient,
            method="SLSQP",
            bounds=[(0.0, float(capacity)) for capacity in self.capacities],
            options={"maxiter": 2000, "ftol": 1e-12, "disp": False},
        )
        if not result.success and (not np.isfinite(result.fun) or result.x is None):
            raise OptimizationError(f"Flow optimization failed: {result.message}")
        x = np.asarray(result.x, dtype=float)
        if x.shape != (len(self.edge_ids),) or not np.all(np.isfinite(x)):
            raise OptimizationError("Optimizer returned an invalid flow vector")
        # Remove tiny numerical excursions at active bounds before diagnostics.
        x = np.clip(x, 0.0, self.capacities)
        residual_vector = self.incidence_matrix @ x - b
        residual_norm = float(np.linalg.norm(residual_vector, ord=2))
        if residual_norm > self.feasibility_tolerance:
            limiting = [
                self.edge_ids[i]
                for i, (value, capacity) in enumerate(zip(x, self.capacities))
                if value <= 1e-8 or value >= capacity - 1e-8
            ]
            raise BoundaryFlowError(
                f"Boundary vector is infeasible under the supplied edge capacities "
                f"(conservation residual={residual_norm:.6g}; active capacity bounds="
                f"{', '.join(limiting) if limiting else 'none'})"
            )

        balances = self.incidence_matrix @ x
        node_metrics: dict[str, dict[str, float]] = {}
        effective = {node_id: float(b[i]) for i, node_id in enumerate(self.node_ids)}
        for index, node_id in enumerate(self.node_ids):
            net_outflow = float(balances[index])
            target_net_outflow = float(b[index])
            node_metrics[node_id] = {
                "net_outflow": net_outflow,
                "requested_net_inflow": float(effective[node_id]),
                "imbalance": float(net_outflow - target_net_outflow),
                "absolute_imbalance": float(abs(net_outflow - target_net_outflow)),
            }
        return FlowSolution(
            edge_flows={edge_id: float(x[i]) for i, edge_id in enumerate(self.edge_ids)},
            saturation_ratios={
                edge_id: float(x[i] / self.capacities[i]) if self.capacities[i] > 0 else 0.0
                for i, edge_id in enumerate(self.edge_ids)
            },
            residual_error=residual_norm,
            node_conservation=node_metrics,
            requested_boundary_flows=requested.copy(),
            effective_boundary_flows=effective,
            objective_value=float(objective(x)),
            optimizer_success=bool(result.success),
            optimizer_message=str(result.message),
        )

    def update_boundary_flows(self, boundary_dict: Mapping[str, Any]) -> FlowSolution:
        """Validate and solve for a new set of boundary flow measurements.

        The solver state is only updated after a complete successful solve, so
        an invalid or infeasible update leaves the prior solution intact.
        """
        requested = self._validate_boundary_flows(boundary_dict)
        candidate = self._solve(requested)
        self._requested_boundary_flows = requested
        self._solution = candidate
        return candidate

    def solve(self, boundary_dict: Mapping[str, Any]) -> FlowSolution:
        """Alias for :meth:`update_boundary_flows` for first-time solves."""
        return self.update_boundary_flows(boundary_dict)

    def incidence_matrix_as_dict(self) -> dict[str, dict[str, int]]:
        """Return the incidence matrix as sparse node-to-edge coefficients."""
        return {
            node_id: {
                edge_id: int(self.incidence_matrix[i, j])
                for j, edge_id in enumerate(self.edge_ids)
                if self.incidence_matrix[i, j] != 0
            }
            for i, node_id in enumerate(self.node_ids)
        }


def _default_network_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "mit_wpu_roads.geojson"


def _print_solution(solver: TrafficMatrixSolver, solution: FlowSolution) -> None:
    print("ASTraM bounded traffic flow solution")
    print(f"Conservation residual: {solution.residual_error:.8f}")
    print(f"Objective value:       {solution.objective_value:.8f}")
    print("\nEdge flow summary")
    print(f"{'Edge':<8} {'Road segment':<42} {'Flow':>12} {'Capacity':>12} {'Saturation':>12}")
    print("-" * 90)
    for edge in solver.edges:
        edge_id = edge["id"]
        flow = solution.edge_flows[edge_id]
        saturation = solution.saturation_ratios[edge_id]
        print(
            f"{edge_id:<8} {edge['name'][:42]:<42} {flow:>12.3f} "
            f"{edge['capacity']:>12.3f} {saturation * 100:>11.2f}%"
        )
    print("\nNode conservation summary")
    print(f"{'Node':<12} {'Requested net inflow':>22} {'Net outflow':>16} {'Imbalance':>14}")
    print("-" * 68)
    for node_id in solver.node_ids:
        metrics = solution.node_conservation[node_id]
        print(
            f"{node_id:<12} {metrics['requested_net_inflow']:>22.3f} "
            f"{metrics['net_outflow']:>16.3f} {metrics['imbalance']:>14.6f}"
        )


if __name__ == "__main__":
    network_path = _default_network_path()
    solver = TrafficMatrixSolver(network_path)
    # Public convention: positive means vehicles enter the campus, negative
    # means vehicles leave. Totals balance at 60 vehicles/hour, within the
    # Gate 1, Cast Gate, and Gate 3 form a balanced illustrative boundary.
    mock_boundary_flows = {"node_1": 40.0, "node_7": 20.0, "node_8": -60.0}
    solved = solver.solve(mock_boundary_flows)
    _print_solution(solver, solved)
