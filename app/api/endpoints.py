"""REST endpoints connecting ASTraM services to HTTP clients."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas import (
    BoundaryFlowRequest,
    FlowSolverResponse,
    GPSFixRequest,
    MapMatchResponse,
    NetworkResponse,
    SignalTimingResponse,
)
from app.services.flow_solver import BoundaryFlowError, NetworkDataError, OptimizationError
from app.services.traffic_physics import BPRCalculator, SignalOptimizer


router = APIRouter(prefix="/api/v1", tags=["ASTraM"])

SIGNAL_PHASE_EDGES: dict[str, tuple[str, ...]] = {
    "north_approach": ("e13", "e11"),
    "east_approach": ("e5", "e15"),
    "south_approach": ("e8", "e10"),
    "west_approach": ("e7", "e17"),
}


def _require_initialized(request: Request) -> None:
    if not getattr(request.app.state, "network_payload", None):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ASTraM network services have not completed startup",
        )


@router.post(
    "/solve-flow",
    response_model=FlowSolverResponse,
    summary="Solve bounded campus traffic flows",
    responses={422: {"description": "Invalid or capacity-infeasible boundary flows"}},
)
async def solve_flow(body: BoundaryFlowRequest, request: Request) -> FlowSolverResponse:
    """Solve node conservation, BPR delays, warnings, and signal green splits."""
    _require_initialized(request)
    app_state = request.app.state
    try:
        async with app_state.flow_lock:
            result = await asyncio.to_thread(
                app_state.traffic_solver.update_boundary_flows, body.boundary_flows
            )
            app_state.latest_solution = result
            metrics = await asyncio.to_thread(
                app_state.bpr_calculator.calculate_from_solver,
                app_state.traffic_solver,
                result,
            )
            timing = app_state.signal_optimizer.allocate_from_solver(
                app_state.traffic_solver,
                SIGNAL_PHASE_EDGES,
                result,
            )
            app_state.latest_signal_timing = timing
            warnings = app_state.signal_optimizer.capacity_warnings(result)
    except (BoundaryFlowError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (NetworkDataError, OptimizationError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return FlowSolverResponse(
        X=result.edge_flows,
        saturation_ratios=result.saturation_ratios,
        bpr_delay_penalties_sec={
            edge_id: metric.congestion_delay_sec for edge_id, metric in metrics.items()
        },
        effective_speeds_kmh={
            edge_id: metric.effective_speed_kmh for edge_id, metric in metrics.items()
        },
        travel_times_sec={edge_id: metric.travel_time_sec for edge_id, metric in metrics.items()},
        residual_error=result.residual_error,
        node_conservation=result.node_conservation,
        signal_timing=SignalTimingResponse(
            cycle_time_sec=timing.cycle_time_sec,
            green_phase_durations_sec=timing.green_times_sec,
            amber_clearance_sec=timing.amber_clearance_sec,
            total_allocated_sec=timing.total_allocated_sec,
            extended_phases=list(timing.extended_phases),
            warning_flags=[
                f"{edge_id} saturation {warning['saturation_ratio']:.3f} reached warning threshold {warning['threshold']:.2f}"
                for edge_id, warning in warnings.items()
            ],
        ),
        capacity_warnings=warnings,
    )


@router.post(
    "/map-match",
    response_model=MapMatchResponse,
    summary="Match a device GPS fix to a campus road",
)
async def map_match(body: GPSFixRequest, request: Request) -> MapMatchResponse:
    """Map-match a GPS fix, retaining one matcher and previous edge per device."""
    _require_initialized(request)
    app_state = request.app.state
    async with app_state.matcher_lock:
        matcher = app_state.device_matchers.get(body.device_id)
        if matcher is None:
            matcher = app_state.matcher_factory()
            app_state.device_matchers[body.device_id] = matcher
        previous_edge = app_state.device_previous_edges.get(body.device_id)
        result = await asyncio.to_thread(
            matcher.snap_location,
            body.latitude,
            body.longitude,
            body.heading,
            body.speed,
            previous_edge,
        )
        if result.is_on_network:
            app_state.device_previous_edges[body.device_id] = result.matched_edge_id
        else:
            app_state.device_previous_edges.pop(body.device_id, None)
    return MapMatchResponse(device_id=body.device_id, **result.__dict__)


@router.get(
    "/network",
    response_model=NetworkResponse,
    summary="Get campus road GeoJSON with latest traffic metrics",
)
async def get_network(request: Request) -> dict[str, Any]:
    """Return the road FeatureCollection enriched with the latest edge state."""
    _require_initialized(request)
    app_state = request.app.state
    payload = json.loads(json.dumps(app_state.network_payload))
    solution = app_state.latest_solution
    if solution is None:
        flow_map: dict[str, float] = {}
        saturation_map: dict[str, float] = {}
        metric_map: dict[str, Any] = {}
    else:
        flow_map = solution.edge_flows
        saturation_map = solution.saturation_ratios
        metric_map = await asyncio.to_thread(
            app_state.bpr_calculator.calculate_from_solver,
            app_state.traffic_solver,
            solution,
        )
    warnings = (
        app_state.signal_optimizer.capacity_warnings(solution)
        if solution is not None
        else {}
    )
    for feature in payload.get("features", []):
        properties = feature.setdefault("properties", {})
        edge_id = properties.get("id")
        metric = metric_map.get(edge_id)
        properties["real_time_flow"] = flow_map.get(edge_id)
        properties["saturation_ratio"] = saturation_map.get(edge_id)
        properties["effective_speed_kmh"] = (
            metric.effective_speed_kmh if metric is not None else None
        )
        properties["travel_time_sec"] = metric.travel_time_sec if metric is not None else None
        properties["delay_sec"] = metric.congestion_delay_sec if metric is not None else None
        properties["capacity_warning"] = edge_id in warnings
    return payload
