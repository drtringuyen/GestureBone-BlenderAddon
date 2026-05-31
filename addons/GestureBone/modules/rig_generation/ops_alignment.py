"""
ops_alignment.py — Steps 3, 4, 5, 6: alignment empty workflow + depsgraph handler.
"""
import bpy
from mathutils import Vector
from .utils import _p, _meta_rig, _ensure_object_mode
from .scene_props import _get_bone_settings

_ALIGN_STATE = {}


def _alignment_scale_handler(scene, depsgraph):
    """Keep alignment empty scale equal to MetaBone world-space length (live)."""
    if not _ALIGN_STATE:
        return
    if not depsgraph.id_type_updated('OBJECT'):
        return
    try:
        empty_obj = bpy.data.objects.get(_ALIGN_STATE['empty'])
        arm_obj   = bpy.data.objects.get(_ALIGN_STATE['arm'])
        bone_name = _ALIGN_STATE['bone']
        if not empty_obj or not arm_obj:
            return
        arm_eval = arm_obj.evaluated_get(depsgraph)
        pb = arm_eval.pose.bones.get(bone_name)
        if not pb:
            return
        head_w = arm_eval.matrix_world @ pb.head
        tail_w = arm_eval.matrix_world @ pb.tail
        length = (tail_w - head_w).length
        if abs(empty_obj.scale[1] - length) > 1e-6:
            empty_obj.scale[1] = length
    except Exception:
        pass


def _register_align_handler():
    if _alignment_scale_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_alignment_scale_handler)


def _unregister_align_handler():
    if _alignment_scale_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_alignment_scale_handler)


# ─── PIVOT PLACEMENT HELPER ───────────────────────────────────────────────────

def _reposition_pivot_bones(context, wip_arm, meta_arm, bone_name):
    """Slide CTRL-{bone_name}.Rotation and CTRL-{bone_name}.Pivot heads to the
    MetaBone midpoint, keeping their original direction, length, and bone roll.

    After AcceptAndBind the WIP armature has transforms applied, so its
    matrix_world is effectively identity — centre_local ≈ centre_world.
    We still go through the full inverse to be safe.
    """
    data_bone = meta_arm.data.bones.get(bone_name)
    if not data_bone:
        return

    head_w   = meta_arm.matrix_world @ Vector(data_bone.head_local)
    tail_w   = meta_arm.matrix_world @ Vector(data_bone.tail_local)
    center_w = (head_w + tail_w) * 0.5

    # WIP armature local space (identity after transform_apply, but kept general)
    center_local = wip_arm.matrix_world.inverted() @ center_w

    target_names = [f"CTRL-{bone_name}.Rotation", f"CTRL-{bone_name}.Pivot"]

    _ensure_object_mode(context)
    bpy.ops.object.select_all(action='DESELECT')
    wip_arm.hide_set(False)
    wip_arm.select_set(True)
    context.view_layer.objects.active = wip_arm
    bpy.ops.object.mode_set(mode='EDIT')

    for bname in target_names:
        eb = wip_arm.data.edit_bones.get(bname)
        if eb:
            direction = eb.tail - eb.head   # preserve length and direction
            eb.head   = center_local.copy()
            eb.tail   = center_local + direction
            # bone roll is unchanged — only head/tail positions moved

    bpy.ops.object.mode_set(mode='OBJECT')


# ─── STEP 3 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ScaleEmptyToRestPose(bpy.types.Operator):
    bl_idname      = "gesturebone.scale_empty_to_rest_pose"
    bl_label       = "Scale Empty to Rest Pose"
    bl_description = "Set the alignment empty's uniform scale to the MetaBone's rest-pose world-space length"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found -- run Step 1 first")
            return {'CANCELLED'}

        data_bone = arm_obj.data.bones.get(bone_name)
        if not data_bone:
            self.report({'ERROR'}, f"Bone '{bone_name}' not found in MetaRig")
            return {'CANCELLED'}

        # Use the evaluated pose bone so pose-level scale/transforms are included.
        # The rest-pose data bone ignores pose scale — that's what caused the
        # "half bone" bug when the MetaBone was scaled bigger in pose mode.
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        arm_eval  = arm_obj.evaluated_get(depsgraph)
        pb_eval   = arm_eval.pose.bones.get(bone_name)
        if not pb_eval:
            self.report({'ERROR'}, f"Evaluated bone '{bone_name}' not found")
            return {'CANCELLED'}

        head_w       = arm_eval.matrix_world @ pb_eval.head
        tail_w       = arm_eval.matrix_world @ pb_eval.tail
        world_length = (tail_w - head_w).length
        bone_x_local = data_bone.matrix_local.col[0].xyz.length

        empty_obj.scale = (1.0, world_length, bone_x_local)

        self.report({'INFO'}, f"Empty scaled: x={bone_x_local:.4f} y={world_length:.4f} z=1.0")
        props.last_step      = self.bl_idname
        props.completed_step = 3
        return {'FINISHED'}


# ─── STEP 4 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_AddAlignConstraints(bpy.types.Operator):
    bl_idname      = "gesturebone.add_align_constraints"
    bl_label       = "Add Copy Loc & Rot Constraints"
    bl_description = "Add Copy Location and Copy Rotation constraints on the alignment empty targeting the MetaBone"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found -- run Step 1 first")
            return {'CANCELLED'}

        for con in list(empty_obj.constraints):
            empty_obj.constraints.remove(con)

        con_loc           = empty_obj.constraints.new('COPY_LOCATION')
        con_loc.name      = "GEN_CopyLoc"
        con_loc.target    = arm_obj
        con_loc.subtarget = bone_name

        con_rot           = empty_obj.constraints.new('COPY_ROTATION')
        con_rot.name      = "GEN_CopyRot"
        con_rot.target    = arm_obj
        con_rot.subtarget = bone_name

        con_scl           = empty_obj.constraints.new('COPY_SCALE')
        con_scl.name      = "GEN_CopyScaleZ"
        con_scl.target    = arm_obj
        con_scl.subtarget = bone_name
        con_scl.use_x     = False
        con_scl.use_y     = False
        con_scl.use_z     = True

        self.report({'INFO'}, f"Copy Location + Copy Rotation + Copy Scale Z added -> '{bone_name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 4
        return {'FINISHED'}


# ─── STEP 5 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_EditAlignmentInMetaRig(bpy.types.Operator):
    bl_idname      = "gesturebone.edit_alignment_in_metarig"
    bl_label       = "Edit Alignment in Meta Rig"
    bl_description = (
        "Enter Pose Mode on MetaRig; the alignment empty follows the bone live. "
        "Adjust the MetaBone pose, then click Step 6 to confirm"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found -- run Step 1 first")
            return {'CANCELLED'}

        _ALIGN_STATE.clear()
        _ALIGN_STATE.update({
            'arm':   arm_obj.name,
            'bone':  bone_name,
            'empty': empty_obj.name,
        })
        _register_align_handler()

        _ensure_object_mode(context)
        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.hide_set(False)
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        props.is_aligning    = True
        props.last_step      = self.bl_idname
        props.completed_step = 5
        self.report({'INFO'}, "Adjust MetaBone in Pose Mode -- then click Step 6 Accept & Bind")
        return {'FINISHED'}


# ─── STEP 6 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_AcceptAndBind(bpy.types.Operator):
    bl_idname      = "gesturebone.accept_and_bind"
    bl_label       = "Accept & Bind"
    bl_description = (
        "Bake the alignment empty's constraints, apply transforms to all children, "
        "unparent them keeping world position, then delete the empty"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found -- run Step 1 first")
            return {'CANCELLED'}

        _unregister_align_handler()
        _ALIGN_STATE.clear()
        _ensure_object_mode(context)

        # Force depsgraph evaluation so constraint-driven position is current.
        # This is critical when called without Step 5 (Rig Part / Auto Rig paths).
        context.view_layer.update()
        depsgraph    = context.evaluated_depsgraph_get()
        empty_eval   = empty_obj.evaluated_get(depsgraph)
        evaluated_matrix = empty_eval.matrix_world.copy()

        for con in list(empty_obj.constraints):
            empty_obj.constraints.remove(con)

        empty_obj.matrix_world = evaluated_matrix

        children = list(empty_obj.children)
        child_world_mats = {child: child.matrix_world.copy() for child in children}

        for child in children:
            child.parent       = None
            child.matrix_world = child_world_mats[child]

        for child in children:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                child.hide_set(False)
                child.select_set(True)
                context.view_layer.objects.active = child
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not apply transforms to '{child.name}': {e}")

        bpy.data.objects.remove(empty_obj, do_unlink=True)
        props.wip_empty   = ''
        props.is_aligning = False

        # Reposition pivot bones if requested (At Center mode)
        bone_name = props.active_meta_bone
        if bone_name and bone_name != 'NONE':
            settings = _get_bone_settings(props, bone_name)
            if settings.pivot_placement == 'CENTER':
                wip_arm  = next((c for c in children if c.type == 'ARMATURE'), None)
                meta_arm = _meta_rig(props)
                if wip_arm and meta_arm:
                    _reposition_pivot_bones(context, wip_arm, meta_arm, bone_name)

        props.last_step      = self.bl_idname
        props.completed_step = 6

        self.report({'INFO'}, f"Bound {len(children)} children -- alignment empty removed")
        return {'FINISHED'}


# ─── REGISTER ─────────────────────────────────────────────────────────────────

_classes = [
    GESTUREBONE_OT_ScaleEmptyToRestPose,
    GESTUREBONE_OT_AddAlignConstraints,
    GESTUREBONE_OT_EditAlignmentInMetaRig,
    GESTUREBONE_OT_AcceptAndBind,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    _unregister_align_handler()
    _ALIGN_STATE.clear()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
