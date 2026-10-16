# MIT-WPU Campus 3D Modeling Specification & Master Technical Blueprint

This document serves as the complete technical specification and execution strategy for recreating the **MIT World Peace University (MIT-WPU), Kothrud, Pune** campus as an accurate, production-ready 3D environment in **Blender**.

---

## 1. Global Scene Calibration & Reference System

### 1.1 Scale & Unit Settings
* **Unit System:** Metric
* **Length Unit:** Meters
* **Scale Factor:** $1.0\text{ Blender Unit (BU)} = 1.0\text{ Meter (m)}$
* **Grid Scale:** $1.0\text{ m}$ (Subdivisions: 10 for $0.1\text{ m}$ grid snap)
* **Default Human Reference Height:** $1.75\text{ m}$ (for scale verification)

### 1.2 Geolocation & Orientation
* **Location:** Kothrud, Pune, Maharashtra, India
* **GPS Coordinates:** $18.5181^\circ\text{ N}, 73.8153^\circ\text{ E}$
* **Elevation:** $\sim 560\text{ meters above sea level}$
* **True North Alignment:**
  * The main campus entry road running from **Main Gate** (South) to the **Sports Complex** (North) runs approximately **$18^\circ$ East of True North**.
  * Blender World Axis: $+Y = \text{True North}$, $+X = \text{True East}$, $+Z = \text{Up}$.
  * Rotate the entire master layout container by $-18^\circ$ on the Z-axis if modeling on a grid-aligned local axis.

### 1.3 Real-World Dimension Standardization Guide
When converting real-world pacing or laser measurements to 3D geometry:
* **Average Walking Pace:** $1\text{ Pace} \approx 0.75\text{ meters}$
* **Standard Door Dimension:** $1.2\text{ m} \times 2.1\text{ m}$ (Double doors: $2.0\text{ m} \times 2.4\text{ m}$)
* **Floor-to-Floor Height (Academic Blocks):** $3.8\text{ m}$ to $4.2\text{ m}$
* **Window Sill Height:** $0.9\text{ m}$ from floor level
* **Standard Window Height:** $1.5\text{ m}$ to $2.0\text{ m}$
* **Stair Riser / Tread:** Riser $= 0.15\text{ m}$, Tread $= 0.30\text{ m}$
* **Road Width (Main Spine):** $8.0\text{ m} - 10.0\text{ m}$ wide asphalt track
* **Pavement / Sidewalk Width:** $1.5\text{ m} - 2.5\text{ m}$ wide with $0.15\text{ m}$ curb height

---

## 2. Complete Campus Spatial Inventory & Structural Specifications

The campus is divided into 5 primary sectors based on the site map layout.

```
       [ North Sector: Sports Complex, Raman, Mahaveer, Gate 3 ]
                                  |
    [ Mid-West Sector: Dhruv,   ] | [ Mid-East Sector: Aryabhata, ]
    [ Vivekanand, Vishwamitra   ] | [ Chanakya, Cafeteria 2       ]
                                  |
    [ Central Sector: Dnyaneshwar,] | [ Central-East Sector:       ]
    [ Vashistha, Lawns, Gate 2  ] | [ Tyagaraja, Bharata        ]
                                  |
       [ South Sector: Main Gate, Saraswati, Ganga, Agastya ]
```

---

### Sector A: South Campus (Entrance & Administrative Zone)

#### 1. Main Gate Structure & Boundary Wall
* **Location:** Southernmost anchor of the campus.
* **Footprint:** $18.0\text{ m (W)} \times 4.0\text{ m (D)} \times 6.5\text{ m (H)}$
* **Floors:** 1 (Archway Gatehouse)
* **Gates:** 1 Primary vehicular entry (4 lanes total), 2 pedestrian side gates.
* **Architectural Details:** Security cabins on left and right, grand entrance arch with LED backlit university sign, boom barriers.

#### 2. Vishwakarma Block
* **Position:** Immediately south-west of Main Gate (outside main perimeter road).
* **Footprint:** $45.0\text{ m} \times 22.0\text{ m}$
* **Floors:** 4 Floors ($\sim 16.0\text{ m}$ total height)
* **Entry/Exit:** 1 Main entrance on the North façade facing the Main Gate road.
* **Primitive Blockout:** Large rectangular cuboid with 2 recessed stairwell towers on the end wings.

#### 3. Saraswati & Ganga Block (H-Shaped Sprawling Complex)
* **Position:** North of Main Gate, flanking the central main spine road.
* **Footprint:** Combined $85.0\text{ m (W)} \times 35.0\text{ m (D)}$
* **Floors:** 5 Floors ($\sim 20.0\text{ m}$ total height)
* **Entry/Exit:** 2 Primary entries (West façade facing road, East courtyard entrance).
* **Architectural Details:** Interconnected wings forming an 'H' or 'U' shape around an internal courtyard, large rectangular glass grid windows, flat concrete roof with HVAC units.

#### 4. Sherai Canteen & Abraham Block
* **Position:** West of Saraswati/Ganga Block.
* **Footprint:** Canteen $25.0\text{ m} \times 18.0\text{ m}$; Abraham Block $30.0\text{ m} \times 15.0\text{ m}$
* **Floors:** Canteen (2 Floors); Abraham Block (3 Floors)
* **Entry/Exit:** Ground-floor outdoor seating patio and side service doors.

#### 5. Mankikar & Executive / Admission Office Complex
* **Position:** East of the Main Spine Road, opposite Saraswati Block.
* **Footprint:** $40.0\text{ m} \times 25.0\text{ m}$
* **Floors:** 3 Floors ($\sim 12.5\text{ m}$ height)
* **Entry/Exit:** West-facing glass entrance door with covered porch/portico.

#### 6. Agastya Lawns & Agastya Student Service Center
* **Position:** West of Main Spine Road, between Saraswati and Dnyaneshwar blocks.
* **Lawns Area:** $\sim 1,200\text{ m}^2$ ($40.0\text{ m} \times 30.0\text{ m}$)
* **Service Center Footprint:** Circular dome structure ($18.0\text{ m}$ diameter).

---

### Sector B: Central Campus (Academic & Central Lawns)

#### 7. Dnyaneshwar Block
* **Position:** West side of central lawn axis.
* **Footprint:** $65.0\text{ m (L)} \times 22.0\text{ m (W)}$
* **Floors:** 5 Floors ($\sim 20.0\text{ m}$ total height)
* **Entry/Exit:** 3 Entrances (East façade opening onto Dnyaneshwar Lawns 1 & 2, North side exit, South fire exit).
* **Architectural Details:** Signature rotunda/octagonal central pavilion on the West wing, recurring concrete pillar colonnade along ground floor walkway.

#### 8. Dnyaneshwar Lawns 1 & 2
* **Position:** Directly in front of Dnyaneshwar Block.
* **Area:** $2,500\text{ m}^2$ combined ($50.0\text{ m} \times 50.0\text{ m}$). Divided into two equal green patches by a $3.0\text{ m}$ wide paved walkway.

#### 9. Vashistha Block & Vashistha Lawns / Kriti Lawns
* **Position:** East side of central lawn axis, mirroring Dnyaneshwar Block.
* **Footprint:** $70.0\text{ m (L)} \times 24.0\text{ m (W)}$
* **Floors:** 5 Floors ($\sim 20.0\text{ m}$ height)
* **Entry/Exit:** West façade primary double-door entrance facing Vashistha Lawns.
* **Lawns Area:** Vashistha Lawns ($\sim 1,100\text{ m}^2$), Kriti Lawns ($\sim 1,000\text{ m}^2$).

#### 10. Jamadagni Block & Enclave Cafeteria 1
* **Position:** North boundary of the central lawns, running East-West.
* **Footprint:** $55.0\text{ m (W)} \times 16.0\text{ m (D)}$
* **Floors:** 3 Floors ($\sim 12.0\text{ m}$ height)
* **Entry/Exit:** South-facing entrance with outdoor cafeteria canopy and seating area.

#### 11. Avanti, Atri, Gargi & Varahi Blocks
* **Position:** Ribbon blocks south of Dnyaneshwar and Vashistha lawn complex.
* **Footprints:** Linear blocks ranging from $30.0\text{ m} \times 12.0\text{ m}$ to $40.0\text{ m} \times 14.0\text{ m}$.
* **Floors:** 2 to 3 Floors.

#### 12. Tyagaraja & Bharata Blocks (East Boundary)
* **Position:** Eastern edge of Central Campus near Cast Gate (Gate 2).
* **Footprint:** $45.0\text{ m (L)} \times 15.0\text{ m (W)}$ each.
* **Floors:** 4 Floors.
* **Entry/Exit:** Gate 2 (Cast Gate) connects directly to the residential colony road via this corridor.

---

### Sector C: Mid-West Campus (Polytechnic, Pharmacy & Domes)

#### 13. Vivekanand Block (Central Rotunda)
* **Position:** West-Central sector.
* **Footprint:** $40.0\text{ m} \times 40.0\text{ m}$ with a central $20.0\text{ m}$ octagonal dome structure.
* **Floors:** 4 Floors
* **Entry/Exit:** 4 Radial entrances facing North, South, East, West.
* **Architectural Signature:** Large glass octagonal dome roof with geometric steel lattice pattern.

#### 14. Vishwamitra & Kashyap Blocks
* **Position:** Adjacent to Vivekanand Block.
* **Footprints:** $35.0\text{ m} \times 16.0\text{ m}$ each.
* **Floors:** 4 Floors.

#### 15. Dhruv Block & Dhruv Pharmacy
* **Position:** Far North-West corner of the mid-campus zone.
* **Footprint:** $60.0\text{ m} \times 20.0\text{ m}$ elongated rectangular geometry.
* **Floors:** 4 Floors.
* **Lawns:** Dhruv Lawns 1 & 2 ($\sim 1,500\text{ m}^2$ total).

---

### Sector D: Mid-East Campus (Innovation & Classrooms)

#### 16. Aryabhata, Gautama, Maitreyi & Anasuya Blocks
* **Position:** East of the main road corridor, opposite Vishwamitra Block.
* **Footprint Cluster:** Interconnected 'U' shape spanning $65.0\text{ m} \times 45.0\text{ m}$.
* **Floors:** 4 to 5 Floors.
* **Entry/Exit:** Inner quadrangle courtyard entrance with covered arcades.

#### 17. Chanakya Block (Admission Centre) & Enclave Cafeteria 2
* **Position:** North of Aryabhata Block.
* **Footprint:** $50.0\text{ m} \times 22.0\text{ m}$.
* **Floors:** 4 Floors.

---

### Sector E: North Campus & Sports Complex

#### 18. University Sports Complex & Underground Parking
* **Position:** Large landmark structure on the East-North quadrant.
* **Footprint:** Ground Field ($110.0\text{ m} \times 70.0\text{ m}$); Sports Building ($45.0\text{ m} \times 25.0\text{ m}$).
* **Floors:** 3 Above-ground sports levels + 2 Underground parking basements.
* **Entry/Exit:** West ramp for underground vehicle parking, North & South main sports pavilion stairs.

#### 19. Urja Innovation Center
* **Position:** West border of the Sports Playground.
* **Footprint:** Elongated structure ($55.0\text{ m} \times 14.0\text{ m}$).
* **Floors:** 3 Floors.

#### 20. Dronacharya Sports Complex
* **Position:** South-East corner of the main playground.
* **Footprint:** $30.0\text{ m} \times 20.0\text{ m}$.
* **Floors:** 2 Floors.

#### 21. Mahaveer, Raman & Shastri Blocks
* **Position:** Northernmost campus boundary.
* **Footprints:** $35.0\text{ m} \times 18.0\text{ m}$ each.
* **Floors:** 4 Floors.

#### 22. Gate 3 (Melek Gate) & Basketball Court
* **Position:** North-East corner of campus.
* **Basketball Court:** Standard $28.0\text{ m} \times 15.0\text{ m}$ synthetic court with green/blue surface coating and perimeter chain-link fence ($4.0\text{ m}$ height).

---

## 3. Blockout Strategy (Primitives to Detailed Geometry)

To avoid performance bottlenecks and maintain correct global scale, strictly follow a **3-Phase Modeling Workflow**:

```
[ Phase 1: Bounding Primitives ] ──> [ Phase 2: Modular Assembly ] ──> [ Phase 3: Hero Detailing ]
  - Simple Cubes & Cylinders           - Snap Window/Door Modules        - Gutters, Cables, Wear
  - Match Footprint & Heights          - Apply Array & Mirror Modifiers  - Micro-Displacement
```

1. **Phase 1: Bounding Blockout**
   * Create low-poly primitive cubes for every building using exact meter dimensions from Section 2.
   * Position blocks according to relative spacing on the site grid.
   * Verify sightlines, corridor widths, and lawn boundaries.

2. **Phase 2: Modular Wall & Facade Assembly**
   * Cut loop-cuts at floor heights ($3.8\text{ m}$ increments).
   * Extrude window recesses ($0.2\text{ m}$ inward depth).
   * Replace wall sections with instanced modular assets (see Section 4).

3. **Phase 3: Roof & Ground Connection Detailing**
   * Add parapet walls ($1.2\text{ m}$ height on roofs).
   * Model roof infrastructure: Water tanks, HVAC chiller units, solar panels, elevator machine rooms.
   * Add stair landings and ground ramp transitions.

---

## 4. Modular Asset Architecture & Instancing

Do **NOT** manually model repeating architectural features. Create a `MODULAR_KIT` collection containing master assets and duplicate them using **Linked Duplicates** (`Alt + D`) or **Array Modifiers**.

### Modular Kit Asset Catalog

| Asset Name | Dimensions ($W \times D \times H$) | Description / Usage |
| :--- | :--- | :--- |
| `Mod_Window_Standard` | $1.5\text{ m} \times 0.2\text{ m} \times 1.8\text{ m}$ | Aluminum double-pane glass window frame. |
| `Mod_Window_Large_Curtain` | $3.0\text{ m} \times 0.2\text{ m} \times 3.5\text{ m}$ | Floor-to-ceiling tinted glass wall module for Saraswati / Chanakya blocks. |
| `Mod_Door_Double_Glass` | $2.0\text{ m} \times 0.2\text{ m} \times 2.4\text{ m}$ | Main entry door with push handles and overhead sensor. |
| `Mod_Pillar_Square` | $0.6\text{ m} \times 0.6\text{ m} \times 3.8\text{ m}$ | Structural concrete support pillar for ground floor corridors. |
| `Mod_Pillar_Round` | $0.5\text{ m}\text{ Ø} \times 3.8\text{ m}$ | Cylindrical pillar for rotunda/pavilion sections. |
| `Mod_Balcony_Railing` | $2.0\text{ m} \times 0.1\text{ m} \times 1.1\text{ m}$ | Stainless steel + glass panel railing segment. |
| `Mod_Stair_Flight` | $1.8\text{ m} \times 3.6\text{ m} \times 1.8\text{ m}$ | Standard 12-step fire stair flight with handrails. |

---

## 5. Photogrammetry & PBR Texture Guidelines

### 5.1 On-Site Photography Protocol for PBR Generation
* **Lighting Condition:** Shoot strictly on an **overcast day** (flat diffuse light) or during shade to eliminate baked direct shadows and specular highlights.
* **Camera Angle:** Flat, $90^\circ$ perpendicular orientation to the target surface.
* **Resolution:** Minimum $4096 \times 4096\text{ pixels}$ per texture tile.

### 5.2 Material Map Specifications

#### Wall Concrete / Plaster Surface
* **Base Color (Albedo):** Off-white / light beige paint (#E6E2D8), light yellow accents for specific blocks.
* **Roughness Map:** High roughness ($0.75 - 0.88$), driven by fine noise texture for matte plaster finish.
* **Normal Map:** Subtle brick/concrete grain map ($0.2\text{ strength}$).

#### Exterior Red Brick Accent Walls
* **Base Color:** Deep terracotta red/orange (#8B3A2B).
* **Roughness Map:** $0.85$ (dry porous clay texture).
* **Normal / Displacement Map:** Mortar depth inlay ($0.015\text{ m}$ depth displacement for physical depth).

#### Facade Tinted Window Glass
* **Base Color:** Dark slate gray / deep blue tint (#1C2833).
* **Roughness Map:** Low roughness ($0.05 - 0.1$).
* **Metallic Map:** $0.1$ (for slight metallic mirror coating reflection).
* **Transmission / IOR:** Transmission $= 0.85$, $\text{IOR} = 1.52$.

---

## 6. UV Unwrapping Strategy & Texel Density Plan

### 6.1 Texel Density Targets
To ensure visual consistency across close-up shots and wide aerial renders:
* **Hero Buildings & Ground Level Doors/Windows:** $1024\text{ pixels/meter}$
* **Upper Floor Facades & Roofs:** $512\text{ pixels/meter}$
* **Large Ground Lawns & Asphalt Roads:** $256\text{ pixels/meter}$ (using detail tile blending)

### 6.2 UV Rules
1. **Trim Sheets:** Use a master $4096 \times 4096$ architectural trim sheet for concrete edges, window frames, steel beams, and door headers.
2. **Seamless Tiling:** Exterior wall textures must tile infinitely along $U$ and $V$ axes without visible seams or repetitive pattern banding.
3. **World-Space UVs / Triplanar Mapping:** For large terrain and road surfaces, use Blender shader nodes with **Object/Generated Texture Coordinates** mapped through a **Mapping Node** set to **Box Blend** (blend value $= 0.2$) to eliminate unwrapping seams across vast ground areas.

---

## 7. Lighting, Environment & Rendering Setup

### 7.1 Day Sky Setup (Cycles & EEVEE)
* **Sun & Sky Texture:** Blender `Nishita` Sky Model.
  * **Sun Elevation:** $45^\circ$ (Mid-morning daylight, sharp structural shadows).
  * **Sun Rotation:** $210^\circ$ (South-West angle to highlight facade depths).
  * **Sun Size:** $0.545^\circ$ (Crisp realistic shadow edges).
  * **Air Dust / Ozone:** Dust $= 1.2$, Ozone $= 2.0$.

### 7.2 Golden Hour Setup (Alternative Scene Slot)
* **Sun Elevation:** $8^\circ$ above horizon.
* **HDRI map:** 8K Warm Sunset HDRI connected to World Surface background ($1.2\text{ strength}$).

### 7.3 Artificial Night Lighting Setup
* **Street Lamps:** Point lights ($3000\text{K}$ warm yellow, $150\text{ Watts}$) spaced every $15.0\text{ m}$ along main roads.
* **Interior Window Glow:** Assign a material slot `Mat_Window_Emission` to $20\%$ of windows with a procedural noise mask controlling `Emission Strength` ($2.0 - 8.0$) to simulate active classrooms at night.

---

## 8. Foliage & Landscape Assets Catalog

| Asset Category | Species / Type | Height / Spread | Placement Locations |
| :--- | :--- | :--- | :--- |
| **Large Trees** | Gulmohar (*Delonix regia*) | $10\text{ m} - 12\text{ m}$ height | Main entry road, around Dnyaneshwar Lawns. |
| **Shade Trees** | Neem (*Azadirachta indica*) | $8\text{ m} - 10\text{ m}$ height | Perimeter boundaries, near Gate 2 & 3. |
| **Palm Trees** | Royal Palm (*Roystonea regia*) | $12\text{ m} - 15\text{ m}$ height | Lining central lawn walkways. |
| **Low Hedges** | Boxwood / Privet Bush | $0.8\text{ m}$ height | Surrounding Agastya & Vashistha lawn borders. |
| **Grass Lawn** | Bermuda Grass Mesh / Particle System | $0.05\text{ m}$ blade height | Dnyaneshwar, Vashistha, Agastya, Dhruv lawns. |

---

## 9. Realism Pass: Micro-Details & Imperfection Map

Realism is achieved through subtle structural imperfections:
1. **Dirt Leaks Under Windows:**
   * Blend an Ambient Occlusion (AO) node with a vertical procedural noise overlay to map dark grime streaks extending $0.5\text{ m} - 1.2\text{ m}$ downwards from window sills.
2. **Road Cracks & Asphalt Potholes:**
   * Overlay a subtle crack Normal map onto the main asphalt material. Add paint markings ($0.1\text{ m}$ wide yellow/white lines) with an erased edge noise filter to simulate worn road paint.
3. **Roof Equipment Infrastructure:**
   * Populate roofs with utility details: HVAC ducting tubes, water storage tanks ($2.0\text{ m}$ height blue cylinders), solar panel racks, satellite dishes, exhaust fans, drainage pipes running vertically down outer walls.
4. **Street Furniture Prop List:**
   * Plastic green/blue trash bins outside cafeterias.
   * Concrete benches along lawn paths.
   * Campus orientation signboards and speed limit signs ($20\text{ km/h}$).
   * Bicycle parking racks near entry gates.

---

## 10. Automated Blender Python (`bpy`) Scene Initialization Script

Run the following Python script inside Blender's Text Editor to automatically configure the unit scale, build the organized collection hierarchy, construct sky lighting, and generate bounding blockout proxies for key campus blocks.

```python
import bpy
import math

def setup_mit_wpu_campus():
    # -------------------------------------------------------------
    # 1. SCENE SCALE & UNITS SETUP
    # -------------------------------------------------------------
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0  # 1 BU = 1 Meter
    scene.unit_settings.length_unit = 'METERS'
    
    # Set view clipping distance for large scale campus
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_start = 0.1
                    space.clip_end = 2000.0

    # -------------------------------------------------------------
    # 2. CREATE COLLECTION HIERARCHY
    # -------------------------------------------------------------
    collections_structure = [
        "01_TERRAIN_ROADS",
        "02_SOUTH_CAMPUS",
        "03_CENTRAL_CAMPUS",
        "04_MIDWEST_CAMPUS",
        "05_MIDEAST_CAMPUS",
        "06_NORTH_SPORTS_CAMPUS",
        "07_MODULAR_KIT",
        "08_FOLIAGE_LANDSCAPE",
        "09_PROPS_STREET_FURNITURE",
        "10_LIGHTING_ENVIRONMENT"
    ]
    
    created_collections = {}
    master_collection = scene.collection
    
    for coll_name in collections_structure:
        if coll_name not in bpy.data.collections:
            new_coll = bpy.data.collections.new(coll_name)
            master_collection.children.link(new_coll)
            created_collections[coll_name] = new_coll
        else:
            created_collections[coll_name] = bpy.data.collections[coll_name]

    # -------------------------------------------------------------
    # 3. BASE TERRAIN PLANE CREATION
    # -------------------------------------------------------------
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, 0))
    terrain = bpy.context.active_object
    terrain.name = "Terrain_Main_Ground"
    
    # Unlink from master and link to TERRAIN collection
    master_collection.objects.unlink(terrain)
    created_collections["01_TERRAIN_ROADS"].objects.link(terrain)

    # -------------------------------------------------------------
    # 4. BUILDING BLOCKOUT PROXIES (Location X, Y, Size X, Y, Z)
    # -------------------------------------------------------------
    building_proxies = [
        # South Sector
        ("Saraswati_Ganga_Block", "02_SOUTH_CAMPUS", (-30, -100, 10), (85, 35, 20)),
        ("Mankikar_Office_Block", "02_SOUTH_CAMPUS", (40, -100, 6.25), (40, 25, 12.5)),
        ("Main_Gate_Structure", "02_SOUTH_CAMPUS", (0, -160, 3.25), (18, 4, 6.5)),
        
        # Central Sector
        ("Dnyaneshwar_Block", "03_CENTRAL_CAMPUS", (-45, 0, 10), (22, 65, 20)),
        ("Vashistha_Block", "03_CENTRAL_CAMPUS", (45, 0, 10), (24, 70, 20)),
        ("Jamadagni_Block", "03_CENTRAL_CAMPUS", (0, 45, 6), (55, 16, 12)),
        
        # Mid-West Sector
        ("Vivekanand_Rotunda_Block", "04_MIDWEST_CAMPUS", (-80, 50, 8), (40, 40, 16)),
        ("Dhruv_Pharmacy_Block", "04_MIDWEST_CAMPUS", (-90, 110, 8), (60, 20, 16)),
        
        # Mid-East Sector
        ("Aryabhata_Block", "05_MIDEAST_CAMPUS", (45, 60, 8), (65, 45, 16)),
        ("Chanakya_Admission_Center", "05_MIDEAST_CAMPUS", (35, 110, 8), (50, 22, 16)),
        
        # North Sector
        ("Sports_Complex_Main", "06_NORTH_SPORTS_CAMPUS", (50, 170, 7.5), (45, 25, 15)),
        ("Playground_Surface", "06_NORTH_SPORTS_CAMPUS", (50, 220, 0.05), (110, 70, 0.1)),
        ("Basketball_Court", "06_NORTH_SPORTS_CAMPUS", (10, 270, 0.05), (28, 15, 0.1))
    ]

    for b_name, coll_target, (loc_x, loc_y, loc_z), (size_x, size_y, size_z) in building_proxies:
        bpy.ops.mesh.primitive_cube_add(location=(loc_x, loc_y, loc_z))
        cube = bpy.context.active_object
        cube.name = f"Bld_Proxy_{b_name}"
        cube.scale = (size_x / 2.0, size_y / 2.0, size_z / 2.0)
        
        # Apply scale transform
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        
        # Re-link to appropriate collection
        master_collection.objects.unlink(cube)
        created_collections[coll_target].objects.link(cube)

    # -------------------------------------------------------------
    # 5. ENVIRONMENT & NISHITA SKY LIGHTING SETUP
    # -------------------------------------------------------------
    world = scene.world
    if not world:
        world = bpy.data.worlds.new("MIT_WPU_World")
        scene.world = world
        
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    
    # Clear existing world nodes
    nodes.clear()
    
    # Create Nishita Sky Setup
    node_background = nodes.new(type='ShaderNodeBackground')
    node_sky = nodes.new(type='ShaderNodeTexSky')
    node_output = nodes.new(type='ShaderNodeOutputWorld')
    
    node_sky.sky_type = 'NISHITA'
    node_sky.sun_elevation = math.radians(45.0)
    node_sky.sun_rotation = math.radians(210.0)
    node_sky.air_density = 1.0
    node_sky.dust_density = 1.2
    node_sky.ozone_density = 2.0
    
    # Connect nodes
    links.new(node_sky.outputs['Sky'], node_background.inputs['Color'])
    links.new(node_background.outputs['Background'], node_output.inputs['Surface'])
    
    print("MIT-WPU Campus scene initialized successfully with exact metric scale and collection hierarchy!")

# Execute scene setup
setup_mit_wpu_campus()
```

---

## 11. Final Checklist Before Submission / Production Render

- [ ] Confirm all scale primitives match real-world building proportions ($1\text{ BU} = 1\text{ m}$).
- [ ] Check that window/door modules use linked duplicates (`Alt + D`) to keep Blender file size compact.
- [ ] Ensure terrain geometry extends beyond campus limits ($500\text{ m}$ perimeter) to prevent horizon cut-offs during low-angle camera renders.
- [ ] Verify HDRI / Nishita sky sun angle aligns with real-world orientation ($18^\circ$ offset to true north).
- [ ] Run test renders in both Cycles (32 samples + OptiX/OpenImageDenoise) and EEVEE Next to check light leakage along modular wall joints.