# ASTraM 3D Campus Modeling Workflow

This document defines the modeling and export conventions used by the ASTraM
WebGL campus viewer. The generated campus GLB is a visualization asset. The
current road GeoJSON is explicitly schematic; building footprints, elevations,
entrances, pathways, and terrain elevations must be replaced or calibrated from
authoritative MIT-WPU survey, CAD, or GIS data before operational planning.

## 1. Coordinate and scale calibration

### Blender scene setup

1. Set **Scene Properties → Units** to **Metric**, with **Unit Scale = 1.0**.
2. Use Blender world axes as follows: **X = east**, **Y = north**, and **Z = up**.
3. Set the campus road layer to Z = 0.08 m, sidewalks/pathways to Z = 0.12 m,
   building footprints to Z = 0.15 m, and terrain ground to Z = 0 m. These small
   offsets prevent z-fighting and do not change the real-world horizontal scale.
4. Set the 3D cursor to the working origin. Imported coordinates are converted
   to a local east/north meter plane near the campus, avoiding large WGS84
   coordinate values inside Blender.
5. Use **Numpad 7** for Top View and **Numpad 1** for Front View. Enable
   **Overlays → Scale** and place a measured 10 m or 20 m reference segment in
   the scene before tracing any surveyed feature.

### 1:1 meter scaling

Model every footprint at **1 Blender unit = 1 meter**. Do not scale the complete
scene to make it fit the viewport. The procedural generator converts longitude
and latitude to local meters and lays road ribbons from GeoJSON centerlines.
For manual edits, keep survey coordinates in a companion GIS/CAD source and
record its CRS. Reproject data to a local metric CRS (or a documented local
east/north origin) before using it for dimensions.

The starter road graph covers only a small campus area and has approximate
coordinates. Check its centerlines against an authoritative map before
calibrating buildings to the road layer. Do not infer real building location,
footprint, height, or access from the generated proxy blocks.

## 2. Collections and scene organization

Use these top-level Blender collections and keep objects in the appropriate
collection. The procedural script creates these collections automatically.

| Collection | Contents |
| --- | --- |
| `Terrain_GroundRoads_Pathways` | Terrain base, road ribbons, sidewalks, pedestrian paths, and parking surfaces |
| `Buildings` | Named building massing and facade objects |
| `Lawns_GreenSpaces` | Lawns, planted beds, and tree canopies |
| `Landmarks` | Gate markers, public art, clock towers, and campus signs |

Keep one interactive building as one named parent object where practical. If a
building uses multiple mesh parts, parent the pieces to the named building
object so the viewer can resolve clicks through the hierarchy.

## 3. Interactive naming and metadata

Names are stable identifiers consumed by the Three.js raycaster. Use these
conventions exactly:

| Object name | Interactive identity |
| --- | --- |
| `Building_Saraswati` | Saraswati building |
| `Building_Vishwakarma` | Vishwakarma building |
| `Building_SportsComplex` | Sports complex |
| `Road_e1`, `Road_e2`, … | Directed GeoJSON edge IDs |

The Blender generator stores `interactiveType`, `displayName`, `description`,
`floors`, `heightMeters`, and `edgeId` as custom properties where applicable.
Keep `Road_<edge id>` exact so WebSocket edge saturation values can be joined to
the GLB meshes without a separate lookup table. Avoid duplicate object names.

For manually modeled buildings, add useful metadata as custom properties. Keep
public-facing descriptions concise and avoid placing sensitive access or
security information in the GLB.

## 4. Building massing and materials

Use survey-derived footprints wherever available. Extrude each floor by
**3.5 m/storey** unless a measured building specification provides a better
value. Set a realistic roof parapet separately rather than stretching the
floor height. Use bevels sparingly; the target is a clear, low-poly campus
overview with readable footprints and roads.

Create and reuse a small shared material set:

| Material | Recommended use | Base appearance |
| --- | --- | --- |
| `M_Asphalt` | Road ribbons and parking surfaces | Charcoal gray, rough, low specular |
| `M_Grass` | Ground and lawns | Muted campus green, rough |
| `M_Concrete` | Sidewalks, plazas, curbs | Warm light gray, rough |
| `M_Glass` | Window bands and glazed entrances | Low-opacity blue gray; avoid excessive transparency |
| `M_BuildingWall` | Building massing | Light neutral wall color, rough |

Use one material per semantic surface where possible. Prefer material color and
simple geometry to unique textures. Keep texture images power-of-two where
possible, use packed images for the GLB, and remove unused materials before
export. The viewer dynamically changes road emissive color; do not bake a fixed
traffic state into `M_Asphalt`.

## 5. Procedural base generation

From the repository root, run the script with Blender's bundled Python:

```text
blender --background --python scripts/generate_3d_campus_placeholder.py
```

It reads `data/mit_wpu_roads.geojson`, converts each LineString to a metric
ribbon, creates clearly labeled schematic building masses and ground surfaces,
and writes `static/assets/mit_wpu_campus.glb`. This output is an initial
visualization base, not a verified campus BIM or survey model.

## 6. glTF 2.0 / GLB export settings

Export a binary **glTF 2.0 (.glb)** with these settings:

- Format: `glTF Binary (.glb)`.
- Include: visible campus collections and their mesh objects; exclude cameras
  and unused construction objects.
- Transform: apply object transforms and export in meters, with +Z up.
- Geometry: apply modifiers, export normals, and triangulate only at export.
- Materials: export Principled BSDF base color, metallic, roughness, and emissive
  channels; pack images.
- Custom properties: enable export of extras so IDs and tooltip metadata remain
  available in `userData`.
- Animation: disabled unless an explicitly authored asset needs it.
- Compression: use mesh compression only when the consuming GLTFLoader has the
  matching decoder configured.

After export, check the GLB in Blender and in the browser. Confirm that a
`Road_e1` node still maps to edge `e1`, a building tooltip resolves through its
child meshes, all materials render, and the campus remains 1:1 in meter units.

## 7. Browser integration

Load `static/js/three_campus_loader.js` as an ES module with Three.js and its
`GLTFLoader`/`OrbitControls` addons available. The viewer connects to
`/ws/traffic-stream`; each state packet contains `edges` with `edge_id` and
`saturation_ratio`. For REST snapshots, pass the `saturation_ratios` map to
`update3DRoadColors`. Road colors communicate traffic state only; they are not a
substitute for measured queue lengths, signal indications, or validated
engineering controls.
