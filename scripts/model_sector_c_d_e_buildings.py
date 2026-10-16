"""Procedurally model MIT-WPU campus Sectors C, D, and E in Blender 5.2.

Run from PowerShell or a terminal:
    blender --background --python scripts/model_sector_c_d_e_buildings.py

If the phase-1 sector collections are absent, the phase-1 setup script is run
automatically. Site positions are schematic local coordinates; the existing
Campus_Orientation_Root applies the campus alignment. Rerunning this script
replaces only its own generated geometry and the matching sector proxies.
"""

from __future__ import annotations

import math
import runpy
from pathlib import Path

import bpy


TAG = "astram_sector_cde_generated"
MAT_COLORS = {
    "Mat_Concrete_Plaster": (0.72, 0.69, 0.61, 1.0),
    "Mat_Brick_Red": (0.38, 0.10, 0.065, 1.0),
    "Mat_Glass_Tinted": (0.055, 0.12, 0.17, 1.0),
    "Mat_Roof_Concrete": (0.48, 0.47, 0.43, 1.0),
    "Mat_Metal_Dark": (0.075, 0.085, 0.09, 1.0),
    "Mat_Turf_Green": (0.13, 0.32, 0.16, 1.0),
    "Mat_Court_Blue": (0.06, 0.28, 0.48, 1.0),
}
SECTOR_NAMES = ("04_MIDWEST_CAMPUS", "05_MIDEAST_CAMPUS", "06_NORTH_SPORTS_CAMPUS")
PROXY_NAMES = {
    "Bld_Proxy_Vivekanand_Rotunda_Block",
    "Bld_Proxy_Dhruv_Pharmacy_Block",
    "Bld_Proxy_Aryabhata_Block",
    "Bld_Proxy_Chanakya_Admission_Center",
    "Bld_Proxy_Sports_Complex_Main",
    "Bld_Proxy_Playground_Surface",
    "Bld_Proxy_Basketball_Court",
}


def ensure_setup() -> None:
    if any(bpy.data.collections.get(name) is None for name in SECTOR_NAMES):
        path = Path(__file__).resolve().with_name("setup_3d_campus_scene.py")
        if not path.is_file():
            raise FileNotFoundError(f"Required scene setup script not found: {path}")
        print(f"Sector collections missing; initializing phase-1 scene from {path}")
        runpy.run_path(str(path), run_name="__main__")


def materials() -> dict[str, bpy.types.Material]:
    output = {}
    for name, color in MAT_COLORS.items():
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.diffuse_color = color
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = 0.28 if "Glass" in name else 0.86
            if "Glass" in name:
                bsdf.inputs["Metallic"].default_value = 0.12
        output[name] = mat
    return output


def box(name, collection, mats, parent, center, size, mat="Mat_Concrete_Plaster"):
    """Create a closed six-quad mesh box with dimensions built into vertices."""
    hx, hy, hz = (v / 2.0 for v in size)
    verts = [(-hx,-hy,-hz),(hx,-hy,-hz),(hx,hy,-hz),(-hx,hy,-hz),
             (-hx,-hy,hz),(hx,-hy,hz),(hx,hy,hz),(-hx,hy,hz)]
    faces = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    mesh.materials.append(mats[mat])
    obj.location = center
    obj.parent = parent
    obj.scale = (1.0, 1.0, 1.0)
    obj[TAG] = True
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    return obj


def prism(name, collection, mats, parent, center, radius, height, sides=8,
          mat="Mat_Concrete_Plaster"):
    verts = []
    for z in (-height / 2, height / 2):
        verts.extend((radius * math.cos(2 * math.pi * i / sides),
                      radius * math.sin(2 * math.pi * i / sides), z) for i in range(sides))
    faces = [tuple(reversed(range(sides))), tuple(range(sides, 2 * sides))]
    faces.extend((i, (i + 1) % sides, (i + 1) % sides + sides, i + sides) for i in range(sides))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    mesh.materials.append(mats[mat])
    obj.location = center
    obj.parent = parent
    obj.scale = (1.0, 1.0, 1.0)
    obj[TAG] = True
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    return obj


def facades(prefix, collection, mats, parent, x, y, width, depth, height, floors, spacing=5.0):
    floor_h = height / floors
    ww, wh = min(2.2, spacing * 0.58), min(1.75, floor_h * 0.5)
    for floor in range(floors):
        z = (floor + 0.58) * floor_h
        for side, sy in (("South", y-depth/2+0.19), ("North", y+depth/2-0.19)):
            count = max(1, int(width // spacing))
            for i in range(count):
                wx = x - (count-1)*spacing/2 + i*spacing
                box(f"{prefix}_{side}_F{floor+1:02d}_Window_{i+1:02d}", collection, mats, parent,
                    (wx, sy, z), (ww, 0.12, wh), "Mat_Glass_Tinted")
        count = max(1, int(depth // spacing))
        for side, sx in (("West", x-width/2+0.19), ("East", x+width/2-0.19)):
            for i in range(count):
                wy = y - (count-1)*spacing/2 + i*spacing
                box(f"{prefix}_{side}_F{floor+1:02d}_Window_{i+1:02d}", collection, mats, parent,
                    (sx, wy, z), (0.12, ww, wh), "Mat_Glass_Tinted")
    for f in range(1, floors):
        box(f"{prefix}_Floor_Band_{f:02d}", collection, mats, parent,
            (x, y, f*floor_h), (width+0.16, depth+0.16, 0.16), "Mat_Roof_Concrete")


def parapet(prefix, collection, mats, parent, x, y, w, d, roof_z, h=1.2):
    t = 0.22
    for side, center, size in (
        ("South", (x, y-d/2, roof_z+h/2), (w, t, h)),
        ("North", (x, y+d/2, roof_z+h/2), (w, t, h)),
        ("West", (x-w/2, y, roof_z+h/2), (t, d, h)),
        ("East", (x+w/2, y, roof_z+h/2), (t, d, h)),
    ):
        box(f"{prefix}_Parapet_{side}", collection, mats, parent, center, size, "Mat_Roof_Concrete")


def block(prefix, collection, mats, parent, x, y, w, d, h, floors):
    box(f"{prefix}_Massing", collection, mats, parent, (x,y,h/2), (w,d,h))
    facades(prefix, collection, mats, parent, x,y,w,d,h,floors)
    parapet(prefix, collection, mats, parent, x,y,w,d,h)


def rotunda_dome(collection, mats, parent, x, y, zbase, radius=10.0, dome_h=5.0):
    """Octagonal glazed dome as eight quad panels over a faceted lower ring."""
    n = 8
    verts = []
    rings = ((radius, zbase), (radius*0.72, zbase+dome_h*0.68), (radius*0.25, zbase+dome_h))
    for r, z in rings:
        verts.extend((r*math.cos(2*math.pi*i/n), r*math.sin(2*math.pi*i/n), z) for i in range(n))
    faces = []
    for ring in range(2):
        lo, hi = ring*n, (ring+1)*n
        faces.extend((lo+i, lo+(i+1)%n, hi+(i+1)%n, hi+i) for i in range(n))
    faces.append(tuple(range(2*n, 3*n)))
    mesh = bpy.data.meshes.new("Vivekanand_Octagonal_Dome_Glazing_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Vivekanand_Octagonal_Dome_Glazing", mesh)
    collection.objects.link(obj)
    mesh.materials.append(mats["Mat_Glass_Tinted"])
    obj.location = (x,y,0)
    obj.parent = parent
    obj.scale = (1,1,1)
    obj[TAG] = True
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    # Dark metal ribs trace the eight meridians and octagonal rings.
    for ring_index, (r,z) in enumerate(rings[:2]):
        for i in range(n):
            a = 2*math.pi*i/n
            box(f"Vivekanand_Dome_Ring_{ring_index}_{i}", collection, mats, parent,
                (x+r*math.cos(a), y+r*math.sin(a), z), (0.16,0.16,0.16), "Mat_Metal_Dark")
    for i in range(n):
        a = 2*math.pi*i/n
        p0 = (x+radius*math.cos(a), y+radius*math.sin(a), zbase)
        p1 = (x+radius*0.72*math.cos(a), y+radius*0.72*math.sin(a), zbase+dome_h*0.68)
        p2 = (x+radius*0.25*math.cos(a), y+radius*0.25*math.sin(a), zbase+dome_h)
        for part, (p,q) in enumerate(((p0,p1),(p1,p2))):
            dx,dy,dz = q[0]-p[0],q[1]-p[1],q[2]-p[2]
            length = math.sqrt(dx*dx+dy*dy+dz*dz)
            rib = box(f"Vivekanand_Dome_Meridian_{i}_{part}", collection, mats, parent,
                      tuple((p[j]+q[j])/2 for j in range(3)), (0.13,0.13,length), "Mat_Metal_Dark")
            rib.rotation_euler[1] = math.atan2(dx, dz)
            rib.rotation_euler[0] = -math.atan2(dy, math.sqrt(dx*dx+dz*dz))


def model_vivekanand(c, m, root):
    x,y,w,d,h = -80.0,50.0,40.0,40.0,16.0
    block("Vivekanand",c,m,root,x,y,w,d,h,4)
    # Central 20 m glass dome rises above the flat block roof.
    box("Vivekanand_Dome_Curb",c,m,root,(x,y,h+0.35),(21.0,21.0,0.7),"Mat_Roof_Concrete")
    rotunda_dome(c,m,root,x,y,h+0.7,10.0,5.0)
    # Four radial entry projections at the cardinal sides.
    entries = (("North",(x,y+d/2+2.0,1.8),(9.0,4.0,3.6)),
               ("South",(x,y-d/2-2.0,1.8),(9.0,4.0,3.6)),
               ("East",(x+w/2+2.0,y,1.8),(4.0,9.0,3.6)),
               ("West",(x-w/2-2.0,y,1.8),(4.0,9.0,3.6)))
    for side,center,size in entries:
        box(f"Vivekanand_{side}_Entry_Projection",c,m,root,center,size,"Mat_Brick_Red")
        box(f"Vivekanand_{side}_Entry_Glazing",c,m,root,
            (center[0],center[1],1.65),(size[0]*0.62,0.12,2.7),"Mat_Glass_Tinted")


def model_dhruv(c,m,root):
    x,y,w,d,h = -90.0,110.0,60.0,20.0,16.0
    block("Dhruv_Pharmacy",c,m,root,x,y,w,d,h,4)
    box("Dhruv_Pharmacy_Main_Entrance",c,m,root,(x,y-d/2-0.08,1.5),(5.0,0.16,3.0),"Mat_Glass_Tinted")
    box("Dhruv_Pharmacy_Entrance_Canopy",c,m,root,(x,y-d/2-1.6,3.4),(9.0,3.0,0.4),"Mat_Roof_Concrete")


def model_aryabhata(c,m,root):
    # Three joined wings form a U open to the south, within 65 x 45 m.
    x,y,w,d,h = 45.0,60.0,65.0,45.0,16.0
    wing = 15.0
    # North bar spans full width; two side wings continue south from it.
    parts = (("North_Wing",x,y+d/2-wing/2,w,wing),
             ("West_Wing",x-w/2+wing/2,y-wing/2,wing,d-wing),
             ("East_Wing",x+w/2-wing/2,y-wing/2,wing,d-wing))
    for suffix,px,py,pw,pd in parts:
        block(f"Aryabhata_{suffix}",c,m,root,px,py,pw,pd,h,4)
    # Inner quadrangle floor is a lower paved court, open to the south.
    courtyard_w, courtyard_d = w-2*wing, d-wing
    box("Aryabhata_Inner_Courtyard_Paving",c,m,root,
        (x,y-wing/2,0.025),(courtyard_w,courtyard_d,0.05),"Mat_Roof_Concrete")
    # Arcade columns line the three courtyard-facing ground-floor elevations.
    for i in range(11):
        px=x-courtyard_w/2+2+i*(courtyard_w-4)/10
        box(f"Aryabhata_Arcade_North_Column_{i+1:02d}",c,m,root,
            (px,y+d/2-wing-0.3,1.85),(0.55,0.55,3.7),"Mat_Roof_Concrete")
    for side,sx in (("West",x-w/2+wing+0.35),("East",x+w/2-wing-0.35)):
        for i in range(6):
            py=y-wing/2-i*3.7
            box(f"Aryabhata_Arcade_{side}_Column_{i+1:02d}",c,m,root,
                (sx,py,1.85),(0.55,0.55,3.7),"Mat_Roof_Concrete")
    # Covered arcade lintel around the inside court edge.
    box("Aryabhata_Arcade_North_Lintel",c,m,root,
        (x,y+d/2-wing-0.3,3.75),(courtyard_w,0.8,0.3),"Mat_Roof_Concrete")
    for side,sx in (("West",x-w/2+wing+0.35),("East",x+w/2-wing-0.35)):
        box(f"Aryabhata_Arcade_{side}_Lintel",c,m,root,
            (sx,y-wing/2-d/4+wing/4,3.75),(0.8,d-wing,0.3),"Mat_Roof_Concrete")


def model_chanakya(c,m,root):
    x,y,w,d,h=35.0,110.0,50.0,22.0,16.0
    block("Chanakya_Admission_Center",c,m,root,x,y,w,d,h,4)
    # Full-height entrance curtain wall as a low-poly projecting glazed bay.
    box("Chanakya_Curtain_Wall_Projection",c,m,root,
        (x,y-d/2-0.65,h/2),(w*0.72,1.3,h*0.86),"Mat_Glass_Tinted")
    box("Chanakya_Curtain_Wall_Canopy",c,m,root,
        (x,y-d/2-1.8,h*0.88),(w*0.82,3.8,0.45),"Mat_Roof_Concrete")
    for i in range(13):
        px=x-w*0.36+i*(w*0.72/12)
        box(f"Chanakya_Curtain_Wall_Mullion_{i+1:02d}",c,m,root,
            (px,y-d/2-1.32,h/2),(0.12,0.12,h*0.86),"Mat_Metal_Dark")


def sloped_ramp(name,c,m,root,x,y,length,width,z_top,z_bottom):
    """Closed ramp slab with quad top, bottom, and side faces."""
    verts=[(-width/2,-length/2,0),(width/2,-length/2,0),(width/2,length/2,0),(-width/2,length/2,0),
           (-width/2,-length/2,0.35),(width/2,-length/2,0.35),
           (width/2,length/2,z_top-z_bottom+0.35),(-width/2,length/2,z_top-z_bottom+0.35)]
    faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    mesh=bpy.data.meshes.new(f"{name}_Mesh"); mesh.from_pydata(verts,[],faces); mesh.update()
    obj=bpy.data.objects.new(name,mesh); c.objects.link(obj); mesh.materials.append(m["Mat_Roof_Concrete"])
    obj.location=(x,y,z_bottom); obj.parent=root; obj.scale=(1,1,1); obj[TAG]=True
    for edge in mesh.edges: edge.use_edge_sharp=True
    return obj


def model_sports(c,m,root):
    x,y,w,d,h=50.0,170.0,45.0,25.0,15.0
    block("Sports_Complex_Main",c,m,root,x,y,w,d,h,3)
    # Sports-hall volume projects from the east façade, with clerestory glazing.
    box("Sports_Complex_Hall_Extrusion",c,m,root,(x+w/2+6.0,y,7.0),(12.0,19.0,14.0),"Mat_Brick_Red")
    for i in range(5):
        py=y-8+i*4
        box(f"Sports_Complex_Hall_Clerestory_{i+1}",c,m,root,
            (x+w/2+12.05,py,10.0),(0.12,2.2,2.0),"Mat_Glass_Tinted")
    # West descending vehicle ramp toward underground parking, with retaining walls.
    rx,ry=x-w/2-13.0,y
    sloped_ramp("Sports_Complex_West_Parking_Ramp",c,m,root,rx,ry,24.0,7.0,0.0,-3.0)
    for side,dx in (("West",-3.8),("East",3.8)):
        box(f"Sports_Complex_Ramp_{side}_Retaining_Wall",c,m,root,
            (rx+dx,ry,-0.25),(0.45,24.0,3.5),"Mat_Concrete_Plaster")
    box("Sports_Complex_Parking_Entry_Header",c,m,root,
        (rx,ry+12.0,2.0),(8.0,0.6,4.0),"Mat_Roof_Concrete")


def model_playground(c,m,root):
    x,y,w,d=50.0,220.0,110.0,70.0
    box("Playground_Surface_Slab",c,m,root,(x,y,0.05),(w,d,0.1),"Mat_Turf_Green")
    curb_h,curb_t=0.25,0.4
    for side,center,size in (
        ("South",(x,y-d/2,0.175),(w,curb_t,curb_h)),
        ("North",(x,y+d/2,0.175),(w,curb_t,curb_h)),
        ("West",(x-w/2,y,0.175),(curb_t,d,curb_h)),
        ("East",(x+w/2,y,0.175),(curb_t,d,curb_h)),
    ):
        box(f"Playground_Track_Curb_{side}",c,m,root,center,size,"Mat_Roof_Concrete")


def model_basketball(c,m,root):
    x,y,w,d=10.0,270.0,28.0,15.0
    box("Basketball_Court_Synthetic_Slab",c,m,root,(x,y,0.05),(w,d,0.1),"Mat_Court_Blue")
    # 4 m perimeter fence: square-tube rails/posts and low-poly mesh infill.
    z0,z1=0.15,4.15
    for side,center,size in (
        ("South",(x,y-d/2,z1),(w,0.12,0.12)),("North",(x,y+d/2,z1),(w,0.12,0.12)),
        ("West",(x-w/2,y,z1),(0.12,d,0.12)),("East",(x+w/2,y,z1),(0.12,d,0.12)),
        ("South_Bottom",(x,y-d/2,z0),(w,0.12,0.12)),("North_Bottom",(x,y+d/2,z0),(w,0.12,0.12)),
        ("West_Bottom",(x-w/2,y,z0),(0.12,d,0.12)),("East_Bottom",(x+w/2,y,z0),(0.12,d,0.12)),
    ):
        box(f"Basketball_Fence_Rail_{side}",c,m,root,center,size,"Mat_Metal_Dark")
    post_index=0
    for side,axis_length,base in (("South",w,(x-w/2,y-d/2)),("North",w,(x-w/2,y+d/2)),
                                   ("West",d,(x-w/2,y-d/2)),("East",d,(x+w/2,y-d/2))):
        count=int(axis_length//3.5)
        for i in range(count+1):
            t=min(i*3.5,axis_length)
            px,py=(base[0]+t,base[1]) if side in ("South","North") else (base[0],base[1]+t)
            box(f"Basketball_Fence_Post_{post_index:02d}",c,m,root,(px,py,2.15),
                (0.1,0.1,4.0),"Mat_Metal_Dark")
            post_index+=1
    # Fine vertical wire proxies in alternating dark metal, spaced 0.6 m.
    for side in ("South","North"):
        fy=y+(-d/2 if side=="South" else d/2)
        for i in range(1,47):
            fx=x-w/2+i*0.6
            box(f"Basketball_Fence_Mesh_{side}_{i:02d}",c,m,root,(fx,fy,2.15),
                (0.025,0.025,3.85),"Mat_Metal_Dark")
    for side in ("West","East"):
        fx=x+(-w/2 if side=="West" else w/2)
        for i in range(1,25):
            fy=y-d/2+i*0.6
            box(f"Basketball_Fence_Mesh_{side}_{i:02d}",c,m,root,(fx,fy,2.15),
                (0.025,0.025,3.85),"Mat_Metal_Dark")


def model_north_blocks(c,m,root):
    specs=(("Mahaveer_Block",-25.0,300.0),("Raman_Block",20.0,300.0),("Shastri_Block",65.0,300.0))
    for name,x,y in specs:
        block(name,c,m,root,x,y,35.0,18.0,16.0,4)
        # South-facing portico, glass entry and paired supports.
        box(f"{name}_South_Entrance",c,m,root,(x,y-9.05,1.5),(5.0,0.14,3.0),"Mat_Glass_Tinted")
        box(f"{name}_Entrance_Canopy",c,m,root,(x,y-11.0,3.25),(9.0,4.0,0.5),"Mat_Roof_Concrete")
        for px in (x-3.6,x+3.6):
            box(f"{name}_Portico_Pillar_{px:.1f}",c,m,root,(px,y-12.6,1.6),
                (0.45,0.45,3.2),"Mat_Metal_Dark")


def main():
    ensure_setup()
    collections={name:bpy.data.collections[name] for name in SECTOR_NAMES}
    root=bpy.data.objects.get("Campus_Orientation_Root")
    for obj in list(bpy.data.objects):
        if obj.get(TAG):
            bpy.data.objects.remove(obj,do_unlink=True)
    for name in PROXY_NAMES:
        obj=bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj,do_unlink=True)
    m=materials()
    model_vivekanand(collections["04_MIDWEST_CAMPUS"],m,root)
    model_dhruv(collections["04_MIDWEST_CAMPUS"],m,root)
    model_aryabhata(collections["05_MIDEAST_CAMPUS"],m,root)
    model_chanakya(collections["05_MIDEAST_CAMPUS"],m,root)
    north=collections["06_NORTH_SPORTS_CAMPUS"]
    model_sports(north,m,root)
    model_playground(north,m,root)
    model_basketball(north,m,root)
    model_north_blocks(north,m,root)
    world=bpy.context.scene.world
    if world and world.use_nodes:
        sky=next((n for n in world.node_tree.nodes if n.bl_idname=="ShaderNodeTexSky"),None)
        if sky and sky.sky_type=="MULTIPLE_SCATTERING" and abs(sky.air_density-1.2)<1e-6:
            print("Preserved multiple-scattering sky and air_density=1.2.")
    print("Sector C, D, and E architectural and sports geometry generated successfully.")


if __name__ == "__main__":
    main()
