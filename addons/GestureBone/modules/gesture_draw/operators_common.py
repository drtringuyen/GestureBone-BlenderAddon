import bpy
from bpy.props import IntProperty, StringProperty
from .utils import (
    _arm, _mod_props,
    _find_gn_modifier, _find_socket_id,
    _ensure_gp_object, _ensure_chain_objects,
    _ensure_gp_layer, _sync_gp_layers, _cleanup_orphan_splines,
    _refresh_bone_lists, _ensure_gp_animation,
)


class GESTUREBONE_OT_AddChain(bpy.types.Operator):
    """Add a new CurveBoneChain entry and its GP layer"""
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

        arm = _arm(context)
        if arm and mod_props.part_gp:
            _ensure_gp_layer(arm, chain)
        return {'FINISHED'}


class GESTUREBONE_OT_RemoveChain(bpy.types.Operator):
    """Remove the selected CurveBoneChain entry and its GP layer"""
    bl_idname = "gesturebone.remove_chain"
    bl_label = "Remove Chain"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        if mod_props is None:
            return {'CANCELLED'}
        idx = self.chain_index
        if not (0 <= idx < len(mod_props.chains)):
            return {'CANCELLED'}

        chain = mod_props.chains[idx]
        layer_name = chain.part_layer  # capture before removal

        # Delete GP layer by name
        gp_obj = mod_props.part_gp
        if gp_obj and layer_name and hasattr(gp_obj.data, 'layers'):
            layer = next((l for l in gp_obj.data.layers if l.name == layer_name), None)
            if layer is not None:
                try:
                    gp_obj.data.layers.remove(layer)
                except Exception as e:
                    self.report({'WARNING'}, f"Could not remove GP layer '{layer_name}': {e}")

        # Delete the gesture and plotting spline objects
        for spline_obj in (chain.part_gesture_spline, chain.part_plotting_spline):
            if spline_obj is not None:
                try:
                    bpy.data.objects.remove(spline_obj, do_unlink=True)
                except Exception as e:
                    self.report({'WARNING'}, f"Could not remove spline '{spline_obj.name}': {e}")

        mod_props.chains.remove(idx)
        mod_props.active_chain_index = max(0, idx - 1)
        return {'FINISHED'}


class GESTUREBONE_OT_MoveChain(bpy.types.Operator):
    """Move a chain up or down; GP layer order follows automatically"""
    bl_idname = "gesturebone.move_chain"
    bl_label = "Move Chain"
    chain_index: IntProperty()
    direction: StringProperty()  # 'UP' or 'DOWN'

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

        arm = _arm(context)
        if arm:
            from .utils_chain import _sort_gp_layers
            _sort_gp_layers(mod_props, mod_props.chains)
        return {'FINISHED'}


class GESTUREBONE_OT_TogglePoseGP(bpy.types.Operator):
    """Switch to GP object (Object mode) or back to armature (Pose mode)"""
    bl_idname = "gesturebone.toggle_pose_gp"
    bl_label = "Switch Active"

    def _going_to_gp(self, context):
        arm_obj = _arm(context)
        return arm_obj is not None and context.view_layer.objects.active == arm_obj

    def _set_gp_visible(self, gp_obj, visible):
        mod = _find_gn_modifier(gp_obj)
        if mod:
            socket_id = _find_socket_id(mod, "Invisible")
            if socket_id:
                mod[socket_id] = not visible
                gp_obj.update_tag()

    def execute(self, context):
        arm_obj = _arm(context)
        mod_props = _mod_props(context)
        gp_obj = (mod_props.part_gp if mod_props else None) or context.scene.gesturebone_props.current_gp
        if self._going_to_gp(context):
            if not gp_obj:
                self.report({'ERROR'}, "No GP object assigned")
                return {'CANCELLED'}
            if gp_obj:
                self._set_gp_visible(gp_obj, True)
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            gp_obj.select_set(True)
            context.view_layer.objects.active = gp_obj
        else:
            if not arm_obj:
                self.report({'ERROR'}, "No armature active")
                return {'CANCELLED'}
            if gp_obj:
                self._set_gp_visible(gp_obj, False)
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            arm_obj.select_set(True)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='POSE')
        return {'FINISHED'}


class GESTUREBONE_OT_RefreshChain(bpy.types.Operator):
    """Resize bone lists, auto-fill from armature, and ensure splines/layer exist"""
    bl_idname = "gesturebone.refresh_chain"
    bl_label = "Refresh Chain"
    chain_index: IntProperty()

    def execute(self, context):
        arm = _arm(context)
        mod_props = _mod_props(context)
        if mod_props is None or not (0 <= self.chain_index < len(mod_props.chains)):
            return {'CANCELLED'}
        chain = mod_props.chains[self.chain_index]
        _ensure_gp_object(arm, mod_props, context)
        _ensure_chain_objects(arm, chain, context)
        _ensure_gp_layer(arm, chain)
        _refresh_bone_lists(chain)
        return {'FINISHED'}


class GESTUREBONE_OT_RefreshAllChains(bpy.types.Operator):
    """Sync GP layers and spline objects with chain list: rename, create, remove orphans, reorder"""
    bl_idname = "gesturebone.refresh_all_chains"
    bl_label = "Refresh All Chains"

    def execute(self, context):
        arm = _arm(context)
        mod_props = _mod_props(context)
        if mod_props is None:
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}
        _ensure_gp_object(arm, mod_props, context)
        for chain in mod_props.chains:
            _ensure_chain_objects(arm, chain, context)
            _refresh_bone_lists(chain)
        _sync_gp_layers(arm, mod_props)
        _cleanup_orphan_splines(arm, mod_props, context.scene)
        _ensure_gp_animation(mod_props, mod_props.chains)
        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_AddChain)
    bpy.utils.register_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_MoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_TogglePoseGP)
    bpy.utils.register_class(GESTUREBONE_OT_RefreshChain)
    bpy.utils.register_class(GESTUREBONE_OT_RefreshAllChains)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_RefreshAllChains)
    bpy.utils.unregister_class(GESTUREBONE_OT_RefreshChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_TogglePoseGP)
    bpy.utils.unregister_class(GESTUREBONE_OT_MoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_AddChain)
