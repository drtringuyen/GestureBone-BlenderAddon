"""
gesture/ops_draw.py — Drawing operators: ActivateChain, ToggleSplineTool, ApplyToBone, ConfirmExitDrawing.
"""
import bpy
from bpy.props import StringProperty, EnumProperty
from ..shared.utils import _arm, _chains_for_gesture_rig
from ..shared.utils_constraints import (
    _constraints_exist, _mute_constraints, _unmute_constraints,
)
from ..shared.utils_bake import _apply_and_key_data
from ..shared.utils_gn import _ensure_object_collections_visible
from .ops_bind import _resolve


def _view3d_ctx(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return {'window': window, 'area': area, 'region': region}
    return {}


def _deselect_all(context):
    for obj in context.view_layer.objects:
        obj.select_set(False)


def _enter_spline_edit_mode(op, context, chain, gesture_arm, tool):
    gesture_spline = chain.gesture_spline
    if not gesture_spline:
        op.report({'ERROR'}, "No gesture spline — load chains first")
        return {'CANCELLED'}

    # Deactivate other drawing chains on this gesture rig
    arm = _arm(context)
    if arm and arm.gesturebone_props.rig_type == 'GESTURE':
        for other in _chains_for_gesture_rig(arm):
            if other != chain and other.is_drawing:
                other.is_drawing    = False
                other.drawing_frame = -1

    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

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

    chain.active_tool   = tool
    chain.drawing_frame = context.scene.frame_current
    chain.is_drawing    = True
    return {'FINISHED'}


# ── ACTIVATE CHAIN ────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ActivateChain(bpy.types.Operator):
    bl_idname  = "gesturebone.activate_chain"
    bl_label   = "Activate Chain"
    bl_options = {'REGISTER'}

    part_name: StringProperty()

    def execute(self, context):
        gesture_arm, chain = _resolve(context, self.part_name)
        if chain is None or gesture_arm is None:
            return {'CANCELLED'}
        return _enter_spline_edit_mode(self, context, chain, gesture_arm, 'DRAW')


# ── TOGGLE SPLINE TOOL ────────────────────────────────────────────────────────

class GESTUREBONE_OT_ToggleSplineTool(bpy.types.Operator):
    bl_idname  = "gesturebone.toggle_spline_tool"
    bl_label   = "Toggle Spline Tool"
    bl_options = {'REGISTER'}

    part_name: StringProperty()

    def execute(self, context):
        gesture_arm, chain = _resolve(context, self.part_name)
        if chain is None or gesture_arm is None:
            return {'CANCELLED'}

        if not chain.is_drawing:
            return _enter_spline_edit_mode(self, context, chain, gesture_arm, 'DRAW')

        gesture_spline = chain.gesture_spline
        in_edit = (gesture_spline
                   and context.active_object == gesture_spline
                   and context.mode == 'EDIT_CURVE')

        if chain.active_tool == 'DRAW':
            if in_edit:
                bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
            chain.active_tool = 'EDIT'
            return {'FINISHED'}
        else:
            return _enter_spline_edit_mode(self, context, chain, gesture_arm, 'DRAW')


# ── APPLY TO BONE ─────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ApplyToBone(bpy.types.Operator):
    bl_idname = "gesturebone.apply_to_bone"
    bl_label  = "Apply to Bone"

    part_name: StringProperty()

    def execute(self, context):
        gesture_arm, chain = _resolve(context, self.part_name)
        if gesture_arm is None or chain is None:
            return {'CANCELLED'}
        if not _constraints_exist(gesture_arm, chain):
            self.report({'ERROR'}, "No constraints — bind the chain first")
            return {'CANCELLED'}

        frame_num = chain.drawing_frame if chain.drawing_frame >= 0 else context.scene.frame_current

        chain.is_drawing    = False
        chain.drawing_frame = -1

        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        gesture_arm.select_set(True)
        context.view_layer.objects.active = gesture_arm
        bpy.ops.object.mode_set(mode='POSE')

        _unmute_constraints(gesture_arm, chain)
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        _apply_and_key_data(gesture_arm, chain, frame_num, depsgraph)
        _mute_constraints(gesture_arm, chain)

        self.report({'INFO'}, f"Applied chain '{chain.part_name}' → frame {frame_num}")
        return {'FINISHED'}


# ── CONFIRM EXIT DRAWING ──────────────────────────────────────────────────────

class GESTUREBONE_OT_ConfirmExitDrawing(bpy.types.Operator):
    bl_idname  = "gesturebone.confirm_exit_drawing"
    bl_label   = "Drawing Mode Interrupted"
    bl_options = {'REGISTER', 'INTERNAL'}

    action: EnumProperty(
        name="Action",
        items=[
            ('STOP', "Stop Drawing",     "Accept the undo — leave object mode"),
            ('EDIT', "Continue Editing", "Re-enter edit mode with the select tool"),
            ('DRAW', "Continue Drawing", "Re-enter edit mode with the draw tool"),
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
        from . import ops_bake as _ob
        _ob.reset_exit_confirm_pending()

        arm = _arm(context)
        if arm is None:
            return {'CANCELLED'}

        chain = None
        if arm.gesturebone_props.rig_type == 'GESTURE':
            chains = _chains_for_gesture_rig(arm)
        elif arm.gesturebone_props.rig_type == 'PLOTTING':
            chains = list(arm.gesturebone_props.chains)
        else:
            chains = []

        chain = next((c for c in chains if c.is_drawing), None)
        if chain is None:
            return {'CANCELLED'}

        ov = _view3d_ctx(context)

        if self.action == 'STOP':
            chain.is_drawing    = False
            chain.drawing_frame = -1
            if arm.gesturebone_props.rig_type == 'GESTURE':
                _deselect_all(context)
                arm.select_set(True)
                context.view_layer.objects.active = arm
                with context.temp_override(**ov):
                    bpy.ops.object.mode_set(mode='POSE')
        else:
            gesture_spline = chain.gesture_spline
            if not gesture_spline:
                chain.is_drawing    = False
                chain.drawing_frame = -1
                return {'CANCELLED'}
            _ensure_object_collections_visible(context.view_layer, gesture_spline)
            gesture_spline.hide_set(False)
            with context.temp_override(**ov):
                if context.object and context.object.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
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

        return {'FINISHED'}

    def cancel(self, context):
        from . import ops_bake as _ob
        _ob.reset_exit_confirm_pending()

        arm = _arm(context)
        if arm is None:
            return

        if arm.gesturebone_props.rig_type == 'GESTURE':
            chains = _chains_for_gesture_rig(arm)
        else:
            chains = []

        chain = next((c for c in chains if c.is_drawing), None)
        if chain is None:
            return
        gesture_spline = chain.gesture_spline
        if not gesture_spline:
            chain.is_drawing    = False
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


_classes = [
    GESTUREBONE_OT_ActivateChain,
    GESTUREBONE_OT_ToggleSplineTool,
    GESTUREBONE_OT_ApplyToBone,
    GESTUREBONE_OT_ConfirmExitDrawing,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
