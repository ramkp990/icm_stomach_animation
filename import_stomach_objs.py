import bpy
import os
import re
import math

# ─── CONFIG ─────────────────────────────────────────────────────────────────
OBJ_DIR      = "/Users/ramankp/Documents/icm/new/ssi_caro_700_0.32_0.05-structure/ssi_caro_700_0.32_0.05-vtk-files/objs"
FPS          = 24
TOTAL_FRAMES = 500
NUM_LOOPS    = 5          # Loop 1 = full sim from rest │ Loops 2-5 = seamless repeat

FULL_START   = 0          # first OBJ file index
FULL_END     = 499        # last  OBJ file index  (500 files total)

# ── Seamless loop window ─────────────────────────────────────────────────────
# OBJ 399 and OBJ 499 look identical → perfect loop point.
# Repeating 399-499 (100 frames) means the cycle never visibly resets.
REPEAT_START = 115
REPEAT_END   = 499

# ── stomach_ROOT transform ───────────────────────────────────────────────────
ROOT_LOCATION = (0.2833,   0.032039, 0.13729)
ROOT_ROTATION = (-46.745,  22.989,  -77.636)   # degrees, XYZ Euler
ROOT_SCALE    = (0.009,    0.009,    0.009)
# ────────────────────────────────────────────────────────────────────────────

frames_per_loop = TOTAL_FRAMES // NUM_LOOPS    # 100 frames per loop

scene = bpy.context.scene
scene.render.fps  = FPS
scene.frame_start = 1
scene.frame_end   = TOTAL_FRAMES

# ── Get all OBJ files sorted NUMERICALLY ────────────────────────────────────
all_obj_files = sorted(
    [f for f in os.listdir(OBJ_DIR) if f.endswith('.obj')],
    key=lambda x: int(re.search(r'\d+', x).group())
)

print(f"Total OBJ files found : {len(all_obj_files)}")

# ── Create parent empty with baked transform ──────────────────────────────────
bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
parent_empty = bpy.context.active_object
parent_empty.name = "stomach_ROOT"

parent_empty.location = ROOT_LOCATION

parent_empty.rotation_euler = (
    math.radians(ROOT_ROTATION[0]),
    math.radians(ROOT_ROTATION[1]),
    math.radians(ROOT_ROTATION[2]),
)

parent_empty.scale = ROOT_SCALE

print(f"stomach_ROOT transform applied:")
print(f"   Location : {ROOT_LOCATION}")
print(f"   Rotation : {ROOT_ROTATION} degrees")
print(f"   Scale    : {ROOT_SCALE}")

# ── Import all OBJ files ──────────────────────────────────────────────────────
imported_objects = []

for filename in all_obj_files:
    filepath = os.path.join(OBJ_DIR, filename)

    try:
        bpy.ops.wm.obj_import(filepath=filepath)
    except AttributeError:
        bpy.ops.import_scene.obj(filepath=filepath)

    obj = bpy.context.selected_objects[0]
    num = int(re.search(r'\d+', filename).group())
    obj.name = f"stomach_full_{num:03d}"
    obj.parent = parent_empty

    obj.hide_viewport = True
    obj.hide_render   = True

    imported_objects.append(obj)

print(f"Imported {len(imported_objects)} meshes")

def assign_visibility_by_frame(mesh_subset, start_frame, end_frame):
    num_meshes = len(mesh_subset)
    span = end_frame - start_frame + 1
    prev_obj = None

    # Hide all meshes at start_frame - 1
    for obj in mesh_subset:
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=start_frame - 1)
        obj.keyframe_insert(data_path="hide_render", frame=start_frame - 1)

    for f in range(start_frame, end_frame + 1):
        mesh_idx = int(((f - start_frame) / span) * num_meshes)
        mesh_idx = min(mesh_idx, num_meshes - 1)
        obj = mesh_subset[mesh_idx]

        if obj != prev_obj:
            if prev_obj is not None:
                # Hide the previous OBJ **at this frame**
                prev_obj.hide_viewport = True
                prev_obj.hide_render = True
                prev_obj.keyframe_insert(data_path="hide_viewport", frame=f)
                prev_obj.keyframe_insert(data_path="hide_render", frame=f)

            # Show current OBJ
            obj.hide_viewport = False
            obj.hide_render = False
            obj.keyframe_insert(data_path="hide_viewport", frame=f)
            obj.keyframe_insert(data_path="hide_render", frame=f)

            prev_obj = obj


        
# ── LOOP 1 — full simulation (starts from rest) ───────────────────────────────
# All 500 OBJ files are stepped through in the first 100 Blender frames.
# This gives the viewer the full motion from rest → established cycle.
full_meshes = imported_objects[FULL_START : FULL_END + 1]
loop1_start = 1
loop1_end   = frames_per_loop   # frame 100

print(f"Loop 1 : frames {loop1_start} → {loop1_end}  |  OBJ {FULL_START} → {FULL_END}  (full sim from rest)")
assign_visibility_by_frame(full_meshes, loop1_start, loop1_end)

# ── LOOPS 2–5 — seamless repeat of OBJ 399→499 ───────────────────────────────
# Because OBJ 399 == OBJ 499 in appearance, this section loops invisibly.
# Blender frame 100 ends on OBJ 499; frame 101 picks up at OBJ 399 — same state.
repeat_meshes = imported_objects[REPEAT_START : REPEAT_END + 1]

for loop in range(1, NUM_LOOPS):
    lstart = loop * frames_per_loop + 1
    lend   = lstart + frames_per_loop - 1
    print(f"Loop {loop+1}: frames {lstart} → {lend}  |  OBJ {REPEAT_START} → {REPEAT_END}  (seamless repeat)")
    assign_visibility_by_frame(repeat_meshes, lstart, lend)

print(f"\n✅ DONE!")
print(f"   stomach_ROOT : location={ROOT_LOCATION}, rotation={ROOT_ROTATION}, scale={ROOT_SCALE}")
print(f"   Loop 1  (frames   1–{frames_per_loop})  : full 500-file simulation from rest")
print(f"   Loops 2–{NUM_LOOPS} (frames {frames_per_loop+1}–{TOTAL_FRAMES}) : OBJ {REPEAT_START}–{REPEAT_END} repeating (seamless — 399≡499)")
print(f"   Press SPACE to play.")
