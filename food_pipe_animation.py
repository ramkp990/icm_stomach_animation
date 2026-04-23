
import bpy
import bmesh
import math

# ═══════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════
TUBE_LENGTH   = 10.0
TUBE_RADIUS   = 0.36
SEGMENTS      = 16
#RINGS         = 30
CONTRACTION   = 0.70
NUM_ZONES     = 40
WAVE_SIGMA    = 2.2
TOTAL_FRAMES  = 100
FPS           = 15
BOLUS_RADIUS  = 0.10
BOLUS_SCALE_Z = 1.8
WAVE_LAG = 0.7   # how far contraction trails the bolus (0.4–0.7 sweet spot)
# ═══════════════════════════════════════════════════════
# ── Placement — match to stomach inlet ──
TUBE_LOCATION = (0.37307, 0.21316, 1.5921)   # move to stomach inlet XYZ
TUBE_ROTATION = (172.18, -0.41627, -70.501)   # rotate in degrees (X, Y, Z)
BULGE_AMOUNT  = 0.16   # how much the tube swells ahead of bolus
RINGS         = 120     # more rings = smoother deformation
SEGMENTS      = 32
WAVE_SIGMA    = 2.0    # tighter gaussian = crisper bulge/squeeze boundary
# ───────────────────────────────────────────────────────
#  COMPATIBILITY HELPER  (Blender 3.x and 4.4+)
# ───────────────────────────────────────────────────────
def get_action_fcurves(action):
    """
    Blender 4.4 moved fcurves out of the top-level Action object
    into a layered structure:
        action.layers[0].strips[0].channelbags[0].fcurves

    This helper transparently handles both old and new API.
    """
    if action is None:
        return []

    # ── Legacy API (Blender ≤ 4.3) ──
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)

    # ── Layered API (Blender 4.4+) ──
    curves = []
    if hasattr(action, 'layers'):
        for layer in action.layers:
            for strip in layer.strips:
                # channelbags holds per-binding fcurve collections
                if hasattr(strip, 'channelbags'):
                    for cb in strip.channelbags:
                        curves.extend(cb.fcurves)
    return curves


def smooth_action(action):
    """Apply AUTO_CLAMPED Bezier to every keyframe point in an action."""
    for fc in get_action_fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation      = 'BEZIER'
            kp.handle_left_type   = 'AUTO_CLAMPED'
            kp.handle_right_type  = 'AUTO_CLAMPED'


def linear_action(action):
    """Apply LINEAR interpolation to every keyframe point in an action."""
    for fc in get_action_fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'

def place_esophagus(tube_obj, curve_obj, bolus_obj):
    """
    Shift and rotate all three objects together so the tube
    lines up with the stomach inlet.
    """
    loc = TUBE_LOCATION
    rot = (math.radians(TUBE_ROTATION[0]),
           math.radians(TUBE_ROTATION[1]),
           math.radians(TUBE_ROTATION[2]))

    for obj in (tube_obj, curve_obj, bolus_obj):
        obj.location.x      += loc[0]
        obj.location.y      += loc[1]
        obj.location.z      += loc[2]
        obj.rotation_euler.x += rot[0]
        obj.rotation_euler.y += rot[1]
        obj.rotation_euler.z += rot[2]

def esophagus_centerline(t):
    """
    t = 0..1 along tube length
    Returns (x,y,z) center of the tube.
    Creates a gentle anatomical S-curve.
    """
    z = -TUBE_LENGTH/2 + t * TUBE_LENGTH

    # gentle forward curve
    x = 0.35 * math.sin(t * math.pi * 0.9)

    # slight sideways drift (very subtle)
    y = 0.15 * math.sin(t * math.pi * 1.7)

    return x, y, z


# ───────────────────────────────────────────────────────
#  1. SCENE SETUP
# ───────────────────────────────────────────────────────
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.curves,
                       bpy.data.materials, bpy.data.cameras,
                       bpy.data.lights, bpy.data.shape_keys):
        for item in list(collection):
            collection.remove(item)


# ───────────────────────────────────────────────────────
#  2. TUBE MESH
# ───────────────────────────────────────────────────────
def build_tube_mesh():
    """
    Open-ended cylinder: RINGS+1 rings × SEGMENTS vertices.
    No caps so the bolus is always visible from the side.
    """
    mesh = bpy.data.meshes.new("FoodPipeMesh")
    bm   = bmesh.new()

    for r in range(RINGS + 1):

        t = r / RINGS
        cx, cy, cz = esophagus_centerline(t)

        # taper: throat thinner, stomach wider
        taper = 0.65 + 0.45 * t
        radius = TUBE_RADIUS * taper

        for s in range(SEGMENTS):
            angle = 2 * math.pi * s / SEGMENTS

            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            z = cz

            bm.verts.new((x, y, z))

    bm.verts.ensure_lookup_table()

    for r in range(RINGS):
        for s in range(SEGMENTS):
            i0 =  r      * SEGMENTS + s
            i1 =  r      * SEGMENTS + (s + 1) % SEGMENTS
            i2 = (r + 1) * SEGMENTS + (s + 1) % SEGMENTS
            i3 = (r + 1) * SEGMENTS + s
            bm.faces.new([bm.verts[i0], bm.verts[i1],
                          bm.verts[i2], bm.verts[i3]])

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new("FoodPipe", mesh)
    bpy.context.collection.objects.link(obj)
    return obj


# ───────────────────────────────────────────────────────
#  3. SHAPE KEYS
# ───────────────────────────────────────────────────────
def build_shape_keys(tube_obj):
    tube_obj.shape_key_add(name="Basis", from_mix=False)
    tube_obj.data.shape_keys.name = "FoodPipeKeys"

    base_z    = [v.co.z for v in tube_obj.data.vertices]
    zone_keys = []

    for z_idx in range(NUM_ZONES):
        centre = z_idx * (RINGS / (NUM_ZONES - 1))
        key    = tube_obj.shape_key_add(name=f"Zone_{z_idx:02d}", from_mix=False)
        key.value = 0.0

        for r in range(RINGS + 1):
            delta     = r - centre
            t_ring    = r / RINGS
            cx, cy, _ = esophagus_centerline(t_ring)
            taper     = 0.65 + 0.45 * t_ring

            # ── transition band around centre — no hard delta==0 jump ──
            transition = WAVE_SIGMA * 1.6   # width of the blend zone

            if delta > transition:
                # purely ahead — round bulge
                reach = WAVE_SIGMA * 3.0
                d     = delta - transition   # measure from end of blend zone
                if d < reach:
                    t_cos = d / reach
                    g     = (0.5 * (1.0 + math.cos(math.pi * t_cos))) ** 2
                    scale = 1.0 + BULGE_AMOUNT * g
                else:
                    scale = 1.0

            elif delta < -transition:
                # purely behind — round squeeze
                reach = WAVE_SIGMA * 3.8
                d     = (-delta) - transition
                if d < reach:
                    t_cos = d / reach
                    g     = (0.5 * (1.0 + math.cos(math.pi * t_cos))) ** 2
                    scale = 1.0 - (1.0 - CONTRACTION) * g
                else:
                    scale = 1.0

            else:
                # ── blend zone: smoothly interpolate bulge→squeeze ──
                t_blend    = (delta + transition) / (2.0 * transition)  # 0→1
                # smooth hermite so velocity is zero at both ends
                t_smooth   = t_blend * t_blend * (3.0 - 2.0 * t_blend)
                t_smooth = t_blend ** 3 * (t_blend * (t_blend * 6.0 - 15.0) + 10.0)
                scale_bulge   = 1.0 + BULGE_AMOUNT
                scale_squeeze = 1.0 - (1.0 - CONTRACTION)
                scale = scale_squeeze + t_smooth * (scale_bulge - scale_squeeze)

            nr = TUBE_RADIUS * taper * scale

            for s in range(SEGMENTS):
                vi    = r * SEGMENTS + s
                angle = 2 * math.pi * s / SEGMENTS
                key.data[vi].co.x = cx + math.cos(angle) * nr
                key.data[vi].co.y = cy + math.sin(angle) * nr
                key.data[vi].co.z = base_z[vi]

        zone_keys.append(key)

    return zone_keys

def add_curve_shape_keys(curve_obj):
    """
    Mirror the tube's Gaussian wave onto the curve control points.
    Each zone key nudges the curve points inward the same way the tube squeezes.
    """
    SAMPLES = len(curve_obj.data.splines[0].points)

    # Basis — store original positions
    curve_obj.shape_key_add(name="Basis", from_mix=False)
    curve_obj.data.shape_keys.name = "CurveKeys"

    base_positions = [p.co.copy() for p in curve_obj.data.splines[0].points]

    zone_curve_keys = []

    for z_idx in range(NUM_ZONES):
        centre = z_idx * ((SAMPLES - 1) / (NUM_ZONES - 1))
        key    = curve_obj.shape_key_add(name=f"CurveZone_{z_idx:02d}", from_mix=False)
        key.value = 0.0

        for i in range(SAMPLES):
            gaussian = math.exp(-0.5 * ((i - centre) / WAVE_SIGMA) ** 2)
            # squeeze toward straight Z axis slightly during contraction
            t  = i / (SAMPLES - 1)
            cx, cy, _ = esophagus_centerline(t)

            # interpolate control point toward centerline during squeeze
            orig = base_positions[i]
            key.data[i].co = (
                            orig.x - cx * gaussian * 0.4,
                            orig.y - cy * gaussian * 0.4,
                            orig.z
                        )

        zone_curve_keys.append(key)

    return zone_curve_keys


def animate_curve_wave(zone_curve_keys):
    fpz = TOTAL_FRAMES / (NUM_ZONES - 1)

    for idx, key in enumerate(zone_curve_keys):
        peak = 1.0 + idx * fpz
        ramp = fpz * 1.8

        schedule = [
            (peak - ramp,        0.0),
            (peak - ramp * 0.5,  0.3),
            (peak - ramp * 0.15, 0.85),
            (peak,               1.0),
            (peak + ramp * 0.15, 0.85),
            (peak + ramp * 0.5,  0.3),
            (peak + ramp,        0.0),
        ]

        for frame, val in schedule:
            key.value = val
            key.keyframe_insert(data_path="value", frame=int(frame))

    ck_block = bpy.data.shape_keys.get("CurveKeys")
    if ck_block and ck_block.animation_data:
        smooth_action(ck_block.animation_data.action)
        
        
# ───────────────────────────────────────────────────────
#  4. WAVE ANIMATION
# ───────────────────────────────────────────────────────
def animate_wave(zone_keys):
    fpz = TOTAL_FRAMES / (NUM_ZONES - 1)

    for idx, key in enumerate(zone_keys):
        peak     = 1.0 + idx * fpz
        # overlap is 2x the zone spacing — neighbours always blending
        ramp     = fpz * 1.8

        schedule = [
            (peak - ramp,        0.0),
            (peak - ramp * 0.5,  0.3),
            (peak - ramp * 0.15, 0.85),
            (peak,               1.0),
            (peak + ramp * 0.15, 0.85),
            (peak + ramp * 0.5,  0.3),
            (peak + ramp,        0.0),
        ]

        for frame, val in schedule:
            key.value = val
            key.keyframe_insert(data_path="value", frame=int(frame))

    sk_block = bpy.data.shape_keys.get("FoodPipeKeys")
    if sk_block and sk_block.animation_data:
        smooth_action(sk_block.animation_data.action)

# ───────────────────────────────────────────────────────
#  5. FOOD BOLUS
# ───────────────────────────────────────────────────────
def create_bolus():
    """
    Elongated sphere travelling bottom→top.
    Squash shape key activates at each zone peak.
    """
    half          = TUBE_LENGTH / 2
    bolus_half_len = BOLUS_RADIUS * BOLUS_SCALE_Z

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=BOLUS_RADIUS, segments=24, ring_count=12,
        location=(0, 0, -half - bolus_half_len)
    )
    bolus = bpy.context.active_object
    bolus.name = "FoodBolus"

    bolus.scale.z = BOLUS_SCALE_Z
    bpy.ops.object.transform_apply(scale=True)


    # ── Squash shape key ──
    bolus.shape_key_add(name="Basis",    from_mix=False)
    sq = bolus.shape_key_add(name="Squeezed", from_mix=False)
    sq.value = 0.0

    for v in sq.data:
        v.co.x *= 1.40
        v.co.y *= 1.40
        v.co.z *= 0.55

    fpz = TOTAL_FRAMES / (NUM_ZONES - 1)
    hw  = max(1, int(fpz * 0.32))

    for idx in range(NUM_ZONES):
        peak = int(1 + idx * fpz + fpz * (WAVE_LAG + 0.05))
        for frame, val in [
            (max(1, peak - hw),             0.0),
            (peak,                          0.35),
            (min(TOTAL_FRAMES, peak + hw),  0.0),
        ]:
            sq.value = val
            sq.keyframe_insert(data_path="value", frame=frame)

    # Smooth bolus squash curves
    # Shape keys for bolus get a default name — find it via the object's key_block
    bolus_sk_block = bolus.data.shape_keys
    if bolus_sk_block and bolus_sk_block.animation_data:
        smooth_action(bolus_sk_block.animation_data.action)  # ← uses helper

    return bolus


# ───────────────────────────────────────────────────────
#  6. MATERIALS
# ───────────────────────────────────────────────────────
def create_materials(tube_obj, bolus_obj):

    # ── Tube: semi-transparent flesh-pink ──
    mt   = bpy.data.materials.new("TubeMat")
    mt.use_nodes = True
    nt   = mt.node_tree
    nt.nodes.clear()

    out  = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    out.location  = (300, 0)
    bsdf.location = (0,   0)

    bsdf.inputs['Base Color'].default_value = (0.88, 0.52, 0.58, 1.0)
    bsdf.inputs['Roughness'].default_value  = 0.50
    bsdf.inputs['Alpha'].default_value      = 0.38

    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    mt.blend_method        = 'BLEND'
    mt.use_backface_culling = False
    tube_obj.data.materials.append(mt)

    # ── Bolus: opaque food-orange ──
    mb   = bpy.data.materials.new("BolusMat")
    mb.use_nodes = True
    nt2  = mb.node_tree
    nt2.nodes.clear()

    out2  = nt2.nodes.new('ShaderNodeOutputMaterial')
    bsdf2 = nt2.nodes.new('ShaderNodeBsdfPrincipled')
    out2.location  = (300, 0)
    bsdf2.location = (0,   0)

    bsdf2.inputs['Base Color'].default_value = (0.76, 0.38, 0.10, 1.0)
    bsdf2.inputs['Roughness'].default_value  = 0.55

    # 'Specular IOR Level' may be named differently across versions
    for specular_name in ('Specular IOR Level', 'Specular', 'IOR'):
        if specular_name in bsdf2.inputs:
            bsdf2.inputs[specular_name].default_value = 0.6
            break

    nt2.links.new(bsdf2.outputs['BSDF'], out2.inputs['Surface'])
    bolus_obj.data.materials.append(mb)

# ───────────────────────────────────────────────────────
#  CURVE PATH  (replaces per-frame location keyframes)
# ───────────────────────────────────────────────────────
def create_centerline_curve():
    """Build a NURBS curve that traces esophagus_centerline()."""
    curve_data = bpy.data.curves.new("CenterlineCurve", type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 64

    spline = curve_data.splines.new('NURBS')

    SAMPLES = 60
    spline.points.add(SAMPLES - 1)   # spline starts with 1 point

    half = TUBE_LENGTH / 2

    for i in range(SAMPLES):
        t = i / (SAMPLES - 1)
        cx, cy, _ = esophagus_centerline(t)
        cz = -half + t * TUBE_LENGTH          # straight Z travel
        spline.points[i].co = (cx, cy, cz, 1.0)  # w=1 for NURBS

    spline.use_endpoint_u = True   # curve passes through first/last point

    curve_obj = bpy.data.objects.new("CenterlinePath", curve_data)
    bpy.context.collection.objects.link(curve_obj)
    return curve_obj


def attach_bolus_to_curve(bolus, curve_obj):
    bolus.animation_data_clear()
    bolus.location = (0, 0, 0)

    # ── IMPORTANT: tell Blender to use offset_factor, not scene time ──
    curve_obj.data.use_path = True
    curve_obj.data.path_duration = TOTAL_FRAMES

    con = bolus.constraints.new(type='FOLLOW_PATH')
    con.target            = curve_obj
    con.use_fixed_location = True    # ← THIS is the key fix
    con.use_curve_follow  = True
    con.forward_axis      = 'FORWARD_Z'
    con.up_axis           = 'UP_Y'

    con.offset_factor = 0.0
    con.keyframe_insert(data_path="offset_factor", frame=1)
    con.offset_factor = 1.0
    con.keyframe_insert(data_path="offset_factor", frame=TOTAL_FRAMES)

    if bolus.animation_data:
        smooth_action(bolus.animation_data.action)
        
# ───────────────────────────────────────────────────────
#  7. CAMERA & LIGHTS
# ───────────────────────────────────────────────────────
def setup_camera_and_lights():
    bpy.ops.object.camera_add(
        location=(14, 0, 0),
        rotation=(math.pi / 2, 0, math.pi / 2)
    )
    cam = bpy.context.active_object
    cam.name = "SideCamera"
    cam.data.lens = 60
    bpy.context.scene.camera = cam

    bpy.ops.object.light_add(type='AREA', location=(5, 6, 7))
    key = bpy.context.active_object
    key.name = "KeyLight"
    key.data.energy = 350.0
    key.data.size   = 5.0
    key.data.color  = (1.0, 0.95, 0.85)
    key.rotation_euler = (math.radians(-40), math.radians(15), math.radians(35))

    bpy.ops.object.light_add(type='AREA', location=(-6, -4, 2))
    fill = bpy.context.active_object
    fill.name = "FillLight"
    fill.data.energy = 180.0
    fill.data.size   = 7.0
    fill.data.color  = (0.85, 0.90, 1.0)


# ───────────────────────────────────────────────────────
#  8. VIEWPORT
# ───────────────────────────────────────────────────────
def set_viewport_material_preview():
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'
            break


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════
def main():
    print("\n╔══════════════════════════════════════════════╗")
    print("║   Peristalsis Simulator — Building scene …   ║")
    print("╚══════════════════════════════════════════════╝")

    #clear_scene()

    scene             = bpy.context.scene
    scene.render.fps  = FPS

    # ── Only extend the frame range, never shrink it ──
    scene.frame_start = min(scene.frame_start, 1)
    scene.frame_end   = max(scene.frame_end, TOTAL_FRAMES)

    scene.frame_set(scene.frame_current)   # don't jump playhead

    print(f"  › Tube mesh  ({RINGS} rings × {SEGMENTS} segments) …")
    tube = build_tube_mesh()

    print(f"  › Shape keys ({NUM_ZONES} Gaussian zones) …")
    keys = build_shape_keys(tube)

    print(f"  › Animating wave over {TOTAL_FRAMES} frames …")
    animate_wave(keys)

    print("  › Food bolus …")
    bolus = create_bolus()
    
    print("  › Centerline curve …")
    path = create_centerline_curve()

    print("  › Curve shape keys …")
    curve_keys = add_curve_shape_keys(path)
    animate_curve_wave(curve_keys)


    print("  › Attaching bolus to curve …")
    attach_bolus_to_curve(bolus, path)

    print("  › Materials …")
    create_materials(tube, bolus)

    print("  › Camera & lights …")
    #setup_camera_and_lights()
    
    print("  › Placing esophagus at stomach inlet …")
    place_esophagus(tube, path, bolus)

    try:
        set_viewport_material_preview()
    except Exception:
        pass

    scene.frame_set(1)

    print("\n✓  Scene ready!")
    print(f"   {NUM_ZONES} wave zones  |  {RINGS} rings  |  {SEGMENTS} segments")
    print(f"   {TOTAL_FRAMES} frames @ {FPS} fps  =  {TOTAL_FRAMES // FPS} seconds")
    print("\n   ► Press SPACE in the 3D Viewport to preview.")
    print("   ► Z → Rendered for final quality.")
    print("   ► Ctrl+F12 to render the full animation.")


main()
