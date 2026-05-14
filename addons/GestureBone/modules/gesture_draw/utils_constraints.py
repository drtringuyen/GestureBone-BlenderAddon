import bpy
from .utils_context import _bone_names

_CONSTRAINT_NAME = "GP_copy"
_CONSTRAINT_TYPE = "GEOMETRY_ATTRIBUTE"


def _mute_constraints(arm_obj, chain):
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if not pb:
            continue
        for c in pb.constraints:
            if c.name == _CONSTRAINT_NAME:
                c.mute = True


def _unmute_constraints(arm_obj, chain):
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if not pb:
            continue
        for c in pb.constraints:
            if c.name == _CONSTRAINT_NAME:
                c.mute = False


def _constraints_exist(arm_obj, chain):
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if pb and any(c.name == _CONSTRAINT_NAME for c in pb.constraints):
            return True
    return False


def _constraints_are_muted(arm_obj, chain):
    """Return True if the GP_copy constraints exist and are currently muted."""
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if pb:
            for c in pb.constraints:
                if c.name == _CONSTRAINT_NAME:
                    return c.mute
    return True
