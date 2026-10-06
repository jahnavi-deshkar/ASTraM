"""ASTraM FastAPI application entry point."""

from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.endpoints import SIGNAL_PHASE_EDGES, router as api_router
from app.schemas import EdgeTrafficState, RealtimeTrafficState, VehiclePosition
from app.services.flow_solver import (
    BoundaryFlowError,
    OptimizationError,
    TrafficMatrixSolver,
)
from app.services.device_tracker import DeviceTracker
from app.services.map_matching import GPSMapMatcher
from app.services.traffic_physics import BPRCalculator, SignalOptimizer


NETWORK_PATH = Path(__file__).resolve().parents[1] / "data" / "mit_wpu_roads.geojson"
STATIC_PATH = Path(__file__).resolve().parents[1] / "static"
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "index.html"
BROADCAST_INTERVAL_SEC = 2.0


class ConnectionManager:
    """Track active WebSocket clients and isolate failed connections."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            connections = tuple(self.active_connections)
        if not connections:
            return
        message = json.dumps(payload, separators=(",", ":"), allow_nan=False)
        results = await asyncio.gather(
            *(connection.send_text(message) for connection in connections),
            return_exceptions=True,
        )
        stale = [
            connection
            for connection, result in zip(connections, results)
            if isinstance(result, BaseException)
        ]
        if stale:
            async with self._lock:
                self.active_connections.difference_update(stale)


def _make_realtime_state(app: FastAPI, tick: int) -> RealtimeTrafficState:
    state = app.state
    solver: TrafficMatrixSolver = state.traffic_solver
    solution = state.latest_solution
    device_aggregation = state.device_tracker.snapshot()
    occupancy_flows = device_aggregation["occupancy_equivalent_flows_vph"]
    base_flows = solution.edge_flows if solution is not None else {}
    flows: dict[str, float] = {}
    ratios: dict[str, float] = {}
    for edge in solver.edges:
        edge_id = edge["id"]
        capacity = float(edge["capacity"])
        measured = float(occupancy_flows.get(edge_id, 0.0))
        baseline = float(base_flows.get(edge_id, 0.0))
        flow = min(capacity, max(baseline, measured)) if capacity > 0 else 0.0
        flows[edge_id] = flow
        ratios[edge_id] = flow / capacity if capacity > 0 else 0.0
    metrics = state.bpr_calculator.calculate_network(solver.edges, flows)

    phase_ratios = {
        phase: max((ratios.get(edge_id, 0.0) for edge_id in edge_ids), default=0.0)
        for phase, edge_ids in SIGNAL_PHASE_EDGES.items()
    }
    live_timing = state.signal_optimizer.allocate_green_times(phase_ratios)
    state.latest_signal_timing = live_timing
    state.latest_live_edge_metrics = metrics
    edge_states: list[EdgeTrafficState] = []
    for edge_id in solver.edge_ids:
        metric = metrics[edge_id]
        density = device_aggregation["edge_density"].get(edge_id, {})
        edge_states.append(
            EdgeTrafficState(
                edge_id=edge_id,
                flow=flows[edge_id],
                saturation_ratio=ratios[edge_id],
                travel_time_sec=metric.travel_time_sec,
                delay_sec=metric.congestion_delay_sec,
                effective_speed_kmh=metric.effective_speed_kmh,
                capacity_warning=ratios[edge_id] >= state.signal_optimizer.warning_threshold,
                active_device_count=int(density.get("active_device_count", 0)),
                crowd_density_people_per_100m=float(density.get("people_per_100m", 0.0)),
            )
        )

    cycle = state.signal_optimizer.cycle_time_sec
    current_time = tick * BROADCAST_INTERVAL_SEC
    phase_names = ("north_approach", "east_approach", "south_approach", "west_approach")
    timing = live_timing
    position_in_cycle = current_time % cycle if cycle > 0 else 0.0
    active_phases = {phase: "red" for phase in phase_names}
    green_cursor = 0.0
    for phase in phase_names:
        phase_green = timing.green_times_sec.get(phase, 0.0)
        if green_cursor <= position_in_cycle < green_cursor + phase_green:
            active_phases[phase] = "green"
            break
        green_cursor += phase_green
    if position_in_cycle >= green_cursor:
        active_phases = {phase: "amber" for phase in phase_names}

    vehicle_positions = [
        VehiclePosition(
            vehicle_id=item["device_id"],
            edge_id=item["edge_id"],
            latitude=item["latitude"],
            longitude=item["longitude"],
            heading=float(item["heading"] or 0.0) % 360.0,
            speed_kmh=float(item["speed_mps"] or 0.0) * 3.6,
        )
        for item in device_aggregation["active_devices"]
        if item["edge_id"] is not None
    ]
    return RealtimeTrafficState(
        timestamp=datetime.now(timezone.utc).isoformat(),
        simulation_tick=tick,
        active_signal_phases=active_phases,
        signal_timing=timing.as_dict(),
        device_aggregation=device_aggregation,
        edges=edge_states,
        vehicle_positions=vehicle_positions,
    )


async def _broadcast_loop(app: FastAPI) -> None:
    tick = 0
    while True:
        tick += 1
        tracker_snapshot = app.state.device_tracker.snapshot()
        gate_flows = tracker_snapshot["solver_boundary_flows_vph"]
        if (
            time.monotonic() >= app.state.manual_override_until
            and any(tracker_snapshot["boundary_event_counts"].values())
            and gate_flows
            and gate_flows != app.state.latest_solution.requested_boundary_flows
        ):
            try:
                async with app.state.flow_lock:
                    app.state.latest_solution = await asyncio.to_thread(
                        app.state.traffic_solver.update_boundary_flows,
                        gate_flows,
                    )
            except (BoundaryFlowError, OptimizationError, ValueError):
                # Keep the last feasible matrix solution; device counts and
                # occupancy-derived road metrics still stream independently.
                pass
        active_ids = set(tracker_snapshot["active_device_ids"])
        async with app.state.matcher_lock:
            for device_id in tuple(app.state.device_matchers):
                if device_id not in active_ids:
                    app.state.device_matchers.pop(device_id, None)
                    app.state.device_previous_edges.pop(device_id, None)
        snapshot = _make_realtime_state(app, tick)
        await app.state.connection_manager.broadcast(snapshot.model_dump(mode="json"))
        await asyncio.sleep(BROADCAST_INTERVAL_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load campus services once and manage the shared broadcast task."""
    payload = json.loads(NETWORK_PATH.read_text(encoding="utf-8-sig"))
    solver = TrafficMatrixSolver(NETWORK_PATH)
    matcher_factory = lambda: GPSMapMatcher(NETWORK_PATH)
    signal_optimizer = SignalOptimizer(
        cycle_time_sec=90.0,
        minimum_green_sec=10.0,
        amber_clearance_sec=8.0,
        warning_threshold=0.75,
    )
    app.state.network_payload = payload
    app.state.traffic_solver = solver
    app.state.latest_solution = None
    app.state.bpr_calculator = BPRCalculator()
    app.state.signal_optimizer = signal_optimizer
    app.state.matcher_factory = matcher_factory
    app.state.device_matchers = {}
    app.state.device_previous_edges = {}
    app.state.device_tracker = DeviceTracker(payload, window_seconds=60.0)
    app.state.latest_live_edge_metrics = {}
    app.state.manual_override_until = 0.0
    app.state.matcher_lock = asyncio.Lock()
    app.state.flow_lock = asyncio.Lock()
    app.state.connection_manager = ConnectionManager()
    # Start with a feasible illustrative state so network and WebSocket
    # responses include calculated metrics immediately after startup.
    app.state.latest_solution = await asyncio.to_thread(
        solver.solve, {"node_1": 40.0, "node_7": 20.0, "node_8": -60.0}
    )
    app.state.latest_signal_timing = signal_optimizer.allocate_from_solver(
        solver, SIGNAL_PHASE_EDGES, app.state.latest_solution
    )
    app.state.broadcast_task = asyncio.create_task(_broadcast_loop(app))
    try:
        yield
    finally:
        app.state.broadcast_task.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.broadcast_task
        app.state.device_matchers.clear()
        app.state.device_previous_edges.clear()


app = FastAPI(
    title="ASTraM Backend Engine",
    description="Traffic flow, road physics, GPS map matching, and real-time campus state API.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    """Serve the ASTraM single-page operations dashboard."""
    return FileResponse(TEMPLATE_PATH, media_type="text/html")


@app.get("/health", tags=["System"])
async def health() -> dict[str, Any]:
    loaded = bool(getattr(app.state, "network_payload", None))
    return {
        "status": "ok" if loaded else "starting",
        "service": "ASTraM Backend Engine",
        "network_loaded": loaded,
        "edge_count": len(getattr(getattr(app.state, "traffic_solver", None), "edge_ids", ())),
        "node_count": len(getattr(getattr(app.state, "traffic_solver", None), "node_ids", ())),
    }


@app.websocket("/ws/traffic-stream")
async def traffic_stream(websocket: WebSocket) -> None:
    """Join the shared two-second traffic-state broadcast stream."""
    manager: ConnectionManager | None = getattr(app.state, "connection_manager", None)
    if manager is None:
        await websocket.close(code=1013, reason="ASTraM services are starting")
        return
    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
