"""
export/ui.py — "Export" section under a single rig's chains.
"""
from . import weights as W, optimize as O, gamerig as G
from .ops import stale_handle_keys


def draw_export_ui(layout, context, arm):
    props = arm.gesturebone_props
    linked = arm.library is not None or arm.override_library is not None
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Export", icon='EXPORT')

    stale = stale_handle_keys(arm) if linked else 0
    if stale:
        r = col.row(align=True)
        r.alert = True
        r.operator("gesturebone.repair_anim_file", text=f"Repair ANIM File ({stale} keys)", icon='ERROR')

    meshes = W.chain_meshes(arm)
    baked = sum(1 for ob in meshes if W.is_baked(ob))
    r = col.row(align=True)
    r.label(text=f"Weights {baked}/{len(meshes)} baked")
    sub = r.row(align=True)
    sub.enabled = not linked
    sub.operator("gesturebone.export_bake_weights", text="Bake", icon='CHECKMARK')
    r.operator("gesturebone.export_live_weights", text="Live", icon='PLAY')

    r = col.row(align=True)
    if O.deform_mode(arm) == O.MODE_BBONE:
        r.label(text="Blender Optimized (BDEF)", icon='BONE_DATA')
    else:
        r.label(text="Sampler deform", icon='OUTLINER_DATA_ARMATURE')
        sub = r.row(align=True)
        sub.enabled = not linked
        sub.operator("gesturebone.export_optimize", text="Optimize", icon='MOD_ARMATURE')

    col.separator(factor=0.5)
    r = col.row(align=True)
    r.prop(props, "export_segments", text="Segments")
    previewing = G.is_previewing(arm)
    r.operator("gesturebone.export_preview", text="Update" if previewing else "Preview",
               icon='FILE_REFRESH' if previewing else 'HIDE_OFF', depress=previewing)
    if previewing:
        r.operator("gesturebone.export_preview", text="", icon='X').clear = True
    if O.deform_mode(arm) == O.MODE_BBONE:
        col.prop(props, "export_weights", text="")
    col.prop(props, "export_path", text="")
    r = col.row(align=True)
    r.operator("gesturebone.export_game", text="Unity FBX").target = 'FBX'
    r.operator("gesturebone.export_game", text="Godot glTF").target = 'GLB'
