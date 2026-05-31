"""
plotting/__init__.py — Rig generation module (renamed from rig_generation).
"""
from . import ops_create, ops_chains, ops_autorig, ops_steps, ops_alignment, ops_bind_mesh, ui


def register():
    ops_create.register()
    ops_chains.register()
    ops_autorig.register()
    ops_steps.register()
    ops_alignment.register()
    ops_bind_mesh.register()
    ui.register()


def unregister():
    ui.unregister()
    ops_bind_mesh.unregister()
    ops_alignment.unregister()
    ops_steps.unregister()
    ops_autorig.unregister()
    ops_chains.unregister()
    ops_create.unregister()
