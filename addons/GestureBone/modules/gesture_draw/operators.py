import bpy
from bpy.props import IntProperty, EnumProperty
from .utils_gn import _ensure_object_collections_visible
from .utils import (
    _CONSTRAINT_NAME, _CONSTRAINT_TYPE,
    _arm, _mod_props, _get_chain, _bone_names,
    _apply_and_key_data,
    _mute_constraints, _unmute_constraints,
    _constraints_exist, _constraints_are_muted,
)


# ── Constraint operators ───────────────────────────────────────────────────────

class GESTUREBONE_OT_CreateBoneConstraints(bpy.types.Operator):
    """Add GP_copy Geometry Attribute constraints to all bones in this chain"""
    bl_idname = "gesturebone.create_bone_constraints"
    bl_label = "Create Bone Constraints"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}
        gesture_spline = chain.part_gesture_spline
        if not gesture_spline:
            self.report({'ERROR'}, "No gesture spline — refresh the chain first")
            return {'CANCELLED'}

        for i, bone_name in enumerate(_bone_names(chain)):
            if not bone_name:
                continue
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if not pose_bone:
                self.report({'WARNING'}, f"Bone not found: {bone_name}")
                continue

            for c in list(pose_bone.constraints):
                if c.type == _CONSTRAINT_TYPE:
                    pose_bone.constraints.remove(c)

            con = pose_bone.constraints.new(type=_CONSTRAINT_TYPE)
            con.name = _CONSTRAINT_NAME
            con.target = gesture_spline
            con.apply_target_transform = True
            con.attribute_name = "instance_transform"
            con.data_type = 'FLOAT4X4'
            con.domain = 'INSTANCE'
            con.sample_index = i  # each chain targets its own spline — index is bone slot within chain
            con.mix_mode = 'REPLACE'
            con.influence = 1.0
            con.mute = True  # start muted; unmuted only during apply_to_bone

        chain.is_bound = True
        return {'FINISHED'}


class GESTUREBONE_OT_DeleteBoneConstraints(bpy.types.Operator):
    """Remove all GP_copy constraints from bones in this chain"""
    bl_idname = "gesturebone.delete_bone_constraints"
    bl_label = "Delete Bone Constraints"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}

        for bone_name in _bone_names(chain):
            if not bone_name:
                continue
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if not pose_bone:
                continue
            for c in list(pose_bone.constraints):
                if c.name == _CONSTRAINT_NAME:
                    pose_bone.constraints.remove(c)

        chain.is_bound = False
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleConstraintActive(bpy.types.Operator):
    """Toggle GP_copy constraints on/off for this chain (creates them if absent)"""
    bl_idname = "gesturebone.toggle_constraint_active"
    bl_label = "Toggle Constraints"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}

        if not _constraints_exist(arm_obj, chain):
            bpy.ops.gesturebone.create_bone_constraints(chain_index=self.chain_index)
            _unmute_constraints(arm_obj, chain)
        elif _constraints_are_muted(arm_obj, chain):
            _unmute_constraints(arm_obj, chain)
        else:
            _mute_constraints(arm_obj, chain)

        return {'FINISHED'}


# ── Context helpers ────────────────────────────────────────────────────────────

def _view3d_ctx(context):
    """Return temp_override kwargs for a VIEW_3D window/area/region, or {} if none found.

    Needed when operators run from a popup dialog whose context is not VIEW_3D
    (e.g. ConfirmExitDrawing), so that mode_set / tool_set_by_id can poll correctly.
    """
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return {'window': window, 'area': area, 'region': region}
    return {}


def _deselect_all(context):
    """Deselect every object in the view layer without needing VIEW_3D context."""
    for obj in context.view_layer.objects:
        obj.select_set(False)


# ── Shared enter-edit-mode helper ─────────────────────────────────────────────

def _enter_spline_edit_mode(op, context, mod_props, chain, arm_obj, tool):
    """Deactivate all other chains, then enter curve Edit mode on chain's gesture spline."""
    gesture_spline = chain.part_gesture_spline
    if not gesture_spline:
        op.report({'ERROR'}, "No gesture spline — refresh the chain first")
        return {'CANCELLED'}

    # Deactivate every other drawing chain
    for other in mod_props.chains:
        if other != chain and other.is_drawing:
            other.is_drawing = False
            other.drawing_frame = -1

    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Clear existing splines when entering draw mode — fresh canvas
    if tool == 'DRAW' and gesture_spline.data.splines:
        gesture_spline.data.splines.clear()

    _ensure_object_collections_visible(context.view_layer, gesture_spline)
    gesture_spline.hide_set(False)

    bpy.ops.object.select_all(action='DESELECT')
    gesture_spline.select_set(True)
    context.view_layer.objects.active = gesture_spline
    bpy.ops.object.mode_set(mode='EDIT')

    tool_id = "builtin.draw" if tool == 'DRAW' else "builtin.select_box"
    bpy.ops.wm.tool_set_by_id(name=tool_id, space_type='VIEW_3D')

    chain.active_tool = tool
    chain.drawing_frame = context.scene.frame_current
    chain.is_drawing = True
    return {'FINISHED'}


# ── Drawing operators ──────────────────────────────────────────────────────────

class GESTUREBONE_OT_ActivateChain(bpy.types.Operator):
    """Enter curve Edit mode on this chain's gesture spline with the draw tool"""
    bl_idname = "gesturebone.activate_chain"
    bl_label = "Activate Chain"
    bl_options = {'REGISTER'}  # no UNDO — chain activation must not be on the undo stack
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if mod_props is None or chain is None:
            return {'CANCELLED'}
        arm_obj = _arm(context)
        return _enter_spline_edit_mode(self, context, mod_props, chain, arm_obj, 'DRAW')


class GESTUREBONE_OT_ToggleSplineTool(bpy.types.Operator):
    """Toggle between draw and edit-spline tools; activates the chain if not yet active"""
    bl_idname = "gesturebone.toggle_spline_tool"
    bl_label = "Toggle Spline Tool"
    bl_options = {'REGISTER'}  # no UNDO — chain activation must not be on the undo stack
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if mod_props is None or chain is None:
            return {'CANCELLED'}
        arm_obj = _arm(context)

        if not chain.is_drawing:
            # Not active — enter draw mode (clears existing splines)
            return _enter_spline_edit_mode(self, context, mod_props, chain, arm_obj, 'DRAW')

        gesture_spline = chain.part_gesture_spline
        in_edit = (gesture_spline
                   and context.active_object == gesture_spline
                   and context.mode == 'EDIT_CURVE')

        if chain.active_tool == 'DRAW':
            # Currently drawing — switch to edit/select tool (no clear)
            if in_edit:
                bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
            chain.active_tool = 'EDIT'
            return {'FINISHED'}
        else:
            # Currently editing — switch back to draw tool (clear and redraw)
            return _enter_spline_edit_mode(self, context, mod_props, chain, arm_obj, 'DRAW')


# ── Apply to bone ──────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ApplyToBone(bpy.types.Operator):
    """Exit spline edit mode, bake curve to GP, then key bone transforms for this chain"""
    bl_idname = "gesturebone.apply_to_bone"
    bl_label = "Apply to Bone"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None or mod_props is None:
            return {'CANCELLED'}
        if not _constraints_exist(arm_obj, chain):
            self.report({'ERROR'}, "No constraints — bind the chain first")
            return {'CANCELLED'}

        frame_num = chain.drawing_frame if chain.drawing_frame >= 0 else context.scene.frame_current

        # Mark as no longer drawing BEFORE mode_set — prevents the depsgraph handler
        # from treating the brief OBJECT-mode window as an unexpected exit.
        chain.is_drawing = False
        chain.drawing_frame = -1

        # Exit edit mode to finalise curve data
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Return to armature in Pose mode
        if arm_obj:
            bpy.ops.object.select_all(action='DESELECT')
            arm_obj.select_set(True)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='POSE')

        # Unmute constraints → evaluate → key bones → mute
        _unmute_constraints(arm_obj, chain)
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        _apply_and_key_data(arm_obj, chain, frame_num, depsgraph)
        _mute_constraints(arm_obj, chain)

        self.report({'INFO'}, f"Applied chain '{chain.part_name}' → frame {frame_num}")
        return {'FINISHED'}


# ── Drawing-exit confirmation ──────────────────────────────────────────────────

class GESTUREBONE_OT_ConfirmExitDrawing(bpy.types.Operator):
    """Shown when Undo or a mode switch exits the active gesture spline edit session"""
    bl_idname = "gesturebone.confirm_exit_drawing"
    bl_label = "Drawing Mode Interrupted"
    bl_options = {'REGISTER', 'INTERNAL'}

    action: EnumProperty(
        name="Action",
        items=[
            ('STOP', "Stop Drawing",      "Accept the undo — leave object mode"),
            ('EDIT', "Continue Editing",  "Re-enter edit mode with the select tool"),
            ('DRAW', "Continue Drawing",  "Re-enter edit mode with the draw tool"),
        ],
        default='STOP',
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Undo exited drawing mode.", icon='INFO')
        layout.separator(factor=0.5)
        layout.prop(self, "action", expand=True)

    def execute(self, context):
        from . import operators_bake as _ob
        _ob.reset_exit_confirm_pending()

        mod_props = _mod_props(context)
        arm_obj = _arm(context)
        if mod_props is None:
            return {'CANCELLED'}

        chain = next((c for c in mod_props.chains if c.is_drawing), None)
        if chain is None:
            return {'CANCELLED'}

        ov = _view3d_ctx(context)  # override for ops that poll VIEW_3D

        if self.action == 'STOP':
            chain.is_drawing = False
            chain.drawing_frame = -1
            if arm_obj:
                _deselect_all(context)
                arm_obj.select_set(True)
                context.view_layer.objects.active = arm_obj
                with context.temp_override(**ov):
                    bpy.ops.object.mode_set(mode='POSE')
        else:
            gesture_spline = chain.part_gesture_spline
            if not gesture_spline:
                chain.is_drawing = False
                chain.drawing_frame = -1
                return {'CANCELLED'}
            _ensure_object_collections_visible(context.view_layer, gesture_spline)
            gesture_spline.hide_set(False)
            with context.temp_override(**ov):
                if context.object and context.object.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
            # DRAW: clear the spline so the user starts fresh; EDIT: preserve undo state
            if self.action == 'DRAW' and gesture_spline.data.splines:
                gesture_spline.data.splines.clear()
            _deselect_all(context)
            gesture_spline.select_set(True)
            context.view_layer.objects.active = gesture_spline
            with context.temp_override(**ov):
                bpy.ops.object.mode_set(mode='EDIT')
                tool_id = "builtin.draw" if self.action == 'DRAW' else "builtin.select_box"
                bpy.ops.wm.tool_set_by_id(name=tool_id, space_type='VIEW_3D')
            chain.active_tool = 'DRAW' if self.action == 'DRAW' else 'EDIT'
            # is_drawing stays True; drawing_frame unchanged — session continues

        return {'FINISHED'}

    def cancel(self, context):
        """User pressed Escape — silently continue drawing (clears spline, fresh canvas)."""
        from . import operators_bake as _ob
        _ob.reset_exit_confirm_pending()
        mod_props = _mod_props(context)
        if mod_props is None:
            return
        chain = next((c for c in mod_props.chains if c.is_drawing), None)
        if chain is None:
            return
        gesture_spline = chain.part_gesture_spline
        if not gesture_spline:
            chain.is_drawing = False
            chain.drawing_frame = -1
            return
        _ensure_object_collections_visible(context.view_layer, gesture_spline)
        gesture_spline.hide_set(False)
        ov = _view3d_ctx(context)
        with context.temp_override(**ov):
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        if gesture_spline.data.splines:
            gesture_spline.data.splines.clear()
        _deselect_all(context)
        gesture_spline.select_set(True)
        context.view_layer.objects.active = gesture_spline
        with context.temp_override(**ov):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.wm.tool_set_by_id(name="builtin.draw", space_type='VIEW_3D')
        chain.active_tool = 'DRAW'
        # is_drawing stays True; drawing_frame unchanged — session continues


def register():
    bpy.utils.register_class(GESTUREBONE_OT_CreateBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleConstraintActive)
    bpy.utils.register_class(GESTUREBONE_OT_ActivateChain)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleSplineTool)
    bpy.utils.register_class(GESTUREBONE_OT_ApplyToBone)
    bpy.utils.register_class(GESTUREBONE_OT_ConfirmExitDrawing)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_ConfirmExitDrawing)
    bpy.utils.unregister_class(GESTUREBONE_OT_ApplyToBone)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleSplineTool)
    bpy.utils.unregister_class(GESTUREBONE_OT_ActivateChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleConstraintActive)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.unregister_class(GESTUREBONE_OT_CreateBoneConstraints)
