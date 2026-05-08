import bpy
from bpy.props import IntProperty
from .utils import _arm, _mod_props


class GESTUREBONE_OT_AddChain(bpy.types.Operator):
    """Add a new CurveBoneChain entry"""
    bl_idname = "gesturebone.add_chain"
    bl_label = "Add Chain"

    def execute(self, context):
        mod_props = _mod_props(context)
        if mod_props is None:
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}
        global_props = context.scene.gesturebone_props
        chain = mod_props.chains.add()
        chain.part_name = f"Chain {len(mod_props.chains)}"
        if global_props.current_gp and not mod_props.part_gp:
            mod_props.part_gp = global_props.current_gp
        mod_props.active_chain_index = len(mod_props.chains) - 1
        return {'FINISHED'}


class GESTUREBONE_OT_RemoveChain(bpy.types.Operator):
    """Remove the selected CurveBoneChain entry"""
    bl_idname = "gesturebone.remove_chain"
    bl_label = "Remove Chain"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        if mod_props is None:
            return {'CANCELLED'}
        idx = self.chain_index
        if 0 <= idx < len(mod_props.chains):
            mod_props.chains.remove(idx)
            mod_props.active_chain_index = max(0, idx - 1)
        return {'FINISHED'}


class GESTUREBONE_OT_TogglePoseGP(bpy.types.Operator):
    """Switch to GP object (Object mode) or back to armature (Pose mode)"""
    bl_idname = "gesturebone.toggle_pose_gp"
    bl_label = "Switch Active"

    def _going_to_gp(self, context):
        """True when the next action will switch TO the GP object."""
        arm_obj = _arm(context)
        return arm_obj is not None and context.view_layer.objects.active == arm_obj

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        arm_obj = _arm(context)
        mod_props = _mod_props(context)
        if self._going_to_gp(context):
            gp_obj = (mod_props.part_gp if mod_props else None) or context.scene.gesturebone_props.current_gp
            if not gp_obj:
                self.report({'ERROR'}, "No GP object assigned")
                return {'CANCELLED'}
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            gp_obj.select_set(True)
            context.view_layer.objects.active = gp_obj
        else:
            if not arm_obj:
                self.report({'ERROR'}, "No armature active")
                return {'CANCELLED'}
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            arm_obj.select_set(True)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='POSE')
        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_AddChain)
    bpy.utils.register_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_TogglePoseGP)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_TogglePoseGP)
    bpy.utils.unregister_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_AddChain)
