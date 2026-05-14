import bpy
from bpy.props import IntProperty
from .utils import (
    _arm, _mod_props, _get_chain, _bone_names,
    _get_fcurve_store, _apply_and_key_data,
    _mute_constraints, _unmute_constraints, _frame_strokes,
    _remove_matching_strokes,
)


# ── Shared delete-all helper ───────────────────────────────────────────────────

def _delete_all_baked_for_chain(arm_obj, chain):
    """Remove all baked bone keyframes for a chain. GP frames are preserved."""
    fcurves = _get_fcurve_store(arm_obj)
    if fcurves is not None:
        for bone_name in _bone_names(chain):
            if not bone_name:
                continue
            pb = arm_obj.pose.bones.get(bone_name)
            rot_mode = pb.rotation_mode if pb else 'QUATERNION'
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
                        fcurves.remove(fc)

    chain.last_baked_frame = -1
    chain.stroke_count_cache = 0


# ── Per-chain operators ────────────────────────────────────────────────────────


class GESTUREBONE_OT_DeleteBakedFrames(bpy.types.Operator):
    """Delete baked bone keys and GP strokes at the current frame for this chain, then restore the last reference pose"""
    bl_idname = "gesturebone.delete_baked_frames"
    bl_label = "Delete Current Frame"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}

        frame_num = context.scene.frame_current

        # 1. Remove bone keyframe points at frame_num
        fcurves = _get_fcurve_store(arm_obj)
        if fcurves is not None:
            for bone_name in _bone_names(chain):
                if not bone_name:
                    continue
                pb = arm_obj.pose.bones.get(bone_name)
                rot_mode = pb.rotation_mode if pb else 'QUATERNION'
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
                            to_remove = [
                                kp for kp in fc.keyframe_points
                                if abs(kp.co[0] - frame_num) < 0.5
                            ]
                            for kp in reversed(to_remove):
                                fc.keyframe_points.remove(kp)

        # 2. Remove GP strokes at frame_num and delete the frame entry if now empty
        mod_props = _mod_props(context)
        gp_obj = mod_props.part_gp if mod_props else None
        mat = chain.part_material
        if gp_obj:
            try:
                for layer in gp_obj.data.layers:
                    gp_frame = next(
                        (f for f in layer.frames if f.frame_number == frame_num), None
                    )
                    if gp_frame is None:
                        continue
                    _remove_matching_strokes(gp_frame, gp_obj, mat)
                    # Delete the frame entry itself if it is now empty
                    remaining = _frame_strokes(gp_frame)
                    if remaining is None or len(list(remaining)) == 0:
                        if hasattr(gp_frame, 'drawing'):  # GP3
                            layer.frames.remove(frame_num)
                        else:                             # GP2
                            layer.frames.remove(gp_frame)
            except Exception as e:
                self.report({'WARNING'}, f"Could not clear GP strokes: {e}")

        return {'FINISHED'}


# ── Global operators ───────────────────────────────────────────────────────────

class GESTUREBONE_OT_BakeAllChains(bpy.types.Operator):
    """Bake any GP frames that lack bone keyframes across all chains on this armature"""
    bl_idname = "gesturebone.bake_all_chains"
    bl_label = "Bake All Chains"

    def execute(self, context):
        arm_obj = _arm(context)
        mod_props = _mod_props(context)
        if arm_obj is None or mod_props is None:
            return {'CANCELLED'}

        baked = 0
        prev_frame = context.scene.frame_current

        gp_obj = mod_props.part_gp
        for chain in mod_props.chains:
            if not chain.is_bound or not gp_obj:
                continue
            mat = chain.part_material

            gp_frames = set()
            try:
                for layer in gp_obj.data.layers:
                    for gp_frame in layer.frames:
                        strokes = _frame_strokes(gp_frame)
                        if strokes is None:
                            continue
                        for stroke in strokes:
                            if mat is None or (
                                stroke.material_index < len(gp_obj.material_slots) and
                                gp_obj.material_slots[stroke.material_index].material == mat
                            ):
                                gp_frames.add(gp_frame.frame_number)
                                break
            except Exception:
                continue

            fcurves = _get_fcurve_store(arm_obj)

            for frame_num in sorted(gp_frames):
                has_key = False
                if fcurves is not None:
                    for bone_name in _bone_names(chain):
                        if not bone_name:
                            continue
                        fc = fcurves.find(f'pose.bones["{bone_name}"].location', index=0)
                        if fc and any(abs(k.co[0] - frame_num) < 0.5 for k in fc.keyframe_points):
                            has_key = True
                            break
                if has_key:
                    continue

                context.scene.frame_set(frame_num)
                _unmute_constraints(arm_obj, chain)
                context.view_layer.update()
                depsgraph = context.evaluated_depsgraph_get()
                _apply_and_key_data(arm_obj, chain, frame_num, depsgraph)
                _mute_constraints(arm_obj, chain)
                baked += 1

        context.scene.frame_set(prev_frame)
        self.report({'INFO'}, f"Baked {baked} missing frame(s)")
        return {'FINISHED'}


class GESTUREBONE_OT_DeleteAllBakedFrames(bpy.types.Operator):
    """Delete all baked bone keyframes and GP strokes across every chain on this armature"""
    bl_idname = "gesturebone.delete_all_baked_frames"
    bl_label = "Delete All Baked Frames"

    def execute(self, context):
        arm_obj = _arm(context)
        mod_props = _mod_props(context)
        if arm_obj is None or mod_props is None:
            return {'CANCELLED'}

        for chain in mod_props.chains:
            _delete_all_baked_for_chain(arm_obj, chain)

        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_DeleteBakedFrames)
    bpy.utils.register_class(GESTUREBONE_OT_BakeAllChains)
    bpy.utils.register_class(GESTUREBONE_OT_DeleteAllBakedFrames)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteAllBakedFrames)
    bpy.utils.unregister_class(GESTUREBONE_OT_BakeAllChains)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBakedFrames)
