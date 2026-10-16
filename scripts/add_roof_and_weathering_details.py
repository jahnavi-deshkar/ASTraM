"""Add roof utilities, weathering shader layers, signs, and campus micro-details.

Blender 5.2 usage (start from the saved Phase 5 scene and save Phase 7):
    blender --background mit_wpu_phase5.blend --python scripts/add_roof_and_weathering_details.py --python-expr "import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'C:\\Users\\Administrator\\Desktop\\ASTraM\\mit_wpu_phase7.blend')"

Building positions match the schematic sector scripts. All generated site props
are parented to Campus_Orientation_Root when present. The script updates the
existing plaster and brick material node trees without replacing the world sky.
"""

from __future__ import annotations

import math
import runpy
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
TAG = "astram_phase7_generated"
PROP_COLLECTION = "09_PROPS_STREET_FURNITURE"
SECTOR_COLLECTIONS = (
    "02_SOUTH_CAMPUS", "03_CENTRAL_CAMPUS", "04_MIDWEST_CAMPUS",
    "05_MIDEAST_CAMPUS", "06_NORTH_SPORTS_CAMPUS",
)


def ensure_scene():
    needed = (PROP_COLLECTION, *SECTOR_COLLECTIONS)
    if any(bpy.data.collections.get(name) is None for name in needed):
        setup = Path(__file__).with_name("setup_3d_campus_scene.py")
        if not setup.is_file():
            raise FileNotFoundError(f"Required scene setup script not found: {setup}")
        print(f"Phase collections missing; bootstrapping base scene with {setup}")
        runpy.run_path(str(setup), run_name="__main__")
    return bpy.data.collections[PROP_COLLECTION]


def srgb(hex_color):
    value = hex_color.lstrip("#")
    rgb = [int(value[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb) + (1.0,)


def material(name, color, roughness=0.75, metallic=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    return mat


def materials():
    return {
        "metal": material("Mat_Metal_Galvanized", srgb("#84909A"), 0.36, 0.82),
        "plastic": material("Mat_Plastic_Blue", srgb("#1261A0"), 0.42, 0.0),
        "solar": material("Mat_Solar_Cell", srgb("#102A50"), 0.22, 0.28),
        "sign": material("Mat_Sign_Graphic", srgb("#F1EBD5"), 0.65, 0.0),
        "concrete": bpy.data.materials.get("Mat_Concrete_Plaster") or material(
            "Mat_Concrete_Plaster", srgb("#E6E2D8"), 0.80),
        "roof": bpy.data.materials.get("Mat_Roof_Concrete") or material(
            "Mat_Roof_Concrete", srgb("#8C8C8C"), 0.78),
        "dark": bpy.data.materials.get("Mat_Metal_Dark") or material(
            "Mat_Metal_Dark", srgb("#334155"), 0.30, 0.90),
        "glass": bpy.data.materials.get("Mat_Glass_Tinted") or material(
            "Mat_Glass_Tinted", srgb("#1C2833"), 0.05, 0.10),
    }


def create_mesh_object(name, verts, faces, mat, collection, parent=None, location=(0, 0, 0), tag=True):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    obj.parent = parent
    obj.scale = (1.0, 1.0, 1.0)
    if tag:
        obj[TAG] = True
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    return obj


def box(name, collection, mat, center, dims, parent=None, rotation=None):
    hx, hy, hz = (v / 2.0 for v in dims)
    verts = [(-hx,-hy,-hz),(hx,-hy,-hz),(hx,hy,-hz),(-hx,hy,-hz),
             (-hx,-hy,hz),(hx,-hy,hz),(hx,hy,hz),(-hx,hy,hz)]
    faces = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    obj = create_mesh_object(name, verts, faces, mat, collection, parent, center)
    if rotation:
        obj.rotation_euler = rotation
    return obj


def cylinder(name, collection, mat, center, radius, depth, parent=None, vertices=12, axis="Z"):
    ring0, ring1 = [], []
    for z in (-depth/2, depth/2):
        for i in range(vertices):
            a=2*math.pi*i/vertices
            if axis == "Z":
                ring0.append((radius*math.cos(a),radius*math.sin(a),z))
            elif axis == "Y":
                ring0.append((radius*math.cos(a),z,radius*math.sin(a)))
            else:
                ring0.append((z,radius*math.cos(a),radius*math.sin(a)))
    faces=[tuple(reversed(range(vertices))),tuple(range(vertices,2*vertices))]
    faces.extend((i,(i+1)%vertices,(i+1)%vertices+vertices,i+vertices) for i in range(vertices))
    return create_mesh_object(name,ring0,faces,mat,collection,parent,center)


def add_weathering(material_name):
    mat=bpy.data.materials.get(material_name)
    if mat is None or mat.node_tree is None:
        return False
    nodes,links=mat.node_tree.nodes,mat.node_tree.links
    if nodes.get("ASTraM_Weathering_Mix"):
        return True
    principled=next((n for n in nodes if n.bl_idname=="ShaderNodeBsdfPrincipled"),None)
    if principled is None:
        return False
    base_socket=principled.inputs.get("Base Color")
    previous=next((link.from_socket for link in links if link.to_socket==base_socket),None)
    if previous:
        links.remove(next(link for link in links if link.to_socket==base_socket))
    else:
        previous=None
    geometry=nodes.new("ShaderNodeNewGeometry");geometry.name="ASTraM_Weathering_World_Position"
    geometry.location=(-1000,-420)
    mapping=nodes.new("ShaderNodeMapping");mapping.name="ASTraM_Weathering_Vertical_Stretch"
    mapping.location=(-800,-420)
    mapping.inputs["Scale"].default_value=(8.0,8.0,1.1)
    links.new(geometry.outputs["Position"],mapping.inputs["Vector"])
    noise=nodes.new("ShaderNodeTexNoise");noise.name="ASTraM_Weathering_Runoff_Noise"
    noise.location=(-560,-400)
    noise.inputs["Scale"].default_value=2.8
    noise.inputs["Detail"].default_value=4.0
    noise.inputs["Roughness"].default_value=0.72
    links.new(mapping.outputs["Vector"],noise.inputs["Vector"])
    ao=nodes.new("ShaderNodeAmbientOcclusion");ao.name="ASTraM_Weathering_AO"
    ao.location=(-560,-650)
    ao.inputs["Distance"].default_value=1.2
    invert=nodes.new("ShaderNodeMath");invert.operation="SUBTRACT"
    invert.name="ASTraM_Weathering_Occlusion_Invert";invert.location=(-340,-620)
    invert.inputs[0].default_value=1.0
    links.new(ao.outputs["AO"],invert.inputs[1])
    mask=nodes.new("ShaderNodeMath");mask.operation="MULTIPLY"
    mask.name="ASTraM_Weathering_Grime_Mask";mask.location=(-130,-460)
    links.new(noise.outputs["Fac"],mask.inputs[0]);links.new(invert.outputs[0],mask.inputs[1])
    ramp=nodes.new("ShaderNodeValToRGB");ramp.name="ASTraM_Weathering_Streak_Range"
    ramp.location=(70,-440)
    ramp.color_ramp.elements[0].position=0.30
    ramp.color_ramp.elements[0].color=(0,0,0,1)
    ramp.color_ramp.elements[1].position=0.78
    ramp.color_ramp.elements[1].color=(0.42,0.36,0.30,1)
    links.new(mask.outputs[0],ramp.inputs["Fac"])
    mix=nodes.new("ShaderNodeMixRGB");mix.blend_type="MIX"
    mix.name="ASTraM_Weathering_Mix";mix.location=(350,80)
    mix.inputs["Color2"].default_value=(0.095,0.075,0.055,1.0)
    if previous:
        links.new(previous,mix.inputs["Color1"])
    else:
        mix.inputs["Color1"].default_value=base_socket.default_value
    links.new(ramp.outputs["Color"],mix.inputs["Fac"])
    links.new(mix.outputs["Color"],base_socket)
    mat["weathering_streak_length_m"]="0.5-1.2"
    mat["weathering_method"]="Ambient Occlusion multiplied by vertical world-space noise"
    return True


BUILDINGS=(
    ("Saraswati_Ganga",-30.0,-100.0,85.0,35.0,20.0),
    ("Dnyaneshwar",-45.0,0.0,65.0,22.0,20.0),
    ("Vashistha",45.0,0.0,70.0,24.0,20.0),
    ("Aryabhata",45.0,60.0,65.0,45.0,16.0),
)


def add_chiller(c,m,parent,prefix,x,y,roof_z):
    box(f"{prefix}_HVAC_Chiller",c,m["metal"],(x,y,roof_z+0.9),(3.0,1.5,1.8),parent)
    for i,fx in enumerate((-0.72,0.72)):
        cylinder(f"{prefix}_HVAC_Fan_Rim_{i+1}",c,m["dark"],(x+fx,y,roof_z+1.84),0.42,0.08,parent,16)
        cylinder(f"{prefix}_HVAC_Fan_Hub_{i+1}",c,m["metal"],(x+fx,y,roof_z+1.90),0.08,0.05,parent,10)
        for blade in range(6):
            angle=2*math.pi*blade/6
            center=(x+fx+0.22*math.cos(angle),y+0.22*math.sin(angle),roof_z+1.91)
            obj=box(f"{prefix}_HVAC_Fan_Blade_{i+1}_{blade+1}",c,m["metal"],center,(0.34,0.07,0.035),parent)
            obj.rotation_euler[2]=angle
    # Side ventilation louver banks.
    for side in (-1,1):
        for row in range(5):
            box(f"{prefix}_HVAC_Louver_{side}_{row}",c,m["dark"],
                (x+side*1.506,y-0.46+row*0.23,roof_z+0.45),(0.035,0.12,0.06),parent)


def add_water_tank(c,m,parent,prefix,x,y,roof_z,index):
    cylinder(f"{prefix}_Water_Tank_{index:02d}",c,m["plastic"],(x,y,roof_z+1.0),0.75,2.0,parent,16)
    cylinder(f"{prefix}_Water_Tank_Lid_{index:02d}",c,m["metal"],(x,y,roof_z+2.02),0.77,0.06,parent,16)
    cylinder(f"{prefix}_Water_Tank_Base_Ring_{index:02d}",c,m["metal"],(x,y,roof_z+0.08),0.79,0.16,parent,16)


def add_penthouse(c,m,parent,prefix,x,y,roof_z):
    box(f"{prefix}_Elevator_Machine_Penthouse",c,m["concrete"],
        (x,y,roof_z+1.4),(4.0,3.0,2.8),parent)
    box(f"{prefix}_Roof_Exit_Door",c,m["metal"],
        (x,y-1.52,roof_z+1.0),(1.1,0.08,2.0),parent)
    box(f"{prefix}_Penthouse_Roof_Cap",c,m["roof"],
        (x,y,roof_z+2.85),(4.25,3.25,0.18),parent)


def add_solar_array(c,m,parent,prefix,x,y,roof_z,columns=4,rows=2):
    tilt=math.radians(18.0)
    for row in range(rows):
        for col in range(columns):
            px=x+(col-(columns-1)/2)*2.35
            py=y+(row-(rows-1)/2)*1.35
            # Aluminum frame legs lift each south-tilted panel above the roof.
            low_y=py-0.42;high_y=py+0.42
            box(f"{prefix}_Solar_Frame_Low_{row}_{col}",c,m["metal"],
                (px,low_y,roof_z+0.22),(2.0,0.08,0.38),parent)
            box(f"{prefix}_Solar_Frame_High_{row}_{col}",c,m["metal"],
                (px,high_y,roof_z+0.43),(2.0,0.08,0.38),parent)
            panel=box(f"{prefix}_Solar_Panel_{row}_{col}",c,m["solar"],
                      (px,py,roof_z+0.42),(2.0,1.0,0.08),parent)
            panel.rotation_euler[0]=tilt
            panel["tilt_degrees_south"]=18.0
            # Fine cell grid on the panel top, split into narrow dark blue cells.
            for cell in range(1,8):
                cx=px-1.0+cell*(2.0/8)
                divider=box(f"{prefix}_Solar_Cell_Divider_{row}_{col}_{cell}",c,m["metal"],
                    (cx,py,roof_z+0.48),(0.018,0.92,0.012),parent)
                divider.rotation_euler[0]=tilt


def add_downspouts(c,m,parent,name,x,y,width,depth,height):
    corners=(
        ("South",y-depth/2-0.06,True,width),
        ("North",y+depth/2+0.06,True,width),
        ("West",x-width/2-0.06,False,depth),
        ("East",x+width/2+0.06,False,depth),
    )
    for side,constant,is_x_axis,span in corners:
        count=max(1,int(span//15.0))
        for i in range(count+1):
            along=-span/2+span*i/count
            px,py=(x+along,constant) if is_x_axis else (constant,y+along)
            cylinder(f"{name}_Downspout_{side}_{i+1:02d}",c,m["metal"],
                     (px,py,height/2),0.05,height,parent,8)
            # Two wall clips anchor each vertical pipe.
            for z in (1.0,height-1.0):
                box(f"{name}_Downspout_Clip_{side}_{i+1}_{int(z)}",c,m["metal"],
                    (px,py,z),(0.16,0.16,0.08),parent)


def make_text(name,body,collection,parent,location,size,rotation=(math.pi/2,0,0),mat=None):
    curve=bpy.data.curves.new(f"{name}_Text","FONT")
    curve.body=body
    curve.size=size
    curve.align_x="CENTER"
    curve.align_y="CENTER"
    obj=bpy.data.objects.new(name,curve)
    collection.objects.link(obj)
    obj.location=location;obj.rotation_euler=rotation;obj.parent=parent
    obj[TAG]=True
    if mat:
        curve.materials.append(mat)
    return obj


def add_direction_board(c,m,parent,gate,x,y,angle):
    # Vertical map face directed toward the approach road.
    board=box(f"{gate}_Campus_Direction_Board",c,m["sign"],
              (x,y,1.5),(1.0,0.10,1.5),parent)
    board.rotation_euler[2]=angle
    pole=box(f"{gate}_Direction_Board_Post",c,m["metal"],
             (x,y,0.75),(0.10,0.10,1.5),parent)
    # Board graphic and title are raised text geometry for legible close views.
    forward=(math.sin(angle),-math.cos(angle))
    text_loc=(x+forward[0]*0.061,y+forward[1]*0.061,1.84)
    make_text(f"{gate}_Campus_Map_Title","MIT-WPU CAMPUS",c,parent,text_loc,0.12,
              (math.pi/2,0,angle),m["dark"])
    for row,body in enumerate(("SPORTS COMPLEX  ↑","CAST GATE  →","ACADEMIC BLOCKS  ←")):
        loc=(x+forward[0]*0.063,y+forward[1]*0.063,1.55-row*0.22)
        make_text(f"{gate}_Campus_Map_Line_{row+1}",body,c,parent,loc,0.075,
                  (math.pi/2,0,angle),m["dark"])


def add_speed_sign(c,m,parent,gate,x,y,angle):
    pole=box(f"{gate}_Speed_Sign_Post",c,m["metal"],(x,y,1.25),(0.08,0.08,2.5),parent)
    face_y=y-0.06
    disc=cylinder(f"{gate}_Speed_Limit_Disc",c,m["sign"],(x,face_y,2.25),0.48,0.08,parent,24,axis="Y")
    disc.rotation_euler[2]=angle
    # Red border ring approximated as a second shallow disc plus white inner face.
    red=cylinder(f"{gate}_Speed_Limit_Red_Border",c,material("Mat_Sign_Red",srgb("#D9272E"),0.45),
             (x,face_y-0.055,2.25),0.44,0.025,parent,24,axis="Y")
    red.rotation_euler[2]=angle
    white=cylinder(f"{gate}_Speed_Limit_White_Face",c,m["sign"],(x,face_y-0.075,2.25),0.37,0.025,parent,24,axis="Y")
    white.rotation_euler[2]=angle
    make_text(f"{gate}_Speed_Limit_Text","20",c,parent,(x,face_y-0.10,2.25),0.30,
              (math.pi/2,0,angle),m["dark"])
    make_text(f"{gate}_Speed_Limit_Units","km/h",c,parent,(x,face_y-0.105,2.03),0.09,
              (math.pi/2,0,angle),m["dark"])


def add_roof_systems(c,m,parent):
    for name,x,y,w,d,h in BUILDINGS:
        # Major roofs receive one penthouse, HVAC equipment, grouped tanks,
        # and downspouts on all four perimeter walls.
        add_penthouse(c,m,parent,name,x,y,h)
        add_chiller(c,m,parent,name,x-w*0.24,y+d*0.18,h)
        tank_count=4 if name in ("Saraswati_Ganga","Dnyaneshwar") else 2
        for index in range(tank_count):
            tx=x+w*0.18+(index%2)*1.9
            ty=y-d*0.18+(index//2)*1.9
            add_water_tank(c,m,parent,name,tx,ty,h,index+1)
        if name in ("Saraswati_Ganga","Dnyaneshwar"):
            add_solar_array(c,m,parent,name,x+w*0.22,y-d*0.12,h,4,2)
        add_downspouts(c,m,parent,name,x,y,w,d,h)


def add_signage(c,m,parent):
    # Main Gate, Cast Gate, Melek Gate site anchors in local campus coordinates.
    gates=(("Main_Gate",0.0,-160.0,0.0),
           ("Cast_Gate",105.0,25.0,math.pi/2),
           ("Melek_Gate",120.0,147.0,math.pi/2))
    for gate,x,y,angle in gates:
        side_x=x+4.0*math.cos(angle)
        side_y=y+4.0*math.sin(angle)
        add_direction_board(c,m,parent,gate,side_x,side_y,angle)
        add_speed_sign(c,m,parent,gate,x-4.5*math.sin(angle),y+4.5*math.cos(angle),angle)


def main():
    collection=ensure_scene()
    parent=bpy.data.objects.get("Campus_Orientation_Root")
    for obj in list(bpy.data.objects):
        if obj.get(TAG):
            bpy.data.objects.remove(obj,do_unlink=True)
    m=materials()
    weathered=[add_weathering("Mat_Concrete_Plaster"),add_weathering("Mat_Brick_Red")]
    add_roof_systems(collection,m,parent)
    add_signage(collection,m,parent)
    world=bpy.context.scene.world
    sky_ok=False
    if world and world.use_nodes:
        sky=next((node for node in world.node_tree.nodes if node.bl_idname=="ShaderNodeTexSky"),None)
        sky_ok=bool(sky and sky.sky_type=="MULTIPLE_SCATTERING" and abs(sky.air_density-1.2)<1e-6)
    print(f"Phase 7 complete: roof utilities and gate signage generated; weathering materials updated={weathered}; sky preserved={sky_ok}.")


if __name__=="__main__":
    main()
