import bpy

# Create or get material
mat_name = "stomach.001"

if mat_name in bpy.data.materials:
    mat = bpy.data.materials[mat_name]
else:
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True

# Assign to all imported objects
for obj in bpy.data.objects:
    if obj.type == 'MESH' and obj.name.startswith("stomach_full_"):
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

print("✅ Material assigned to all frames!")


import bpy
import bmesh

# ═══════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════

TUBE_NAME      = "FoodPipe.001"
STOMACH_CHILD  = "stomach_full_000"

ALPHA          = 0.35    # translucency of the bottom section

RINGS          = 120     # must match your food pipe script
SEGMENTS       = 32      # must match your food pipe script

TRANSLUCENT_FRACTION = 0.95   # bottom 90% = translucent, top 10% = opaque

# ═══════════════════════════════════════════════════════

def get_object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found in scene.")
    return obj


def make_translucent_mat(orig_mat, alpha):
    mat = orig_mat.copy()
    mat.name = orig_mat.name + "_translucent"

    if not mat.use_nodes:
        mat.use_nodes = True

    bsdf = next(
        (n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None
    )
    if bsdf is None:
        raise ValueError("No Principled BSDF found in stomach material.")

    bsdf.inputs['Alpha'].default_value = alpha

    for name in ('Transmission Weight', 'Transmission'):
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = 0.2
            break

    mat.blend_method        = 'BLEND'
    mat.use_backface_culling = False

    print(f"  ✓ Translucent material '{mat.name}' (alpha={alpha})")
    return mat


def make_opaque_mat(orig_mat):
    mat = orig_mat.copy()
    mat.name = orig_mat.name + "_opaque"

    if not mat.use_nodes:
        mat.use_nodes = True

    bsdf = next(
        (n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None
    )
    if bsdf:
        bsdf.inputs['Alpha'].default_value = 1.0
        for name in ('Transmission Weight', 'Transmission'):
            if name in bsdf.inputs:
                bsdf.inputs[name].default_value = 0.0
                break

    mat.blend_method        = 'OPAQUE'
    mat.use_backface_culling = False

    print(f"  ✓ Opaque material '{mat.name}'")
    return mat


def assign_materials_by_ring(tube_obj, mat_translucent, mat_opaque,
                              rings, segments, translucent_fraction):
    """
    Slot 0 → translucent  (bottom N rings)
    Slot 1 → opaque        (top remaining rings)
    """
    mesh = tube_obj.data

    # ── clear existing materials and add two slots ──
    mesh.materials.clear()
    mesh.materials.append(mat_translucent)   # slot 0
    mesh.materials.append(mat_opaque)        # slot 1

    cutoff_ring = int(rings * translucent_fraction)  # e.g. 108 for 90%

    # ── use bmesh to assign material index per face ──
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    # Face index = ring * segments + segment
    # Ring 0 = bottom of tube
    for r in range(rings):
        for s in range(segments):
            face_idx = r * segments + s
            if face_idx < len(bm.faces):
                if r < cutoff_ring:
                    bm.faces[face_idx].material_index = 0   # translucent
                else:
                    bm.faces[face_idx].material_index = 1   # opaque

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    print(f"  ✓ Faces assigned: rings 0–{cutoff_ring-1} → translucent | "
          f"rings {cutoff_ring}–{rings-1} → opaque")


def fix_tube_texture_coordinates(tube_obj, stomach_obj):
    """
    Make the tube sample texture from stomach's object space
    so the pattern looks identical.
    """
    for mat in tube_obj.data.materials:
        if mat is None or not mat.use_nodes:
            continue

        nt = mat.node_tree

        # find existing Texture Coordinate node or make one
        tex_coord = next((n for n in nt.nodes 
                         if n.type == 'TEX_COORD'), None)
        if tex_coord is None:
            tex_coord = nt.nodes.new('ShaderNodeTexCoord')
            tex_coord.location = (-600, 0)

        # ── KEY FIX: point at stomach, use its Object output ──
        tex_coord.object = stomach_obj   # sample from stomach's space

        # find Mapping node or make one
        mapping = next((n for n in nt.nodes 
                       if n.type == 'MAPPING'), None)
        if mapping is None:
            mapping = nt.nodes.new('ShaderNodeMapping')
            mapping.location = (-400, 0)

        # connect Object → Mapping if not already
        already_linked = any(
            l.from_node == tex_coord and l.to_node == mapping
            for l in nt.links
        )
        if not already_linked:
            nt.links.new(tex_coord.outputs['Object'], 
                        mapping.inputs['Vector'])

        print(f"  ✓ {mat.name} now samples from stomach object space")

def force_world_position_texture(tube_obj):
    """
    Replace texture coordinate source with world Position.
    Both tube and stomach will sample identical world-space coordinates.
    """
    for mat in tube_obj.data.materials:
        if mat is None or not mat.use_nodes:
            continue

        nt = mat.node_tree

        # remove ALL existing Texture Coordinate and Mapping nodes
        for node in list(nt.nodes):
            if node.type in ('TEX_COORD', 'MAPPING', 'UVMAP'):
                nt.nodes.remove(node)

        # add Geometry node — gives true world Position
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        geo.location = (-700, 0)

        # add fresh Mapping node to control scale
        mapping = nt.nodes.new('ShaderNodeMapping')
        mapping.location = (-500, 0)
        # copy stomach scale — adjust these if pattern is too big/small
        mapping.inputs['Scale'].default_value = (1.0, 1.0, 1.0)

        # connect Position → Mapping
        nt.links.new(geo.outputs['Position'], mapping.inputs['Vector'])

        # find every texture node and plug mapping into it
        for node in nt.nodes:
            if node.type in ('TEX_NOISE', 'TEX_MUSGRAVE', 
                            'TEX_VORONOI', 'TEX_IMAGE',
                            'TEX_WAVE', 'TEX_MAGIC'):
                # disconnect whatever was in Vector input
                for link in list(nt.links):
                    if link.to_node == node and link.to_socket.name == 'Vector':
                        nt.links.remove(link)
                # plug in world position
                nt.links.new(mapping.outputs['Vector'], 
                           node.inputs['Vector'])
                print(f"  ✓ {node.name} now uses world Position")

        print(f"  ✓ Material '{mat.name}' → world space coordinates")





def main():
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  FoodPipe: bottom 90% translucent / top 10% opaque  ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    tube_obj    = get_object(TUBE_NAME)
    stomach_obj = get_object(STOMACH_CHILD)

    if not stomach_obj.data.materials:
        raise ValueError(f"'{STOMACH_CHILD}' has no materials assigned.")

    orig_mat = stomach_obj.data.materials[0]
    print(f"  Source material : '{orig_mat.name}'\n")

    mat_translucent = make_translucent_mat(orig_mat, ALPHA)
    mat_opaque      = make_opaque_mat(orig_mat)

    assign_materials_by_ring(
        tube_obj, mat_translucent, mat_opaque,
        RINGS, SEGMENTS, TRANSLUCENT_FRACTION
    )
    stomach_obj = get_object(STOMACH_CHILD)
    fix_tube_texture_coordinates(tube_obj, stomach_obj)


    force_world_position_texture(tube_obj)
    bpy.context.view_layer.update()


    print("\n✅ Done!")
    print(f"   Bottom {int(TRANSLUCENT_FRACTION*100)}% of tube → translucent (alpha={ALPHA})")
    print(f"   Top    {int((1-TRANSLUCENT_FRACTION)*100)}% of tube → opaque (matches stomach)")
    print()
    print("   ── Tuning tips ──────────────────────────────────────")
    print("   • Adjust split point  → change TRANSLUCENT_FRACTION (0.0–1.0)")
    print("   • More transparent    → decrease ALPHA (try 0.2)")
    print("   • Less transparent    → increase ALPHA (try 0.5)")
    print("   ─────────────────────────────────────────────────────")


main()
