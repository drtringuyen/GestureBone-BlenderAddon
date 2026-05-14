import bpy
from .utils_context import _bone_names


def _get_fcurve_store(arm_obj):
    """Return the F-curve collection for this armature's action.

    Handles both Blender < 4.4 (action.fcurves) and Blender 4.4+ slotted actions
    (action.layers[].strips[].channelbag(slot).fcurves).
    Returns None if no action or access fails.
    """
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


def _apply_and_key_data(arm_obj, chain, frame, depsgraph):
    """Bake visual transform to local space and insert keyframes — no mode switching."""
    arm_eval = arm_obj.evaluated_get(depsgraph)
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pose_bone = arm_obj.pose.bones.get(bone_name)
        pose_bone_eval = arm_eval.pose.bones.get(bone_name)
        if not pose_bone or not pose_bone_eval:
            continue
        pose_bone.matrix_basis = arm_obj.convert_space(
            pose_bone=pose_bone,
            matrix=pose_bone_eval.matrix,
            from_space='POSE',
            to_space='LOCAL',
        )
        pose_bone.keyframe_insert(data_path="location", frame=frame)
        if pose_bone.rotation_mode == 'QUATERNION':
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        elif pose_bone.rotation_mode == 'AXIS_ANGLE':
            pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        else:
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        pose_bone.keyframe_insert(data_path="scale", frame=frame)
    chain.last_baked_frame = max(chain.last_baked_frame, frame)
