"""Prepare and export the MIT-WPU campus scene for the ASTraM Three.js viewer.

Run from the project root with Blender 5.2:
    blender --background mit_wpu_phase7.blend --python scripts/export_gltf_campus_model.py

The script writes static/assets/mit_wpu_campus.glb, bakes evaluated mesh
modifiers (including Geometry Nodes instances), and preserves WebGL identifier
names used by static/js/three_campus_loader.js.
"""

from __future__ import annotations

import re
from pathlib import Path

import bpy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "static" / "assets" / "mit_wpu_campus.glb"
FOLIAGE_COLLECTION = "08_FOLIAGE_LANDSCAPE"
ROAD_COLLECTION = "01_TERRAIN_ROADS"
BUILDING_GROUPS = (
    ("Building_Saraswati", "Saraswati", "Saraswati academic building", 5, 20.0,
     "02_SOUTH_CAMPUS"),
    ("Building_Dnyaneshwar", "Dnyaneshwar", "Dnyaneshwar academic building", 5, 20.0,
     "03_CENTRAL_CAMPUS"),
    ("Building_Vashistha", "Vashistha", "Vashistha academic building", 5, 20.0,
     "03_CENTRAL_CAMPUS"),
    ("Building_SportsComplex", "Sports_Complex", "Sports and recreation facility", 2, 15.0,
     "06_NORTH_SPORTS_CAMPUS"),
    ("Building_VivekanandRotunda", "Vivekanand", "Vivekanand Rotunda academic building", 4, 16.0,
     "04_MIDWEST_CAMPUS"),
    ("Building_Aryabhata", "Aryabhata", "Aryabhata academic building", 4, 16.0,
     "05_MIDEAST_CAMPUS"),
)


def require_blender_52():
    version = bpy.app.version
    if version < (5, 2, 0):
        raise RuntimeError(
            f"Blender 5.2 or newer is required; running {bpy.app.version_string}."
        )


def find_collection(name: str):
    return bpy.data.collections.get(name)


def iter_collection_objects(collection):
    """Yield objects from a collection and its nested collections once."""
    if collection is None:
        return
    seen = set()
    stack = [collection]
    while stack:
        current = stack.pop()
        for obj in current.objects:
            if obj.name not in seen:
                seen.add(obj.name)
                yield obj
        stack.extend(current.children)


def collection_memberships(obj):
    return {collection.name for collection in obj.users_collection}


def split_road_mesh(mesh, prefix):
    """Return left/right half-width meshes from the Phase 3 road ribbon layout."""
    vertex_count = len(mesh.vertices)
    if vertex_count == 0 or vertex_count % 4:
        raise RuntimeError(
            f"Road mesh {mesh.name!r} does not have the expected four ribbon vertex rows."
        )
    count = vertex_count // 4
    rows = [[vertex.co.copy() for vertex in mesh.vertices[start:start + count]]
            for start in (0, count, 2 * count, 3 * count)]
    bottom_left, bottom_right, top_left, top_right = rows
    bottom_center = [(a + b) * 0.5 for a, b in zip(bottom_left, bottom_right)]
    top_center = [(a + b) * 0.5 for a, b in zip(top_left, top_right)]

    def build_half(name, edge_a_bottom, edge_b_bottom, edge_a_top, edge_b_top):
        vertices = [tuple(v) for row in (edge_a_bottom, edge_b_bottom, edge_a_top, edge_b_top)
                    for v in row]
        n = count
        base = 2 * n
        faces = []
        for i in range(n - 1):
            faces.append((base + i, base + i + 1, base + n + i + 1, base + n + i))
            faces.append((i, n + i, n + i + 1, i + 1))
            faces.append((i, i + 1, base + i + 1, base + i))
            faces.append((n + i, base + n + i, base + n + i + 1, n + i + 1))
        faces.extend(((0, base, base + n, n),
                      (n - 1, 2 * n - 1, 3 * n - 1, base + n - 1)))
        result = bpy.data.meshes.new(name)
        result.from_pydata(vertices, [], faces)
        for material in mesh.materials:
            result.materials.append(material)
        result.update()
        return result

    # An edge is oriented in the GeoJSON direction. Its right half corresponds
    # to the opposite edge's left half under right-hand campus traffic.
    left_mesh = build_half(f"{prefix}_LeftLane_Mesh", bottom_left, bottom_center,
                           top_left, top_center)
    right_mesh = build_half(f"{prefix}_RightLane_Mesh", bottom_center, bottom_right,
                            top_center, top_right)
    return left_mesh, right_mesh


def ensure_building_identifiers():
    """Create named raycast parents around each building's component meshes."""
    orientation = bpy.data.objects.get("Campus_Orientation_Root")
    created = []
    for object_name, name_token, description, floors, height, sector_name in BUILDING_GROUPS:
        sector = find_collection(sector_name)
        if sector is None:
            print(f"WARNING: Missing {sector_name}; cannot group {object_name} components.")
            continue

        root = bpy.data.objects.get(object_name)
        if root is None:
            root = bpy.data.objects.new(object_name, None)
            root.empty_display_type = "PLAIN_AXES"
            root.empty_display_size = 2.0
            sector.objects.link(root)
            if orientation is not None:
                root.parent = orientation
                root.location = (0.0, 0.0, 0.0)
                root.rotation_euler = (0.0, 0.0, 0.0)
            created.append(object_name)

        root["interactiveType"] = "building"
        root["displayName"] = object_name.removeprefix("Building_")
        root["description"] = description
        root["floors"] = floors
        root["heightMeters"] = height

        candidates = []
        for obj in iter_collection_objects(sector):
            if obj == root or obj.type != "MESH":
                continue
            if obj.name.startswith("Building_"):
                continue
            if name_token.casefold() in obj.name.casefold():
                candidates.append(obj)

        # Keep each component's world matrix unchanged while placing it under a
        # named root. The viewer raycasts child meshes and resolves their parent.
        for obj in candidates:
            if obj.parent == root:
                continue
            world_matrix = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = world_matrix

    print(f"Interactive building identifiers ready; created {len(created)} root(s): "
          f"{', '.join(created) if created else 'none (existing roots reused)'}")


def normalize_road_names():
    """Rename road ribbons and restore deduplicated reverse-direction IDs.

    Phase 3 creates one physical mesh for each pair of opposite directed
    GeoJSON edges (e1/e2, e3/e4, ...). The reverse edge gets its own named
    object sharing the physical ribbon mesh, so the loader can index every
    edge ID without duplicating the underlying geometry data.
    """
    collection = find_collection(ROAD_COLLECTION)
    if collection is None:
        raise RuntimeError(f"Required road collection {ROAD_COLLECTION!r} is missing.")

    pattern = re.compile(r"^RoadRibbon_(?:Road_)?(e\d+)(?:_|$)", re.IGNORECASE)
    found = {}
    for obj in iter_collection_objects(collection):
        if obj.type != "MESH":
            continue
        match = pattern.match(obj.name)
        if not match:
            # Allow scenes whose road ribbons were already renamed.
            match = re.match(r"^Road_(e\d+)$", obj.name, re.IGNORECASE)
        if not match:
            continue
        edge_id = match.group(1).lower()
        expected_name = f"Road_{edge_id}"
        if edge_id in found and found[edge_id] != obj:
            raise RuntimeError(
                f"Multiple road ribbon meshes map to {expected_name}: "
                f"{found[edge_id].name!r}, {obj.name!r}."
            )
        found[edge_id] = obj
        obj.name = expected_name
        obj["edgeId"] = edge_id
        obj["interactiveType"] = "road"

    expected = {f"e{i}" for i in range(1, 31)}
    missing = sorted(expected - set(found), key=lambda value: int(value[1:]))
    aliases = []
    for edge_id in missing:
        number = int(edge_id[1:])
        # The GeoJSON road graph stores each undirected physical path twice,
        # once for each direction. Phase 3's canonical path dedupe retains the
        # first (odd-numbered) member of each pair.
        source_number = number - 1 if number % 2 == 0 else number + 1
        source_id = f"e{source_number}"
        source = found.get(source_id)
        if source is None:
            continue
        old_mesh = source.data
        left_mesh, right_mesh = split_road_mesh(old_mesh, f"Road_{source_id}")
        source.data = right_mesh
        alias = source.copy()
        alias.data = left_mesh
        alias.name = f"Road_{edge_id}"
        alias["edgeId"] = edge_id
        alias["interactiveType"] = "road"
        alias["directionAliasOf"] = source_id
        collection.objects.link(alias)
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        found[edge_id] = alias
        aliases.append((edge_id, source_id))

    missing = sorted(expected - set(found), key=lambda value: int(value[1:]))
    extra = sorted(set(found) - expected)
    if missing:
        raise RuntimeError(
            "Road ribbon validation failed. Missing road IDs: " + ", ".join(missing) +
            ". Ensure Phase 3 road meshes from data/mit_wpu_roads.geojson are in " +
            "01_TERRAIN_ROADS before exporting."
        )
    if extra:
        print("WARNING: Extra road IDs found: " + ", ".join(extra))
    alias_summary = ", ".join(f"{alias}<-{source}" for alias, source in aliases)
    print(f"Road raycast IDs validated: {len(found)} objects named Road_e1 through Road_e30; "
          f"reverse-direction aliases: {alias_summary or 'none'}.")


def bake_mesh_modifiers_and_instances():
    """Replace evaluated modifier output with real mesh data on each mesh object."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    baked_modifiers = 0
    baked_instances = 0
    for obj in mesh_objects:
        if not obj.modifiers:
            continue

        modifier_count = len(obj.modifiers)
        had_geometry_nodes = any(mod.type == "NODES" for mod in obj.modifiers)
        evaluated = obj.evaluated_get(depsgraph)
        baked_mesh = bpy.data.meshes.new_from_object(
            evaluated,
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        if baked_mesh is None:
            raise RuntimeError(f"Could not bake evaluated mesh for {obj.name!r}.")
        baked_mesh.name = f"{obj.name}_BakedMesh"
        old_mesh = obj.data
        obj.data = baked_mesh
        for modifier in list(obj.modifiers):
            obj.modifiers.remove(modifier)
        if old_mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        baked_modifiers += modifier_count
        if had_geometry_nodes:
            baked_instances += 1

    print(f"Baked modifiers: {baked_modifiers}; Geometry Nodes mesh objects realized: "
          f"{baked_instances}.")


def purge_orphan_datablocks():
    # Repeat because removal of one datablock can orphan another datablock type.
    removed_total = 0
    while True:
        removed = bpy.data.orphans_purge(
            do_local_ids=True,
            do_linked_ids=True,
            do_recursive=True,
        )
        if not removed:
            break
        removed_total += removed
    print(f"Purged {removed_total} orphan datablock(s).")


def export_glb():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.gltf(
        filepath=str(OUTPUT_PATH),
        export_format="GLB",
        export_apply=True,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        # Blender 5.2 exposes vertex-color export as an enum (the former
        # export_colors boolean is no longer a supported operator argument).
        export_vertex_color="MATERIAL",
        export_all_vertex_colors=True,
        export_cameras=False,
        export_lights=False,
        export_extras=True,
        export_yup=True,
        export_image_format="AUTO",
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF export did not finish successfully: {result}")
    if not OUTPUT_PATH.is_file() or OUTPUT_PATH.stat().st_size == 0:
        raise RuntimeError(f"Export reported success but GLB is missing or empty: {OUTPUT_PATH}")
    print(f"Exported binary glTF: {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")


def main():
    require_blender_52()
    if bpy.context.scene is None:
        raise RuntimeError("No active Blender scene is available to export.")
    if find_collection(FOLIAGE_COLLECTION) is None:
        print(f"WARNING: {FOLIAGE_COLLECTION} is missing; continuing without foliage scattering.")

    ensure_building_identifiers()
    normalize_road_names()
    bake_mesh_modifiers_and_instances()
    purge_orphan_datablocks()
    export_glb()


if __name__ == "__main__":
    main()
