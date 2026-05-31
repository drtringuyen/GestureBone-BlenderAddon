"""
shared/utils_constraints.py — GEOMETRY_ATTRIBUTE constraint helpers.
Moved from gesture_draw/utils_constraints.py; updated to read chain.control_bones.
"""
import bpy
from .utils import bone_names

_CONSTRAINT_NAME = "Gesture_copy"
_CONSTRAINT_TYPE = "GEOMETRY_ATTRIBUTE"


def _mute_constraints(arm_obj, chain):
    for bname in bone_names(chain):
        pb = arm_obj.pose.bones.get(bname)
        if pb:
            for c in pb.constraints:
                if c.name == _CONSTRAINT_NAME:
                    c.mute = True


def _unmute_constraints(arm_obj, chain):
    for bname in bone_names(chain):
        pb = arm_obj.pose.bones.get(bname)
        if pb:
            for c in pb.constraints:
                if c.name == _CONSTRAINT_NAME:
                    c.mute = False


def _constraints_exist(arm_obj, chain):
    for bname in bone_names(chain):
        pb = arm_obj.pose.bones.get(bname)
        if pb and any(c.name == _CONSTRAINT_NAME for c in pb.constraints):
            return True
    return False


def _constraints_are_muted(arm_obj, chain):
    for bname in bone_names(chain):
        pb = arm_obj.pose.bones.get(bname)
        if pb:
            for c in pb.constraints:
                if c.name == _CONSTRAINT_NAME:
                    return c.mute
    return True
