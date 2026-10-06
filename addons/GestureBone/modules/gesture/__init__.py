"""
gesture/__init__.py — Gesture drawing module (renamed from gesture_draw).
"""
from . import ops_bind, ops_draw, ops_bake, ops_select, ui


def register():
    ops_bind.register()
    ops_draw.register()
    ops_bake.register()
    ops_select.register()
    ui.register()


def unregister():
    ui.unregister()
    ops_select.unregister()
    ops_bake.unregister()
    ops_draw.unregister()
    ops_bind.unregister()
