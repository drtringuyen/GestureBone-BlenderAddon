"""
spritesheet/__init__.py — Spritesheet module.

Two tools that share one GPU sprite-grid widget (grid.py):
  * ops_cell       — sprite-cell selector (per-object cell index)
  * ops_pose_expr  — Pose-mode E-key expression grid (keys bone exp_index)
Both read the unified grid settings in props.py.
"""
from . import props, ops_cell, ops_pose_expr, ui


def register():
    props.register()
    ops_cell.register()
    ops_pose_expr.register()
    ui.register()


def unregister():
    ui.unregister()
    ops_pose_expr.unregister()
    ops_cell.unregister()
    props.unregister()
