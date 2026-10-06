"""Integration coverage for ASTraM numerical services and HTTP API."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.flow_solver import TrafficMatrixSolver
from app.services.map_matching import GPSMapMatcher
from app.services.traffic_physics import BPRCalculator, MarkovTurnModel, SignalOptimizer


ROOT = Path(__file__).resolve().parents[1]
NETWORK_PATH = ROOT / "data" / "mit_wpu_roads.geojson"
BALANCED_FLOWS = {"node_1": 40.0, "node_7": 20.0, "node_8": -60.0}


def test_flow_solver() -> None:
    solver = TrafficMatrixSolver(NETWORK_PATH)
    first = solver.solve(BALANCED_FLOWS)
    vector = np.asarray([first.edge_flows[edge_id] for edge_id in solver.edge_ids])
    target = np.zeros(len(solver.node_ids), dtype=float)
    for node_id, value in BALANCED_FLOWS.items():
        target[solver.node_index[node_id]] = value

    assert np.linalg.norm(solver.A @ vector - target, ord=2) < 1e-4
    assert first.residual_error < 1e-4
    for index, edge_id in enumerate(solver.edge_ids):
        assert -1e-8 <= vector[index] <= solver.capacities[index] + 1e-8, edge_id
    assert all(abs(metrics["imbalance"]) < 1e-4 for metrics in first.node_conservation.values())

    updated_flows = {"node_1": 30.0, "node_7": 10.0, "node_8": -40.0}
    second = solver.update_boundary_flows(updated_flows)
    assert second.residual_error < 1e-4
    assert second.requested_boundary_flows == updated_flows
    assert second.edge_flows != first.edge_flows


def test_traffic_physics() -> None:
    calculator = BPRCalculator(alpha=0.15, beta=4.0)
    metric = calculator.calculate_segment(
        edge_id="test_link",
        name="Test Link",
        flow=50.0,
        capacity=100.0,
        free_flow_time_sec=20.0,
        length_m=100.0,
    )
    assert np.isclose(metric.congestion_delay_sec, 0.1875, atol=1e-10)
    free_flow_speed = 100.0 / 20.0 * 3.6
    assert 0.0 < metric.effective_speed_kmh <= free_flow_speed
    assert metric.travel_time_sec >= metric.free_flow_time_sec

    turn_flows = MarkovTurnModel.predict_turning_flows(
        {"north": 60.0, "south": 40.0},
        np.asarray([[0.2, 0.5, 0.3], [0.1, 0.6, 0.3]], dtype=float),
        ("left", "through", "right"),
    )
    assert np.isclose(sum(turn_flows.values()), 100.0)

    optimizer = SignalOptimizer(cycle_time_sec=90.0, minimum_green_sec=10.0, amber_clearance_sec=8.0)
    plan = optimizer.allocate_green_times(
        {"north": 0.4, "east": 0.7, "south": 0.2, "west": 0.5}
    )
    assert np.isclose(sum(plan.green_times_sec.values()), 82.0, atol=1e-9)
    assert np.isclose(plan.total_allocated_sec, 90.0, atol=1e-9)
    assert all(value >= 10.0 for value in plan.green_times_sec.values())


def test_map_matching(tmp_path: Path) -> None:
    matcher = GPSMapMatcher(NETWORK_PATH)
    matched = matcher.snap_location(18.5175, 73.81761, heading=53.0, speed=4.0)
    assert matched.is_on_network
    assert matched.matched_edge_id in {"e1", "e2"}
    assert matched.cross_track_distance_m is not None
    assert matched.cross_track_distance_m <= 5.0
    assert matched.heading_delta_deg is not None
    assert matched.heading_delta_deg <= 45.0

    perpendicular = matcher.snap_location(18.5175, 73.8176, heading=143.0)
    assert not perpendicular.is_on_network
    assert perpendicular.status == "Off-Road / Pedestrian Path"

    off_network = matcher.snap_location(18.5200, 73.8200, heading=53.0)
    assert not off_network.is_on_network

    # Two parallel centerlines exercise the multi-tick hysteresis contract.
    offset = 0.00002
    custom_network = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "road_a_feature",
                "geometry": {"type": "LineString", "coordinates": [[73.8178, 18.5180], [73.8182, 18.5180]]},
                "properties": {"id": "road_a", "name": "Parallel Road A"},
            },
            {
                "type": "Feature",
                "id": "road_b_feature",
                "geometry": {"type": "LineString", "coordinates": [[73.8178, 18.5180 + offset], [73.8182, 18.5180 + offset]]},
                "properties": {"id": "road_b", "name": "Parallel Road B"},
            },
        ],
    }
    custom_path = tmp_path / "parallel_roads.geojson"
    custom_path.write_text(json.dumps(custom_network), encoding="utf-8")
    hysteresis = GPSMapMatcher(custom_path, switch_score_margin=0.12, switch_confirmation_ticks=2)
    first_match = hysteresis.snap_location(18.5180 + offset, 73.8180, previous_edge_id="road_a")
    assert first_match.matched_edge_id == "road_a"
    second_match = hysteresis.snap_location(18.5180 + offset, 73.8180, previous_edge_id="road_a")
    assert second_match.matched_edge_id == "road_b"


def test_api_endpoints() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["network_loaded"] is True

        network = client.get("/api/v1/network")
        assert network.status_code == 200
        network_payload = network.json()
        assert network_payload["type"] == "FeatureCollection"
        assert len(network_payload["features"]) >= 10
        assert "saturation_ratio" in network_payload["features"][0]["properties"]

        flow = client.post("/api/v1/solve-flow", json=BALANCED_FLOWS)
        assert flow.status_code == 200, flow.text
        flow_payload = flow.json()
        assert set(flow_payload["X"]) >= {"e1", "e19"}
        assert flow_payload["residual_error"] < 1e-4
        assert np.isclose(
            sum(flow_payload["signal_timing"]["green_phase_durations_sec"].values())
            + flow_payload["signal_timing"]["amber_clearance_sec"],
            flow_payload["signal_timing"]["cycle_time_sec"],
            atol=1e-6,
        )

        match = client.post(
            "/api/v1/map-match",
            json={
                "device_id": "integration-test-device",
                "latitude": 18.5175,
                "longitude": 73.81761,
                "heading": 53.0,
                "speed": 4.0,
            },
        )
        assert match.status_code == 200, match.text
        match_payload = match.json()
        assert match_payload["device_id"] == "integration-test-device"
        assert match_payload["is_on_network"] is True
        assert match_payload["matched_edge_id"] in {"e1", "e2"}


def test_closed_edge_has_zero_saturation() -> None:
    """A zero-capacity link is represented as closed without NaN saturation."""
    solver = TrafficMatrixSolver(NETWORK_PATH)
    edge_index = solver.edge_index["e1"]
    solver.capacities[edge_index] = 0.0
    solver.edges[edge_index]["capacity"] = 0.0
    result = solver.solve({"node_1": 90.0, "node_7": -20.0, "node_8": -70.0})
    assert result.edge_flows["e1"] == 0.0
    assert result.saturation_ratios["e1"] == 0.0
    assert result.edge_flows["e19"] > 0.0
