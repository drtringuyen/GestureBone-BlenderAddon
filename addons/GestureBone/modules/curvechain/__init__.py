"""
curvechain/__init__.py — Single-armature rig: B-Bone curve machinery, Annotate
drawing, and the two-rig → single-rig converter.
"""
from . import builder, convert, fit, ops, ui  # noqa: F401


def register():
    ops.register()


def unregister():
    ops.unregister()
