"""
expression_sheet/__init__.py -- Expression Sheet module.

Merges what used to be two separate modules, since they only ever worked as a
pair: the 'UV From Bone (Shared)' Shader Editor node (nodes.py) reads a bone's
`exp_index` custom property live, and the sprite-grid tools below are what set
that property.

  * nodes.py           -- shader node types + Add-menu entries (nodes.register())
  * props.py           -- scene grid defaults + per-bone resolution
  * grid.py            -- shared GPU sprite-grid modal widget
  * ops_expr_bones.py  -- expression-bone registry + per-bone cell picker
  * ops_pose_expr.py   -- Pose-mode E-key expression grid (keys exp_index)
  * ui.py              -- single combined "Expression Sheet" panel

The per-bone registry itself lives on the armature Object, in
shared/arm_props.py rather than here, so it survives this module being toggled
off in a downstream file. See docs/expression-bones-design.md.
"""
from . import nodes, operators, props, ops_expr_bones, ops_pose_expr, ui


def register():
    props.register()
    nodes.register()
    operators.register()
    ops_pose_expr.register()
    ops_expr_bones.register()
    ui.register()


def unregister():
    ui.unregister()
    ops_expr_bones.unregister()
    ops_pose_expr.unregister()
    operators.unregister()
    nodes.unregister()
    props.unregister()
