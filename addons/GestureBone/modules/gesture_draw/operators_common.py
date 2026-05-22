import bpy
from bpy.props import IntProperty, EnumProperty, BoolProperty
from .utils import (
    _arm, _mod_props,
    _ensure_chain_objects,
    _cleanup_orphan_splines,
    _refresh_bone_lists,
)


class GESTUREBONE_OT_AddChain(bpy.types.Operator):
    """Add a new CurveBoneChain entry"""
    bl_idname = "gesturebone.add_chain"
    bl_label = "Add Chain"

    def execute(self, context):
        mod_props = _mod_props(context)
        if mod_props is None:
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}
        chain = mod_props.chains.add()
        chain.part_name = f"Chain {len(mod_props.chains)}"
        mod_props.active_chain_index = len(mod_props.chains) - 1
        return {'FINISHED'}


class GESTUREBONE_OT_RemoveChain(bpy.types.Operator):
    """Remove the selected CurveBoneChain entry"""
    bl_idname = "gesturebone.remove_chain"
    bl_label = "Remove Chain"
    chain_index: IntProperty()
    delete_gesture_spline: BoolProperty(name="Delete Gesture Spline", default=True)
    delete_plotting_spline: BoolProperty(name="Delete Plotting Spline", default=True)

    def invoke(self, context, event):
        mod_props = _mod_props(context)
        if mod_props is None or not (0 <= self.chain_index < len(mod_props.chains)):
            return {'CANCELLED'}
        chain = mod_props.chains[self.chain_index]
        self.delete_gesture_spline = chain.part_gesture_spline is not None
        self.delete_plotting_spline = chain.part_plotting_spline is not None
        if chain.part_gesture_spline or chain.part_plotting_spline:
            return context.window_manager.invoke_props_dialog(self, width=320)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        mod_props = _mod_props(context)
        if mod_props is None or not (0 <= self.chain_index < len(mod_props.chains)):
            return
        chain = mod_props.chains[self.chain_index]
        layout.label(text="Also delete these spline objects?", icon='QUESTION')
        if chain.part_gesture_spline:
            layout.prop(self, "delete_gesture_spline",
                        text=f"Gesture: '{chain.part_gesture_spline.name}'")
        if chain.part_plotting_spline:
            layout.prop(self, "delete_plotting_spline",
                        text=f"Plotting: '{chain.part_plotting_spline.name}'")

    def execute(self, context):
        mod_props = _mod_props(context)
        if mod_props is None:
            return {'CANCELLED'}
        idx = self.chain_index
        if not (0 <= idx < len(mod_props.chains)):
            return {'CANCELLED'}
        chain = mod_props.chains[idx]

        if self.delete_gesture_spline and chain.part_gesture_spline:
            try:
                bpy.data.objects.remove(chain.part_gesture_spline, do_unlink=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not remove gesture spline: {e}")

        if self.delete_plotting_spline and chain.part_plotting_spline:
            try:
                bpy.data.objects.remove(chain.part_plotting_spline, do_unlink=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not remove plotting spline: {e}")

        mod_props.chains.remove(idx)
        mod_props.active_chain_index = max(0, idx - 1)
        return {'FINISHED'}


class GESTUREBONE_OT_MoveChain(bpy.types.Operator):
    """Move a chain up or down in the list"""
    bl_idname = "gesturebone.move_chain"
    bl_label = "Move Chain"
    chain_index: IntProperty()
    direction: EnumProperty(items=[('UP', 'Up', ''), ('DOWN', 'Down', '')])

    def execute(self, context):
        mod_props = _mod_props(context)
        if mod_props is None:
            return {'CANCELLED'}
        idx = self.chain_index
        chains = mod_props.chains

        if self.direction == 'UP' and idx > 0:
            chains.move(idx, idx - 1)
            mod_props.active_chain_index = idx - 1
        elif self.direction == 'DOWN' and idx < len(chains) - 1:
            chains.move(idx, idx + 1)
            mod_props.active_chain_index = idx + 1
        else:
            return {'CANCELLED'}

        return {'FINISHED'}


class GESTUREBONE_OT_RefreshChain(bpy.types.Operator):
    """Resize bone lists, auto-fill from armature, and ensure spline objects exist"""
    bl_idname = "gesturebone.refresh_chain"
    bl_label = "Refresh Chain"
    chain_index: IntProperty()

    def execute(self, context):
        arm = _arm(context)
        mod_props = _mod_props(context)
        if mod_props is None or not (0 <= self.chain_index < len(mod_props.chains)):
            return {'CANCELLED'}
        chain = mod_props.chains[self.chain_index]
        _ensure_chain_objects(arm, chain, context)
        _refresh_bone_lists(chain)
        return {'FINISHED'}


class GESTUREBONE_OT_RefreshAllChains(bpy.types.Operator):
    """Sync spline objects with chain list: create missing, remove orphans, resize bone lists"""
    bl_idname = "gesturebone.refresh_all_chains"
    bl_label = "Refresh All Chains"

    def execute(self, context):
        arm = _arm(context)
        mod_props = _mod_props(context)
        if mod_props is None:
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}
        for chain in mod_props.chains:
            _ensure_chain_objects(arm, chain, context)
            _refresh_bone_lists(chain)
        _cleanup_orphan_splines(arm, mod_props, context.scene)
        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_AddChain)
    bpy.utils.register_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_MoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_RefreshChain)
    bpy.utils.register_class(GESTUREBONE_OT_RefreshAllChains)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_RefreshAllChains)
    bpy.utils.unregister_class(GESTUREBONE_OT_RefreshChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_MoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_AddChain)
