import bpy


def _arm(context):
    obj = context.active_object
    if obj and obj.type == 'ARMATURE':
        return obj
    fallback = context.scene.gesturebone_props.current_armature
    return fallback if fallback and fallback.type == 'ARMATURE' else None


def _mod_props(context):
    obj = _arm(context)
    return obj.gesturebone_gesture_draw_props if obj else None


def _get_chain(context, index):
    props = _mod_props(context)
    return props.chains[index] if props and 0 <= index < len(props.chains) else None


def _bone_names(chain):
    return [entry.bone for entry in chain.part_control_bones if entry.bone]
