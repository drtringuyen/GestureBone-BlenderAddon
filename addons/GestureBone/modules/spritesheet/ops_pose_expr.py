"""
spritesheet/ops_pose_expr.py — Pose-mode expression grid (E key).

Merged from the standalone PoseExpressionGrid script. Opens the shared sprite
grid in Pose mode and keyframes each selected bone's ``exp_index`` as a
CONSTANT step, so an expression sprite holds until the next keyed change.
Handles Blender <4.4 and 4.4+ layered actions when locating the fcurve.
"""
import bpy

from .grid import _SpriteGridBase

_EXP_PROP = "exp_index"   # custom int property on each pose bone


# ── Action / fcurve compatibility (Blender 4.4+ layered Actions) ──────────────
#  (same pattern as GestureBone/modules/shared/utils_bake.py::_get_fcurve_store)

def _get_fcurve_store(arm_obj):
    """F-curve collection for this armature's action (handles <4.4 and 4.4+)."""
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


def _bone_exp_fcurve(arm_obj, bone_name):
    """Find the exp_index fcurve for this bone, or None if never keyed."""
    fcurves = _get_fcurve_store(arm_obj)
    if fcurves is None:
        return None
    data_path = f'pose.bones["{bone_name}"]["{_EXP_PROP}"]'
    return fcurves.find(data_path, index=0)


def _force_constant(fcurve):
    """Set every existing keyframe on this fcurve to CONSTANT interpolation."""
    if fcurve is None:
        return
    for kp in fcurve.keyframe_points:
        kp.interpolation = 'CONSTANT'


def _ensure_exp_index(pose_bone):
    """Ensure pose_bone has the exp_index custom property; return its value."""
    if _EXP_PROP not in pose_bone.keys():
        pose_bone[_EXP_PROP] = 0
    return int(pose_bone[_EXP_PROP])


def _key_expression_change(context, arm_obj, bones, new_idx):
    """Apply *new_idx* to *bones*, keying a one-frame constant step.

    For each bone: if it already has keyframes on exp_index, key the previous
    value one frame earlier, then key the new value on the current frame. If it
    has never been keyed, just key the new value on the current frame.
    """
    frame = context.scene.frame_current

    for pb in bones:
        prev_value = _ensure_exp_index(pb)
        fcurve = _bone_exp_fcurve(arm_obj, pb.name)
        has_existing_keys = fcurve is not None and len(fcurve.keyframe_points) > 0

        if has_existing_keys:
            # Hold the previous value one frame earlier.
            pb[_EXP_PROP] = prev_value
            pb.keyframe_insert(data_path=f'["{_EXP_PROP}"]', frame=frame - 1)

        pb[_EXP_PROP] = new_idx
        pb.keyframe_insert(data_path=f'["{_EXP_PROP}"]', frame=frame)

        # keyframe_insert can (re)create the fcurve — re-fetch, then normalize.
        _force_constant(_bone_exp_fcurve(arm_obj, pb.name))


# ── Operator ──────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_PoseExpressionGrid(_SpriteGridBase):
    """Open the pose-bone expression grid at the mouse and key the selected bones"""
    bl_idname  = "gesturebone.pose_expression_grid"
    bl_label   = "Pose Expression Grid"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            return False
        return any(pb.select for pb in obj.pose.bones)

    def _grid_props(self, context):
        return context.scene.gesturebone_spritesheet

    def _prepare(self, context):
        arm = context.active_object
        self._arm = arm
        self._bones = [pb for pb in arm.pose.bones if pb.select]
        if not self._bones:
            return False
        # Ensure exp_index exists and any existing keys on these bones' channels
        # are (still) CONSTANT before we show the grid.
        for pb in self._bones:
            _ensure_exp_index(pb)
            _force_constant(_bone_exp_fcurve(arm, pb.name))
        return True

    def _seed_chosen(self, context):
        props = context.scene.gesturebone_spritesheet
        max_idx = props.grid_count ** 2 - 1
        active_pb = context.active_pose_bone
        return min(_ensure_exp_index(active_pb), max_idx) if active_pb else -1

    def _commit(self, context, idx):
        _key_expression_change(context, self._arm, self._bones, idx)


_addon_keymaps = []


def register():
    bpy.utils.register_class(GESTUREBONE_OT_PoseExpressionGrid)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Pose', space_type='EMPTY')
        kmi = km.keymap_items.new(GESTUREBONE_OT_PoseExpressionGrid.bl_idname, 'E', 'PRESS')
        _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    bpy.utils.unregister_class(GESTUREBONE_OT_PoseExpressionGrid)
