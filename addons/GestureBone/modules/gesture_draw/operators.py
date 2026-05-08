import bpy
from bpy.props import IntProperty

_CONSTRAINT_NAME = "GP_copy"
_CONSTRAINT_TYPE = "GEOMETRY_ATTRIBUTE"


def _arm(context):
    """Return the active armature, falling back to the last tracked one."""
    obj = context.active_object
    if obj and obj.type == 'ARMATURE':
        return obj
    fallback = context.scene.gesturebone_props.current_armature
    return fallback if fallback and fallback.type == 'ARMATURE' else None


def _mod_props(context):
    """Return the gesture_draw props for the active armature, or None."""
    obj = _arm(context)
    return obj.gesturebone_gesture_draw_props if obj else None


def _get_chain(context, index):
    props = _mod_props(context)
    return props.chains[index] if props else None


def _bone_names(chain):
    return [chain.bone_0, chain.bone_1, chain.bone_2, chain.bone_3, chain.bone_4]


# ── Collection management ──────────────────────────────────────────────────────

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
        if global_props.current_gp:
            chain.part_gp = global_props.current_gp
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


class GESTUREBONE_OT_ApplyAndKeyBoneConstraints(bpy.types.Operator):
    """Apply visual transforms of GP_copy constraints and insert keyframes"""
    bl_idname = "gesturebone.apply_and_key_bone_constraints"
    bl_label = "Apply and Key"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}

        prev_active = context.view_layer.objects.active
        prev_mode = context.object.mode if context.object else 'OBJECT'

        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        frame = context.scene.frame_current
        for bone_name in _bone_names(chain):
            if not bone_name:
                continue
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if not pose_bone:
                continue
            pose_bone.matrix_basis = arm_obj.convert_space(
                pose_bone=pose_bone,
                matrix=pose_bone.matrix,
                from_space='POSE',
                to_space='LOCAL',
            )
            pose_bone.keyframe_insert(data_path="location", frame=frame)
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            pose_bone.keyframe_insert(data_path="scale", frame=frame)

        bpy.ops.object.mode_set(mode='OBJECT')
        if prev_active:
            bpy.ops.object.select_all(action='DESELECT')
            prev_active.select_set(True)
            context.view_layer.objects.active = prev_active
            try:
                bpy.ops.object.mode_set(mode=prev_mode)
            except Exception:
                pass

        return {'FINISHED'}


# ── Mode / drawing operators ───────────────────────────────────────────────────

class GESTUREBONE_OT_ToggleDrawing(bpy.types.Operator):
    """Toggle: enter GP draw mode + set material (ON) / restore previous state (OFF)"""
    bl_idname = "gesturebone.toggle_drawing"
    bl_label = "Toggle Drawing"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if mod_props is None or chain is None:
            return {'CANCELLED'}
        gp_obj = chain.part_gp or context.scene.gesturebone_props.current_gp

        if chain.is_drawing:
            chain.is_drawing = False
            prev_obj = bpy.data.objects.get(chain.prev_active_object)
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            if prev_obj:
                bpy.ops.object.select_all(action='DESELECT')
                prev_obj.select_set(True)
                context.view_layer.objects.active = prev_obj
                try:
                    bpy.ops.object.mode_set(mode=chain.prev_mode)
                except Exception:
                    pass
        else:
            if not gp_obj:
                self.report({'ERROR'}, "No GP object set")
                return {'CANCELLED'}
            for j, other in enumerate(mod_props.chains):
                if j != self.chain_index and other.is_drawing:
                    other.is_drawing = False
            if context.active_object:
                chain.prev_active_object = context.active_object.name
                chain.prev_mode = context.active_object.mode
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
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
            chain.is_drawing = True

        return {'FINISHED'}


class GESTUREBONE_OT_ToggleGPVisibility(bpy.types.Operator):
    """Toggle the viewport visibility of this chain's GP object"""
    bl_idname = "gesturebone.toggle_gp_visibility"
    bl_label = "Toggle GP Visibility"
    chain_index: IntProperty()

    def execute(self, context):
        chain = _get_chain(context, self.chain_index)
        if chain and chain.part_gp:
            chain.part_gp.hide_viewport = not chain.part_gp.hide_viewport
        return {'FINISHED'}


class GESTUREBONE_OT_EditPose(bpy.types.Operator):
    """Select the active armature and enter Pose mode"""
    bl_idname = "gesturebone.edit_pose"
    bl_label = "Edit Pose"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
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


# ── Auto-reset is_drawing when user manually leaves GP draw mode ───────────────

def _check_drawing_state(scene, depsgraph):
    active = bpy.context.view_layer.objects.active if bpy.context else None
    mode = bpy.context.mode if bpy.context else ''
    for obj in scene.objects:
        if obj.type != 'ARMATURE':
            continue
        try:
            props = obj.gesturebone_gesture_draw_props
        except AttributeError:
            continue
        for chain in props.chains:
            if chain.is_drawing:
                gp_obj = chain.part_gp
                if active != gp_obj or mode != 'PAINT_GREASE_PENCIL':
                    chain.is_drawing = False


def register():
    bpy.utils.register_class(GESTUREBONE_OT_AddChain)
    bpy.utils.register_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.register_class(GESTUREBONE_OT_CreateBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_ApplyAndKeyBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleGPVisibility)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleDrawing)
    bpy.utils.register_class(GESTUREBONE_OT_EditPose)
    bpy.app.handlers.depsgraph_update_post.append(_check_drawing_state)


def unregister():
    if _check_drawing_state in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_check_drawing_state)
    bpy.utils.unregister_class(GESTUREBONE_OT_EditPose)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleDrawing)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleGPVisibility)
    bpy.utils.unregister_class(GESTUREBONE_OT_ApplyAndKeyBoneConstraints)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.unregister_class(GESTUREBONE_OT_CreateBoneConstraints)
    bpy.utils.unregister_class(GESTUREBONE_OT_RemoveChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_AddChain)
