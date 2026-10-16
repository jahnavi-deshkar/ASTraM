"""Build low-poly foliage masters and Geometry Nodes lawn scattering for Blender 5.2.

Run in a saved Phase-4 campus scene, or run and save in one Blender process:
    blender --background [phase4_scene.blend] --python scripts/scatter_foliage_and_lawns.py --python-expr "import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'C:\\Users\\Administrator\\Desktop\\ASTraM\\mit_wpu_phase5.blend')"

When no phase collections exist, the phase-1 setup script is bootstrapped.
Road and lawn locations remain schematic campus-local coordinates. The existing
Campus_Orientation_Root and world sky are preserved.
"""

from __future__ import annotations

import math
import runpy
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


FOLIAGE_COLLECTION = "08_FOLIAGE_LANDSCAPE"
TAG = "astram_phase5_generated"
CHILD_COLLECTIONS = {
    "gulmohar": "Foliage_Master_Gulmohar",
    "palm": "Foliage_Master_Royal_Palm",
    "neem": "Foliage_Master_Neem",
    "hedge": "Foliage_Master_Boxwood",
    "grass": "Foliage_Master_Grass",
}


def ensure_scene():
    if bpy.data.collections.get(FOLIAGE_COLLECTION) is None:
        setup = Path(__file__).with_name("setup_3d_campus_scene.py")
        if not setup.is_file():
            raise FileNotFoundError(f"Required scene setup script not found: {setup}")
        runpy.run_path(str(setup), run_name="__main__")
    return bpy.data.collections[FOLIAGE_COLLECTION]


def get_material(name, color, roughness=0.82):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def foliage_materials():
    return {
        "bark": get_material("Mat_Tree_Bark", (0.19, 0.09, 0.045, 1.0)),
        "foliage": get_material("Mat_Foliage_Green", (0.10, 0.30, 0.08, 1.0)),
        "grass": get_material("Mat_Grass_Blade", (0.16, 0.39, 0.09, 1.0)),
        "hedge": get_material("Mat_Hedge_Green", (0.08, 0.27, 0.06, 1.0)),
    }


def get_child_collection(parent, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if collection.name not in {child.name for child in parent.children}:
        parent.children.link(collection)
    return collection


class MeshBuilder:
    """Small mesh accumulator for tapered quad branches and low-poly canopies."""
    def __init__(self):
        self.vertices = []
        self.faces = []
        self.material_ids = []

    def frustum(self, start, end, radius_start, radius_end, material_id=0, sides=6):
        a, b = Vector(start), Vector(end)
        axis = (b-a).normalized()
        helper = Vector((0, 0, 1)) if abs(axis.z) < 0.92 else Vector((0, 1, 0))
        u = axis.cross(helper).normalized()
        v = axis.cross(u).normalized()
        offset = len(self.vertices)
        for center, radius in ((a, radius_start), (b, radius_end)):
            for i in range(sides):
                angle = 2*math.pi*i/sides
                point = center + radius*(math.cos(angle)*u + math.sin(angle)*v)
                self.vertices.append(tuple(point))
        self.faces.append(tuple(reversed(tuple(offset+i for i in range(sides)))))
        self.material_ids.append(material_id)
        self.faces.append(tuple(offset+sides+i for i in range(sides)))
        self.material_ids.append(material_id)
        for i in range(sides):
            self.faces.append((offset+i, offset+(i+1)%sides,
                               offset+sides+(i+1)%sides, offset+sides+i))
            self.material_ids.append(material_id)

    def icosphere(self, center, scale, material_id=1, subdivisions=1):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=1.0)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        offset = len(self.vertices)
        c, s = Vector(center), Vector(scale)
        self.vertices.extend(tuple(c + Vector((v.co.x*s.x, v.co.y*s.y, v.co.z*s.z))) for v in bm.verts)
        for face in bm.faces:
            self.faces.append(tuple(offset+v.index for v in face.verts))
            self.material_ids.append(material_id)
        bm.free()

    def blade(self, start, end, width, material_id=1):
        """Create a tapered quad leaf oriented in the vertical plane."""
        a,b=Vector(start),Vector(end)
        direction=(b-a).normalized()
        side=direction.cross(Vector((0,1,0)))
        if side.length<1e-5:
            side=direction.cross(Vector((1,0,0)))
        side.normalize()
        offset=len(self.vertices)
        self.vertices.extend((tuple(a-side*width/2),tuple(a+side*width/2),
                              tuple(b+side*width*0.12),tuple(b-side*width*0.12)))
        self.faces.append((offset,offset+1,offset+2,offset+3))
        self.material_ids.append(material_id)

    def object(self, name, collection, mats, parent=None):
        mesh=bpy.data.meshes.new(f"{name}_Mesh")
        mesh.from_pydata(self.vertices,[],self.faces)
        mesh.materials.append(mats["bark"])
        mesh.materials.append(mats["foliage"])
        mesh.materials.append(mats["grass"])
        mesh.materials.append(mats["hedge"])
        mesh.update()
        for poly, material_id in zip(mesh.polygons,self.material_ids):
            poly.material_index=material_id
        obj=bpy.data.objects.new(name,mesh)
        collection.objects.link(obj)
        obj.parent=parent
        obj.location=(0,0,0)
        obj.scale=(1,1,1)
        obj[TAG]=True
        obj["origin_note"]="Bottom-center at local (0, 0, 0)"
        for edge in mesh.edges:
            edge.use_edge_sharp=True
        return obj


def build_gulmohar(collection,mats,parent):
    b=MeshBuilder()
    b.frustum((0,0,0),(0,0,6.2),0.38,0.20,0,8)
    branches=[((-0.1,0,3.7),(-2.8,0.2,8.2)),((0.0,0,4.0),(2.6,0.3,8.4)),
              ((0,0,4.2),(0.3,2.7,8.6)),((0,0,4.2),(-0.2,-2.7,8.4)),
              ((0,0,5.0),(1.8,-1.8,9.3)),((0,0,5.0),(-1.8,1.8,9.1))]
    for start,end in branches:
        b.frustum(start,end,0.16,0.07,0,6)
    canopies=[(-2.8,0.2,8.5,2.1,1.9,1.9),(2.6,0.3,8.8,2.2,2.1,1.8),
              (0.3,2.7,9.0,2.0,1.8,1.8),(-0.2,-2.7,8.8,2.0,1.8,1.8),
              (1.8,-1.8,9.4,2.0,1.9,1.7),(-1.8,1.8,9.2,2.0,1.8,1.8)]
    for x,y,z,sx,sy,sz in canopies:
        b.icosphere((x,y,z),(sx,sy,sz),1,1)
    obj=b.object("Tree_Gulmohar_Master",collection,mats,parent)
    obj["height_m"]=11.2
    return obj


def build_neem(collection,mats,parent):
    b=MeshBuilder()
    b.frustum((0,0,0),(0,0,5.4),0.34,0.18,0,8)
    for i in range(7):
        angle=2*math.pi*i/7
        start=(0,0,3.4)
        end=(2.2*math.cos(angle),2.2*math.sin(angle),7.0+(i%3)*0.35)
        b.frustum(start,end,0.15,0.06,0,6)
    for z,rad in ((6.2,2.0),(7.2,2.5),(8.0,2.0)):
        for i in range(7):
            angle=2*math.pi*i/7
            b.icosphere((rad*0.72*math.cos(angle),rad*0.72*math.sin(angle),z),
                        (1.45,1.35,1.35),1,1)
    obj=b.object("Tree_Neem_Master",collection,mats,parent)
    obj["height_m"]=9.4
    return obj


def build_palm(collection,mats,parent):
    b=MeshBuilder()
    b.frustum((0,0,0),(0,0,12.6),0.27,0.14,0,8)
    crown=13.0
    for i in range(9):
        angle=2*math.pi*i/9
        dx,dy=math.cos(angle),math.sin(angle)
        tip=(dx*4.0,dy*4.0, crown-1.65+(i%3)*0.12)
        b.frustum((0,0,crown),tip,0.075,0.035,1,5)
        # Segmented leaf blades fan out from each central frond rachis.
        for j in range(1,7):
            t=j/7
            px=dx*4.0*t; py=dy*4.0*t
            pz=crown-1.65*t
            side_angle=angle + (1 if j%2 else -1)*0.45
            reach=0.55*(1.0-t)+0.12
            endpoint=(px+math.cos(side_angle)*reach,py+math.sin(side_angle)*reach,pz-0.12)
            b.blade((px,py,pz),endpoint,0.20*(1.0-t)+0.07,1)
    obj=b.object("Tree_Royal_Palm_Master",collection,mats,parent)
    obj["height_m"]=13.2
    return obj


def build_hedge(collection,mats,parent):
    b=MeshBuilder()
    # Dense cluster of low-poly foliage volumes; overall bounds approximately 1 x .55 x .8 m.
    for x in (-0.20,0.0,0.20):
        b.icosphere((x,0,0.40),(0.30,0.28,0.38),3,1)
    obj=b.object("Hedge_Boxwood_Master",collection,mats,parent)
    obj["dimensions_m"]=[1.0,0.56,0.8]
    return obj


def build_grass(collection,mats,parent):
    b=MeshBuilder()
    count=9
    for i in range(count):
        angle=2*math.pi*i/count
        height=0.08
        radius=0.012+0.009*(i%2)
        start=(radius*math.cos(angle),radius*math.sin(angle),0.0)
        end=(0.045*math.cos(angle),0.045*math.sin(angle),height)
        b.blade(start,end,0.012,2)
    obj=b.object("Grass_Blade_Cluster",collection,mats,parent)
    obj["height_m"]=0.08
    return obj


def make_lawn(name,collection,parent,x,y,width,depth,material):
    old=bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old,do_unlink=True)
    hx,hy=width/2,depth/2
    mesh=bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata([(-hx,-hy,0),(hx,-hy,0),(hx,hy,0),(-hx,hy,0)],[],[(0,1,2,3)])
    mesh.materials.append(material);mesh.update()
    obj=bpy.data.objects.new(name,mesh)
    collection.objects.link(obj)
    obj.location=(x,y,0.025);obj.parent=parent;obj.scale=(1,1,1)
    obj[TAG]=True;obj["lawn_dimensions_m"]=[width,depth]
    return obj


def ensure_geo_group(asset_collections):
    old=bpy.data.node_groups.get("GeoNode_FoliageScatter")
    if old:
        bpy.data.node_groups.remove(old,do_unlink=True)
    group=bpy.data.node_groups.new("GeoNode_FoliageScatter","GeometryNodeTree")
    interface=group.interface
    def input_socket(name,socket_type,default=None,minimum=None,maximum=None):
        sock=interface.new_socket(name=name,in_out="INPUT",socket_type=socket_type)
        if default is not None and hasattr(sock,"default_value"):
            sock.default_value=default
        if minimum is not None and hasattr(sock,"min_value"):
            sock.min_value=minimum
        if maximum is not None and hasattr(sock,"max_value"):
            sock.max_value=maximum
        return sock
    output=interface.new_socket(name="Geometry",in_out="OUTPUT",socket_type="NodeSocketGeometry")
    input_socket("Geometry","NodeSocketGeometry")
    assets={"gulmohar":"Gulmohar","palm":"Royal Palm","neem":"Neem",
            "hedge":"Hedge","grass":"Grass"}
    densities={"Gulmohar Density":0.012,"Royal Palm Density":0.0,"Neem Density":0.0,
               "Hedge Density":0.0,"Grass Density":2.5}
    for title,value in densities.items():
        input_socket(title,"NodeSocketFloat",value,0.0,1000.0)
    distances={"Tree Distance Min":8.0,"Hedge Distance Min":0.9,"Grass Distance Min":0.16}
    for title,value in distances.items():
        input_socket(title,"NodeSocketFloat",value,0.01,100.0)
    input_socket("Seed","NodeSocketInt",1,0,100000)

    nodes,links=group.nodes,group.links
    group_input=nodes.new("NodeGroupInput");group_input.location=(-1000,0)
    group_output=nodes.new("NodeGroupOutput");group_output.location=(1050,0)
    geo_in=group_input.outputs["Geometry"]
    object_outputs={}
    for i,(asset_key,label) in enumerate(assets.items()):
        info=nodes.new("GeometryNodeCollectionInfo")
        info.location=(-760,500-i*230)
        info.name=f"{label}_Master_Collection_Info"
        info.inputs["Separate Children"].default_value=True
        info.inputs["Reset Children"].default_value=True
        info.inputs["Collection"].default_value=asset_collections[asset_key]
        object_outputs[asset_key]=info.outputs.get("Instances") or info.outputs.get("Geometry")

    species=(
        ("gulmohar","Gulmohar Density","Tree Distance Min",480),
        ("palm","Royal Palm Density","Tree Distance Min",240),
        ("neem","Neem Density","Tree Distance Min",0),
        ("hedge","Hedge Density","Hedge Distance Min",-240),
        ("grass","Grass Density","Grass Distance Min",-480),
    )
    instance_outputs=[]
    for index,(asset_key,density_socket,distance_socket,y) in enumerate(species):
        distribute=nodes.new("GeometryNodeDistributePointsOnFaces")
        distribute.location=(-430,y)
        distribute.name=f"{asset_key.title()}_Poisson_Distribution"
        distribute.distribute_method="POISSON"
        links.new(geo_in,distribute.inputs["Mesh"])
        if "Density" in distribute.inputs:
            links.new(group_input.outputs[density_socket],distribute.inputs["Density"])
        if "Density Max" in distribute.inputs:
            distribute.inputs["Density Max"].default_value=1.0
        if "Distance Min" in distribute.inputs:
            links.new(group_input.outputs[distance_socket],distribute.inputs["Distance Min"])
        if "Seed" in distribute.inputs:
            links.new(group_input.outputs["Seed"],distribute.inputs["Seed"])
        inst=nodes.new("GeometryNodeInstanceOnPoints")
        inst.location=(350,y)
        inst.name=f"{asset_key.title()}_Instance_On_Points"
        links.new(distribute.outputs["Points"],inst.inputs["Points"])
        links.new(object_outputs[asset_key],inst.inputs["Instance"])
        inst.inputs["Pick Instance"].default_value=True
        random_rotation=nodes.new("FunctionNodeRandomValue")
        random_rotation.data_type="FLOAT_VECTOR"
        random_rotation.location=(80,y-80)
        random_rotation.name=f"{asset_key.title()}_Random_Z_Rotation_0_to_2Pi"
        random_rotation.inputs["Min"].default_value=(0.0,0.0,0.0)
        random_rotation.inputs["Max"].default_value=(0.0,0.0,2*math.pi)
        links.new(random_rotation.outputs["Value"],inst.inputs["Rotation"])
        random_scale=nodes.new("FunctionNodeRandomValue")
        random_scale.data_type="FLOAT_VECTOR"
        random_scale.location=(80,y-220)
        random_scale.name=f"{asset_key.title()}_Random_Uniform_Scale_0_85_to_1_15"
        random_scale.inputs["Min"].default_value=(0.85,0.85,0.85)
        random_scale.inputs["Max"].default_value=(1.15,1.15,1.15)
        links.new(random_scale.outputs["Value"],inst.inputs["Scale"])
        instance_outputs.append(inst.outputs["Instances"])
    join=nodes.new("GeometryNodeJoinGeometry");join.location=(800,0)
    links.new(geo_in,join.inputs["Geometry"])
    for output_socket in instance_outputs:
        links.new(output_socket,join.inputs["Geometry"])
    links.new(join.outputs["Geometry"],group_output.inputs["Geometry"])
    return group,assets


def modifier_with_assets(obj,group,densities,distances,seed):
    for modifier in list(obj.modifiers):
        if modifier.name=="GN_FoliageScatter":
            obj.modifiers.remove(modifier)
    mod=obj.modifiers.new("GN_FoliageScatter","NODES")
    mod.node_group=group
    sockets={item.name:item for item in group.interface.items_tree if item.item_type=="SOCKET" and item.in_out=="INPUT"}
    values={}
    values.update(densities);values.update(distances);values["Seed"]=seed
    for name,value in values.items():
        identifier=sockets[name].identifier
        if bpy.app.version >= (5,2,0):
            getattr(mod.properties.inputs,identifier).value=value
        else:
            mod[identifier]=value
    return mod


def make_border_hedges(source,collection,parent,x,y,width,depth,interval=0.9):
    # Use linked mesh duplicates as a deliberate continuous hedge line.
    index=0
    for side,axis_length,center in (("South",width,(x,y-depth/2)),("North",width,(x,y+depth/2)),
                                    ("West",depth,(x-width/2,y)),("East",depth,(x+width/2,y))):
        count=max(1,int(axis_length/interval))
        for i in range(count+1):
            t=-axis_length/2+axis_length*i/count
            px,py=(x+t,center[1]) if side in ("South","North") else (center[0],y+t)
            obj=source.copy();obj.data=source.data
            obj.name=f"Hedge_Lawn_Border_{side}_{index:03d}"
            collection.objects.link(obj)
            obj.location=(px,py,0.03);obj.parent=parent
            obj[TAG]=True
            index+=1


def duplicate_asset(source,collection,parent,name,location,rotation_z=0.0):
    obj=source.copy();obj.data=source.data;obj.name=name
    collection.objects.link(obj)
    obj.location=location;obj.parent=parent;obj.rotation_euler[2]=rotation_z
    obj[TAG]=True
    return obj


def main():
    foliage=ensure_scene()
    root=bpy.data.objects.get("Campus_Orientation_Root")
    for obj in list(bpy.data.objects):
        if obj.get(TAG):
            bpy.data.objects.remove(obj,do_unlink=True)
    # Reuse nested asset collections, but clear their prior master geometry.
    child={key:get_child_collection(foliage,name) for key,name in CHILD_COLLECTIONS.items()}
    for collection in child.values():
        for obj in list(collection.objects):
            bpy.data.objects.remove(obj,do_unlink=True)
    mats=foliage_materials()
    masters={
        "gulmohar":build_gulmohar(child["gulmohar"],mats,None),
        "palm":build_palm(child["palm"],mats,None),
        "neem":build_neem(child["neem"],mats,None),
        "hedge":build_hedge(child["hedge"],mats,None),
        "grass":build_grass(child["grass"],mats,None),
    }
    # Generate missing lawn surfaces at schematic positions; each surface is a
    # single upward-facing quad so points distribute only on its top face.
    lawns=[
        ("Lawn_Dnyaneshwar_1",-18.0,-12.0,22.0,22.0,"grass"),
        ("Lawn_Dnyaneshwar_2",-18.0,12.0,22.0,22.0,"grass"),
        ("Lawn_Vashistha",20.0,0.0,22.0,48.0,"grass"),
        ("Lawn_Agastya",-60.0,-57.0,40.0,30.0,"gulmohar"),
        ("Lawn_Dhruv",-90.0,150.0,50.0,30.0,"gulmohar"),
        ("Perimeter_Cast_Gate_Strip",143.0,25.0,5.0,62.0,"neem"),
        ("Perimeter_Melek_Gate_Strip",143.0,165.0,5.0,70.0,"neem"),
    ]
    turf=bpy.data.materials.get("Mat_Turf_Green") or get_material("Mat_Turf_Green",(0.13,0.32,0.16,1))
    lawn_objects={}
    for name,x,y,w,d,kind in lawns:
        lawn_objects[name]=make_lawn(name,foliage,root,x,y,w,d,turf)
    group,_=ensure_geo_group(child)
    density_profiles={
        "Lawn_Dnyaneshwar_1":({"Gulmohar Density":0.0,"Royal Palm Density":0.0,"Neem Density":0.0,"Hedge Density":0.0,"Grass Density":2.4},
                              {"Tree Distance Min":8.0,"Hedge Distance Min":0.9,"Grass Distance Min":0.14}),
        "Lawn_Dnyaneshwar_2":({"Gulmohar Density":0.0,"Royal Palm Density":0.0,"Neem Density":0.0,"Hedge Density":0.0,"Grass Density":2.4},
                              {"Tree Distance Min":8.0,"Hedge Distance Min":0.9,"Grass Distance Min":0.14}),
        "Lawn_Vashistha":({"Gulmohar Density":0.0,"Royal Palm Density":0.0,"Neem Density":0.0,"Hedge Density":0.0,"Grass Density":2.4},
                           {"Tree Distance Min":8.0,"Hedge Distance Min":0.9,"Grass Distance Min":0.14}),
        "Lawn_Agastya":({"Gulmohar Density":0.018,"Royal Palm Density":0.0,"Neem Density":0.0,"Hedge Density":0.0,"Grass Density":0.7},
                        {"Tree Distance Min":8.5,"Hedge Distance Min":0.9,"Grass Distance Min":0.18}),
        "Lawn_Dhruv":({"Gulmohar Density":0.018,"Royal Palm Density":0.0,"Neem Density":0.0,"Hedge Density":0.0,"Grass Density":0.7},
                      {"Tree Distance Min":8.5,"Hedge Distance Min":0.9,"Grass Distance Min":0.18}),
        "Perimeter_Cast_Gate_Strip":({"Gulmohar Density":0.0,"Royal Palm Density":0.0,"Neem Density":0.012,"Hedge Density":0.0,"Grass Density":0.0},
                                      {"Tree Distance Min":9.0,"Hedge Distance Min":0.9,"Grass Distance Min":0.18}),
        "Perimeter_Melek_Gate_Strip":({"Gulmohar Density":0.0,"Royal Palm Density":0.0,"Neem Density":0.012,"Hedge Density":0.0,"Grass Density":0.0},
                                       {"Tree Distance Min":9.0,"Hedge Distance Min":0.9,"Grass Distance Min":0.18}),
    }
    for index,(name,obj) in enumerate(lawn_objects.items()):
        density,distance=density_profiles[name]
        modifier_with_assets(obj,group,density,distance,index+1)
    # Royal palms form a regular north-south avenue beside the central 3 m path.
    for row_x in (1.0,4.0):
        for index,row_y in enumerate(range(-20,25,10)):
            duplicate_asset(masters["palm"],foliage,root,
                            f"Palm_Central_Walkway_{int(row_x)}_{index+1:02d}",
                            (row_x,float(row_y),0),0.2*(index%2))
    # Boxwood modules form continuous low hedges around Agastya and Dhruv lawns.
    make_border_hedges(masters["hedge"],foliage,root,-60.0,-57.0,40.0,30.0)
    make_border_hedges(masters["hedge"],foliage,root,-90.0,150.0,50.0,30.0)
    world=bpy.context.scene.world
    sky_ok=False
    if world and world.use_nodes:
        sky=next((node for node in world.node_tree.nodes if node.bl_idname=="ShaderNodeTexSky"),None)
        sky_ok=bool(sky and sky.sky_type=="MULTIPLE_SCATTERING" and abs(sky.air_density-1.2)<1e-6)
    print(f"Phase 5 complete: 5 low-poly masters, {len(lawn_objects)} Geometry Nodes lawns, sky preserved={sky_ok}.")


if __name__=="__main__":
    main()
