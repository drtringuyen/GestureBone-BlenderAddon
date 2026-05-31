import bpy
from bpy.props import IntProperty, EnumProperty, BoolProperty
from .utils import (
    _arm, _mod_props,
    _ensure_chain_objects,
    _cleanup_orphan_splines,
    _refresh_bone_lists,
    _resize_collection,
)
from .curve_bone_chain import CONTROL_MODE_COUNT, _ctrl_bone_indices

_GN_GESTURE_NAME = "TOB-Gesture_drawing"


def _sync_gesture_spline_gn(chain):
    """Ensure the gesture spline has the TOB-Gesture_drawing modifier and
    its sockets match the chain's current settings (live after load/refresh)."""
    spline = chain.part_gesture_spline
    if spline is None:
        return
    ng = bpy.data.node_groups.get(_GN_GESTURE_NAME)
    if ng is None:
        return
    # Find or create the modifier
    mod = next((m for m in spline.modifiers if m.type == 'NODES' and m.node_group == ng), None)
    if mod is None:
        mod = spline.modifiers.new(name="GeometryNodes", type='NODES')
        mod.node_group = ng
    # Sync sockets
    mod["Socket_10"] = chain.part_control_point_count   # Control Point Count
    mod["Socket_8"]  = 2                                 # Resample Precision
    mod["Socket_6"]  = chain.bone_handle_smoothness      # Bone Handle Smoothness


def _get_bones_in_collection(arm_data, coll_name):
    """Return bone names assigned to a specific bone collection."""
    bc = arm_data.collections.get(coll_name)
    if not bc:
        return []
    try:
        return [b.name for b in bc.bones]
    except AttributeError:
        result = []
        for b in arm_data.bones:
            if any(c.name == coll_name for c in getattr(b, 'collections', [])):
                result.append(b.name)
        return result



def _switch_spline_direction(curve_obj):
    """Reverse every spline in curve_obj using the data API.

    Works regardless of whether the object is in the view layer, selected,
    or in any particular mode.  Returns the number of splines reversed.
    """
    reversed_count = 0
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            pts  = spline.bezier_points
            n    = len(pts)
            snap = [(
                p.co.copy(),
                p.handle_left.copy(),  p.handle_right.copy(),
                p.handle_left_type,    p.handle_right_type,
                p.radius, p.tilt, p.weight_softbody,
            ) for p in pts]
            for i, p in enumerate(pts):
                co, hl, hr, ht_l, ht_r, rad, tilt, wsb = snap[n - 1 - i]
                p.co                = co
                p.handle_left       = hr    # left ↔ right swapped when reversed
                p.handle_right      = hl
                p.handle_left_type  = ht_r
                p.handle_right_type = ht_l
                p.radius            = rad
                p.tilt              = tilt
                p.weight_softbody   = wsb
            reversed_count += 1
        elif spline.type in ('NURBS', 'POLY'):
            pts  = spline.points
            n    = len(pts)
            snap = [(p.co.copy(), p.radius, p.tilt, p.weight_softbody) for p in pts]
            for i, p in enumerate(pts):
                co, rad, tilt, wsb = snap[n - 1 - i]
                p.co              = co
                p.radius          = rad
                p.tilt            = tilt
                p.weight_softbody = wsb
            reversed_count += 1
    curve_obj.data.update_tag()
    return reversed_count


class GESTUREBONE_OT_SwitchCurveDirection(bpy.types.Operator):
    """Reverse the direction of the gesture spline for this chain"""
    bl_idname  = "gesturebone.switch_curve_direction"
    bl_label   = "Switch Curve Direction"
    bl_options = {'REGISTER', 'UNDO'}

    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        if mod_props is None or not (0 <= self.chain_index < len(mod_props.chains)):
            return {'CANCELLED'}
        chain  = mod_props.chains[self.chain_index]
        spline = chain.part_gesture_spline
        if spline is None:
            self.report({'WARNING'}, "No gesture spline assigned to this chain")
            return {'CANCELLED'}

        n = _switch_spline_direction(spline)
        self.report({'INFO'}, f"Switched direction of '{spline.name}' ({n} spline(s))")
        return {'FINISHED'}


class GESTUREBONE_OT_LoadChainsFromMetaRig(bpy.types.Operator):
    """Clear chains and rebuild one per MetaBone, linking existing splines and control bones"""
    bl_idname = "gesturebone.load_chains_from_meta_rig"
    bl_label  = "Load Chain From Meta Rig"

    def execute(self, context):
        # Access rig_generation scene props without importing from sibling module
        rig_gen = getattr(context.scene, 'gesturebone_rig_generation_props', None)
        if rig_gen is None:
            self.report({'ERROR'}, "Rig Generation module not active — enable it first")
            return {'CANCELLED'}

        meta_rig_name  = rig_gen.meta_rig
        meta_coll_name = rig_gen.meta_collection

        meta_arm = bpy.data.objects.get(meta_rig_name)
        if not meta_arm or meta_arm.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{meta_rig_name}' not found")
            return {'CANCELLED'}

        bone_names = _get_bones_in_collection(meta_arm.data, meta_coll_name)
        if not bone_names:
            self.report({'ERROR'}, f"No bones found in collection '{meta_coll_name}'")
            return {'CANCELLED'}

        # Always target the merged .Gesture armature — redirect current_armature to it
        gesture_arm_name = f"{meta_rig_name}.Gesture"
        gesture_arm      = bpy.data.objects.get(gesture_arm_name)

        if gesture_arm and gesture_arm.type == 'ARMATURE':
            # Wipe stale is_drawing flags on ALL armatures to prevent spurious popup loops.
            from . import operators_bake as _ob
            _ob.clear_all_drawing_state()

            mod_props = gesture_arm.gesturebone_gesture_draw_props
        else:
            # Gesture armature not generated yet — fall back to whatever is active
            mod_props = _mod_props(context)
            gesture_arm = None

        if mod_props is None:
            self.report({'ERROR'}, "No armature found — select one or generate the rig first")
            return {'CANCELLED'}

        # Clear existing chains
        mod_props.chains.clear()
        mod_props.active_chain_index = 0

        built = 0
        for bone_name in bone_names:
            chain = mod_props.chains.add()
            chain.part_name = bone_name

            # Sync Control Mode from rig_generation bone_settings if available
            bone_settings = rig_gen.bone_settings.get(bone_name)
            if bone_settings:
                chain.part_control_mode        = bone_settings.control_mode
                chain.part_control_point_count = CONTROL_MODE_COUNT.get(bone_settings.control_mode, 5)
            _resize_collection(chain.part_control_bones, chain.part_control_point_count)

            # Link GestureSpline — prefer canonical naming (RigName-Bone.GestureSpline)
            # then fall back to legacy merged naming (RigName.Gesture_Bone_GestureSpline)
            g_obj = (
                bpy.data.objects.get(f"{meta_rig_name}-{bone_name}.GestureSpline")
                or bpy.data.objects.get(f"{gesture_arm_name}_{bone_name}_GestureSpline")
            )
            if g_obj and g_obj.type == 'CURVE':
                chain.part_gesture_spline = g_obj

            # Link PlottingSpline — same preference order
            p_obj = (
                bpy.data.objects.get(f"{meta_rig_name}-{bone_name}.PlottingSpline")
                or bpy.data.objects.get(f"{gesture_arm_name}_{bone_name}_PlottingSpline")
            )
            if p_obj and p_obj.type == 'CURVE':
                chain.part_plotting_spline = p_obj

            # Auto-populate control bones using the 0-based index convention:
            # template keeps CTRL-{bone}_0…_4; PT_3 deletes _1,_3 → _0,_2,_4 remain;
            # PT_2 keeps _0,_4; PT_5 keeps all five.
            if gesture_arm:
                indices = _ctrl_bone_indices(chain.part_control_point_count)
                for i, entry in enumerate(chain.part_control_bones):
                    if i < len(indices):
                        ctrl_name = f"CTRL-{bone_name}_{indices[i]}"
                        if gesture_arm.data.bones.get(ctrl_name):
                            entry.bone = ctrl_name

            built += 1

        target_name = gesture_arm.name if gesture_arm else "current armature"

        # Auto-create (or refresh) bone constraints; sync GN modifier for every chain
        for i in range(len(mod_props.chains)):
            chain_i = mod_props.chains[i]
            if chain_i.part_gesture_spline:
                bpy.ops.gesturebone.create_bone_constraints(chain_index=i)
                _sync_gesture_spline_gn(chain_i)

        self.report({'INFO'}, f"Loaded {built} chain(s) from '{meta_rig_name}' onto '{target_name}'")
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
    """Resize bone lists, auto-fill control bones from .Gesture armature, and ensure spline objects exist"""
    bl_idname = "gesturebone.refresh_chain"
    bl_label = "Refresh Chain"
    chain_index: IntProperty()

    def execute(self, context):
        arm       = _arm(context)
        mod_props = _mod_props(context)
        if mod_props is None or not (0 <= self.chain_index < len(mod_props.chains)):
            return {'CANCELLED'}
        chain = mod_props.chains[self.chain_index]
        _ensure_chain_objects(arm, chain, context)
        _refresh_bone_lists(chain)

        # Auto-populate control bones from the generated .Gesture armature
        # Uses the 0-based index convention (_0…_4); PT_3 keeps _0,_2,_4 etc.
        rig_gen = getattr(context.scene, 'gesturebone_rig_generation_props', None)
        if rig_gen:
            gesture_arm_name = f"{rig_gen.meta_rig}.Gesture"
            gesture_arm = bpy.data.objects.get(gesture_arm_name)
            if gesture_arm and gesture_arm.type == 'ARMATURE':
                part_name = chain.part_name
                indices   = _ctrl_bone_indices(chain.part_control_point_count)
                for i, entry in enumerate(chain.part_control_bones):
                    if i < len(indices):
                        ctrl_name = f"CTRL-{part_name}_{indices[i]}"
                        entry.bone = ctrl_name if gesture_arm.data.bones.get(ctrl_name) else entry.bone

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

        # Auto-create (or refresh) bone constraints; sync GN modifier for every chain
        for i in range(len(mod_props.chains)):
            chain_i = mod_props.chains[i]
            if chain_i.part_gesture_spline:
                bpy.ops.gesturebone.create_bone_constraints(chain_index=i)
                _sync_gesture_spline_gn(chain_i)

        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_SwitchCurveDirection)
    bpy.utils.register_class(GESTUREBONE_OT_LoadChainsFromMetaRig)
    bpy.utils.register_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_MoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_RefreshChain)
    bpy.utils.register_class(GESTUREBONE_OT_RefreshAllChains)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_RefreshAllChains)
    bpy.utils.unregister_class(GESTUREBONE_OT_RefreshChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_MoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_LoadChainsFromMetaRig)
    bpy.utils.unregister_class(GESTUREBONE_OT_SwitchCurveDirection)
