"""Procedurally model MIT-WPU Sector A and B buildings in Blender 5.2.

Run from the repository root:
    blender --background --python scripts/model_sector_a_b_buildings.py

The script expects the scene and sector collections from
scripts/setup_3d_campus_scene.py. Coordinates are schematic local site positions;
the existing Campus_Orientation_Root continues to provide the -18 degree site
alignment. The generated low-poly architectural geometry is editable and
repeatable: rerunning this script replaces its previous generated objects.
"""

from __future__ import annotations

import math
import runpy
from pathlib import Path

import bpy


GENERATED_TAG = "astram_sector_ab_generated"
MATERIALS = {
    "Mat_Concrete_Plaster": (0.72, 0.69, 0.61, 1.0),
    "Mat_Brick_Red": (0.38, 0.10, 0.065, 1.0),
    "Mat_Glass_Tinted": (0.055, 0.12, 0.17, 1.0),
    "Mat_Roof_Concrete": (0.48, 0.47, 0.43, 1.0),
    "Mat_Metal_Dark": (0.075, 0.085, 0.09, 1.0),
}


def get_materials() -> dict[str, bpy.types.Material]:
    result = {}
    for name, color in MATERIALS.items():
        material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        material.diffuse_color = color
        material.use_nodes = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled:
            principled.inputs["Base Color"].default_value = color
            principled.inputs["Roughness"].default_value = 0.28 if "Glass" in name else 0.82
            if "Glass" in name:
                principled.inputs["Metallic"].default_value = 0.12
        result[name] = material
    return result


def get_context() -> tuple[dict[str, bpy.types.Collection], bpy.types.Object | None]:
    required = ("02_SOUTH_CAMPUS", "03_CENTRAL_CAMPUS")
    collections = {}
    for name in required:
        collection = bpy.data.collections.get(name)
        if collection is None:
            raise RuntimeError(
                f"Required collection {name!r} is missing. Run "
                "scripts/setup_3d_campus_scene.py first."
            )
        collections[name] = collection
    root = bpy.data.objects.get("Campus_Orientation_Root")
    return collections, root


def remove_previous_geometry(collections: dict[str, bpy.types.Collection]) -> None:
    for obj in list(bpy.data.objects):
        if obj.get(GENERATED_TAG):
            bpy.data.objects.remove(obj, do_unlink=True)
    proxy_names = {
        "Bld_Proxy_Saraswati_Ganga_Block",
        "Bld_Proxy_Mankikar_Office_Block",
        "Bld_Proxy_Main_Gate_Structure",
        "Bld_Proxy_Vishwakarma_Block",
        "Bld_Proxy_Dnyaneshwar_Block",
        "Bld_Proxy_Vashistha_Block",
        "Bld_Proxy_Jamadagni_Block",
    }
    for name in proxy_names:
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)


def finish_object(
    name: str,
    mesh: bpy.types.Mesh,
    collection: bpy.types.Collection,
    material: bpy.types.Material,
    location: tuple[float, float, float],
    parent: bpy.types.Object | None,
) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    mesh.materials.append(material)
    obj.location = location
    obj.parent = parent
    obj[GENERATED_TAG] = True
    # Components are built directly in mesh coordinates, so object transforms
    # remain identity and dimensions are represented by actual mesh vertices.
    obj.scale = (1.0, 1.0, 1.0)
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    return obj


def box(
    name: str,
    collection: bpy.types.Collection,
    materials: dict[str, bpy.types.Material],
    parent: bpy.types.Object | None,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    material_key: str = "Mat_Concrete_Plaster",
) -> bpy.types.Object:
    """Create a closed six-quad box mesh with dimensions baked into vertices."""
    hx, hy, hz = (v * 0.5 for v in size)
    vertices = [
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
        (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return finish_object(name, mesh, collection, materials[material_key], center, parent)


def polygon_prism(
    name: str,
    collection: bpy.types.Collection,
    materials: dict[str, bpy.types.Material],
    parent: bpy.types.Object | None,
    center: tuple[float, float, float],
    radius: float,
    height: float,
    sides: int = 8,
    material_key: str = "Mat_Concrete_Plaster",
) -> bpy.types.Object:
    """Create an extruded polygon with quad sides and ngon caps."""
    verts = []
    for z in (-height / 2.0, height / 2.0):
        verts.extend(
            (radius * math.cos(2 * math.pi * i / sides),
             radius * math.sin(2 * math.pi * i / sides), z)
            for i in range(sides)
        )
    faces = [tuple(reversed(range(sides))), tuple(range(sides, 2 * sides))]
    faces.extend((i, (i + 1) % sides, (i + 1) % sides + sides, i + sides) for i in range(sides))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return finish_object(name, mesh, collection, materials[material_key], center, parent)


def facade_grid(
    prefix: str,
    collection: bpy.types.Collection,
    materials: dict[str, bpy.types.Material],
    parent: bpy.types.Object | None,
    center: tuple[float, float, float],
    width: float,
    depth: float,
    height: float,
    floors: int,
    window_spacing: float = 5.0,
    omit_front: tuple[float, float] | None = None,
) -> None:
    """Add repeated dark inset panels with concrete reveals and horizontal bands."""
    floor_h = height / floors
    window_h = min(1.65, floor_h * 0.47)
    window_w = min(2.1, window_spacing * 0.60)
    cx, cy, _ = center
    for floor in range(floors):
        z = (floor + 0.58) * floor_h
        # Long front/back elevations. Panels are set behind the facade plane by
        # 0.20 m and held in their own meshes for a clean, inspectable kit.
        for side, y in (("South", cy - depth / 2 + 0.20), ("North", cy + depth / 2 - 0.20)):
            count = max(1, int(width // window_spacing))
            for index in range(count):
                x = cx - (count - 1) * window_spacing / 2 + index * window_spacing
                if side == "South" and omit_front and omit_front[0] <= x <= omit_front[1]:
                    continue
                box(f"{prefix}_{side}_F{floor + 1:02d}_Window_{index + 1:02d}", collection,
                    materials, parent, (x, y, z), (window_w, 0.12, window_h), "Mat_Glass_Tinted")
        # End elevations.
        count_d = max(1, int(depth // window_spacing))
        for side, x in (("West", cx - width / 2 + 0.20), ("East", cx + width / 2 - 0.20)):
            for index in range(count_d):
                y = cy - (count_d - 1) * window_spacing / 2 + index * window_spacing
                box(f"{prefix}_{side}_F{floor + 1:02d}_Window_{index + 1:02d}", collection,
                    materials, parent, (x, y, z), (0.12, window_w, window_h), "Mat_Glass_Tinted")
    # Explicit floor ledges give the massing readable floor-to-floor courses.
    for floor in range(1, floors):
        z = floor * floor_h
        box(f"{prefix}_Floor_Band_{floor:02d}", collection, materials, parent,
            (cx, cy, z), (width + 0.18, depth + 0.18, 0.16), "Mat_Roof_Concrete")


def parapet(prefix, collection, materials, parent, x, y, width, depth, roof_z, thickness=0.22, h=1.2):
    box(f"{prefix}_Parapet_South", collection, materials, parent,
        (x, y - depth / 2, roof_z + h / 2), (width, thickness, h), "Mat_Roof_Concrete")
    box(f"{prefix}_Parapet_North", collection, materials, parent,
        (x, y + depth / 2, roof_z + h / 2), (width, thickness, h), "Mat_Roof_Concrete")
    box(f"{prefix}_Parapet_West", collection, materials, parent,
        (x - width / 2, y, roof_z + h / 2), (thickness, depth, h), "Mat_Roof_Concrete")
    box(f"{prefix}_Parapet_East", collection, materials, parent,
        (x + width / 2, y, roof_z + h / 2), (thickness, depth, h), "Mat_Roof_Concrete")


def academic_block(prefix, collection, materials, parent, x, y, width, depth, height, floors):
    box(f"{prefix}_Massing", collection, materials, parent,
        (x, y, height / 2), (width, depth, height))
    facade_grid(prefix, collection, materials, parent, (x, y, 0), width, depth, height, floors)
    parapet(prefix, collection, materials, parent, x, y, width, depth, height)


def model_gate(collection, materials, parent):
    x, y = 0.0, -160.0
    # Seven piers separate four vehicle openings and two narrow pedestrian
    # cutouts at the outer ends of the 18 m gate structure.
    pier_w, span = 0.6, 18.0
    opening_widths = (1.1, 2.9, 2.9, 2.9, 2.9, 1.1)
    z_top, beam_h = 6.5, 1.2
    cursor = x - span / 2
    opening_centers = []
    for index in range(7):
        px = cursor + pier_w / 2
        box(f"Main_Gate_Pier_{index + 1}", collection, materials, parent,
            (px, y, (z_top - beam_h) / 2), (pier_w, 4.0, z_top - beam_h), "Mat_Brick_Red")
        cursor += pier_w
        if index < len(opening_widths):
            gap = opening_widths[index]
            opening_centers.append((cursor + gap / 2, gap))
            cursor += gap
    box("Main_Gate_Overhead_Sign_Slab", collection, materials, parent,
        (x, y, z_top - beam_h / 2), (span, 4.0, beam_h), "Mat_Roof_Concrete")
    # Inset dark panels indicate four lane gates; posts remain separate for edits.
    for i, (lane_x, opening_w) in enumerate(opening_centers[1:5]):
        box(f"Main_Gate_Vehicle_Boom_{i + 1}", collection, materials, parent,
            (lane_x, y - 1.45, 1.05), (opening_w * 0.86, 0.10, 0.12), "Mat_Metal_Dark")
    for side, (ped_x, ped_w) in zip(("West", "East"), (opening_centers[0], opening_centers[-1])):
        box(f"Main_Gate_Pedestrian_Cutout_{side}_Marker", collection, materials, parent,
            (ped_x, y - 1.45, 2.1), (ped_w * 0.7, 0.08, 0.12), "Mat_Metal_Dark")
    for side, px in (("West", -span / 2 + 1.5), ("East", span / 2 - 1.5)):
        box(f"Main_Gate_Security_Cabin_{side}", collection, materials, parent,
            (x + px, y, 1.55), (2.5, 3.5, 3.1), "Mat_Concrete_Plaster")
        box(f"Main_Gate_Cabin_Glass_{side}", collection, materials, parent,
            (x + px, y - 1.78, 1.8), (1.7, 0.08, 1.2), "Mat_Glass_Tinted")
    # Sign fascia face.
    box("Main_Gate_Sign_Fascia", collection, materials, parent,
        (x, y - 2.04, 5.82), (8.0, 0.12, 0.72), "Mat_Metal_Dark")


def model_saraswati(collection, materials, parent):
    # H-plan: two 25 m end wings joined by 35 m transverse bars at front/back,
    # leaving an open central court in the middle of the footprint.
    prefix = "Saraswati_Ganga"
    x, y, w, d, h = -30.0, -100.0, 85.0, 35.0, 20.0
    wing_w = 25.0
    wing_xs = (x - (w - wing_w) / 2, x + (w - wing_w) / 2)
    for suffix, wx in zip(("West_Wing", "East_Wing"), wing_xs):
        academic_block(f"{prefix}_{suffix}", collection, materials, parent,
                       wx, y, wing_w, d, h, 5)
    bar_depth = 7.0
    for suffix, by in (("North_Link", y + d / 2 - bar_depth / 2),
                       ("South_Link", y - d / 2 + bar_depth / 2)):
        academic_block(f"{prefix}_{suffix}", collection, materials, parent,
                       x, by, w - 2 * wing_w + 6.0, bar_depth, h, 5)
    # Courtyard paving at grade, recessed relative to the surrounding wings.
    box("Saraswati_Ganga_Courtyard_Paving", collection, materials, parent,
        (x, y, 0.015), (w - 2 * wing_w - 6.0, d - 2 * bar_depth, 0.03), "Mat_Roof_Concrete")


def model_vishwakarma(collection, materials, parent):
    prefix = "Vishwakarma"
    x, y, w, d, h = -42.0, -178.0, 45.0, 22.0, 16.0
    academic_block(prefix, collection, materials, parent, x, y, w, d, h, 4)
    # Slightly recessed end stair towers with narrow vertical glazing.
    for side, tx in (("West", x - w / 2 + 3.2), ("East", x + w / 2 - 3.2)):
        box(f"{prefix}_{side}_Stairwell_Tower", collection, materials, parent,
            (tx, y, h / 2), (5.5, d - 1.2, h + 0.2), "Mat_Brick_Red")
        for floor in range(4):
            box(f"{prefix}_{side}_Stairwell_Slit_{floor + 1}", collection, materials, parent,
                (tx, y - d / 2 + 0.58, floor * 3.8 + 1.9), (0.65, 0.12, 1.9), "Mat_Glass_Tinted")
    # North-facing entrance and covered portico canopy.
    box(f"{prefix}_North_Entrance_Glazing", collection, materials, parent,
        (x, y + d / 2 - 0.12, 1.35), (3.2, 0.16, 2.7), "Mat_Glass_Tinted")
    box(f"{prefix}_North_Portico_Canopy", collection, materials, parent,
        (x, y + d / 2 + 2.0, 3.5), (10.0, 4.0, 0.45), "Mat_Roof_Concrete")
    for px in (x - 4.3, x + 4.3):
        box(f"{prefix}_Portico_Pillar_{px:.1f}", collection, materials, parent,
            (px, y + d / 2 + 3.5, 1.75), (0.45, 0.45, 3.5), "Mat_Metal_Dark")


def model_mankikar(collection, materials, parent):
    prefix = "Mankikar_Office"
    x, y, w, d, h = 40.0, -100.0, 40.0, 25.0, 12.5
    academic_block(prefix, collection, materials, parent, x, y, w, d, h, 3)
    # West façade glass lobby projects 2.5 m beyond the wall.
    box(f"{prefix}_West_Glass_Lobby", collection, materials, parent,
        (x - w / 2 - 1.25, y, 2.0), (2.5, 8.0, 4.0), "Mat_Glass_Tinted")
    box(f"{prefix}_West_Portico_Canopy", collection, materials, parent,
        (x - w / 2 - 2.5, y, 4.25), (4.5, 11.0, 0.45), "Mat_Roof_Concrete")
    for py in (y - 4.5, y + 4.5):
        box(f"{prefix}_Portico_Pillar_{py:.1f}", collection, materials, parent,
            (x - w / 2 - 4.2, py, 2.0), (0.4, 0.4, 4.0), "Mat_Metal_Dark")


def model_service_dome(collection, materials, parent):
    cx, cy, radius = -74.0, -52.0, 9.0
    # Octagonal pavilion ring and faceted low dome segments, all low-poly.
    polygon_prism("Agastya_Service_Center_Base", collection, materials, parent,
                  (cx, cy, 1.15), radius, 2.3, 8)
    polygon_prism("Agastya_Service_Center_Roof_Ring", collection, materials, parent,
                  (cx, cy, 2.55), radius + 0.35, 0.35, 8, "Mat_Roof_Concrete")
    # Eight quad roof facets rise from the eave ring to a smaller octagonal crown.
    verts = []
    crown_radius = 2.0
    for z, ring_radius in ((2.7, radius), (5.2, crown_radius)):
        verts.extend(
            (ring_radius * math.cos(2 * math.pi * i / 8),
             ring_radius * math.sin(2 * math.pi * i / 8), z)
            for i in range(8)
        )
    faces = [(i, (i + 1) % 8, (i + 1) % 8 + 8, i + 8) for i in range(8)]
    faces.append(tuple(range(8, 16)))
    mesh = bpy.data.meshes.new("Agastya_Service_Center_Octagonal_Roof_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    finish_object("Agastya_Service_Center_Octagonal_Roof", mesh, collection,
                  materials["Mat_Roof_Concrete"], (cx, cy, 0.0), parent)
    for i in range(8):
        a = 2 * math.pi * i / 8
        box(f"Agastya_Service_Center_Glass_{i + 1}", collection, materials, parent,
            (cx + 8.83 * math.cos(a), cy + 8.83 * math.sin(a), 1.55),
            (0.12, 2.0, 1.25), "Mat_Glass_Tinted")


def model_dnyaneshwar(collection, materials, parent):
    prefix = "Dnyaneshwar"
    x, y, w, d, h = -45.0, 0.0, 65.0, 22.0, 20.0
    academic_block(prefix, collection, materials, parent, x, y, w, d, h, 5)
    # Ground-floor colonnade along the lawn-facing east elevation, 4 m spacing.
    for index in range(17):
        px = x - w / 2 + 2.0 + index * 3.8
        box(f"{prefix}_Colonnade_Pillar_{index + 1:02d}", collection, materials, parent,
            (px, y + d / 2 + 0.55, 1.9), (0.6, 0.6, 3.8), "Mat_Roof_Concrete")
    # Octagonal rotunda attached at the west end wing.
    rx, ry = x - w / 2 - 4.0, y
    polygon_prism(f"{prefix}_West_Rotunda_Pavilion", collection, materials, parent,
                  (rx, ry, 2.0), 8.0, 4.0, 8, "Mat_Brick_Red")
    polygon_prism(f"{prefix}_West_Rotunda_Roof", collection, materials, parent,
                  (rx, ry, 4.3), 8.6, 0.6, 8, "Mat_Roof_Concrete")
    for i in range(8):
        a = 2 * math.pi * i / 8
        box(f"{prefix}_Rotunda_Glass_{i + 1}", collection, materials, parent,
            (rx + 7.55 * math.cos(a), ry + 7.55 * math.sin(a), 2.05),
            (0.12, 1.65, 2.1), "Mat_Glass_Tinted")


def model_vashistha(collection, materials, parent):
    prefix = "Vashistha"
    x, y, w, d, h = 45.0, 0.0, 70.0, 24.0, 20.0
    academic_block(prefix, collection, materials, parent, x, y, w, d, h, 5)
    # Main double-door entrance faces west toward the central lawn axis.
    box(f"{prefix}_West_Double_Door_Recess", collection, materials, parent,
        (x - w / 2 - 0.04, y, 1.25), (0.16, 3.8, 2.5), "Mat_Glass_Tinted")
    for py in (y - 2.4, y + 2.4):
        box(f"{prefix}_West_Entrance_Pilaster_{py:.1f}", collection, materials, parent,
            (x - w / 2 - 0.16, py, 1.55), (0.42, 0.42, 3.1), "Mat_Roof_Concrete")
    box(f"{prefix}_West_Entrance_Canopy", collection, materials, parent,
        (x - w / 2 - 1.4, y, 3.15), (3.0, 6.5, 0.42), "Mat_Roof_Concrete")


def model_jamadagni(collection, materials, parent):
    prefix = "Jamadagni_Enclave_Cafeteria_1"
    x, y, w, d, h = 0.0, 45.0, 55.0, 16.0, 12.0
    academic_block(prefix, collection, materials, parent, x, y, w, d, h, 3)
    # South-facing ground-level cafeteria glazing and an open canopy zone.
    box(f"{prefix}_South_Cafeteria_Glazing", collection, materials, parent,
        (x, y - d / 2 - 0.05, 1.55), (18.0, 0.12, 3.1), "Mat_Glass_Tinted")
    canopy_y = y - d / 2 - 3.0
    box(f"{prefix}_Outdoor_Cafeteria_Canopy", collection, materials, parent,
        (x, canopy_y, 4.0), (25.0, 7.0, 0.4), "Mat_Roof_Concrete")
    for index in range(6):
        px = x - 10.0 + index * 4.0
        box(f"{prefix}_Canopy_Pillar_{index + 1:02d}", collection, materials, parent,
            (px, canopy_y - 2.7, 2.0), (0.35, 0.35, 4.0), "Mat_Metal_Dark")


def main() -> None:
    # A background Blender invocation starts a fresh scene for each command.
    # Bootstrap the phase-1 scene when this script is run by itself.
    required = ("02_SOUTH_CAMPUS", "03_CENTRAL_CAMPUS")
    if any(bpy.data.collections.get(name) is None for name in required):
        setup_script = Path(__file__).resolve().with_name("setup_3d_campus_scene.py")
        if not setup_script.is_file():
            raise FileNotFoundError(
                f"Cannot find scene setup script required for bootstrap: {setup_script}"
            )
        print(f"Sector collections missing; running scene setup: {setup_script}")
        runpy.run_path(str(setup_script), run_name="__main__")

    collections, parent = get_context()
    remove_previous_geometry(collections)
    materials = get_materials()
    south, central = collections["02_SOUTH_CAMPUS"], collections["03_CENTRAL_CAMPUS"]

    model_gate(south, materials, parent)
    model_saraswati(south, materials, parent)
    model_vishwakarma(south, materials, parent)
    model_mankikar(south, materials, parent)
    model_service_dome(south, materials, parent)

    model_dnyaneshwar(central, materials, parent)
    model_vashistha(central, materials, parent)
    model_jamadagni(central, materials, parent)

    # The setup scene's multiple-scattering sky is preserved; this script only
    # creates architectural geometry and its five named material placeholders.
    world = bpy.context.scene.world
    if world and world.use_nodes:
        sky = next((node for node in world.node_tree.nodes if node.bl_idname == "ShaderNodeTexSky"), None)
        if sky and sky.sky_type == "MULTIPLE_SCATTERING" and abs(sky.air_density - 1.2) < 1e-6:
            print("Preserved Blender 5.2 multiple-scattering sky and air_density=1.2.")
    print("Sector A and B architectural geometry generated successfully.")


if __name__ == "__main__":
    main()
