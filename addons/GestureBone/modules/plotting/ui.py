"""
plotting/ui.py — UI for PLOTTING rigs.
draw_plotting_ui() is called inline from panels.py when rig_type == 'PLOTTING'.

UI style ported back from the "fine tune UI" commit: a "Registration" box with
Default Template / Meta Rig / Meta Collection split rows, and a wide Auto Rig
button followed by a compact icon cluster. Behaviour and operators are unchanged
from the rearchitected backend.
"""
import bpy
from ..shared.utils import _all_bone_colls


def _step(col, props, idname, icon, step_num, label, always_enabled=False):
    row = col.row()
    if not always_enabled:
        row.enabled = (props.completed_step == step_num - 1)
    row.operator(idname, text=label, icon=icon, depress=props.last_step == idname)


def _status_badge(chain):
    """Return (text, icon, alert) status for a chain row."""
    step = chain.rig_completed_step
    if step == 0:
        return "○ Not rigged", 'RADIOBUT_OFF', False
    if step >= 11:
        return "✓ Rigged", 'CHECKMARK', False
    return f"⚠ Step {step}/11", 'ERROR', True


def draw_plotting_ui(layout, context, arm):
    """Draw the full PLOTTING rig panel content."""
    props      = arm.gesturebone_props
    scene_gp   = getattr(context.scene, 'gesturebone_props', None)
    debug_mode = getattr(scene_gp, 'debug_mode', False)
    extra_info = getattr(scene_gp, 'extra_infos_mode', False)

    # Icon reflecting which armature the switch button jumps to (mirrors the
    # switch button in the Auto Rig bar below so both stay visually in sync).
    switch_icon = 'CON_SPLINEIK' if props.gesture_active else 'ARMATURE_DATA'

    # ── Registration ──────────────────────────────────────────────────────────
    box = layout.box()
    reg_head = box.row(align=True)
    reg_head.label(text="Registration", icon='PROPERTIES')
    reg_head.operator("gesturebone.append_essentials", text="", icon='FILE_REFRESH')
    # Switch back to the Gesture armature (kept here so it stays reachable from
    # the top of the PLOTTING UI, mirroring the switch button on the GESTURE UI —
    # same ARROW_LEFTRIGHT icon for consistency across both rig panels).
    reg_head.operator("gesturebone.switch_armature", text="", icon='ARROW_LEFTRIGHT',
                      depress=props.gesture_active)

    col = box.column(align=True)
    col.operator("gesturebone.create_rig", text="Create Rig", icon='ADD')
    col.separator()

    split = col.split(factor=0.5)
    split.label(text="Default Template")
    split.prop(props, "atomic_chain", text="")

    split = col.split(factor=0.5)
    split.label(text="Meta Rig")
    meta_sub = split.row()
    meta_sub.enabled = False
    meta_sub.label(text=arm.name, icon='ARMATURE_DATA')

    split = col.split(factor=0.5)
    split.label(text="Meta Collection")
    split.prop(props, "meta_collection", text="")

    # ── Chains ────────────────────────────────────────────────────────────────
    layout.separator(factor=0.5)
    chain_header = layout.row(align=True)
    chain_header.label(text="Chains", icon='BONE_DATA')
    chain_header.operator("gesturebone.sync_chains_from_meta_bones", text="", icon='FILE_REFRESH')

    chains = props.chains
    if not chains:
        hint = layout.row()
        hint.enabled = False
        hint.label(text="No chains — add bones to META collection then Sync", icon='INFO')
    else:
        for i, chain in enumerate(chains):
            status_text, status_icon, status_alert = _status_badge(chain)
            chain_box = layout.box()

            # Header row
            header = chain_box.row(align=True)
            header.prop(chain, "ui_expanded",
                        icon='TRIA_DOWN' if chain.ui_expanded else 'TRIA_RIGHT',
                        text="", emboss=False)
            header.label(text=chain.part_name)
            status_sub = header.row(align=True)
            status_sub.alert = status_alert
            status_sub.label(text=status_text, icon=status_icon)

            # Move buttons (inline in header, old-style)
            move_sub = header.row(align=True)
            up_op = move_sub.operator("gesturebone.move_chain", text="", icon='TRIA_UP')
            up_op.chain_index = i
            up_op.direction   = 'UP'
            dn_op = move_sub.operator("gesturebone.move_chain", text="", icon='TRIA_DOWN')
            dn_op.chain_index = i
            dn_op.direction   = 'DOWN'

            op = header.operator("gesturebone.rerig_part", text="", icon='FILE_REFRESH')
            op.bone_name = chain.part_name

            if not chain.ui_expanded:
                continue

            # Body
            body = chain_box.column(align=True)

            split = body.split(factor=0.32, align=True)
            split.label(text="Template:")
            split.prop(chain, "atomic_chain", text="")

            row = body.row(align=True)
            row.prop(chain, "control_mode", text="Mode")
            row.prop(chain, "pivot_placement", text="", icon_only=True)

            # Bind mesh
            bm_row = body.row(align=True)
            bm_row.alert = chain.bind_mesh is None
            bm_row.prop(chain, "bind_mesh", text="Bind Mesh")
            if extra_info and chain.bind_mesh:
                op = bm_row.operator("gesturebone.bind_to_mesh", text="", icon='MESH_DATA')
                op.bone_name = chain.part_name

            # Gesture rig display (read-only)
            rig_row = body.row()
            rig_row.enabled = False
            rig_row.label(
                text=f"Gesture Rig: {chain.gesture_rig.name}" if chain.gesture_rig else "Gesture Rig: (not generated)",
                icon='ARMATURE_DATA',
            )

    # ── Auto Rig + operations bar (old two-row style) ─────────────────────────
    layout.separator(factor=0.5)

    gesture_arm_obj = bpy.data.objects.get(f"{arm.name}.Gesture")

    connect_selectable = True
    pivot_active       = False
    if gesture_arm_obj:
        cb = [b for b in gesture_arm_obj.data.bones if b.name.startswith('CONNECT')]
        if cb:
            connect_selectable = sum(1 for b in cb if not b.hide_select) > len(cb) // 2
        pivot_bc = gesture_arm_obj.data.collections.get('PIVOT-ROTATION')
        if pivot_bc:
            pivot_active = pivot_bc.is_visible

    connect_icon = 'RESTRICT_SELECT_OFF' if connect_selectable else 'RESTRICT_SELECT_ON'
    meta_icon    = 'BONE_DATA' if props.meta_solo_mode else 'GROUP_BONE'
    vis_icon     = 'HIDE_OFF' if props.show_both_armatures else 'HIDE_ON'

    ops_col = layout.column(align=True)

    # Row 1: Auto Rig (wide) + management icon cluster
    auto_row = ops_col.row(align=True)
    main_btn = auto_row.row(align=True)
    main_btn.scale_x = 6.0
    main_btn.operator("gesturebone.auto_rig", text="Auto Rig", icon='PLAY')
    auto_row.operator("gesturebone.toggle_armature_visibility", text="", icon=vis_icon,
                      depress=props.show_both_armatures)
    auto_row.operator("gesturebone.switch_armature", text="", icon=switch_icon,
                      depress=props.gesture_active)
    auto_row.operator("gesturebone.clear_rig", text="", icon='GHOST_DISABLED')
    auto_row.operator("gesturebone.delete_sample_folder", text="", icon='ORPHAN_DATA')
    auto_row.operator("gesturebone.toggle_meta_collection", text="", icon=meta_icon,
                      depress=props.meta_solo_mode)

    # Row 2: labelled adjustment buttons filling the row
    util_row = ops_col.row(align=True)
    util_row.operator("gesturebone.toggle_connect_selectable", icon=connect_icon,
                      depress=connect_selectable)
    util_row.operator("gesturebone.reset_all_bones_stretch", icon='SNAP_MIDPOINT')
    util_row.operator("gesturebone.toggle_pivot_rotation", icon='PIVOT_CURSOR',
                      depress=pivot_active)

    # ── Debug: step-by-step ───────────────────────────────────────────────────
    if debug_mode:
        layout.separator()
        box = layout.box()
        box.label(text="Debug: Step by Step", icon='TOOL_SETTINGS')
        col = box.column(align=False)

        # Active bone override — use active_chain_index
        if props.chains:
            idx   = min(props.active_chain_index, len(props.chains) - 1)
            chain = props.chains[idx]
            col.label(text=f"MetaBone: {chain.part_name}", icon='BONE_DATA')
        col.separator()

        _step(col, props, "gesturebone.duplicate_atomic_chain",
              'MOD_THICKNESS', 1, "1.  Duplicate and Rename", always_enabled=True)
        _step(col, props, "gesturebone.rebind_constraints_geonodes",
              'CON_SPLINEIK',  2, "2.  Rebind Constraints & Geonodes")
        col.separator()
        col.label(text="  Align Chain to Bone:", icon='EMPTY_AXIS')
        _step(col, props, "gesturebone.scale_empty_to_rest_pose",  'FULLSCREEN_ENTER', 3, "3.  Scale Empty to Rest Pose")
        _step(col, props, "gesturebone.add_align_constraints",     'CON_LOCLIKE',      4, "4.  Add Copy Loc & Rot")
        _step(col, props, "gesturebone.edit_alignment_in_metarig", 'POSE_HLT',         5, "5.  Edit Alignment in Meta Rig")
        if props.is_aligning:
            hint = col.row()
            hint.enabled = False
            hint.label(text="     Adjust pose → then Step 6", icon='INFO')
        _step(col, props, "gesturebone.accept_and_bind",           'CHECKMARK',        6, "6.  Accept & Bind")
        col.separator()
        _step(col, props, "gesturebone.refresh_rigs",              'CON_ROTLIKE',           7,  "7.  Refresh Gesture & Plot Rigs")
        _step(col, props, "gesturebone.rebind_final_armatures",    'OUTLINER_OB_ARMATURE',  8,  "8.  Rebind Final Armatures")
        _step(col, props, "gesturebone.finish_merging",            'OUTLINER_DATA_ARMATURE',9,  "9.  Merge & Clean")
        _step(col, props, "gesturebone.merge_rig_into_metarig",    'ARMATURE_DATA',         10, "10. Merge .Rig into MetaRig")
        col.separator()
        _step(col, props, "gesturebone.rebind_armature_deform",    'MOD_ARMATURE',          11, "11. Rebind Armature Deform")
        col.separator()

        def _bind_step(idname, label, icon, gate):
            r = col.row()
            r.enabled = (props.completed_step == gate)
            if props.chains and props.active_chain_index < len(props.chains):
                bone_n = props.chains[props.active_chain_index].part_name
                op = r.operator(idname, text=label, icon=icon, depress=(props.last_step == idname))
                op.bone_name = bone_n
            else:
                r.label(text=label, icon=icon)

        _bind_step("gesturebone.bind_step_move_collection", "12a. Move Bind Mesh to Collection", 'COLLECTION_NEW', 11)
        _bind_step("gesturebone.bind_step_sync_materials",  "12b. Sync Materials to Sample",     'MATERIAL',       12)
        _bind_step("gesturebone.bind_step_copy_geometry",   "12c. Copy Geometry to Sample",      'MESH_DATA',      13)


def register():
    pass  # No panels registered here — drawn inline from panels.py


def unregister():
    pass
