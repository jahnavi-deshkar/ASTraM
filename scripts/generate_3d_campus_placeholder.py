"""Generate a low-poly, meter-scaled ASTraM campus base mesh in Blender.

Run from the repository root with:
    blender --background --python scripts/generate_3d_campus_placeholder.py

The road network is schematic. Building blocks and green spaces are explicitly
illustrative proxies positioned relative to the GeoJSON road extent; replace
them with surveyed footprints before using the model for engineering decisions.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
GEOJSON_PATH = ROOT / "data" / "mit_wpu_roads.geojson"
OUTPUT_PATH = ROOT / "static" / "assets" / "mit_wpu_campus.glb"
METERS_PER_DEGREE_LAT = 111_195.08
EARTH_RADIUS_M = 6_371_008.8
LANE_WIDTH_M = 3.2
FLOOR_HEIGHT_M = 3.5


def load_geojson(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as source:
        data = json.load(source)
    if data.get("type") != "FeatureCollection" or not data.get("features"):
        raise ValueError(f"{path} must be a GeoJSON FeatureCollection with road features")
    if not data.get("nodes"):
        raise ValueError(f"{path} must include node metadata")
    return data


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100


def make_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def move_to_collection(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float = 0.85,
    metallic: float = 0.0,
) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = roughness
        principled.inputs["Metallic"].default_value = metallic
    return material


class LocalProjection:
    """Convert WGS84 coordinates near campus into local Blender meters."""

    def __init__(self, coordinates: list[tuple[float, float]]) -> None:
        self.origin_lon = sum(lon for lon, _ in coordinates) / len(coordinates)
        self.origin_lat = sum(lat for _, lat in coordinates) / len(coordinates)
        self.origin_lat_rad = math.radians(self.origin_lat)
        self.lon_scale = EARTH_RADIUS_M * math.cos(self.origin_lat_rad) * math.pi / 180.0
        self.lat_scale = EARTH_RADIUS_M * math.pi / 180.0

    def project(self, longitude: float, latitude: float) -> tuple[float, float]:
        return (
            (longitude - self.origin_lon) * self.lon_scale,
            (latitude - self.origin_lat) * self.lat_scale,
        )


def make_polygon_object(
    name: str,
    points_xy: list[tuple[float, float]],
    z_bottom: float,
    z_top: float,
    material: bpy.types.Material,
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    if len(points_xy) < 3 or z_top <= z_bottom:
        raise ValueError(f"Polygon {name} must have at least 3 points and positive height")
    vertices = [(x, y, z_bottom) for x, y in points_xy] + [
        (x, y, z_top) for x, y in points_xy
    ]
    count = len(points_xy)
    faces = [tuple(range(count - 1, -1, -1)), tuple(range(count, count * 2))]
    faces.extend((index, (index + 1) % count, (index + 1) % count + count, index + count)
                 for index in range(count))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def line_ribbon(points: list[tuple[float, float]], width: float) -> list[tuple[float, float]]:
    """Build a stable mitered ribbon polygon around a polyline."""
    if len(points) < 2:
        raise ValueError("A road line requires at least two points")
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    half = width / 2.0
    for index, (x, y) in enumerate(points):
        before = points[max(index - 1, 0)]
        after = points[min(index + 1, len(points) - 1)]
        dx, dy = after[0] - before[0], after[1] - before[1]
        length = math.hypot(dx, dy)
        if length <= 1e-7:
            raise ValueError("Road centerline contains repeated coordinates")
        nx, ny = -dy / length, dx / length
        miter_scale = 1.0
        if 0 < index < len(points) - 1:
            previous = points[index - 1]
            following = points[index + 1]
            v1 = (x - previous[0], y - previous[1])
            v2 = (following[0] - x, following[1] - y)
            l1, l2 = math.hypot(*v1), math.hypot(*v2)
            n1 = (-v1[1] / l1, v1[0] / l1)
            n2 = (-v2[1] / l2, v2[0] / l2)
            mx, my = n1[0] + n2[0], n1[1] + n2[1]
            mlen = math.hypot(mx, my)
            if mlen > 1e-7:
                mx, my = mx / mlen, my / mlen
                denominator = max(abs(mx * n2[0] + my * n2[1]), 0.25)
                miter_scale = min(1.0 / denominator, 2.5)
                nx, ny = mx, my
        offset = half * miter_scale
        left.append((x + nx * offset, y + ny * offset))
        right.append((x - nx * offset, y - ny * offset))
    return left + list(reversed(right))


def create_road_network(
    geojson: dict,
    projection: LocalProjection,
    roads_collection: bpy.types.Collection,
    asphalt: bpy.types.Material,
) -> list[dict]:
    features = [feature for feature in geojson["features"] if feature.get("geometry", {}).get("type") == "LineString"]
    path_keys: dict[tuple[tuple[float, float], ...], list[dict]] = {}
    for feature in features:
        props = feature.get("properties", {})
        edge_id = str(props.get("id", ""))
        coordinates = feature["geometry"].get("coordinates", [])
        if not edge_id or len(coordinates) < 2:
            raise ValueError("Every road must have an edge id and at least two coordinates")
        xy = [projection.project(float(lon), float(lat)) for lon, lat, *_ in coordinates]
        key_forward = tuple((round(x, 3), round(y, 3)) for x, y in xy)
        key_reverse = tuple(reversed(key_forward))
        key = min(key_forward, key_reverse)
        path_keys.setdefault(key, []).append(
            {"feature": feature, "edge_id": edge_id, "xy": xy, "properties": props}
        )

    road_metadata: list[dict] = []
    for group in path_keys.values():
        for entry in group:
            props = entry["properties"]
            edge_id = entry["edge_id"]
            lanes = int(props.get("lanes", 1))
            if lanes < 1:
                raise ValueError(f"Road {edge_id} has invalid lane count {lanes}")
            ribbon_width = lanes * LANE_WIDTH_M
            # Opposite directed features share one physical carriageway pair.
            # Offset each directional ribbon to its left to avoid duplicate
            # overlapping polygons and preserve edge-specific dynamic coloring.
            is_paired = len(group) > 1
            offset = ribbon_width / 2.0 if is_paired else 0.0
            if is_paired:
                start, end = entry["xy"][0], entry["xy"][-1]
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = math.hypot(dx, dy)
                normal = (-dy / length, dx / length)
                centerline = [
                    (x + normal[0] * offset, y + normal[1] * offset)
                    for x, y in entry["xy"]
                ]
            else:
                centerline = entry["xy"]
            footprint = line_ribbon(centerline, ribbon_width)
            road = make_polygon_object(
                f"Road_{edge_id}", footprint, 0.075, 0.14, asphalt, roads_collection
            )
            road["interactiveType"] = "road"
            road["edgeId"] = edge_id
            road["displayName"] = str(props.get("name", edge_id))
            road["capacity"] = float(props.get("capacity", 0.0))
            road["lanes"] = lanes
            road_metadata.append(
                {"edge_id": edge_id, "name": road.name, "width_m": ribbon_width}
            )
    return road_metadata


def create_ground(
    geojson: dict,
    projection: LocalProjection,
    collection: bpy.types.Collection,
    grass: bpy.types.Material,
    concrete: bpy.types.Material,
) -> tuple[float, float, float, float]:
    all_points = [
        projection.project(float(lon), float(lat))
        for feature in geojson["features"]
        for lon, lat, *_ in feature["geometry"]["coordinates"]
        if feature.get("geometry", {}).get("type") == "LineString"
    ]
    min_x, max_x = min(x for x, _ in all_points), max(x for x, _ in all_points)
    min_y, max_y = min(y for _, y in all_points), max(y for _, y in all_points)
    margin = 38.0
    bounds = (min_x - margin, max_x + margin, min_y - margin, max_y + margin)
    x0, x1, y0, y1 = bounds
    ground = make_polygon_object(
        "Campus_Terrain_Base",
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        -0.35,
        -0.08,
        grass,
        collection,
    )
    ground["description"] = "Flat visualization base; terrain elevation is not surveyed."
    # A thin concrete apron visually distinguishes circulation surfaces from lawns.
    apron_margin = 5.0
    apron = make_polygon_object(
        "Campus_Concrete_Apron",
        [
            (x0 + apron_margin, y0 + apron_margin),
            (x1 - apron_margin, y0 + apron_margin),
            (x1 - apron_margin, y1 - apron_margin),
            (x0 + apron_margin, y1 - apron_margin),
        ],
        -0.075,
        -0.025,
        concrete,
        collection,
    )
    apron["interactiveType"] = "pathway"
    return bounds


def create_building_proxies(
    projection: LocalProjection,
    campus_center: tuple[float, float],
    collection: bpy.types.Collection,
    wall: bpy.types.Material,
    glass: bpy.types.Material,
) -> None:
    """Create clearly labeled schematic blocks, not surveyed footprints."""
    center_x, center_y = projection.project(*campus_center)
    proxies = [
        ("Saraswati", "Academic building proxy", -36.0, 12.0, 30.0, 22.0, 4),
        ("Vishwakarma", "Academic building proxy", 31.0, 19.0, 27.0, 20.0, 5),
        ("SportsComplex", "Sports complex massing proxy", 2.0, -48.0, 42.0, 30.0, 2),
    ]
    for suffix, description, offset_x, offset_y, width, depth, floors in proxies:
        x, y = center_x + offset_x, center_y + offset_y
        obj = make_polygon_object(
            f"Building_{suffix}",
            [
                (x - width / 2, y - depth / 2),
                (x + width / 2, y - depth / 2),
                (x + width / 2, y + depth / 2),
                (x - width / 2, y + depth / 2),
            ],
            0.15,
            0.15 + floors * FLOOR_HEIGHT_M,
            wall,
            collection,
        )
        obj["interactiveType"] = "building"
        obj["displayName"] = suffix.replace("Complex", " Complex")
        obj["description"] = description
        obj["floors"] = floors
        obj["heightMeters"] = floors * FLOOR_HEIGHT_M
        obj["geometryStatus"] = "illustrative_proxy"
        # A restrained glass entry strip enriches the massing while staying low-poly.
        glass_width = min(4.0, width * 0.2)
        glass_depth = 0.18
        entrance = make_polygon_object(
            f"{obj.name}_EntryGlazing",
            [
                (x - glass_width / 2, y - depth / 2 - 0.04),
                (x + glass_width / 2, y - depth / 2 - 0.04),
                (x + glass_width / 2, y - depth / 2 + glass_depth),
                (x - glass_width / 2, y - depth / 2 + glass_depth),
            ],
            0.18,
            0.18 + min(3.0, floors * FLOOR_HEIGHT_M),
            glass,
            collection,
        )
        entrance["interactiveType"] = "building_detail"
        entrance.parent = obj


def create_green_spaces(
    bounds: tuple[float, float, float, float],
    collection: bpy.types.Collection,
    grass: bpy.types.Material,
) -> None:
    x0, x1, y0, y1 = bounds
    patches = [
        ("Lawn_CentralWest", x0 + 42, y0 + 111, 27, 18),
        ("Lawn_NorthEast", x1 - 39, y1 - 54, 24, 16),
        ("Lawn_SouthEast", x1 - 48, y0 + 48, 22, 17),
    ]
    for name, x, y, width, depth in patches:
        patch = make_polygon_object(
            name,
            [
                (x - width / 2, y - depth / 2),
                (x + width / 2, y - depth / 2),
                (x + width / 2, y + depth / 2),
                (x - width / 2, y + depth / 2),
            ],
            -0.015,
            0.015,
            grass,
            collection,
        )
        patch["geometryStatus"] = "illustrative_green_space"


def create_landmarks(
    collection: bpy.types.Collection,
    concrete: bpy.types.Material,
) -> None:
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=2.0, depth=4.0, location=(0.0, 0.0, 2.0))
    gate = bpy.context.object
    gate.name = "Landmark_Gate1Marker"
    gate.data.name = "Landmark_Gate1Marker_Mesh"
    gate.data.materials.append(concrete)
    move_to_collection(gate, collection)
    gate["interactiveType"] = "landmark"
    gate["displayName"] = "Gate 1 Marker"
    gate["description"] = "Illustrative entry marker anchored at the local model origin."


def export_glb(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
        export_extras=True,
        export_yup=True,
    )


def main() -> None:
    if not GEOJSON_PATH.is_file():
        raise FileNotFoundError(f"Campus road file does not exist: {GEOJSON_PATH}")
    geojson = load_geojson(GEOJSON_PATH)
    geographic_coordinates = [
        (float(lon), float(lat))
        for feature in geojson["features"]
        if feature.get("geometry", {}).get("type") == "LineString"
        for lon, lat, *_ in feature["geometry"]["coordinates"]
    ]
    if not geographic_coordinates:
        raise ValueError("No LineString coordinates found in campus GeoJSON")

    clear_scene()
    projection = LocalProjection(geographic_coordinates)
    roads_collection = make_collection("Terrain_GroundRoads_Pathways")
    buildings_collection = make_collection("Buildings")
    lawns_collection = make_collection("Lawns_GreenSpaces")
    landmarks_collection = make_collection("Landmarks")

    asphalt = make_material("M_Asphalt", (0.105, 0.125, 0.145, 1.0), 0.94)
    grass = make_material("M_Grass", (0.16, 0.32, 0.19, 1.0), 0.96)
    concrete = make_material("M_Concrete", (0.55, 0.55, 0.51, 1.0), 0.88)
    glass = make_material("M_Glass", (0.24, 0.46, 0.56, 1.0), 0.28, 0.05)
    wall = make_material("M_BuildingWall", (0.72, 0.69, 0.61, 1.0), 0.84)

    bounds = create_ground(geojson, projection, roads_collection, grass, concrete)
    road_records = create_road_network(geojson, projection, roads_collection, asphalt)
    campus_center = (
        sum(lon for lon, _ in geographic_coordinates) / len(geographic_coordinates),
        sum(lat for _, lat in geographic_coordinates) / len(geographic_coordinates),
    )
    create_building_proxies(projection, campus_center, buildings_collection, wall, glass)
    create_green_spaces(bounds, lawns_collection, grass)
    create_landmarks(landmarks_collection, concrete)

    bpy.context.scene["coordinateOriginLongitude"] = projection.origin_lon
    bpy.context.scene["coordinateOriginLatitude"] = projection.origin_lat
    bpy.context.scene["linearUnit"] = "meter"
    bpy.context.scene["roadEdgeCount"] = len(road_records)
    bpy.context.scene["geometryStatus"] = "schematic_visualization_base"
    export_glb(OUTPUT_PATH)
    print(f"Generated {len(road_records)} edge-specific road meshes at {OUTPUT_PATH}")
    print("Building footprints and ground heights are illustrative, not surveyed.")


if __name__ == "__main__":
    main()
