"""Create modular facade assets, campus roads, curbs, markings, and street props.

Blender 5.2 usage from PowerShell (build and save a .blend in one process):
    blender --background --python scripts/generate_modular_kit_and_roads.py --python-expr "import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'C:\\Users\\Administrator\\Desktop\\ASTraM\\mit_wpu_phase3.blend')"

Road paths are read from data/mit_wpu_roads.geojson, a provisional poster trace.
They are not surveyed. The traced network is mapped into schematic campus-local
meters and follows Campus_Orientation_Root when that object exists. Rerunning
this script replaces only its own generated assets and props.
"""

from __future__ import annotations

import json
import math
import runpy
from pathlib import Path

import bpy


TAG = "astram_phase3_generated"
ROOT_DIR = Path(__file__).resolve().parents[1]
GEOJSON = ROOT_DIR / "data" / "mit_wpu_roads.geojson"
COLLECTIONS = ("07_MODULAR_KIT", "01_TERRAIN_ROADS", "09_PROPS_STREET_FURNITURE")
COLORS = {
    "Mat_Asphalt": (0.105, 0.12, 0.135, 1.0),
    "Mat_Curb_Concrete": (0.52, 0.51, 0.47, 1.0),
    "Mat_Paint_Yellow": (0.95, 0.68, 0.035, 1.0),
    "Mat_Paint_White": (0.9, 0.9, 0.84, 1.0),
    "Mat_Metal_Dark": (0.055, 0.065, 0.07, 1.0),
    "Mat_Glass_Clear": (0.25, 0.55, 0.68, 1.0),
    "Mat_Concrete_Plaster": (0.72, 0.69, 0.61, 1.0),
}


def ensure_scene() -> dict[str, bpy.types.Collection]:
    if any(bpy.data.collections.get(name) is None for name in COLLECTIONS):
        setup = Path(__file__).with_name("setup_3d_campus_scene.py")
        if not setup.is_file():
            raise FileNotFoundError(f"Required setup script is missing: {setup}")
        runpy.run_path(str(setup), run_name="__main__")
    return {name: bpy.data.collections[name] for name in COLLECTIONS}


def get_materials():
    result = {}
    for name, rgba in COLORS.items():
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.diffuse_color = rgba
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = rgba
            bsdf.inputs["Roughness"].default_value = 0.28 if "Glass" in name else 0.85
            if "Glass" in name:
                bsdf.inputs["Metallic"].default_value = 0.08
        result[name] = mat
    return result


def tagged_object(name, mesh, collection, parent=None, location=(0, 0, 0)):
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    obj.parent = parent
    obj.scale = (1.0, 1.0, 1.0)
    obj[TAG] = True
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    return obj


def mesh_from_parts(name, parts, mats, collection, parent=None, location=(0, 0, 0)):
    """Build one multi-material mesh from axis-aligned quad boxes.

    Each part is (center, dimensions, material_name); coordinates are local to
    the object's origin, allowing kit origins at the bottom-center base.
    """
    verts, faces, face_mats = [], [], []
    for center, dims, mat_name in parts:
        cx, cy, cz = center
        hx, hy, hz = (v / 2 for v in dims)
        base = len(verts)
        verts.extend(((cx-hx,cy-hy,cz-hz),(cx+hx,cy-hy,cz-hz),(cx+hx,cy+hy,cz-hz),(cx-hx,cy+hy,cz-hz),
                      (cx-hx,cy-hy,cz+hz),(cx+hx,cy-hy,cz+hz),(cx+hx,cy+hy,cz+hz),(cx-hx,cy+hy,cz+hz)))
        faces.extend(tuple(base+i for i in f) for f in ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)))
        face_mats.extend([mat_name] * 6)
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    for mat in mats.values():
        mesh.materials.append(mat)
    mat_indices = {material.name: i for i, material in enumerate(mesh.materials)}
    for poly, mat_name in zip(mesh.polygons, face_mats):
        poly.material_index = mat_indices[mats[mat_name].name]
    mesh.update()
    return tagged_object(name, mesh, collection, parent, location)


def create_window_kit(c, m):
    # Outside bounds exactly 1.5 x 0.2 x 1.8 m; object origin at bottom center.
    frame, glass, metal = "Mat_Concrete_Plaster", "Mat_Glass_Clear", "Mat_Metal_Dark"
    w, d, h, t = 1.5, 0.2, 1.8, 0.07
    parts = [((0,0,t/2),(w,d,t),frame), ((0,0,h-t/2),(w,d,t),frame),
             ((-w/2+t/2,0,h/2),(t,d,h),frame), ((w/2-t/2,0,h/2),(t,d,h),frame),
             ((-0.36,0,h/2),(0.62,d*0.55,h-t*2),glass),
             ((w/2-0.04,0,h/2),(0.025,d*0.8,h-t*2),metal),
             ((0,0,h/2),(0.045,d*0.8,h-t*2),frame)]
    mesh_from_parts("Mod_Window_Standard",parts,m,c)


def create_door_kit(c,m):
    w,d,h,t=2.0,0.2,2.4,0.08
    parts=[((0,0,h-t/2),(w,d,t),"Mat_Metal_Dark"),
           ((-w/2+t/2,0,h/2),(t,d,h),"Mat_Metal_Dark"),
           ((w/2-t/2,0,h/2),(t,d,h),"Mat_Metal_Dark"),
           ((-0.48,0,h/2),(0.86,d*0.55,h-t),"Mat_Glass_Clear"),
           ((0.48,0,h/2),(0.86,d*0.55,h-t),"Mat_Glass_Clear"),
           ((0,0,h/2),(0.045,d*0.8,h-t),"Mat_Metal_Dark")]
    for side,x in (("L",-0.10),("R",0.10)):
        parts.append(((x,-0.07,1.12),(0.035,0.06,0.42),"Mat_Metal_Dark"))
        parts.append(((x,-0.07,1.33),(0.13,0.06,0.035),"Mat_Metal_Dark"))
    mesh_from_parts("Mod_Door_Double_Glass",parts,m,c)


def create_pillar_kit(c,m):
    mesh_from_parts("Mod_Pillar_Square",[((0,0,1.9),(0.6,0.6,3.8),"Mat_Concrete_Plaster")],m,c)
    n,r,h=16,0.25,3.8
    verts=[]
    for z in (0,h):
        verts.extend((r*math.cos(2*math.pi*i/n),r*math.sin(2*math.pi*i/n),z) for i in range(n))
    faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
    faces.extend((i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n))
    mesh=bpy.data.meshes.new("Mod_Pillar_Round_Mesh");mesh.from_pydata(verts,[],faces);mesh.materials.append(m["Mat_Concrete_Plaster"]);mesh.update()
    tagged_object("Mod_Pillar_Round",mesh,c)


def create_railing_kit(c,m):
    parts=[((0,0,0.055),(2.0,0.1,0.11),"Mat_Metal_Dark"),
           ((0,0,1.045),(2.0,0.1,0.11),"Mat_Metal_Dark"),
           ((-0.95,0,0.55),(0.1,0.1,1.1),"Mat_Metal_Dark"),
           ((0.95,0,0.55),(0.1,0.1,1.1),"Mat_Metal_Dark"),
           ((0,0,0.55),(1.78,0.035,0.78),"Mat_Glass_Clear")]
    for i in range(1,7):
        parts.append(((-0.9+i*0.257,0,0.55),(0.035,0.08,0.78),"Mat_Metal_Dark"))
    mesh_from_parts("Mod_Balcony_Railing",parts,m,c)


def project_path(pixel_points, anchor_pixel=(147.0,735.0), meters_per_pixel=0.55):
    ax,ay=anchor_pixel
    return [((px-ax)*meters_per_pixel,(ay-py)*meters_per_pixel) for px,py in pixel_points]


def load_paths():
    if not GEOJSON.is_file():
        raise FileNotFoundError(f"Campus road GeoJSON not found: {GEOJSON}")
    data=json.loads(GEOJSON.read_text(encoding="utf-8-sig"))
    records={}
    for feature in data.get("features",[]):
        props=feature.get("properties",{})
        geometry=feature.get("geometry",{})
        if geometry.get("type")!="LineString":
            continue
        pixels=props.get("layout_coordinates")
        if not pixels or len(pixels)<2:
            continue
        forward=tuple((round(float(x),3),round(float(y),3)) for x,y in pixels)
        reverse=tuple(reversed(forward))
        key=min(forward,reverse)
        if key in records:
            continue
        records[key]={"id":str(props.get("id",feature.get("id","road"))),
                      "name":str(props.get("name",props.get("id","road"))),
                      "lanes":max(1,int(props.get("lanes",1))),
                      "points":project_path(pixels)}
    if not records:
        raise ValueError("The campus GeoJSON has no usable LineString layout_coordinates")
    return list(records.values())


def ribbon_offsets(points,width):
    """Miter-limited left/right offsets for a polyline."""
    left,right=[],[]
    half=width/2
    for i,(x,y) in enumerate(points):
        p0=points[max(0,i-1)];p1=points[min(len(points)-1,i+1)]
        dx,dy=p1[0]-p0[0],p1[1]-p0[1]
        length=math.hypot(dx,dy)
        if length<1e-8:
            continue
        nx,ny=-dy/length,dx/length
        scale=1.0
        if 0<i<len(points)-1:
            a=points[i-1];b=points[i+1]
            v1=(x-a[0],y-a[1]);v2=(b[0]-x,b[1]-y)
            l1,l2=math.hypot(*v1),math.hypot(*v2)
            n1=(-v1[1]/l1,v1[0]/l1);n2=(-v2[1]/l2,v2[0]/l2)
            mx,my=n1[0]+n2[0],n1[1]+n2[1];ml=math.hypot(mx,my)
            if ml>1e-8:
                mx,my=mx/ml,my/ml
                scale=min(1.0/max(abs(mx*n2[0]+my*n2[1]),0.25),2.5)
                nx,ny=mx,my
        left.append((x+nx*half*scale,y+ny*half*scale))
        right.append((x-nx*half*scale,y-ny*half*scale))
    return left,right


def extruded_ribbon(name,points,width,z0,z1,collection,material,parent,cap_sides=True):
    left,right=ribbon_offsets(points,width)
    if len(left)<2:
        return None
    verts=[]
    for z in (z0,z1):
        verts.extend((x,y,z) for x,y in left)
        verts.extend((x,y,z) for x,y in right)
    n=len(left); base=2*n
    faces=[]
    # Top surface split into quads; bottom likewise.
    for i in range(n-1):
        faces.append((base+i,base+i+1,base+n+i+1,base+n+i))
        faces.append((i,n+i,n+i+1,i+1))
        faces.append((i,i+1,base+i+1,base+i))
        faces.append((n+i,base+n+i,base+n+i+1,n+i+1))
    if cap_sides:
        faces.extend(((0,base,base+n,n),(n-1,2*n-1,3*n-1,base+n-1)))
    mesh=bpy.data.meshes.new(f"{name}_Mesh");mesh.from_pydata(verts,[],faces);mesh.update()
    mesh.materials.append(material)
    obj=tagged_object(name,mesh,collection,parent)
    return obj


def create_roads(collection,m,parent,paths):
    main_records=[]
    for record in paths:
        name=record["name"].replace(" ","_").replace("/","_")
        road_name=record["name"].lower()
        is_spine=any(token in road_name for token in (
            "spine", "main gate road trunk", "central avenue to cast gate",
            "cast gate access", "gate 3 north link", "sports complex"
        ))
        width=8.0 if is_spine else max(5.0,record["lanes"]*3.2)
        record["width"]=width
        road=extruded_ribbon(f"RoadRibbon_{record['id']}_{name}",record["points"],width,0.015,0.16,
                             collection,m["Mat_Asphalt"],parent)
        if road:
            road["road_name"]=record["name"]
            road["width_m"]=width
        left,right=ribbon_offsets(record["points"],width)
        for side,edgepoints in (("L",left),("R",right)):
            extruded_ribbon(f"RoadCurb_{record['id']}_{side}",edgepoints,0.2,0.0,0.15,
                            collection,m["Mat_Curb_Concrete"],parent)
        if is_spine:
            main_records.append(record)
            add_centerline_dashes(record,collection,m,parent)
            inner_left,inner_right=ribbon_offsets(record["points"],width-0.45)
            extruded_ribbon(f"Road_Edge_Marking_{record['id']}_L",inner_left,0.12,0.162,0.17,
                            collection,m["Mat_Paint_White"],parent)
            extruded_ribbon(f"Road_Edge_Marking_{record['id']}_R",inner_right,0.12,0.162,0.17,
                            collection,m["Mat_Paint_White"],parent)
    return main_records


def add_centerline_dashes(record,collection,m,parent):
    points=record["points"]
    dash_len,gap=3.0,4.0
    index=0
    for a,b in zip(points,points[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if length<1e-5: continue
        ux,uy=dx/length,dy/length
        distance=0.0
        while distance<length:
            end=min(distance+dash_len,length)
            if end>distance:
                p0=(a[0]+ux*distance,a[1]+uy*distance)
                p1=(a[0]+ux*end,a[1]+uy*end)
                # Yellow center dash has a narrow extruded rectangular ribbon.
                half=0.075
                normal=(-uy*half,ux*half)
                poly=[(p0[0]+normal[0],p0[1]+normal[1]),(p1[0]+normal[0],p1[1]+normal[1]),
                      (p1[0]-normal[0],p1[1]-normal[1]),(p0[0]-normal[0],p0[1]-normal[1])]
                mesh=bpy.data.meshes.new(f"Spine_Marking_{index:03d}_Mesh")
                mesh.from_pydata([(x,y,0.162) for x,y in poly],[],[(0,1,2,3)])
                mesh.materials.append(m["Mat_Paint_Yellow"]);mesh.update()
                obj=tagged_object(f"Spine_Marking_{index:03d}",mesh,collection,parent)
                obj["marking_type"]="centerline"
                index+=1
            distance+=dash_len+gap


def sample_polyline(points,spacing):
    samples=[];carry=0.0
    for a,b in zip(points,points[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if length<1e-8: continue
        direction=(dx/length,dy/length)
        dist=spacing-carry
        while dist<=length:
            samples.append((a[0]+direction[0]*dist,a[1]+direction[1]*dist,direction))
            dist+=spacing
        carry=(carry+length)%spacing
    return samples


def create_props(collection,m,parent,paths):
    lamp_index=0
    for record in paths:
        # Lamps along primary roads and the main campus spine at 15 m intervals.
        is_primary=("spine" in record["name"].lower() or "main gate" in record["name"].lower()
                    or "sports" in record["name"].lower() or "cast" in record["name"].lower())
        if not is_primary: continue
        for x,y,direction in sample_polyline(record["points"],15.0):
            # Alternate side placements; stay outside the corresponding curb.
            side=-1 if lamp_index%2==0 else 1
            nx,ny=-direction[1],direction[0]
            px=x+nx*side*(record.get("width",8.0)/2+1.2)
            py=y+ny*side*(record.get("width",8.0)/2+1.2)
            create_lamp(collection,m,parent,px,py,direction,lamp_index)
            lamp_index+=1
    # Three gate barriers use site anchors consistent with phase-1 schematic.
    for name,x,y,angle in (("Main_Gate",0.0,-160.0,0.0),
                           ("Cast_Gate",105.0,25.0,math.pi/2),
                           ("Melek_Gate",120.0,147.0,math.pi/2)):
        create_barrier(collection,m,parent,name,x,y,angle)
    for i,(x,y,angle) in enumerate(((-12.0,-8.0,0.0),(12.0,10.0,math.pi/2),
                                     (30.0,38.0,0.0),(-65.0,55.0,math.pi/2))):
        create_bench(collection,m,parent,x,y,angle,i)
    for i,(x,y) in enumerate(((-22.0,-105.0),(18.0,-105.0),(-63.0,55.0),(64.0,65.0))):
        create_bin(collection,m,parent,x,y,i)


def create_lamp(c,m,parent,x,y,direction,index):
    boxparts=[((0,0,2.2),(0.16,0.16,4.4),"Mat_Metal_Dark"),
              ((0,0,4.35),(0.30,0.30,0.18),"Mat_Metal_Dark")]
    # Fixture arm points forward along the road, elevated and angled downward.
    dx,dy=direction
    boxparts.append(((0.38,0,4.48),(0.9,0.12,0.12),"Mat_Metal_Dark"))
    obj=mesh_from_parts(f"Prop_Street_Lamp_{index:03d}",boxparts,m,c,parent,(x,y,0))
    obj.rotation_euler[2]=math.atan2(dy,dx)
    obj["height_m"]=4.5
    mesh_from_parts(f"Prop_Street_Lamp_LED_{index:03d}",
                    [((0.72,0,4.22),(0.52,0.24,0.09),"Mat_Glass_Clear")],m,c,parent,(x,y,0))
    bpy.data.objects[f"Prop_Street_Lamp_LED_{index:03d}"].rotation_euler[2]=math.atan2(dy,dx)


def create_barrier(c,m,parent,name,x,y,angle):
    parts=[((0,0,0.48),(0.48,0.48,0.96),"Mat_Concrete_Plaster"),
           ((0,0,0.98),(0.62,0.62,0.18),"Mat_Metal_Dark"),
           ((0,2.0,1.05),(0.14,4.0,0.14),"Mat_Metal_Dark")]
    arm_parts=[]
    for i in range(8):
        arm_parts.append(((0,0.25+i*0.5,1.05),(0.15,0.22,0.15),"Mat_Paint_Yellow" if i%2==0 else "Mat_Metal_Dark"))
    obj=mesh_from_parts(f"Prop_Security_Boom_Barrier_{name}",parts+arm_parts,m,c,parent,(x,y,0))
    obj.rotation_euler[2]=angle


def create_bench(c,m,parent,x,y,angle,index):
    parts=[((0,0,0.40),(1.8,0.6,0.10),"Mat_Concrete_Plaster"),
           ((0,-0.20,0.20),(1.65,0.12,0.40),"Mat_Concrete_Plaster"),
           ((0,0.20,0.20),(1.65,0.12,0.40),"Mat_Concrete_Plaster")]
    obj=mesh_from_parts(f"Prop_Concrete_Bench_{index+1:02d}",parts,m,c,parent,(x,y,0))
    obj.rotation_euler[2]=angle


def create_bin(c,m,parent,x,y,index):
    n,r,h=16,0.25,0.9
    verts=[]
    for z in (0,h):
        verts.extend((r*math.cos(2*math.pi*i/n),r*math.sin(2*math.pi*i/n),z) for i in range(n))
    faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
    faces.extend((i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n))
    mesh=bpy.data.meshes.new(f"Prop_Trash_Bin_{index+1:02d}_Mesh");mesh.from_pydata(verts,[],faces)
    mesh.materials.append(m["Mat_Metal_Dark"]);mesh.update()
    obj=tagged_object(f"Prop_Trash_Bin_{index+1:02d}",mesh,c,parent,(x,y,0))
    obj["diameter_m"]=0.5;obj["height_m"]=0.9


def main():
    col=ensure_scene()
    for obj in list(bpy.data.objects):
        if obj.get(TAG): bpy.data.objects.remove(obj,do_unlink=True)
    m=get_materials()
    kit=col["07_MODULAR_KIT"]
    create_window_kit(kit,m)
    create_door_kit(kit,m)
    create_pillar_kit(kit,m)
    create_railing_kit(kit,m)
    root=bpy.data.objects.get("Campus_Orientation_Root")
    paths=load_paths()
    create_roads(col["01_TERRAIN_ROADS"],m,root,paths)
    create_props(col["09_PROPS_STREET_FURNITURE"],m,root,paths)
    world=bpy.context.scene.world
    if world and world.use_nodes:
        sky=next((n for n in world.node_tree.nodes if n.bl_idname=="ShaderNodeTexSky"),None)
        if sky and sky.sky_type=="MULTIPLE_SCATTERING" and abs(sky.air_density-1.2)<1e-6:
            print("Preserved multiple-scattering sky and air_density=1.2.")
    print(f"Phase 3 complete: {len(paths)} unique traced road ribbons, modular kit assets, and street props.")


if __name__=="__main__":
    main()
