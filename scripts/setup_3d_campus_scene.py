"""Initialize a meter-scaled MIT-WPU campus blockout scene in Blender.

Run from the repository root with Blender 5.2:
    blender --background --python scripts/setup_3d_campus_scene.py

The campus coordinates below are schematic placeholders for spatial blockout,
not surveyed building footprints. All campus objects share a -18 degree parent
rotation so the local +Y axis can be treated as true north while the campus
spine follows the approximate real-world alignment.
"""

from __future__ import annotations

import math

import bpy


COLLECTION_NAMES = (
    "01_TERRAIN_ROADS",
    "02_SOUTH_CAMPUS",
    "03_CENTRAL_CAMPUS",
    "04_MIDWEST_CAMPUS",
    "05_MIDEAST_CAMPUS",
    "06_NORTH_SPORTS_CAMPUS",
    "07_MODULAR_KIT",
    "08_FOLIAGE_LANDSCAPE",
    "09_PROPS_STREET_FURNITURE",
    "10_LIGHTING_ENVIRONMENT",
)

# Name, collection, local X/Y center, dimensions X/Y/Z (meters).
# The layout follows the campus map approximately; only the supplied sizes are
# treated as authoritative for this blockout.
PROXIES = (
    ("Saraswati_Ganga_Block", "02_SOUTH_CAMPUS", -30.0, -100.0, 85.0, 35.0, 20.0),
    ("Mankikar_Office_Block", "02_SOUTH_CAMPUS", 40.0, -100.0, 40.0, 25.0, 12.5),
    ("Main_Gate_Structure", "02_SOUTH_CAMPUS", 0.0, -160.0, 18.0, 4.0, 6.5),
    ("Vishwakarma_Block", "02_SOUTH_CAMPUS", -42.0, -178.0, 45.0, 22.0, 16.0),
    ("Dnyaneshwar_Block", "03_CENTRAL_CAMPUS", -45.0, 0.0, 22.0, 65.0, 20.0),
    ("Vashistha_Block", "03_CENTRAL_CAMPUS", 45.0, 0.0, 24.0, 70.0, 20.0),
    ("Jamadagni_Block", "03_CENTRAL_CAMPUS", 0.0, 45.0, 55.0, 16.0, 12.0),
    ("Vivekanand_Rotunda_Block", "04_MIDWEST_CAMPUS", -80.0, 50.0, 40.0, 40.0, 16.0),
    ("Dhruv_Pharmacy_Block", "04_MIDWEST_CAMPUS", -90.0, 110.0, 60.0, 20.0, 16.0),
    ("Aryabhata_Block", "05_MIDEAST_CAMPUS", 45.0, 60.0, 65.0, 45.0, 16.0),
    ("Chanakya_Admission_Center", "05_MIDEAST_CAMPUS", 35.0, 110.0, 50.0, 22.0, 16.0),
    ("Sports_Complex_Main", "06_NORTH_SPORTS_CAMPUS", 50.0, 170.0, 45.0, 25.0, 15.0),
    ("Playground_Surface", "06_NORTH_SPORTS_CAMPUS", 50.0, 220.0, 110.0, 70.0, 0.1),
    ("Basketball_Court", "06_NORTH_SPORTS_CAMPUS", 10.0, 270.0, 28.0, 15.0, 0.1),
)


def clear_scene(scene: bpy.types.Scene) -> None:
    """Remove scene objects and child collections while retaining master collection."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(scene.collection.children):
        scene.collection.children.unlink(collection)
        if collection.users == 0:
            bpy.data.collections.remove(collection)


def create_collections(scene: bpy.types.Scene) -> dict[str, bpy.types.Collection]:
    collections = {}
    for name in COLLECTION_NAMES:
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        collections[name] = collection
    return collections


def create_proxy(
    name: str,
    collection: bpy.types.Collection,
    location_xy: tuple[float, float],
    dimensions: tuple[float, float, float],
    parent: bpy.types.Object,
) -> bpy.types.Object:
    """Create a cube mesh with exact applied dimensions, centered on its footprint."""
    mesh = bpy.data.meshes.new(f"Bld_Proxy_{name}_Mesh")
    x, y, z = (dimension / 2.0 for dimension in dimensions)
    vertices = (
        (-x, -y, 0.0), (x, -y, 0.0), (x, y, 0.0), (-x, y, 0.0),
        (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z),
    )
    faces = (
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    )
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(f"Bld_Proxy_{name}", mesh)
    collection.objects.link(obj)
    obj.location = (location_xy[0], location_xy[1], 0.0)
    obj.parent = parent
    obj["dimensions_m"] = list(dimensions)
    obj["geometry_status"] = "schematic_blockout_proxy"
    return obj


def create_world(scene: bpy.types.Scene) -> None:
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("MIT_WPU_World")
        scene.world = world
    world.name = "MIT_WPU_World"
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    sky = nodes.new("ShaderNodeTexSky")
    sky.name = "MIT_WPU_Multiple_Scattering"
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = math.radians(45.0)
    sky.sun_rotation = math.radians(210.0)
    sky.air_density = 1.2
    sky.ozone_density = 2.0
    background = nodes.new("ShaderNodeBackground")
    background.name = "MIT_WPU_Daylight_Background"
    output = nodes.new("ShaderNodeOutputWorld")
    output.name = "MIT_WPU_World_Output"
    links.new(sky.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])


def setup_scene() -> None:
    scene = bpy.context.scene
    clear_scene(scene)

    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.clip_start = 0.1
                        space.clip_end = 2000.0

    collections = create_collections(scene)

    # This parent is the single orientation control for all site geometry.
    # Its -18 degree Z rotation represents the campus spine's east-of-north angle.
    root_mesh = bpy.data.meshes.new("Campus_Orientation_Root_Mesh")
    campus_root = bpy.data.objects.new("Campus_Orientation_Root", root_mesh)
    collections["01_TERRAIN_ROADS"].objects.link(campus_root)
    campus_root.rotation_euler[2] = math.radians(-18.0)
    campus_root["orientation_degrees_from_true_north"] = -18.0

    terrain_mesh = bpy.data.meshes.new("Terrain_Main_Ground_Mesh")
    half = 250.0
    terrain_mesh.from_pydata(
        [(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)],
        [], [(0, 1, 2, 3)],
    )
    terrain_mesh.update()
    terrain = bpy.data.objects.new("Terrain_Main_Ground", terrain_mesh)
    collections["01_TERRAIN_ROADS"].objects.link(terrain)
    terrain.parent = campus_root
    terrain["dimensions_m"] = [500.0, 500.0, 0.0]

    for name, collection_name, x, y, width, depth, height in PROXIES:
        create_proxy(
            name,
            collections[collection_name],
            (x, y),
            (width, depth, height),
            campus_root,
        )

    create_world(scene)
    scene["campus_model_units"] = "meters"
    scene["campus_orientation_note"] = "Campus local coordinates rotated -18 degrees around Z."
    scene["campus_geometry_status"] = "schematic_blockout"
    print(
        "MIT-WPU scene initialized: metric units, 10 collections, "
        f"{len(PROXIES)} exact-size proxy meshes, 500 m terrain, and multiple-scattering daylight."
    )


if __name__ == "__main__":
    setup_scene()
