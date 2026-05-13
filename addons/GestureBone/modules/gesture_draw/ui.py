import bpy
from .utils import _find_gn_modifier, _find_socket_id, _constraints_are_muted, _constraints_exist


def _chain_is_ready(mod_props, chain):
    has_bone = any(entry.bone for entry in chain.part_control_bones)
    return mod_props.part_gp is not None and chain.is_bound and has_bone


def _active_arm(context):
    obj = context.active_object
    if obj and obj.type == 'ARMATURE':
        return obj
    fallback = context.scene.gesturebone_props.current_armature
    return fallback if fallback and fallback.type == 'ARMATURE' else None


def _get_gp_invisible(mod_props):
    """Return True if the GP Invisible socket is ON (i.e. geometry is hidden)."""
    gp_obj = mod_props.part_gp if mod_props else None
    if not gp_obj:
        return False
    mod = _find_gn_modifier(gp_obj)
    if not mod:
        return False
    sid = _find_socket_id(mod, "Invisible")
    if sid is None:
        return False
    return bool(mod.get(sid, False))


class GESTUREBONE_PT_GestureDraw(bpy.types.Panel):
    bl_label = "GestureDraw"
    bl_idname = "GESTUREBONE_PT_gesture_draw"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_main"
    bl_order = 0

    def draw(self, context):
        pass


class GESTUREBONE_PT_GestureDrawBinding(bpy.types.Panel):
    """List and bind CurveBoneChain entries"""
    bl_label = "Binding"
    bl_idname = "GESTUREBONE_PT_gesture_draw_binding"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_gesture_draw"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        arm = _active_arm(context)

        if arm is None:
            row = layout.row()
            row.alert = True
            row.label(text="Select an armature to bind chains", icon='ERROR')
            return

        mod_props = getattr(arm, 'gesturebone_gesture_draw_props', None)
        if mod_props is None:
            layout.label(text="Properties not initialized", icon='ERROR')
            return

        gp_row = layout.row(align=True)
        gp_row.prop(mod_props, "part_gp", text="GP", icon='GREASEPENCIL')

        row = layout.row(align=True)
        row.operator("gesturebone.add_chain", icon='ADD', text="Add Chain")
        if mod_props.chains:
            row.operator("gesturebone.remove_chain", icon='REMOVE', text="").chain_index = len(mod_props.chains) - 1
        row.operator("gesturebone.refresh_all_chains", icon='FILE_REFRESH', text="")

        for i, chain in enumerate(mod_props.chains):
            ready = _chain_is_ready(mod_props, chain)
            box = layout.box()

            # ── Header row: collapse toggle | status | name | bind ──────────
            header = box.row(align=True)
            header.prop(
                chain, "bones_expanded",
                text="",
                icon='TRIA_DOWN' if chain.bones_expanded else 'TRIA_RIGHT',
                emboss=False,
            )
            header.label(text="", icon='LAYER_ACTIVE' if ready else 'ERROR')
            header.prop(chain, "part_name", text="")

            bind_sub = header.row(align=True)
            bind_sub.active_default = chain.is_bound
            if chain.is_bound:
                op = bind_sub.operator("gesturebone.delete_bone_constraints", text="", icon='LINKED')
            else:
                op = bind_sub.operator("gesturebone.create_bone_constraints", text="", icon='UNLINKED')
            op.chain_index = i

            # ── Body (only when expanded) ───────────────────────────────────
            if chain.bones_expanded:
                # Layer + Material row
                lm_row = box.row(align=True)
                lm_row.prop(chain, "part_layer", text="", icon='RENDERLAYERS')
                lm_row.prop(chain, "part_material", text="", icon='MATERIAL')

                col = box.column(align=True)

                # Gesture spline + control mode enum on same row
                gesture_row = col.row(align=True)
                gesture_row.prop(chain, "part_gesture_spline", text="Gesture Spline", icon='CURVE_BEZCURVE')
                pt_sub = gesture_row.row(align=True)
                pt_sub.scale_x = 0.65
                pt_sub.prop(chain, "part_control_mode", text="")

                # Control bones collapsible header + refresh button
                ctrl_header = col.row(align=True)
                ctrl_header.prop(
                    chain, "control_bones_expanded",
                    text="Control Bones",
                    icon='TRIA_DOWN' if chain.control_bones_expanded else 'TRIA_RIGHT',
                    emboss=False,
                )
                op = ctrl_header.operator("gesturebone.refresh_chain", text="", icon='FILE_REFRESH')
                op.chain_index = i
                if chain.control_bones_expanded:
                    for j, entry in enumerate(chain.part_control_bones):
                        col.prop(entry, "bone", text=f"  Bone {j + 1}")

                col.separator(factor=0.5)

                # Plotting spline + plotting mode enum on same row
                plotting_row = col.row(align=True)
                plotting_row.prop(chain, "part_plotting_spline", text="Plotting Spline", icon='CURVE_DATA')
                pp_sub = plotting_row.row(align=True)
                pp_sub.scale_x = 0.65
                pp_sub.prop(chain, "part_plotting_mode", text="")

                # Plotting bones collapsible header + refresh button
                plot_header = col.row(align=True)
                plot_header.prop(
                    chain, "plotting_bones_expanded",
                    text="Plotting Bones",
                    icon='TRIA_DOWN' if chain.plotting_bones_expanded else 'TRIA_RIGHT',
                    emboss=False,
                )
                op = plot_header.operator("gesturebone.refresh_chain", text="", icon='FILE_REFRESH')
                op.chain_index = i
                if chain.plotting_bones_expanded:
                    for j, entry in enumerate(chain.part_plotting_bones):
                        col.prop(entry, "bone", text=f"  Bone {j + 1}")


class GESTUREBONE_PT_GestureDrawGestures(bpy.types.Panel):
    """Perform gesture operations on the chain list"""
    bl_label = "Gesture Draw"
    bl_idname = "GESTUREBONE_PT_gesture_draw_gestures"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_gesture_draw"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        arm = _active_arm(context)

        if arm is None:
            row = layout.row()
            row.alert = True
            row.label(text="Select an armature", icon='ERROR')
            return

        mod_props = getattr(arm, 'gesturebone_gesture_draw_props', None)
        if mod_props is None:
            return

        # ── Top row: Pose↔GP toggle + Bake All + Delete All ─────────────────
        on_arm = arm is not None and context.view_layer.objects.active == arm
        top_row = layout.row(align=True)
        top_row.operator(
            "gesturebone.toggle_pose_gp",
            text="Edit Pose" if not on_arm else "Frame Gesture",
            icon='ARMATURE_DATA' if not on_arm else 'GP_SELECT_BETWEEN_STROKES',
        )
        top_row.operator("gesturebone.bake_all_chains", text="Bake All", icon='FILE_REFRESH')
        top_row.operator("gesturebone.delete_all_baked_frames", text="", icon='TRASH')

        if not mod_props.chains:
            layout.label(text="No chains — add in Binding", icon='INFO')
            return

        # ── Per-chain rows ───────────────────────────────────────────────────
        for i, chain in enumerate(mod_props.chains):
            row = layout.row(align=True)

            # Visibility eye — reads from GN Invisible socket
            is_invisible = _get_gp_invisible(mod_props)
            vis_sub = row.row(align=True)
            vis_sub.active_default = not is_invisible
            op = vis_sub.operator(
                "gesturebone.toggle_gp_visibility", text="",
                icon='HIDE_ON' if is_invisible else 'HIDE_OFF',
            )
            op.chain_index = i

            # Wide draw toggle
            draw_sub = row.row(align=True)
            draw_sub.scale_x = 4.0
            draw_sub.alert = chain.is_drawing
            op = draw_sub.operator(
                "gesturebone.toggle_drawing",
                text=chain.part_name or f"Chain {i + 1}",
                icon='GREASEPENCIL',
            )
            op.chain_index = i

            # Delete current frame keys + strokes, then restore last reference pose
            op = row.operator("gesturebone.delete_baked_frames", text="", icon='KEY_DEHLT')
            op.chain_index = i

            # Constraint toggle: active (unmuted) / muted / unbound
            con_sub = row.row(align=True)
            if chain.is_bound and arm and _constraints_exist(arm, chain):
                is_active = not _constraints_are_muted(arm, chain)
                con_sub.active_default = is_active
                icon = 'LINKED' if is_active else 'UNLINKED'
            else:
                con_sub.active_default = False
                icon = 'UNLINKED'
            op = con_sub.operator("gesturebone.toggle_constraint_active", text="", icon=icon)
            op.chain_index = i


_CHAIN_FIELDS = [
    ("part_name",                "Name"),
    ("part_layer",               "Layer"),
    ("part_material",            "Material"),
    ("part_gesture_spline",      "Gesture Spline"),
    ("part_control_mode",        "Control Mode"),
    ("part_control_point_count", "Control Count (derived)"),
    ("part_plotting_spline",     "Plotting Spline"),
    ("part_plotting_mode",       "Plotting Mode"),
    ("part_plotting_point_count","Plotting Count (derived)"),
    ("is_bound",                 "Is Bound"),
    ("is_drawing",               "Is Drawing"),
    ("bones_expanded",           "Bones Expanded"),
    ("control_bones_expanded",   "Ctrl Bones Expanded"),
    ("plotting_bones_expanded",  "Plot Bones Expanded"),
    ("prev_active_object",       "Prev Active Object"),
    ("prev_mode",                "Prev Mode"),
    ("last_baked_frame",         "Last Baked Frame"),
    ("stroke_count_cache",       "Stroke Count Cache"),
    ("drawing_frame",            "Drawing Frame"),
]


class GESTUREBONE_PT_GestureDrawDebug(bpy.types.Panel):
    """Live view of all CurveBoneChain properties — visible only in debug mode"""
    bl_label = "Debug: Chain Props"
    bl_idname = "GESTUREBONE_PT_gesture_draw_debug"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_main"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = -1

    @classmethod
    def poll(cls, context):
        return getattr(context.scene.gesturebone_props, 'debug_mode', False)

    def draw(self, context):
        layout = self.layout
        arm = _active_arm(context)

        if arm is None:
            layout.label(text="No armature", icon='ERROR')
            return

        mod_props = getattr(arm, 'gesturebone_gesture_draw_props', None)
        if mod_props is None:
            layout.label(text="Props not initialized", icon='ERROR')
            return

        if not mod_props.chains:
            layout.label(text="No chains", icon='INFO')
            return

        for i, chain in enumerate(mod_props.chains):
            box = layout.box()
            box.label(text=f"[{i}]  {chain.part_name or '(unnamed)'}", icon='SEQUENCE_COLOR_0' if chain.is_drawing else 'LAYER_USED')
            col = box.column(align=True)
            for attr, label in _CHAIN_FIELDS:
                col.prop(chain, attr, text=label)
            col.label(text=f"Control Bones ({len(chain.part_control_bones)})")
            for j, entry in enumerate(chain.part_control_bones):
                col.prop(entry, "bone", text=f"  [{j}]")
            col.label(text=f"Plotting Bones ({len(chain.part_plotting_bones)})")
            for j, entry in enumerate(chain.part_plotting_bones):
                col.prop(entry, "bone", text=f"  [{j}]")


def register():
    bpy.utils.register_class(GESTUREBONE_PT_GestureDraw)
    bpy.utils.register_class(GESTUREBONE_PT_GestureDrawBinding)
    bpy.utils.register_class(GESTUREBONE_PT_GestureDrawGestures)
    bpy.utils.register_class(GESTUREBONE_PT_GestureDrawDebug)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDrawDebug)
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDrawGestures)
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDrawBinding)
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDraw)
