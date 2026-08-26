"""
expression_sheet/__init__.py -- Expression Sheet module.

Merges what used to be two separate modules, since they only ever worked as a
pair: the 'UV From Bone (Shared)' Shader Editor node (nodes.py) reads a bone's
`exp_index` custom property live, and the sprite-grid tools below are what set
that property.

  * nodes.py         -- shader node types + Add-menu entries (nodes.register())
  * props.py          -- unified grid settings, scene.gesturebone_spritesheet
  * grid.py           -- shared GPU sprite-grid modal widget
  * ops_cell.py        -- per-object sprite-cell selector
  * ops_pose_expr.py   -- Pose-mode E-key expression grid (keys exp_index)
  * ui.py              -- single combined "Expression Sheet" panel
"""
from . import nodes, operators, props, ops_cell, ops_pose_expr, ui


def register():
    props.register()
    nodes.register()
    operators.register()
    ops_cell.register()
    ops_pose_expr.register()
    ui.register()


def unregister():
    ui.unregister()
    ops_pose_expr.unregister()
    ops_cell.unregister()
    operators.unregister()
    nodes.unregister()
    props.unregister()
