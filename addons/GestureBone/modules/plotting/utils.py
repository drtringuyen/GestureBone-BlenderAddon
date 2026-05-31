"""
plotting/utils.py — Helpers for the plotting module.
Thin wrappers over shared/utils.py with plotting-specific conventions.
"""
import bpy
from ..shared.utils import (
    _arm, _bones_in_bone_coll, _all_bone_colls, _ensure_object_mode,
    _all_objects, _delete_coll, _ensure_child_coll, _move_obj_to_coll,
    _deep_copy_coll, _clean, _rename_coll_tree, _rig_target_colls, _atomic_coll,
)


def _p(arm):
    """Shorthand: arm.gesturebone_props (the PLOTTING rig's props)."""
    return arm.gesturebone_props


def _meta_arm(arm):
    """The PLOTTING rig IS the MetaRig — return it directly."""
    return arm


def _active_plotting_arm(context):
    """Return the active PLOTTING armature, or None.

    Checks active object first. Falls back to scene.gesturebone_props.current_armature
    so that step operators (which change the active object while processing template
    armatures) still resolve the correct PLOTTING rig throughout a multi-step run.
    """
    obj = context.active_object
    if obj and obj.type == 'ARMATURE' and obj.gesturebone_props.rig_type == 'PLOTTING':
        return obj
    # Fallback: current_armature is kept in sync by the depsgraph handler and
    # is not changed when operators switch the active object internally.
    fallback = getattr(getattr(context.scene, 'gesturebone_props', None), 'current_armature', None)
    if fallback and fallback.type == 'ARMATURE' and fallback.gesturebone_props.rig_type == 'PLOTTING':
        return fallback
    return None


def _default_template():
    """First tagged collection with '<4_Handles', else first tagged, else ''."""
    tagged = [c for c in bpy.data.collections if "gesturebone_template" in c]
    for c in tagged:
        if '<4_Handles' in c.name:
            return c.name
    return tagged[0].name if tagged else ""


def _get_chain(props, bone_name):
    """Return (or create) a ChainDefinition entry for bone_name."""
    entry = props.chains.get(bone_name)
    if entry is None:
        entry = props.chains.add()
        entry.part_name = bone_name
        entry.name      = bone_name
    return entry
