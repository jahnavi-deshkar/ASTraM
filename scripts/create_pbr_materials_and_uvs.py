"""Create campus PBR materials, world-space triplanar shaders, and calibrated UVs.

Blender 5.2 command line (run and save in one process):
    blender --background --python scripts/create_pbr_materials_and_uvs.py --python-expr "import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'C:\\Users\\Administrator\\Desktop\\ASTraM\\mit_wpu_phase4.blend')"

The script can also be run from Blender's Text Editor. It creates missing
phase-1 collections when necessary, preserves the campus orientation parent and
world sky node, and updates material datablocks by name so existing assignments
receive the new shaders.
"""

from __future__ import annotations

import math
import re
import runpy
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_COLLECTIONS = (
    "01_TERRAIN_ROADS", "02_SOUTH_CAMPUS", "03_CENTRAL_CAMPUS",
    "04_MIDWEST_CAMPUS", "05_MIDEAST_CAMPUS", "06_NORTH_SPORTS_CAMPUS",
    "07_MODULAR_KIT",
)
UV_COLLECTIONS = REQUIRED_COLLECTIONS[1:]
IMAGE_RESOLUTION = 4096
TARGET_HERO_TEXELS_PER_METER = 1024.0
TARGET_ROOF_TEXELS_PER_METER = 512.0


def ensure_collections() -> None:
    if any(bpy.data.collections.get(name) is None for name in REQUIRED_COLLECTIONS):
        setup = Path(__file__).with_name("setup_3d_campus_scene.py")
        if not setup.is_file():
            raise FileNotFoundError(f"Required scene setup script not found: {setup}")
        print(f"Required collections missing; initializing scene with {setup}")
        runpy.run_path(str(setup), run_name="__main__")


def srgb_hex_to_linear(hex_color: str) -> tuple[float, float, float, float]:
    value = hex_color.lstrip("#")
    channels = [int(value[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return linear[0], linear[1], linear[2], 1.0


def socket(node, *names):
    for name in names:
        found = node.inputs.get(name)
        if found is not None:
            return found
    return None


def set_input(node, names, value) -> None:
    target = socket(node, *names)
    if target is not None:
        target.default_value = value


def make_material(name: str, hex_color: str, roughness: float, metallic: float = 0.0,
                  transmission: float = 0.0, ior: float = 1.45,
                  bump_strength: float = 0.0, noise_scale: float = 90.0,
                  triplanar: bool = False, brick: bool = False,
                  color_noise: bool = False) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    base = srgb_hex_to_linear(hex_color)
    mat.diffuse_color = base
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 100)
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (620, 100)
    principled.name = f"{name}_Principled"
    set_input(principled, ("Base Color",), base)
    set_input(principled, ("Roughness",), roughness)
    set_input(principled, ("Metallic",), metallic)
    set_input(principled, ("IOR",), ior)
    set_input(principled, ("Transmission Weight", "Transmission"), transmission)
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    if triplanar:
        build_triplanar_nodes(mat, principled, bump_strength, noise_scale)
    elif brick:
        brick_node = nodes.new("ShaderNodeTexBrick")
        brick_node.location = (-500, 160)
        brick_node.name = f"{name}_Mortar_Brick_Grid"
        brick_node.inputs["Color1"].default_value = srgb_hex_to_linear("#9F4937")
        brick_node.inputs["Color2"].default_value = srgb_hex_to_linear("#783427")
        brick_node.inputs["Mortar"].default_value = srgb_hex_to_linear("#B7A89A")
        brick_node.inputs["Scale"].default_value = 5.0
        brick_node.inputs["Mortar Size"].default_value = 0.025
        brick_node.inputs["Mortar Smooth"].default_value = 0.01
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-500, -120)
        noise.name = f"{name}_Clay_Porous_Noise"
        noise.inputs["Scale"].default_value = 38.0
        bump = nodes.new("ShaderNodeBump")
        bump.location = (350, -30)
        bump.inputs["Strength"].default_value = bump_strength
        bump.inputs["Distance"].default_value = 0.035
        # Preserve the requested terracotta color as the base and let the grid
        # contribute surface relief, with porous noise blended into its height.
        mix = nodes.new("ShaderNodeMixRGB")
        mix.location = (-60, 130)
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 0.32
        mix.inputs["Color1"].default_value = base
        links.new(brick_node.outputs["Color"], mix.inputs["Color2"])
        links.new(mix.outputs["Color"], principled.inputs["Base Color"])
        porous_grid = nodes.new("ShaderNodeMath")
        porous_grid.operation = "MULTIPLY"
        porous_grid.location = (-80, -100)
        porous_grid.name = f"{name}_Mortar_Porosity"
        links.new(brick_node.outputs["Fac"], porous_grid.inputs[0])
        links.new(noise.outputs["Fac"], porous_grid.inputs[1])
        links.new(porous_grid.outputs[0], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    elif bump_strength > 0.0 or color_noise:
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-700, 100)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-430, 100)
        noise.name = f"{name}_Procedural_Noise"
        noise.inputs["Scale"].default_value = noise_scale
        noise.inputs["Detail"].default_value = 3.0
        noise.inputs["Roughness"].default_value = 0.68
        links.new(texcoord.outputs["Object"], noise.inputs["Vector"])
        if color_noise:
            ramp = nodes.new("ShaderNodeValToRGB")
            ramp.location = (-100, 170)
            ramp.name = f"{name}_Color_Variation"
            ramp.color_ramp.elements[0].position = 0.22
            ramp.color_ramp.elements[0].color = srgb_hex_to_linear("#264D20")
            ramp.color_ramp.elements[1].position = 0.78
            ramp.color_ramp.elements[1].color = srgb_hex_to_linear("#35672E")
            links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
            links.new(ramp.outputs["Color"], principled.inputs["Base Color"])
        if bump_strength > 0.0:
            bump = nodes.new("ShaderNodeBump")
            bump.location = (350, -40)
            bump.name = f"{name}_Micro_Bump"
            bump.inputs["Strength"].default_value = bump_strength
            bump.inputs["Distance"].default_value = 0.018
            links.new(noise.outputs["Fac"], bump.inputs["Height"])
            links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    mat["shader_library_version"] = "ASTraM_Phase4_Blender_5_2"
    if triplanar:
        mat["projection"] = "WORLD_SPACE_TRIPLANAR_BOX_BLEND"
        mat["box_blend_factor"] = 0.20
    return mat


def build_triplanar_nodes(mat, principled, bump_strength, noise_scale):
    """Build weighted three-axis world-position noise projection.

    Procedural Noise Texture nodes do not expose an Image Texture-style Box
    Projection socket. This implements Box Blend procedurally: world position
    is sampled on XY, XZ, and YZ planes, then blended by the absolute world
    surface normal. A 0.20 softness exponent rounds the axis transition weights.
    """
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-1100, 100)
    geometry.name = "World_Position_And_Normal"
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-880, 180)
    mapping.name = "World_Scale_Mapping"
    mapping.inputs["Scale"].default_value = (1.0, 1.0, 1.0)
    links.new(geometry.outputs["Position"], mapping.inputs["Vector"])
    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.location = (-660, 260)
    links.new(mapping.outputs["Vector"], separate.inputs["Vector"])
    normal_sep = nodes.new("ShaderNodeSeparateXYZ")
    normal_sep.location = (-880, -340)
    links.new(geometry.outputs["Normal"], normal_sep.inputs["Vector"])

    # Axis projections: X-facing uses YZ; Y-facing uses XZ; Z-facing uses XY.
    projection_vectors = (("X", 1, 2), ("Y", 0, 2), ("Z", 0, 1))
    projected_noises = []
    weights = []
    for index, (axis, first, second) in enumerate(projection_vectors):
        combine = nodes.new("ShaderNodeCombineXYZ")
        combine.location = (-430, 340-index*180)
        combine.name = f"Box_Projection_{axis}_Vector"
        links.new(separate.outputs["XYZ"[first]], combine.inputs["X"])
        links.new(separate.outputs["XYZ"[second]], combine.inputs["Y"])
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-180, 340-index*180)
        noise.name = f"Box_Projection_{axis}_Noise"
        noise.inputs["Scale"].default_value = noise_scale
        noise.inputs["Detail"].default_value = 3.0
        noise.inputs["Roughness"].default_value = 0.68
        links.new(combine.outputs["Vector"], noise.inputs["Vector"])
        projected_noises.append(noise.outputs["Fac"])

        absolute = nodes.new("ShaderNodeMath")
        absolute.operation = "ABSOLUTE"
        absolute.location = (-650, -330-index*110)
        links.new(normal_sep.outputs["XYZ"[index]], absolute.inputs[0])
        power = nodes.new("ShaderNodeMath")
        power.operation = "POWER"
        power.location = (-450, -330-index*110)
        power.inputs[1].default_value = 0.20
        power.name = f"Box_Blend_0_20_{axis}"
        links.new(absolute.outputs[0], power.inputs[0])
        weights.append(power.outputs[0])

    weight_sum_1 = nodes.new("ShaderNodeMath")
    weight_sum_1.operation = "ADD"
    weight_sum_1.location = (-220, -440)
    links.new(weights[0], weight_sum_1.inputs[0]); links.new(weights[1], weight_sum_1.inputs[1])
    weight_sum_2 = nodes.new("ShaderNodeMath")
    weight_sum_2.operation = "ADD"
    weight_sum_2.location = (-30, -440)
    links.new(weight_sum_1.outputs[0], weight_sum_2.inputs[0]); links.new(weights[2], weight_sum_2.inputs[1])

    weighted = []
    for index in range(3):
        multiply = nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.location = (30, 340-index*160)
        links.new(projected_noises[index], multiply.inputs[0]); links.new(weights[index], multiply.inputs[1])
        normalize = nodes.new("ShaderNodeMath")
        normalize.operation = "DIVIDE"
        normalize.location = (220, 340-index*160)
        links.new(multiply.outputs[0], normalize.inputs[0]); links.new(weight_sum_2.outputs[0], normalize.inputs[1])
        weighted.append(normalize.outputs[0])
    mix_a = nodes.new("ShaderNodeMath"); mix_a.operation = "ADD"; mix_a.location = (410, 250)
    links.new(weighted[0], mix_a.inputs[0]); links.new(weighted[1], mix_a.inputs[1])
    mix_b = nodes.new("ShaderNodeMath"); mix_b.operation = "ADD"; mix_b.location = (500, 100)
    links.new(mix_a.outputs[0], mix_b.inputs[0]); links.new(weighted[2], mix_b.inputs[1])
    bump = nodes.new("ShaderNodeBump")
    bump.location = (520, -80)
    bump.name = f"{mat.name}_Triplanar_Bump"
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = 0.035
    links.new(mix_b.outputs[0], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    # The base procedural color also receives the continuous box-blended field
    # where a subtle variation is requested for terrain and road materials.
    if mat.name == "Mat_Turf_Green":
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (260, 500)
        ramp.name = "Turf_World_Color_Variation"
        ramp.color_ramp.elements[0].color = srgb_hex_to_linear("#264D20")
        ramp.color_ramp.elements[1].color = srgb_hex_to_linear("#35672E")
        links.new(mix_b.outputs[0], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], principled.inputs["Base Color"])


def create_library() -> dict[str, bpy.types.Material]:
    mats = {}
    mats["Mat_Concrete_Plaster"] = make_material(
        "Mat_Concrete_Plaster", "#E6E2D8", 0.80, bump_strength=0.15, noise_scale=95.0)
    mats["Mat_Brick_Red"] = make_material(
        "Mat_Brick_Red", "#8B3A2B", 0.85, bump_strength=0.35, brick=True)
    mats["Mat_Glass_Tinted"] = make_material(
        "Mat_Glass_Tinted", "#1C2833", 0.05, metallic=0.10, transmission=0.85, ior=1.52)
    mats["Mat_Asphalt"] = make_material(
        "Mat_Asphalt", "#262626", 0.90, bump_strength=0.25, noise_scale=72.0, triplanar=True)
    mats["Mat_Turf_Green"] = make_material(
        "Mat_Turf_Green", "#2D5A27", 0.80, bump_strength=0.10, noise_scale=12.0,
        triplanar=True, color_noise=True)
    mats["Mat_Curb_Concrete"] = make_material(
        "Mat_Curb_Concrete", "#8C8C8C", 0.75, bump_strength=0.08, noise_scale=80.0, triplanar=True)
    mats["Mat_Court_Blue"] = make_material("Mat_Court_Blue", "#1E40AF", 0.40)
    mats["Mat_Metal_Dark"] = make_material("Mat_Metal_Dark", "#334155", 0.30, metallic=0.90)
    # Existing phase materials remain supported and receive matching PBR nodes.
    mats["Mat_Roof_Concrete"] = make_material(
        "Mat_Roof_Concrete", "#8C8C8C", 0.78, bump_strength=0.08, noise_scale=80.0)
    mats["Mat_Glass_Clear"] = make_material(
        "Mat_Glass_Clear", "#A6D5E3", 0.08, metallic=0.03, transmission=0.82, ior=1.45)
    mats["Mat_Paint_Yellow"] = make_material("Mat_Paint_Yellow", "#F2AD09", 0.55)
    mats["Mat_Paint_White"] = make_material("Mat_Paint_White", "#E8E8E0", 0.55)
    return mats


def assign_terrain_materials(collections, mats):
    roads = collections["01_TERRAIN_ROADS"]
    for obj in roads.all_objects:
        if obj.type != "MESH":
            continue
        if obj.name == "Terrain_Main_Ground":
            material = mats["Mat_Turf_Green"]
        elif obj.name.startswith("RoadRibbon_"):
            material = mats["Mat_Asphalt"]
        elif obj.name.startswith("RoadCurb_"):
            material = mats["Mat_Curb_Concrete"]
        elif "Marking" in obj.name:
            material = mats["Mat_Paint_Yellow"] if "Spine_Marking" in obj.name else mats["Mat_Paint_White"]
        else:
            continue
        obj.data.materials.clear()
        obj.data.materials.append(material)


def smart_uv_and_density(collections):
    """Smart unwrap each mesh and scale UVs to the specified 4096 px/m targets."""
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_selected = list(bpy.context.selected_objects)
    processed = 0
    try:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for collection_name in UV_COLLECTIONS:
            collection = collections[collection_name]
            for obj in list(collection.all_objects):
                if obj.type != "MESH" or len(obj.data.polygons) == 0:
                    continue
                # The terrain and road infrastructure use world triplanar maps.
                if collection_name == "01_TERRAIN_ROADS":
                    continue
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.02)
                bpy.ops.object.mode_set(mode="OBJECT")
                if not obj.data.uv_layers:
                    continue
                target_px_m = choose_density_target(obj)
                target_uv_m = target_px_m / IMAGE_RESOLUTION
                current_uv_m = estimate_uv_density(obj)
                if current_uv_m > 1e-10:
                    multiplier = target_uv_m / current_uv_m
                    uv_data = obj.data.uv_layers.active.data
                    for loop_uv in uv_data:
                        loop_uv.uv *= multiplier
                obj["target_texel_density_px_per_meter"] = target_px_m
                obj["uv_reference_image_resolution"] = IMAGE_RESOLUTION
                obj["uv_projection"] = "SMART_PROJECT_CALIBRATED"
                processed += 1
    finally:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        for obj in previous_selected:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if previous_active and previous_active.name in bpy.data.objects:
            view_layer.objects.active = previous_active
    scene["phase4_uv_reference_resolution"] = IMAGE_RESOLUTION
    scene["phase4_uv_texel_density_hero_px_m"] = TARGET_HERO_TEXELS_PER_METER
    scene["phase4_uv_texel_density_roof_px_m"] = TARGET_ROOF_TEXELS_PER_METER
    return processed


def choose_density_target(obj):
    name = obj.name.lower()
    floor_match = re.search(r"_f(\d{2})_", name)
    upper_floor = bool(floor_match and int(floor_match.group(1)) >= 3)
    if upper_floor or any(token in name for token in ("roof", "parapet", "floor_band", "upper_facade", "canopy")):
        return TARGET_ROOF_TEXELS_PER_METER
    return TARGET_HERO_TEXELS_PER_METER


def estimate_uv_density(obj):
    uv_layer = obj.data.uv_layers.active
    if uv_layer is None:
        return 0.0
    mesh = obj.data
    ratios = []
    for poly in mesh.polygons:
        loops = list(poly.loop_indices)
        for index, loop_index in enumerate(loops):
            next_loop = loops[(index + 1) % len(loops)]
            loop_a, loop_b = mesh.loops[loop_index], mesh.loops[next_loop]
            uv_a = uv_layer.data[loop_index].uv
            uv_b = uv_layer.data[next_loop].uv
            vertex_a, vertex_b = mesh.vertices[loop_a.vertex_index], mesh.vertices[loop_b.vertex_index]
            world_length = (vertex_a.co - vertex_b.co).length
            uv_length = (uv_a - uv_b).length
            if world_length > 1e-8:
                ratios.append(uv_length / world_length)
    if not ratios:
        return 0.0
    ratios.sort()
    return ratios[len(ratios)//2]


def main():
    ensure_collections()
    collections = {name: bpy.data.collections[name] for name in REQUIRED_COLLECTIONS}
    mats = create_library()
    assign_terrain_materials(collections, mats)
    count = smart_uv_and_density(collections)
    world = bpy.context.scene.world
    sky_preserved = False
    if world and world.use_nodes:
        sky = next((node for node in world.node_tree.nodes if node.bl_idname == "ShaderNodeTexSky"), None)
        sky_preserved = bool(sky and sky.sky_type == "MULTIPLE_SCATTERING"
                             and abs(sky.air_density - 1.2) < 1e-6)
    print(f"Phase 4 complete: {len(mats)} PBR materials updated; {count} hard-surface meshes UV-unwrapped and calibrated.")
    print(f"Terrain and road materials use world-space triplanar box blending; sky preserved={sky_preserved}.")


if __name__ == "__main__":
    main()
