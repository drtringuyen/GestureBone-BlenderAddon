import bpy
import re

_BLENDER_SUFFIX = re.compile(r'(\.\d{3})+$')


def _p(context):
    return context.scene.gesturebone_rig_generation_props


def _meta_rig(props):
    return bpy.data.objects.get(props.meta_rig)


def _atomic_coll(props):
    return bpy.data.collections.get(props.atomic_chain)


def _rig_target_colls(props):
    arm = _meta_rig(props)
    return list(arm.users_collection) if arm else []


def _all_objects(coll):
    objs = list(coll.objects)
    for child in coll.children:
        objs.extend(_all_objects(child))
    return objs


def _bones_in_bone_coll(arm_data, coll_name):
    bc = arm_data.collections.get(coll_name)
    if not bc:
        return []
    try:
        return [b.name for b in bc.bones]
    except AttributeError:
        result = []
        for b in arm_data.bones:
            try:
                if any(c.name == coll_name for c in b.collections):
                    result.append(b.name)
            except Exception:
                pass
        return result


def _copy_coll_tree(src, parent_coll, obj_map):
    dst = bpy.data.collections.new(src.name)
    parent_coll.children.link(dst)
    for obj in src.objects:
        new_obj      = obj.copy()
        new_obj.data = obj.data.copy() if obj.data else None
        dst.objects.link(new_obj)
        obj_map[obj] = new_obj
    for child in src.children:
        _copy_coll_tree(child, dst, obj_map)
    return dst


def _deep_copy_coll(src, parent_coll):
    obj_map = {}
    dst = _copy_coll_tree(src, parent_coll, obj_map)
    for orig, copy in obj_map.items():
        if orig.parent and orig.parent in obj_map:
            copy.parent = obj_map[orig.parent]
            copy.matrix_parent_inverse = orig.matrix_parent_inverse.copy()
    return dst


def _delete_coll(coll):
    for child in list(coll.children):
        _delete_coll(child)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)


def _ensure_child_coll(name, parent_coll):
    existing = parent_coll.children.get(name)
    if existing:
        return existing
    new_coll = bpy.data.collections.new(name)
    parent_coll.children.link(new_coll)
    return new_coll


def _move_obj_to_coll(obj, dst_coll):
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    dst_coll.objects.link(obj)


def _ensure_object_mode(context):
    ao = context.active_object
    if ao and ao.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def _clean(s, token, bone_name):
    return _BLENDER_SUFFIX.sub('', s).replace(token, bone_name)


def _rename_coll_tree(coll, token, bone_name):
    coll.name = _clean(coll.name, token, bone_name)
    for child in coll.children:
        _rename_coll_tree(child, token, bone_name)


def _all_bone_colls(arm_data):
    """Return ALL bone collections including nested children.

    arm_data.collections only iterates top-level collections; nested ones
    are accessible via bc.children and must be collected recursively.
    """
    result = []

    def _recurse(bc):
        result.append(bc)
        for child in getattr(bc, 'children', ()):
            _recurse(child)

    for bc in arm_data.collections:
        _recurse(bc)
    return result
