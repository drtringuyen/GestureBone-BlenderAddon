"""
gesture/ui.py — UI for GESTURE rigs.
draw_gesture_ui() is called inline from panels.py when rig_type == 'GESTURE'.
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
    op = header_row.operator("gesturebone.switch_armature", text="→ Switch", icon='ARROW_LEFTRIGHT')

    # ── Load Chains button ────────────────────────────────────────────────────
    layout.operator("gesturebone.load_chains", text="↺ Load Chains", icon='FILE_REFRESH')

    # ── Chain rows ────────────────────────────────────────────────────────────
    chains = _chains_for_gesture_rig(arm)
    if not chains:
        hint = layout.row()
        hint.enabled = False
        hint.label(text="No chains — run Auto Rig or Load Chains", icon='INFO')
        return

    for chain in chains:
        is_bound  = _constraints_exist(arm, chain)
        is_live   = is_bound and not _constraints_are_muted(arm, chain)
        is_drawing = chain.is_drawing

        chain_box = layout.box()

        # Header
        header = chain_box.row(align=True)
        header.prop(chain, "ui_expanded",
                    icon='TRIA_DOWN' if chain.ui_expanded else 'TRIA_RIGHT',
                    text="", emboss=False)
        header.label(text=chain.part_name)

        # Bound status
        status_sub = header.row(align=True)
        if is_drawing:
            status_sub.alert = True
            status_sub.label(text="Drawing...", icon='GREASEPENCIL')
        elif is_bound:
            status_sub.label(text="Bound", icon='CHECKMARK')
        else:
            status_sub.label(text="Unbound", icon='RADIOBUT_OFF')

        # Bind / Unbind toggle
        if is_bound:
            op = header.operator("gesturebone.delete_bone_constraints", text="", icon='UNLINKED')
            op.part_name = chain.part_name
        else:
            op = header.operator("gesturebone.create_bone_constraints", text="", icon='LINKED')
            op.part_name = chain.part_name

        if not chain.ui_expanded:
            continue

        # Body
        body = chain_box.column(align=True)

        # Spline picker
        body.prop(chain, "gesture_spline", text="Spline")

        # Control bones (always visible for debugging)
        ctrl_header = body.row()
        ctrl_header.prop(
            chain, "control_bones_expanded",
            icon='TRIA_DOWN' if chain.control_bones_expanded else 'TRIA_RIGHT',
            text=f"Control Bones ({len(chain.control_bones)})", emboss=False,
        )
        if chain.control_bones_expanded:
            ctrl_col = body.column(align=True)
            if chain.control_bones:
                for i, entry in enumerate(chain.control_bones):
                    ctrl_col.prop(entry, "bone", text=f"[{i}]")
            else:
                no_b = ctrl_col.row()
                no_b.enabled = False
                no_b.label(text="No control bones — run Load Chains")

        # Draw controls
        if is_bound:
            draw_row = body.row(align=True)

            # Activate / Toggle tool button
            if is_drawing:
                tgl = draw_row.operator("gesturebone.toggle_spline_tool",
                                        text="Edit Mode" if chain.active_tool == 'DRAW' else "Draw Mode",
                                        icon='GREASEPENCIL', depress=True)
                tgl.part_name = chain.part_name
                # Apply and Delete Frame
                apply_row = body.row(align=True)
                apply_op = apply_row.operator("gesturebone.apply_to_bone",
                                              text="Apply to Bone", icon='CHECKMARK')
                apply_op.part_name = chain.part_name
                del_op = apply_row.operator("gesturebone.delete_baked_frames",
                                            text="", icon='TRASH')
                del_op.part_name = chain.part_name
            else:
                act_op = draw_row.operator("gesturebone.activate_chain",
                                           text="Activate Draw", icon='GREASEPENCIL')
                act_op.part_name = chain.part_name

            # Switch Direction
            dir_op = draw_row.operator("gesturebone.switch_curve_direction",
                                       text="", icon='ARROW_LEFTRIGHT')
            dir_op.part_name = chain.part_name

            # Smoothness slider
            body.prop(chain, "bone_handle_smoothness", text="Smoothness", slider=True)

            # Live preview toggle
            live_op = body.operator(
                "gesturebone.toggle_constraint_active",
                text="Live Preview",
                icon='HIDE_OFF' if is_live else 'HIDE_ON',
                depress=is_live,
            )
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
