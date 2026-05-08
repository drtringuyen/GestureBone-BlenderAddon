import bpy
from .utils import _find_gn_modifier, _find_socket_id, _constraints_are_muted, _constraints_exist


def _chain_is_ready(mod_props, chain):
    has_bone = any([chain.bone_0, chain.bone_1, chain.bone_2, chain.bone_3, chain.bone_4])
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
        gp_row.alert = mod_props.part_gp is None
        gp_row.prop(mod_props, "part_gp", text="GP", icon='GREASEPENCIL')

        row = layout.row(align=True)
        row.operator("gesturebone.add_chain", icon='ADD', text="Add Chain")
        if mod_props.chains:
            row.operator("gesturebone.remove_chain", icon='REMOVE', text="").chain_index = len(mod_props.chains) - 1

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
                bind_row = box.row(align=True)
                bind_row.label(text="Bindings")
                bind_row.prop(chain, "part_material", text="", icon='MATERIAL')

                col = box.column(align=True)
                for j, attr in enumerate(["bone_0", "bone_1", "bone_2", "bone_3", "bone_4"]):
                    col.prop(chain, attr, text=f"Bone {j + 1}")


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
            text="Edit Pose" if not on_arm else "Draw Gesture",
            icon='ARMATURE_DATA' if not on_arm else 'GP_ONLY_SELECTED',
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
            draw_sub.active_default = chain.is_drawing
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


def register():
    bpy.utils.register_class(GESTUREBONE_PT_GestureDraw)
    bpy.utils.register_class(GESTUREBONE_PT_GestureDrawBinding)
    bpy.utils.register_class(GESTUREBONE_PT_GestureDrawGestures)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDrawGestures)
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDrawBinding)
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDraw)
