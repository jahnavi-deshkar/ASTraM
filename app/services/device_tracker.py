"""Rolling aggregation of GPS-matched devices and campus road occupancy."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class DeviceObservation:
    device_id: str
    edge_id: str | None
    latitude: float
    longitude: float
    heading: float | None
    speed_mps: float | None
    confidence: float
    last_seen: str
    seen_monotonic: float


class DeviceTracker:
    """Aggregate active device counts, edge occupancy, and gate crossings.

    ``capacity_share_per_device`` converts live occupancy into a conservative
    equivalent flow contribution for the BPR display. This calibration is a
    demo default, not an engineering measurement; configure it from locally
    observed probe penetration and segment occupancy data before operational
    use. Gate crossing events remain separate from occupancy estimates. The
    solver boundary estimate pairs the lower observed entry and exit rates so
    that a rolling window with devices still inside campus stays conservative
    and obeys steady-state conservation.
    """

    def __init__(
        self,
        network: Mapping[str, Any],
        window_seconds: float = 60.0,
        capacity_share_per_device: float = 0.12,
        max_devices: int = 10_000,
    ) -> None:
        self.window_seconds = self._positive(window_seconds, "window_seconds")
        self.capacity_share_per_device = self._positive(
            capacity_share_per_device, "capacity_share_per_device"
        )
        if self.capacity_share_per_device > 1.0:
            raise ValueError("capacity_share_per_device cannot exceed 1.0")
        if isinstance(max_devices, bool) or not isinstance(max_devices, int) or max_devices < 1:
            raise ValueError("max_devices must be a positive integer")
        features = network.get("features")
        nodes = network.get("nodes")
        if not isinstance(features, list) or not isinstance(nodes, list):
            raise ValueError("Network must include nodes and features arrays")
        self.nodes = {node["id"]: dict(node) for node in nodes if isinstance(node, Mapping) and node.get("id")}
        self.edges: dict[str, dict[str, Any]] = {}
        self.edge_lengths_m: dict[str, float] = {}
        self.reverse_edges: dict[str, str] = {}
        by_direction: dict[tuple[str, str], str] = {}
        for feature in features:
            if not isinstance(feature, Mapping):
                continue
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            edge_id = properties.get("id") if isinstance(properties, Mapping) else None
            if not edge_id or geometry.get("type") != "LineString":
                continue
            edge = dict(properties)
            edge["geometry"] = dict(geometry)
            self.edges[str(edge_id)] = edge
            self.edge_lengths_m[str(edge_id)] = self._line_length_m(geometry["coordinates"])
            by_direction[(str(edge.get("source")), str(edge.get("target")))] = str(edge_id)
        for (source, target), edge_id in by_direction.items():
            reverse_id = by_direction.get((target, source))
            if reverse_id:
                self.reverse_edges[edge_id] = reverse_id
        self.max_devices = max_devices
        self._devices: dict[str, DeviceObservation] = {}
        self._gate_events: deque[tuple[float, str, int]] = deque()
        self._lock = threading.RLock()

    @staticmethod
    def _positive(value: float, label: str) -> float:
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError(f"{label} must be finite and greater than zero")
        return result

    @staticmethod
    def _line_length_m(coordinates: list[list[float]]) -> float:
        total = 0.0
        for first, second in zip(coordinates, coordinates[1:]):
            lon1, lat1 = math.radians(float(first[0])), math.radians(float(first[1]))
            lon2, lat2 = math.radians(float(second[0])), math.radians(float(second[1]))
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            total += 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))
        return max(total, 0.1)

    @staticmethod
    def _angle_delta(first: float, second: float) -> float:
        return abs((first - second + 180.0) % 360.0 - 180.0)

    @staticmethod
    def _bearing(coordinates: list[list[float]]) -> float:
        first, last = coordinates[0], coordinates[-1]
        lat1, lat2 = math.radians(float(first[1])), math.radians(float(last[1]))
        delta_lon = math.radians(float(last[0]) - float(first[0]))
        y = math.sin(delta_lon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    def _orient_edge(self, edge_id: str | None, heading: float | None) -> str | None:
        if edge_id is None or edge_id not in self.edges or heading is None:
            return edge_id
        edge = self.edges[edge_id]
        forward_delta = self._angle_delta(heading % 360.0, self._bearing(edge["geometry"]["coordinates"]))
        reverse_id = self.reverse_edges.get(edge_id)
        if reverse_id is None:
            return edge_id
        reverse = self.edges[reverse_id]
        reverse_delta = self._angle_delta(
            heading % 360.0, self._bearing(reverse["geometry"]["coordinates"])
        )
        return reverse_id if reverse_delta + 8.0 < forward_delta else edge_id

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self.window_seconds
        expired = [
            device_id
            for device_id, observation in self._devices.items()
            if observation.seen_monotonic < cutoff
        ]
        for device_id in expired:
            del self._devices[device_id]
        while self._gate_events and self._gate_events[0][0] < cutoff:
            self._gate_events.popleft()

    def _record_gate_hits(self, edge_id: str | None, now: float) -> None:
        if edge_id is None or edge_id not in self.edges:
            return
        edge = self.edges[edge_id]
        source = self.nodes.get(str(edge.get("source")), {})
        target = self.nodes.get(str(edge.get("target")), {})
        source_type = source.get("boundary_type", "internal")
        target_type = target.get("boundary_type", "internal")
        if source_type in {"entry", "entry_exit"}:
            self._gate_events.append((now, str(source["id"]), 1))
        if target_type in {"exit", "entry_exit"}:
            self._gate_events.append((now, str(target["id"]), -1))

    def record_fix(
        self,
        *,
        device_id: str,
        latitude: float,
        longitude: float,
        heading: float | None,
        speed_mps: float | None,
        matched_edge_id: str | None,
        confidence: float,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Store one successful or off-road fix and return its aggregate state."""
        now = time.monotonic()
        timestamp = observed_at or datetime.now(timezone.utc)
        edge_id = self._orient_edge(matched_edge_id, heading)
        if edge_id is not None and edge_id not in self.edges:
            raise ValueError(f"Unknown matched road edge: {edge_id}")
        with self._lock:
            self._prune_locked(now)
            previous = self._devices.get(device_id)
            if previous is None or previous.edge_id != edge_id:
                self._record_gate_hits(edge_id, now)
            observation = DeviceObservation(
                device_id=device_id,
                edge_id=edge_id,
                latitude=float(latitude),
                longitude=float(longitude),
                heading=None if heading is None else float(heading) % 360.0,
                speed_mps=None if speed_mps is None else max(0.0, float(speed_mps)),
                confidence=min(1.0, max(0.0, float(confidence))),
                last_seen=timestamp.astimezone(timezone.utc).isoformat(),
                seen_monotonic=now,
            )
            self._devices[device_id] = observation
            if len(self._devices) > self.max_devices:
                oldest = min(self._devices, key=lambda key: self._devices[key].seen_monotonic)
                del self._devices[oldest]
            return self._snapshot_locked(now)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked(time.monotonic())

    def _snapshot_locked(self, now: float) -> dict[str, Any]:
        self._prune_locked(now)
        edge_counts = {edge_id: 0 for edge_id in self.edges}
        active_devices: list[dict[str, Any]] = []
        for item in self._devices.values():
            if item.edge_id is not None:
                edge_counts[item.edge_id] = edge_counts.get(item.edge_id, 0) + 1
            active_devices.append(
                {
                    "device_id": item.device_id,
                    "edge_id": item.edge_id,
                    "latitude": item.latitude,
                    "longitude": item.longitude,
                    "heading": item.heading,
                    "speed_mps": item.speed_mps,
                    "confidence_score": item.confidence,
                    "last_seen": item.last_seen,
                }
            )
        edge_density: dict[str, dict[str, float | int]] = {}
        equivalent_flows: dict[str, float] = {}
        for edge_id, edge in self.edges.items():
            count = edge_counts.get(edge_id, 0)
            length_m = self.edge_lengths_m[edge_id]
            capacity = max(float(edge.get("capacity", 0.0)), 0.0)
            density = count / length_m * 100.0
            equivalent_flow = min(capacity, count * capacity * self.capacity_share_per_device)
            edge_density[edge_id] = {
                "active_device_count": count,
                "people_per_100m": density,
                "segment_length_m": length_m,
                "occupancy_equivalent_flow_vph": equivalent_flow,
            }
            equivalent_flows[edge_id] = equivalent_flow

        gate_counts = {node_id: 0 for node_id, node in self.nodes.items() if node.get("boundary_type") != "internal"}
        for _, node_id, sign in self._gate_events:
            gate_counts[node_id] = gate_counts.get(node_id, 0) + sign
        scale = 3600.0 / self.window_seconds
        gate_rates = {node_id: count * scale for node_id, count in gate_counts.items() if count != 0}
        raw_total = sum(gate_rates.values())
        inflow_total = sum(value for value in gate_rates.values() if value > 0.0)
        outflow_total = -sum(value for value in gate_rates.values() if value < 0.0)
        paired_rate = min(inflow_total, outflow_total)
        solver_gate_rates: dict[str, float] = {}
        if paired_rate > 0.0:
            inflow_scale = paired_rate / inflow_total
            outflow_scale = paired_rate / outflow_total
            solver_gate_rates = {
                node_id: value * (inflow_scale if value > 0.0 else outflow_scale)
                for node_id, value in gate_rates.items()
            }
        return {
            "window_seconds": self.window_seconds,
            "active_device_count": len(self._devices),
            "active_device_ids": sorted(self._devices),
            "active_devices": sorted(active_devices, key=lambda item: item["device_id"]),
            "edge_device_counts": edge_counts,
            "edge_density": edge_density,
            "occupancy_equivalent_flows_vph": equivalent_flows,
            "boundary_event_counts": gate_counts,
            "boundary_flows_vph": gate_rates,
            "solver_boundary_flows_vph": solver_gate_rates,
            "boundary_flows_balanced": abs(raw_total) < 1e-9,
            "boundary_flow_net_vph": raw_total,
        }
