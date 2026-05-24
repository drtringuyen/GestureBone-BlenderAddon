import bpy


def reset_stretch_to_constraints(arm_obj):
    """Reset all Stretch To constraints on an armature to current bone length."""
    if not arm_obj or arm_obj.type != 'ARMATURE':
        print("Active object is not an armature.")
        return

    original_mode = arm_obj.mode
    bpy.ops.object.mode_set(mode='POSE')

    count = 0
    for pbone in arm_obj.pose.bones:
        for constraint in pbone.constraints:
            if constraint.type != 'STRETCH_TO':
                continue
            with bpy.context.temp_override(active_pose_bone=pbone):
                bpy.ops.constraint.stretchto_reset(
                    constraint=constraint.name,
                    owner='BONE',
                )
            print(f"  Reset: {pbone.name} → {constraint.name}")
            count += 1

    bpy.ops.object.mode_set(mode=original_mode)
    print(f"Done — reset {count} Stretch To constraint(s) on '{arm_obj.name}'.")


reset_stretch_to_constraints(bpy.context.active_object)
