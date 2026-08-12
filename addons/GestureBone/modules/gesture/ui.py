"""
gesture/ui.py — UI for GESTURE rigs.
draw_gesture_ui() is called inline from panels.py when rig_type == 'GESTURE'.

UI style ported back from the "fine tune UI" commit: compact per-chain cards
with a double-height activate/toggle button, inline apply/delete icons, and a
slim smoothness slider + live-preview toggle. Behaviour and operators are
unchanged from the rearchitected backend.
"""
import bpy
from ..shared.utils import _arm, _chains_for_gesture_rig, _validate_plotting_rig
from ..shared.utils_constraints import _constraints_exist, _constraints_are_muted


def draw_gesture_ui(layout, context, arm):
    """Draw the full GESTURE rig panel content."""
    props    = arm.gesturebone_props
    plotting = props.plotting_rig

    # ── Header: Plotting Rig info ─────────────────────────────────────────────
    header_box = layout.box()
    if plotting is None:
        row = header_box.row()
        row.alert = True
        row.label(text="Plotting Rig not set — assign below", icon='ERROR')
        header_box.prop(props, "plotting_rig", text="Plotting Rig")
        return

    if plotting.gesturebone_props.rig_type != 'PLOTTING':
        row = header_box.row()
        row.alert = True
        row.label(text=f"'{plotting.name}' is not a PLOTTING rig", icon='ERROR')
        header_box.prop(props, "plotting_rig", text="Plotting Rig")
        return

    header_row = header_box.row(align=True)
    header_row.label(text=f"Plotting Rig: {plotting.name}", icon='ARMATURE_DATA')
    header_row.operator("gesturebone.switch_armature", text="", icon='ARROW_LEFTRIGHT')

    # ── Load Chains button ────────────────────────────────────────────────────
    load_row = layout.row(align=True)
    load_row.operator("gesturebone.load_chains", text="Load Chains", icon='FILE_REFRESH')

    # ── Chain cards ───────────────────────────────────────────────────────────
    chains = _chains_for_gesture_rig(arm)
    if not chains:
        hint = layout.row()
        hint.enabled = False
        hint.label(text="No chains — run Auto Rig or Load Chains", icon='INFO')
        return

    for chain in chains:
        is_bound   = _constraints_exist(arm, chain)
        is_live    = is_bound and not _constraints_are_muted(arm, chain)
        is_drawing = chain.is_drawing

        box = layout.box()
        stack = box.column(align=True)  # single aligned column → tight vertical spacing

        # ── Header row: collapse | name | status | bind toggle ───────────────
        header = stack.row(align=True)
        header.prop(chain, "ui_expanded",
                    icon='TRIA_DOWN' if chain.ui_expanded else 'TRIA_RIGHT',
                    text="", emboss=False)
        header.label(text=chain.part_name)

        status_sub = header.row(align=True)
        if is_drawing:
            status_sub.alert = True
            status_sub.label(text="", icon='GREASEPENCIL')
        elif is_bound:
            status_sub.label(text="", icon='CHECKMARK')
        else:
            status_sub.label(text="", icon='RADIOBUT_OFF')

        bind_sub = header.row(align=True)
        bind_sub.active_default = is_bound
        if is_bound:
            op = bind_sub.operator("gesturebone.delete_bone_constraints", text="", icon='LINKED')
        else:
            op = bind_sub.operator("gesturebone.create_bone_constraints", text="", icon='UNLINKED')
        op.part_name = chain.part_name

        if not chain.ui_expanded:
            continue

        # ── Body ─────────────────────────────────────────────────────────────
        body = stack.column(align=True)

        # Bindings (collapsible): Spline picker + control bones
        ctrl_header = body.row(align=True)
        ctrl_header.prop(
            chain, "control_bones_expanded",
            icon='TRIA_DOWN' if chain.control_bones_expanded else 'TRIA_RIGHT',
            text=f"Bindings ({len(chain.control_bones)})", emboss=False,
        )
        if chain.control_bones_expanded:
            ctrl_col = body.column(align=True)
            # Spline picker
            ctrl_col.prop(chain, "gesture_spline", text="Spline", icon='CURVE_BEZCURVE')
            if chain.control_bones:
                for i, entry in enumerate(chain.control_bones):
                    ctrl_col.prop(entry, "bone", text=f"  Bone {i}")
            else:
                no_b = ctrl_col.row()
                no_b.enabled = False
                no_b.label(text="No control bones — run Load Chains")

        if not is_bound:
            hint = body.row()
            hint.enabled = False
            hint.label(text="Bind (link) to enable drawing", icon='INFO')
            continue

        # ── Compact draw card (double-height row + slim slider row) ──────────
        card = stack.column(align=True)

        # Row 1 (double height): activate/toggle | switch dir | apply | delete
        row = card.row(align=True)
        row.scale_y = 2.0

        name_sub = row.row(align=True)
        name_sub.scale_x = 4.0
        name_sub.alert = is_drawing
        if is_drawing:
            # While drawing, the big button flips between Draw / Edit tools.
            if chain.active_tool == 'DRAW':
                tgl = name_sub.operator("gesturebone.toggle_spline_tool",
                                        text="Edit Handles", icon='CON_SPLINEIK', depress=True)
            else:
                tgl = name_sub.operator("gesturebone.toggle_spline_tool",
                                        text="Draw Stroke", icon='GREASEPENCIL', depress=True)
            tgl.part_name = chain.part_name
        else:
            act = name_sub.operator("gesturebone.activate_chain",
                                    text=chain.part_name, icon='GREASEPENCIL')
            act.part_name = chain.part_name

        dir_op = row.operator("gesturebone.switch_curve_direction", text="", icon='ARROW_LEFTRIGHT')
        dir_op.part_name = chain.part_name

        apply_op = row.operator("gesturebone.apply_to_bone", text="", icon='SORT_ASC')
        apply_op.part_name = chain.part_name

        del_op = row.operator("gesturebone.delete_baked_frames", text="", icon='KEY_DEHLT')
        del_op.part_name = chain.part_name

        # Row 2 (half height): smoothness slider | live-preview toggle
        row2 = card.row(align=True)
        row2.scale_y = 0.5
        row2.prop(chain, "bone_handle_smoothness", text="", slider=True)
        live_op = row2.operator("gesturebone.toggle_constraint_active",
                                text="", icon='HANDLE_ALIGNED', depress=is_live)
        live_op.part_name = chain.part_name

    # ── Debug: Chain Props ────────────────────────────────────────────────────
    scene_gp   = getattr(context.scene, 'gesturebone_props', None)
    debug_mode = getattr(scene_gp, 'debug_mode', False)
    if debug_mode and chains:
        layout.separator()
        debug_box = layout.box()
        debug_box.label(text="Debug: Chain Props", icon='TOOL_SETTINGS')
        for chain in chains:
            col = debug_box.column(align=True)
            col.label(text=chain.part_name, icon='BONE_DATA')
            col.label(text=f"  rig_completed_step: {chain.rig_completed_step}")
            col.label(text=f"  control_mode: {chain.control_mode}")
            col.label(text=f"  is_bound: {chain.is_bound}")
            col.label(text=f"  is_drawing: {chain.is_drawing}")
            col.label(text=f"  gesture_rig: {chain.gesture_rig.name if chain.gesture_rig else 'None'}")


def register():
    pass  # drawn inline from panels.py


def unregister():
    pass
