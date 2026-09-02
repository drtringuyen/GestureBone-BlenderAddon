"""
shared/utils_bake.py — Keyframing helpers.
Moved from gesture_draw/utils_bake.py; updated to read chain.control_bones.
"""
import bpy
from .utils import bone_names


def _get_fcurve_store(arm_obj):
    """F-curve collection for this armature's action (handles Blender <4.4 and 4.4+)."""
    anim = arm_obj.animation_data
    if not anim or not anim.action:
        return None
    action = anim.action
    if hasattr(action, 'fcurves'):
        return action.fcurves
    try:
        slot = getattr(anim, 'action_slot', None)
        if slot is None and action.slots:
            slot = action.slots[0]
        if slot is None:
            return None
        for layer in action.layers:
            for strip in layer.strips:
                for method_name in ('channelbag', 'channelbag_for_slot'):
                    cb_fn = getattr(strip, method_name, None)
                    if cb_fn:
                        try:
                            cb = cb_fn(slot)
                            if cb and hasattr(cb, 'fcurves'):
                                return cb.fcurves
                        except Exception:
                            pass
    except Exception:
        pass
    return None


def _locked_flags(pose_bone, data_path):
    """Per-component lock flags for a transform channel, in F-Curve array order."""
    if data_path == "location":
        return tuple(pose_bone.lock_location)
    if data_path == "scale":
        return tuple(pose_bone.lock_scale)
    if data_path == "rotation_euler":
        return tuple(pose_bone.lock_rotation)
    # quaternion is (W, X, Y, Z), axis_angle is (angle, X, Y, Z) — slot 0 is lock_rotation_w
    if data_path in {"rotation_quaternion", "rotation_axis_angle"}:
        return (pose_bone.lock_rotation_w,) + tuple(pose_bone.lock_rotation)
    return ()


def _key_unlocked(pose_bone, data_path, frame):
    """Key a transform channel component-by-component, skipping locked axes.

    Keying the whole vector makes Blender attempt the locked components too; RNA
    reports those as non-editable and Blender logs
    "anim.action | WARNING Could not insert key into FCurve ...".
    """
    flags = _locked_flags(pose_bone, data_path)
    if not any(flags):
        pose_bone.keyframe_insert(data_path=data_path, frame=frame)
        return
    for index, locked in enumerate(flags):
        if not locked:
            pose_bone.keyframe_insert(data_path=data_path, index=index, frame=frame)


def _apply_and_key_data(arm_obj, chain, frame, depsgraph):
    """Bake visual transform to local space and insert keyframes — no mode switching."""
    arm_eval = arm_obj.evaluated_get(depsgraph)
    for bname in bone_names(chain):
        pose_bone      = arm_obj.pose.bones.get(bname)
        pose_bone_eval = arm_eval.pose.bones.get(bname)
        if not pose_bone or not pose_bone_eval:
            continue
        pose_bone.matrix_basis = arm_obj.convert_space(
            pose_bone=pose_bone,
            matrix=pose_bone_eval.matrix,
            from_space='POSE',
            to_space='LOCAL',
        )
        _key_unlocked(pose_bone, "location", frame)
        if pose_bone.rotation_mode == 'QUATERNION':
            _key_unlocked(pose_bone, "rotation_quaternion", frame)
        elif pose_bone.rotation_mode == 'AXIS_ANGLE':
            _key_unlocked(pose_bone, "rotation_axis_angle", frame)
        else:
            _key_unlocked(pose_bone, "rotation_euler", frame)
        _key_unlocked(pose_bone, "scale", frame)
