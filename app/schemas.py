"""Pydantic request and response models for the ASTraM backend API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BoundaryFlowRequest(BaseModel):
    """Net external flow by node; entries are positive, exits negative."""

    boundary_flows: dict[str, float] = Field(..., min_length=1)

    @model_validator(mode="before")
    @classmethod
    def accept_direct_mapping(cls, value: Any) -> Any:
        if isinstance(value, dict) and "boundary_flows" not in value:
            return {"boundary_flows": value}
        return value

    @field_validator("boundary_flows")
    @classmethod
    def validate_boundary_flows(cls, values: dict[str, float]) -> dict[str, float]:
        if not values:
            raise ValueError("boundary_flows cannot be empty")
        if any(not node_id.strip() for node_id in values):
            raise ValueError("boundary flow node IDs cannot be empty")
        return values


class GPSFixRequest(BaseModel):
    """One device GPS fix for map matching."""

    device_id: str = Field(..., min_length=1, max_length=128)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    heading: float | None = Field(default=None, ge=0.0, le=360.0)
    speed: float | None = Field(default=None, ge=0.0, description="Speed in meters/second")

    @field_validator("device_id")
    @classmethod
    def normalize_device_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("device_id cannot be blank")
        return value


class SignalTimingResponse(BaseModel):
    cycle_time_sec: float = Field(..., ge=0.0)
    green_phase_durations_sec: dict[str, float]
    amber_clearance_sec: float = Field(..., ge=0.0)
    total_allocated_sec: float = Field(..., ge=0.0)
    extended_phases: list[str] = Field(default_factory=list)
    warning_flags: list[str] = Field(default_factory=list)


class FlowSolverResponse(BaseModel):
    X: dict[str, float]
    saturation_ratios: dict[str, float]
    bpr_delay_penalties_sec: dict[str, float]
    effective_speeds_kmh: dict[str, float]
    travel_times_sec: dict[str, float]
    residual_error: float = Field(..., ge=0.0)
    node_conservation: dict[str, dict[str, float]]
    signal_timing: SignalTimingResponse
    capacity_warnings: dict[str, dict[str, Any]] = Field(default_factory=dict)


class MapMatchResponse(BaseModel):
    device_id: str
    snapped_latitude: float
    snapped_longitude: float
    matched_edge_id: str | None
    matched_edge_name: str | None
    cross_track_distance_m: float | None
    heading_delta_deg: float | None
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    is_on_network: bool
    status: str
    active_device_count: int = Field(default=0, ge=0)
    matched_edge_device_count: int = Field(default=0, ge=0)
    crowd_density_people_per_100m: float = Field(default=0.0, ge=0.0)


class ActiveDeviceState(BaseModel):
    device_id: str
    edge_id: str | None
    latitude: float
    longitude: float
    heading: float | None = None
    speed_mps: float | None = Field(default=None, ge=0.0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    last_seen: str


class DeviceAggregationResponse(BaseModel):
    window_seconds: float = Field(..., gt=0.0)
    active_device_count: int = Field(..., ge=0)
    active_devices: list[ActiveDeviceState]
    edge_device_counts: dict[str, int]
    edge_density: dict[str, dict[str, float | int]]
    boundary_event_counts: dict[str, int]
    boundary_flows_vph: dict[str, float]
    solver_boundary_flows_vph: dict[str, float]
    boundary_flows_balanced: bool
    boundary_flow_net_vph: float


class EdgeTrafficState(BaseModel):
    edge_id: str
    flow: float
    saturation_ratio: float = Field(..., ge=0.0)
    travel_time_sec: float = Field(..., ge=0.0)
    delay_sec: float = Field(..., ge=0.0)
    effective_speed_kmh: float = Field(..., ge=0.0)
    capacity_warning: bool
    active_device_count: int = Field(default=0, ge=0)
    crowd_density_people_per_100m: float = Field(default=0.0, ge=0.0)


class VehiclePosition(BaseModel):
    vehicle_id: str
    edge_id: str
    latitude: float
    longitude: float
    heading: float = Field(..., ge=0.0, le=360.0)
    speed_kmh: float = Field(..., ge=0.0)


class RealtimeTrafficState(BaseModel):
    timestamp: str
    simulation_tick: int
    active_signal_phases: dict[str, str]
    signal_timing: dict[str, Any] = Field(default_factory=dict)
    device_aggregation: DeviceAggregationResponse
    edges: list[EdgeTrafficState]
    vehicle_positions: list[VehiclePosition]


class HealthResponse(BaseModel):
    status: str
    service: str
    network_loaded: bool
    edge_count: int
    node_count: int


class ErrorResponse(BaseModel):
    detail: str
    context: dict[str, Any] | None = None


class NetworkResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    features: list[dict[str, Any]]
