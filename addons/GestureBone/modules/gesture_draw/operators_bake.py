import bpy
from bpy.props import IntProperty
from .utils import (
    _arm, _get_chain, _bone_names,
    _get_fcurve_store,
)

# ── Mode-exit detection state ──────────────────────────────────────────────────

_exit_confirm_pending = False  # guard: only one popup at a time


def reset_exit_confirm_pending():
    """Called by ConfirmExitDrawing.execute() after the user responds."""
    global _exit_confirm_pending
    _exit_confirm_pending = False


def _trigger_exit_confirm():
    """Deferred timer: invoke the confirmation popup in a safe context."""
    global _exit_confirm_pending
    try:
        result = bpy.ops.gesturebone.confirm_exit_drawing('INVOKE_DEFAULT')
        if 'CANCELLED' in result:
            _exit_confirm_pending = False
    except Exception as e:
        print(f"GestureBone: confirm_exit_drawing failed: {e}")
        _exit_confirm_pending = False
    return None  # don't repeat


@bpy.app.handlers.persistent
def _check_drawing_state(scene, depsgraph):
    """Detect when a chain's gesture spline unexpectedly exits Edit mode.

    Fires after every depsgraph update. Triggers a confirmation popup via a
    deferred timer so the user can choose: stop drawing, re-enter edit, or
    re-enter draw. The ApplyToBone operator sets is_drawing=False BEFORE
    calling mode_set, so normal apply does not trigger this handler.
    """
    global _exit_confirm_pending
    if _exit_confirm_pending:
        return

    ctx = bpy.context
    if ctx is None:
        return

    active = getattr(ctx, 'active_object', None)
    mode = getattr(ctx, 'mode', 'OBJECT')

    for obj in scene.objects:
        if obj.type != 'ARMATURE':
            continue
        mod_props = getattr(obj, 'gesturebone_gesture_draw_props', None)
        if mod_props is None:
            continue
        for chain in mod_props.chains:
            if not chain.is_drawing:
                continue
            spline = chain.part_gesture_spline
            if spline is None:
                continue
            in_edit = (active is spline and mode == 'EDIT_CURVE')
            if not in_edit:
                _exit_confirm_pending = True
                bpy.app.timers.register(_trigger_exit_confirm, first_interval=0.0)
                return  # handle one chain at a time


# ── Bone hierarchy helpers ─────────────────────────────────────────────────────

def _iter_bone_and_descendants(arm_obj, bone_name):
    """Yield bone_name and every descendant bone name (breadth-first)."""
    bone = arm_obj.data.bones.get(bone_name)
    if bone is None:
        return
    stack = [bone]
    while stack:
        b = stack.pop()
        yield b.name
        stack.extend(b.children)


def _collect_bones_with_descendants(arm_obj, bone_names):
    """Return an ordered, deduplicated list of bone_names plus all their descendants."""
    seen = set()
    result = []
    for name in bone_names:
        if not name:
            continue
        for desc in _iter_bone_and_descendants(arm_obj, name):
            if desc not in seen:
                seen.add(desc)
                result.append(desc)
    return result


def _delete_bone_keypoints_at_frame(fcurves, arm_obj, bone_name, frame_num):
    """Remove all keyframe points at frame_num for a single bone across all transform channels."""
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


# ── Per-chain operators ────────────────────────────────────────────────────────


class GESTUREBONE_OT_DeleteBakedFrames(bpy.types.Operator):
    """Delete keyframe points at the current frame for this chain's control bones and all their descendants"""
    bl_idname = "gesturebone.delete_baked_frames"
    bl_label = "Delete Current Frame"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}

        frame_num = context.scene.frame_current

        fcurves = _get_fcurve_store(arm_obj)
        if fcurves is None:
            return {'FINISHED'}

        all_bones = _collect_bones_with_descendants(arm_obj, _bone_names(chain))
        for bone_name in all_bones:
            _delete_bone_keypoints_at_frame(fcurves, arm_obj, bone_name, frame_num)

        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_DeleteBakedFrames)
    if _check_drawing_state not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_check_drawing_state)


def unregister():
    if _check_drawing_state in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_check_drawing_state)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBakedFrames)
