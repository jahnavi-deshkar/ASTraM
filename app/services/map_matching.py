"""GPS-to-road map matching for the ASTraM campus network.

Coordinates in the GeoJSON are WGS84 longitude/latitude. For campus-scale
distance and projection calculations, geometries are transformed into a local
east/north tangent plane centered on the network. This avoids measuring
Shapely distances directly in degrees while remaining accurate over the small
MIT-WPU operating area.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from shapely.geometry import LineString, Point
from shapely.ops import transform


EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class MapMatchResult:
    """Result of snapping one GPS fix to the campus road network."""

    snapped_latitude: float
    snapped_longitude: float
    matched_edge_id: str | None
    matched_edge_name: str | None
    cross_track_distance_m: float | None
    heading_delta_deg: float | None
    confidence_score: float
    is_on_network: bool
    status: str


@dataclass(frozen=True)
class _RoadCandidate:
    edge_id: str
    name: str
    geometry: LineString
    source_geometry: LineString


@dataclass(frozen=True)
class _ScoredCandidate:
    road: _RoadCandidate
    snapped_x: float
    snapped_y: float
    distance_m: float
    heading_delta_deg: float | None
    score: float


class GPSMapMatcher:
    """Match GPS fixes to valid road centerlines with heading and hysteresis.

    Args:
        geojson_path: Path to a GeoJSON FeatureCollection containing LineString
            features with unique ``properties.id`` and ``properties.name``.
        max_snap_distance_m: Maximum perpendicular distance for a match.
        max_heading_delta_deg: Candidates with a larger direction-independent
            heading delta are rejected when a heading is supplied.
        switch_score_margin: A replacement candidate must beat the previous
            edge by this score margin on consecutive observations.
        switch_confirmation_ticks: Consecutive superior observations needed
            before changing away from ``previous_edge_id``. Use one to disable
            multi-tick hysteresis.
        distance_weight: Weight of proximity in the composite score.
        heading_weight: Weight of heading agreement in the composite score.

    A matcher instance stores the pending switch counter. Use one matcher per
    tracked device/session to keep hysteresis state isolated between users.
    """

    def __init__(
        self,
        geojson_path: str | Path,
        max_snap_distance_m: float = 5.0,
        max_heading_delta_deg: float = 45.0,
        switch_score_margin: float = 0.12,
        switch_confirmation_ticks: int = 2,
        distance_weight: float = 0.65,
        heading_weight: float = 0.35,
    ) -> None:
        self.geojson_path = Path(geojson_path)
        self.max_snap_distance_m = self._finite(max_snap_distance_m, "max_snap_distance_m")
        self.max_heading_delta_deg = self._finite(max_heading_delta_deg, "max_heading_delta_deg")
        self.switch_score_margin = self._finite(switch_score_margin, "switch_score_margin")
        self.distance_weight = self._finite(distance_weight, "distance_weight")
        self.heading_weight = self._finite(heading_weight, "heading_weight")
        if self.max_snap_distance_m <= 0:
            raise ValueError("max_snap_distance_m must be greater than zero")
        if not 0.0 <= self.max_heading_delta_deg <= 90.0:
            raise ValueError("max_heading_delta_deg must be between 0 and 90 degrees")
        if self.switch_score_margin < 0:
            raise ValueError("switch_score_margin cannot be negative")
        if self.distance_weight < 0 or self.heading_weight < 0:
            raise ValueError("candidate score weights cannot be negative")
        if self.distance_weight + self.heading_weight <= 0:
            raise ValueError("at least one candidate score weight must be positive")
        if isinstance(switch_confirmation_ticks, bool) or not isinstance(
            switch_confirmation_ticks, int
        ) or switch_confirmation_ticks < 1:
            raise ValueError("switch_confirmation_ticks must be a positive integer")
        self.switch_confirmation_ticks = switch_confirmation_ticks

        payload = self._read_geojson(self.geojson_path)
        self._roads = self._parse_roads(payload)
        if not self._roads:
            raise ValueError("GeoJSON contains no usable LineString road features")
        coordinates = [coord for road in self._roads for coord in road.source_geometry.coords]
        self._origin_lon = sum(point[0] for point in coordinates) / len(coordinates)
        self._origin_lat = sum(point[1] for point in coordinates) / len(coordinates)
        self._origin_lat_rad = math.radians(self._origin_lat)
        self._projected_roads = tuple(
            _RoadCandidate(
                edge_id=road.edge_id,
                name=road.name,
                source_geometry=road.source_geometry,
                geometry=self._project_linestring(road.source_geometry),
            )
            for road in self._roads
        )
        self._roads_by_id = {road.edge_id: road for road in self._projected_roads}
        self._pending_switch: dict[str, tuple[str, int]] = {}

    @staticmethod
    def _finite(value: Any, label: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{label} must be a finite number")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a finite number") from exc
        if not math.isfinite(number):
            raise ValueError(f"{label} must be a finite number")
        return number

    @staticmethod
    def _haversine_distance_m(
        latitude_a: float,
        longitude_a: float,
        latitude_b: float,
        longitude_b: float,
    ) -> float:
        """Great-circle distance in meters between two WGS84 coordinates."""
        lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
        delta_lat = lat_b - lat_a
        delta_lon = math.radians(longitude_b - longitude_a)
        haversine = (
            math.sin(delta_lat / 2.0) ** 2
            + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2.0) ** 2
        )
        return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))

    @staticmethod
    def _read_geojson(path: Path) -> Mapping[str, Any]:
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                payload = json.load(file)
        except OSError as exc:
            raise ValueError(f"Unable to read road GeoJSON {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in road GeoJSON {path}: {exc}") from exc
        if not isinstance(payload, Mapping) or payload.get("type") != "FeatureCollection":
            raise ValueError("Road data must be a GeoJSON FeatureCollection")
        return payload

    @staticmethod
    def _parse_roads(payload: Mapping[str, Any]) -> list[_RoadCandidate]:
        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError("GeoJSON FeatureCollection must have a features array")
        roads: list[_RoadCandidate] = []
        seen: set[str] = set()
        for index, feature in enumerate(features):
            if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
                raise ValueError(f"GeoJSON feature {index} is invalid")
            geometry_data = feature.get("geometry")
            properties = feature.get("properties")
            if not isinstance(geometry_data, Mapping) or geometry_data.get("type") != "LineString":
                continue
            if not isinstance(properties, Mapping):
                raise ValueError(f"GeoJSON road feature {index} has no properties")
            edge_id, name = properties.get("id"), properties.get("name")
            if not isinstance(edge_id, str) or not edge_id:
                raise ValueError(f"GeoJSON road feature {index} has no valid properties.id")
            if edge_id in seen:
                raise ValueError(f"Duplicate road edge id: {edge_id}")
            if not isinstance(name, str) or not name:
                raise ValueError(f"Road edge {edge_id} has no valid properties.name")
            coordinates = geometry_data.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                raise ValueError(f"Road edge {edge_id} needs at least two coordinates")
            try:
                line = LineString(coordinates)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Road edge {edge_id} has invalid LineString coordinates") from exc
            if line.is_empty or not line.is_valid or line.length == 0:
                raise ValueError(f"Road edge {edge_id} has an empty, invalid, or zero-length LineString")
            if not all(math.isfinite(value) for coord in line.coords for value in coord[:2]):
                raise ValueError(f"Road edge {edge_id} contains non-finite coordinates")
            seen.add(edge_id)
            roads.append(_RoadCandidate(edge_id, name, line, line))
        return roads

    def _project_xy(self, longitude: float, latitude: float) -> tuple[float, float]:
        """Project WGS84 coordinates to local east/north meters."""
        lon_rad, lat_rad = math.radians(longitude), math.radians(latitude)
        x = EARTH_RADIUS_M * (lon_rad - math.radians(self._origin_lon)) * math.cos(
            self._origin_lat_rad
        )
        y = EARTH_RADIUS_M * (lat_rad - math.radians(self._origin_lat))
        return x, y

    def _unproject_xy(self, x: float, y: float) -> tuple[float, float]:
        latitude = self._origin_lat + math.degrees(y / EARTH_RADIUS_M)
        longitude = self._origin_lon + math.degrees(
            x / (EARTH_RADIUS_M * math.cos(self._origin_lat_rad))
        )
        return longitude, latitude

    def _project_linestring(self, line: LineString) -> LineString:
        projected = [self._project_xy(point[0], point[1]) for point in line.coords]
        return LineString(projected)

    @staticmethod
    def _bearing_degrees(x1: float, y1: float, x2: float, y2: float) -> float:
        """Return compass bearing clockwise from north in [0, 360)."""
        east, north = x2 - x1, y2 - y1
        return (math.degrees(math.atan2(east, north)) + 360.0) % 360.0

    @staticmethod
    def _direction_independent_delta(first: float, second: float) -> float:
        """Smallest angle between unoriented road axes, in [0, 90]."""
        delta = abs((first - second) % 180.0)
        return min(delta, 180.0 - delta)

    @staticmethod
    def _local_road_bearing(line: LineString, distance_along: float) -> float:
        """Get tangent bearing at the projected point, robust at vertices."""
        epsilon = min(0.75, max(line.length * 1e-4, 0.02))
        start = max(0.0, distance_along - epsilon)
        end = min(line.length, distance_along + epsilon)
        if end - start < 1e-8:
            start, end = 0.0, line.length
        first, second = line.interpolate(start), line.interpolate(end)
        return GPSMapMatcher._bearing_degrees(first.x, first.y, second.x, second.y)

    def _off_network_result(self, latitude: float, longitude: float) -> MapMatchResult:
        return MapMatchResult(
            snapped_latitude=latitude,
            snapped_longitude=longitude,
            matched_edge_id=None,
            matched_edge_name=None,
            cross_track_distance_m=None,
            heading_delta_deg=None,
            confidence_score=0.0,
            is_on_network=False,
            status="Off-Road / Pedestrian Path",
        )

    def snap_location(
        self,
        latitude: float,
        longitude: float,
        heading: float | None = None,
        speed: float | None = None,
        previous_edge_id: str | None = None,
    ) -> MapMatchResult:
        """Snap a GPS fix to a road candidate within distance and heading gates.

        Heading is a compass bearing in degrees clockwise from north. Road
        direction is compared modulo 180 degrees so opposite directed copies
        of a bidirectional road are treated as the same physical axis.
        """
        lat = self._finite(latitude, "latitude")
        lon = self._finite(longitude, "longitude")
        if not -90.0 <= lat <= 90.0:
            raise ValueError("latitude must be between -90 and 90 degrees")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("longitude must be between -180 and 180 degrees")
        gps_heading = None if heading is None else self._finite(heading, "heading") % 360.0
        if speed is not None and self._finite(speed, "speed") < 0:
            raise ValueError("speed cannot be negative")
        if previous_edge_id is not None and previous_edge_id not in self._roads_by_id:
            raise ValueError(f"Unknown previous_edge_id: {previous_edge_id}")

        x, y = self._project_xy(lon, lat)
        point = Point(x, y)
        candidates: list[_ScoredCandidate] = []
        for road in self._projected_roads:
            distance = point.distance(road.geometry)
            if distance > self.max_snap_distance_m:
                continue
            along = road.geometry.project(point)
            snapped = road.geometry.interpolate(along)
            snapped_lon, snapped_lat = self._unproject_xy(snapped.x, snapped.y)
            # Shapely supplies the nearest point on the projected line. Report
            # the actual WGS84 separation using a Haversine distance.
            distance = self._haversine_distance_m(lat, lon, snapped_lat, snapped_lon)
            if distance > self.max_snap_distance_m:
                continue
            delta: float | None = None
            heading_score = 1.0
            if gps_heading is not None:
                road_bearing = self._local_road_bearing(road.geometry, along)
                delta = self._direction_independent_delta(gps_heading, road_bearing)
                if delta > self.max_heading_delta_deg:
                    continue
                heading_score = max(0.0, math.cos(math.radians(delta)))
            distance_score = max(0.0, 1.0 - distance / self.max_snap_distance_m)
            weight_sum = self.distance_weight + (self.heading_weight if gps_heading is not None else 0.0)
            score = (
                self.distance_weight * distance_score
                + (self.heading_weight * heading_score if gps_heading is not None else 0.0)
            ) / weight_sum
            candidates.append(_ScoredCandidate(road, snapped.x, snapped.y, distance, delta, score))

        if not candidates:
            if previous_edge_id is not None:
                self._pending_switch.pop(previous_edge_id, None)
            return self._off_network_result(lat, lon)

        candidates.sort(key=lambda candidate: (-candidate.score, candidate.distance_m, candidate.road.edge_id))
        best = candidates[0]
        selected = best
        if previous_edge_id is not None:
            previous = next(
                (candidate for candidate in candidates if candidate.road.edge_id == previous_edge_id),
                None,
            )
            if previous is not None and best.road.edge_id != previous_edge_id:
                if best.score >= previous.score + self.switch_score_margin:
                    pending_edge, count = self._pending_switch.get(previous_edge_id, ("", 0))
                    count = count + 1 if pending_edge == best.road.edge_id else 1
                    self._pending_switch[previous_edge_id] = (best.road.edge_id, count)
                    if count < self.switch_confirmation_ticks:
                        selected = previous
                    else:
                        self._pending_switch.pop(previous_edge_id, None)
                else:
                    self._pending_switch.pop(previous_edge_id, None)
                    selected = previous
            else:
                self._pending_switch.pop(previous_edge_id, None)

        snapped_lon, snapped_lat = self._unproject_xy(selected.snapped_x, selected.snapped_y)
        return MapMatchResult(
            snapped_latitude=snapped_lat,
            snapped_longitude=snapped_lon,
            matched_edge_id=selected.road.edge_id,
            matched_edge_name=selected.road.name,
            cross_track_distance_m=selected.distance_m,
            heading_delta_deg=selected.heading_delta_deg,
            confidence_score=min(1.0, max(0.0, selected.score)),
            is_on_network=True,
            status="Matched",
        )


def _default_network_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "mit_wpu_roads.geojson"


if __name__ == "__main__":
    matcher = GPSMapMatcher(_default_network_path(), switch_confirmation_ticks=2)
    # Gate 1 Main Entrance follows a northeast bearing. Each point is about
    # one meter to the east of its centerline. The final fix moves near a
    # perpendicular connector to exercise heading rejection and hysteresis.
    simulated_track = [
        (18.517205, 73.817210, 53.0),
        (18.517355, 73.817410, 53.0),
        (18.517505, 73.817610, 53.0),
        (18.517655, 73.817810, 53.0),
        (18.517800, 73.818000, 53.0),
        (18.517810, 73.818020, 0.0),  # near junction; stationary heading can be noisy
    ]
    previous = None
    print("ASTraM GPS map-matching track")
    print(
        f"{'Fix':<5} {'GPS latitude':>14} {'GPS longitude':>15} "
        f"{'Matched edge':<8} {'Distance (m)':>13} {'Heading delta':>15} {'Status':<30}"
    )
    print("-" * 108)
    for index, (track_lat, track_lon, track_heading) in enumerate(simulated_track, start=1):
        result = matcher.snap_location(
            track_lat,
            track_lon,
            heading=track_heading,
            speed=2.0 if index < len(simulated_track) else 0.0,
            previous_edge_id=previous,
        )
        edge = result.matched_edge_id or "—"
        distance = "—" if result.cross_track_distance_m is None else f"{result.cross_track_distance_m:.2f}"
        delta = "—" if result.heading_delta_deg is None else f"{result.heading_delta_deg:.1f}°"
        print(
            f"{index:<5} {track_lat:>14.6f} {track_lon:>15.6f} "
            f"{edge:<8} {distance:>13} {delta:>15} {result.status:<30}"
        )
        if result.is_on_network:
            previous = result.matched_edge_id

    off_road = matcher.snap_location(18.5200, 73.8200, heading=53.0)
    print(
        f"\nOff-network check: {off_road.status}; "
        f"is_on_network={off_road.is_on_network}; confidence={off_road.confidence_score:.2f}"
    )

    # This fix lies on Gate 1 Main Avenue, but its reported heading is 90
    # degrees across the road axis. All nearby candidates must be rejected.
    perpendicular = matcher.snap_location(18.517500, 73.817600, heading=143.0)
    if perpendicular.is_on_network:
        raise AssertionError("Perpendicular heading should reject the Gate 1 road candidate")
    print(
        "Perpendicular-heading check: rejected as expected "
        f"(status={perpendicular.status})"
    )
