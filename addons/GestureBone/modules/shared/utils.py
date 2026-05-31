"""
shared/utils.py — Shared utilities for plotting and gesture modules.
Merged from gesture_draw/utils_chain.py, gesture_draw/utils_context.py,
and rig_generation/utils.py.
"""
import bpy
import re

_BLENDER_SUFFIX = re.compile(r'(\.\d{3})+$')


# ── Context helpers ────────────────────────────────────────────────────────────

def _arm(context):
    """Active object if ARMATURE, else scene.gesturebone_props.current_armature."""
    obj = context.active_object
    if obj and obj.type == 'ARMATURE':
        return obj
    fallback = context.scene.gesturebone_props.current_armature
    return fallback if fallback and fallback.type == 'ARMATURE' else None


def _plotting_props(arm):
    """Return arm.gesturebone_props, asserting rig_type == PLOTTING."""
    if arm is None:
        return None
    props = arm.gesturebone_props
    return props if props.rig_type == 'PLOTTING' else None


def _chains_for_gesture_rig(gesture_arm):
    """Return chains from the plotting_rig that belong to this GESTURE rig."""
    if gesture_arm is None:
        return []
    plotting_rig = gesture_arm.gesturebone_props.plotting_rig
    if plotting_rig is None or plotting_rig.gesturebone_props.rig_type != 'PLOTTING':
        return []
    return [c for c in plotting_rig.gesturebone_props.chains if c.gesture_rig == gesture_arm]


def _validate_plotting_rig(gesture_arm):
    """Return the PLOTTING rig for a GESTURE rig, or None with a console warning."""
    plotting = gesture_arm.gesturebone_props.plotting_rig
    if plotting is None:
        print(f"GestureBone: '{gesture_arm.name}' has no plotting_rig pointer set")
        return None
    if plotting.gesturebone_props.rig_type != 'PLOTTING':
        print(f"GestureBone: '{plotting.name}' is not tagged as PLOTTING")
        return None
    return plotting


def bone_names(chain):
    """Return list of non-empty control bone name strings for a chain."""
    return [entry.bone for entry in chain.control_bones if entry.bone]


# ── Collection management (merged from both modules) ──────────────────────────

def _find_arm_collection(arm, scene):
    """First non-root collection containing arm, or scene root."""
    for coll in arm.users_collection:
        if coll != scene.collection:
            return coll
    return scene.collection


def _ensure_child_collection(name, parent_coll):
    """Get or create a collection named *name* as a child of parent_coll."""
    existing = bpy.data.collections.get(name)
    if existing is None:
        existing = bpy.data.collections.new(name)
    if name not in {c.name for c in parent_coll.children}:
        try:
            parent_coll.children.link(existing)
        except Exception:
            pass
    return existing


# Alias used by rig_generation ops (shorter name)
_ensure_child_coll = _ensure_child_collection


def _move_object_to_collection(obj, target_coll):
    """Move obj into target_coll, unlinking from all other collections."""
    for coll in list(obj.users_collection):
        if coll.name != target_coll.name:
            try:
                coll.objects.unlink(obj)
            except Exception:
                pass
    if obj.name not in target_coll.objects:
        try:
            target_coll.objects.link(obj)
        except Exception:
            pass


# Alias
_move_obj_to_coll = _move_object_to_collection


def _all_objects(coll):
    """Recursively gather all objects in a collection tree."""
    objs = list(coll.objects)
    for child in coll.children:
        objs.extend(_all_objects(child))
    return objs


def _delete_coll(coll):
    """Recursively delete a collection and all its objects."""
    for child in list(coll.children):
        _delete_coll(child)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)


# ── Armature helpers ───────────────────────────────────────────────────────────

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


def _all_bone_colls(arm_data):
    """All bone collections including nested children."""
    result = []

    def _recurse(bc):
        result.append(bc)
        for child in getattr(bc, 'children', ()):
            _recurse(child)

    for bc in arm_data.collections:
        _recurse(bc)
    return result


def _ensure_object_mode(context):
    ao = context.active_object
    if ao and ao.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


# ── Naming helpers (rig_generation) ───────────────────────────────────────────

def _clean(s, token, bone_name):
    stripped = _BLENDER_SUFFIX.sub('', s)
    return re.sub(re.escape(token), bone_name, stripped, flags=re.IGNORECASE)


def _rename_coll_tree(coll, token, bone_name):
    coll.name = _clean(coll.name, token, bone_name)
    for child in coll.children:
        _rename_coll_tree(child, token, bone_name)


# ── Collection copy helpers (rig_generation) ──────────────────────────────────

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


# ── Spline object management (gesture_draw) ───────────────────────────────────

def _resize_collection(coll, count):
    while len(coll) < count:
        coll.add()
    while len(coll) > count:
        coll.remove(len(coll) - 1)


def _ensure_chain_objects(plotting_arm, chain, context):
    """Find or create gesture/plotting spline curve objects for this chain.

    Splines are sorted into {MetaRig}.GestureSplines and {MetaRig}.PlottingSplines
    collections. plotting_arm is always the PLOTTING (MetaRig) armature.
    """
    if plotting_arm is None or not chain.part_name:
        return
    scene = getattr(context, 'scene', None)
    if scene is None:
        return

    meta_name = plotting_arm.name
    part_name = chain.part_name

    arm_coll      = _find_arm_collection(plotting_arm, scene)
    gesture_coll  = _ensure_child_collection(f"{meta_name}.GestureSplines",  arm_coll)
    plotting_coll = _ensure_child_collection(f"{meta_name}.PlottingSplines", arm_coll)

    gesture_name = f"{meta_name}-{part_name}.GestureSpline"
    existing_g   = bpy.data.objects.get(gesture_name)
    if existing_g and existing_g.type == 'CURVE':
        chain.gesture_spline = existing_g
    elif not chain.gesture_spline:
        curve_data        = bpy.data.curves.new(gesture_name, 'CURVE')
        curve_data.dimensions = '3D'
        obj               = bpy.data.objects.new(gesture_name, curve_data)
        gesture_coll.objects.link(obj)
        chain.gesture_spline = obj
    if chain.gesture_spline:
        _move_object_to_collection(chain.gesture_spline, gesture_coll)

    plotting_name = f"{meta_name}-{part_name}.PlottingSpline"
    existing_p    = bpy.data.objects.get(plotting_name)
    if existing_p and existing_p.type == 'CURVE':
        chain.plotting_spline = existing_p
    elif not chain.plotting_spline:
        curve_data        = bpy.data.curves.new(plotting_name, 'CURVE')
        curve_data.dimensions = '3D'
        obj               = bpy.data.objects.new(plotting_name, curve_data)
        plotting_coll.objects.link(obj)
        chain.plotting_spline = obj
    if chain.plotting_spline:
        _move_object_to_collection(chain.plotting_spline, plotting_coll)


def _cleanup_orphan_splines(plotting_arm, chains, scene):
    """Delete CURVE objects in spline collections not referenced by any chain."""
    meta_name = plotting_arm.name
    active = set()
    for chain in chains:
        if chain.gesture_spline:
            active.add(chain.gesture_spline.name)
        if chain.plotting_spline:
            active.add(chain.plotting_spline.name)

    for coll_name in (f"{meta_name}.GestureSplines", f"{meta_name}.PlottingSplines"):
        coll = bpy.data.collections.get(coll_name)
        if coll is None:
            continue
        for obj in list(coll.objects):
            if obj.type == 'CURVE' and obj.name not in active:
                print(f"GestureBone: removing orphan spline '{obj.name}'")
                try:
                    bpy.data.objects.remove(obj, do_unlink=True)
                except Exception as e:
                    print(f"GestureBone: could not remove '{obj.name}': {e}")


# ── Rig-generation collection helpers ─────────────────────────────────────────

def _rig_target_colls(arm):
    """Collections containing the PLOTTING armature."""
    return list(arm.users_collection) if arm else []


def _atomic_coll(props):
    """Template collection — prefers wip_token over atomic_chain."""
    name = props.wip_token if props.wip_token else props.atomic_chain
    return bpy.data.collections.get(name)
