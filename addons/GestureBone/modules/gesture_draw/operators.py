import bpy
from bpy.props import IntProperty
from .utils import (
    _CONSTRAINT_NAME, _CONSTRAINT_TYPE,
    _arm, _mod_props, _get_chain, _bone_names,
    _apply_and_key_data, _count_strokes_at_frame,
    _mute_constraints, _unmute_constraints,
    _constraints_exist, _constraints_are_muted,
    _find_gn_modifier, _find_socket_id,
    _copy_last_frame_strokes,
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
        gp_obj = chain.part_gp or context.scene.gesturebone_props.current_gp
        if not gp_obj:
            self.report({'ERROR'}, "GP object not set on this chain")
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
            con.target = gp_obj
            con.apply_target_transform = True
            con.attribute_name = "instance_transform"
            con.data_type = 'FLOAT4X4'
            con.domain = 'INSTANCE'
            con.sample_index = i + self.chain_index * 5
            con.mix_mode = 'REPLACE'
            con.influence = 1.0
            con.mute = True  # start muted; unmuted only during active drawing

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

        if chain.is_drawing:
            depsgraph = context.evaluated_depsgraph_get()
            _apply_and_key_data(arm_obj, chain, context.scene.frame_current, depsgraph)

        if not _constraints_exist(arm_obj, chain):
            bpy.ops.gesturebone.create_bone_constraints(chain_index=self.chain_index)
            _unmute_constraints(arm_obj, chain)
        elif _constraints_are_muted(arm_obj, chain):
            _unmute_constraints(arm_obj, chain)
        else:
            _mute_constraints(arm_obj, chain)

        return {'FINISHED'}


# ── Drawing operators ──────────────────────────────────────────────────────────

class GESTUREBONE_OT_ToggleDrawing(bpy.types.Operator):
    """Toggle: enter GP draw mode (ON) / bake + restore previous state (OFF)"""
    bl_idname = "gesturebone.toggle_drawing"
    bl_label = "Toggle Drawing"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if mod_props is None or chain is None:
            return {'CANCELLED'}
        arm_obj = _arm(context)
        gp_obj = chain.part_gp or context.scene.gesturebone_props.current_gp

        if chain.is_drawing:
            if arm_obj and _constraints_exist(arm_obj, chain):
                depsgraph = context.evaluated_depsgraph_get()
                _apply_and_key_data(arm_obj, chain, context.scene.frame_current, depsgraph)
                _mute_constraints(arm_obj, chain)
            chain.is_drawing = False
            chain.drawing_frame = -1
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            if arm_obj:
                bpy.ops.object.select_all(action='DESELECT')
                arm_obj.select_set(True)
                context.view_layer.objects.active = arm_obj
                bpy.ops.object.mode_set(mode='POSE')
        else:
            if not gp_obj:
                self.report({'ERROR'}, "No GP object set")
                return {'CANCELLED'}
            for j, other in enumerate(mod_props.chains):
                if j != self.chain_index and other.is_drawing:
                    if arm_obj and _constraints_exist(arm_obj, other):
                        depsgraph = context.evaluated_depsgraph_get()
                        _apply_and_key_data(arm_obj, other, context.scene.frame_current, depsgraph)
                        _mute_constraints(arm_obj, other)
                    other.is_drawing = False
                    other.drawing_frame = -1
            if context.active_object:
                chain.prev_active_object = context.active_object.name
                chain.prev_mode = context.active_object.mode
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            # Prepare GP frame data before entering paint mode so the copy is
            # not disrupted by mode-switch side-effects on GP data.
            frame_num = context.scene.frame_current
            _copy_last_frame_strokes(chain, frame_num)
            # Fallback: ensure every layer has a frame at frame_current
            for layer in gp_obj.data.layers:
                try:
                    if not any(f.frame_number == frame_num for f in layer.frames):
                        layer.frames.new(frame_num)
                except Exception:
                    pass
            bpy.ops.object.select_all(action='DESELECT')
            gp_obj.select_set(True)
            context.view_layer.objects.active = gp_obj
            bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')
            mat = chain.part_material
            if mat:
                for i, slot in enumerate(gp_obj.material_slots):
                    if slot.material == mat:
                        gp_obj.active_material_index = i
                        break
            if arm_obj:
                if not _constraints_exist(arm_obj, chain):
                    bpy.ops.gesturebone.create_bone_constraints(chain_index=self.chain_index)
                # Count strokes after the frame is ready, before unmuting so the
                # depsgraph handler doesn't see a stale baseline and double-bake.
                chain.stroke_count_cache = _count_strokes_at_frame(chain, frame_num)
                _unmute_constraints(arm_obj, chain)
            chain.drawing_frame = frame_num
            chain.is_drawing = True

        return {'FINISHED'}


class GESTUREBONE_OT_ToggleGPVisibility(bpy.types.Operator):
    """Toggle the Invisible socket on this chain's GP geometry node modifier"""
    bl_idname = "gesturebone.toggle_gp_visibility"
    bl_label = "Toggle GP Visibility"
    chain_index: IntProperty()

    def execute(self, context):
        chain = _get_chain(context, self.chain_index)
        if not chain or not chain.part_gp:
            return {'CANCELLED'}
        gp_obj = chain.part_gp
        mod = _find_gn_modifier(gp_obj)
        if not mod:
            mod = gp_obj.modifiers.new(name="TOB-Gesture_drawing", type='NODES')
            self.report({'WARNING'}, "Added empty GeoNode modifier — assign the TOB-Gesture_drawing node group")
            return {'FINISHED'}
        socket_id = _find_socket_id(mod, "Invisible")
        if socket_id is None:
            self.report({'WARNING'}, f"Socket 'Invisible' not found in modifier '{mod.name}'")
            return {'CANCELLED'}
        mod[socket_id] = not mod[socket_id]
        gp_obj.update_tag()
        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_CreateBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleConstraintActive)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleDrawing)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleGPVisibility)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleGPVisibility)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleDrawing)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleConstraintActive)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.unregister_class(GESTUREBONE_OT_CreateBoneConstraints)
