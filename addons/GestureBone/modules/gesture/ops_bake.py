"""
gesture/ops_bake.py — DeleteBakedFrames and drawing-state depsgraph handler.
Adapted from gesture_draw/operators_bake.py; reads from gesturebone_props.
"""
import bpy
from bpy.props import StringProperty
from ..shared.utils import _arm, _chains_for_gesture_rig
from ..shared.utils_bake import _get_fcurve_store
from ..shared.utils import bone_names as _bnames

_exit_confirm_pending = False


def reset_exit_confirm_pending():
    global _exit_confirm_pending
    _exit_confirm_pending = False


def clear_all_drawing_state():
    """Clear is_drawing on every chain on every armature."""
    global _exit_confirm_pending
    _exit_confirm_pending = False
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE':
            continue
        props = obj.gesturebone_props
        if props.rig_type == 'GESTURE':
            chains = _chains_for_gesture_rig(obj)
        elif props.rig_type == 'PLOTTING':
            chains = list(props.chains)
        else:
            continue
        for chain in chains:
            if chain.is_drawing:
                chain.is_drawing    = False
                chain.drawing_frame = -1


def _trigger_exit_confirm():
    global _exit_confirm_pending
    try:
        result = bpy.ops.gesturebone.confirm_exit_drawing('INVOKE_DEFAULT')
        if 'CANCELLED' in result:
            _exit_confirm_pending = False
    except Exception as e:
        print(f"GestureBone: confirm_exit_drawing failed: {e}")
        _exit_confirm_pending = False
    return None


@bpy.app.handlers.persistent
def _check_drawing_state(scene, depsgraph):
    """Detect when a gesture spline unexpectedly exits Edit mode and show confirmation popup."""
    global _exit_confirm_pending
    if _exit_confirm_pending:
        return

    ctx = bpy.context
    if ctx is None:
        return

    scene_gp = getattr(scene, 'gesturebone_props', None)
    if scene_gp is None:
        return
    arm = scene_gp.current_armature
    if arm is None or arm.type != 'ARMATURE':
        return

    props = arm.gesturebone_props
    if props.rig_type == 'GESTURE':
        chains = _chains_for_gesture_rig(arm)
    elif props.rig_type == 'PLOTTING':
        chains = list(props.chains)
    else:
        return

    active = getattr(ctx, 'active_object', None)
    mode   = getattr(ctx, 'mode', 'OBJECT')

    for chain in chains:
        if not chain.is_drawing:
            continue
        spline  = chain.gesture_spline
        if spline is None:
            continue
        in_edit = (active is spline and mode == 'EDIT_CURVE')
        if not in_edit:
            _exit_confirm_pending = True
            bpy.app.timers.register(_trigger_exit_confirm, first_interval=0.0)
            return


# ── Bone hierarchy helpers ────────────────────────────────────────────────────

def _iter_bone_and_descendants(arm_obj, bone_name):
    bone = arm_obj.data.bones.get(bone_name)
    if bone is None:
        return
    stack = [bone]
    while stack:
        b = stack.pop()
        yield b.name
        stack.extend(b.children)


def _collect_bones_with_descendants(arm_obj, names):
    seen   = set()
    result = []
    for name in names:
        if not name:
            continue
        for desc in _iter_bone_and_descendants(arm_obj, name):
            if desc not in seen:
                seen.add(desc)
                result.append(desc)
    return result


def _delete_bone_keypoints_at_frame(fcurves, arm_obj, bone_name, frame_num):
    pb = arm_obj.pose.bones.get(bone_name)
    if pb is None:
        return
    rot_mode = pb.rotation_mode
    if rot_mode == 'QUATERNION':
        rot_channels = [("rotation_quaternion", 4)]
    elif rot_mode == 'AXIS_ANGLE':
        rot_channels = [("rotation_axis_angle", 4)]
    else:
        rot_channels = [("rotation_euler", 3)]
    for path_suffix, n in [("location", 3)] + rot_channels + [("scale", 3)]:
        data_path = f'pose.bones["{bone_name}"].{path_suffix}'
        for idx in range(n):
            fc = fcurves.find(data_path, index=idx)
            if fc:
                to_remove = [kp for kp in fc.keyframe_points if abs(kp.co[0] - frame_num) < 0.5]
                for kp in reversed(to_remove):
                    fc.keyframe_points.remove(kp)


# ── Operator ─────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_DeleteBakedFrames(bpy.types.Operator):
    bl_idname      = "gesturebone.delete_baked_frames"
    bl_label       = "Delete Current Frame"
    bl_description = "Delete keyframes at the current frame for this chain's CTRL bones and descendants"
    bl_options     = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        from .ops_bind import _resolve
        gesture_arm, chain = _resolve(context, self.part_name)
        if gesture_arm is None or chain is None:
            return {'CANCELLED'}

        frame_num = context.scene.frame_current
        fcurves   = _get_fcurve_store(gesture_arm)
        if fcurves is None:
            return {'FINISHED'}

        all_bones = _collect_bones_with_descendants(gesture_arm, _bnames(chain))
        for bname in all_bones:
            _delete_bone_keypoints_at_frame(fcurves, gesture_arm, bname, frame_num)

        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_DeleteBakedFrames)
    if _check_drawing_state not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_check_drawing_state)


def unregister():
    if _check_drawing_state in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_check_drawing_state)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBakedFrames)
