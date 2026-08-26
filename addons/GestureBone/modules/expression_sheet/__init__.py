"""
expression_sheet/__init__.py -- Expression Sheet module.

Wraps a self-contained shader-node addon (nodes.py) that adds two custom
Shader Editor nodes -- 'Bone Info' and 'UV From Bone' -- driven live from an
Armature bone's pose, plus a 'UV From Bone' output for the bone's exp_index
custom property (pairs with the spritesheet module's E-key expression grid).

Toggling this module on/off registers/unregisters the node types and their
Add-menu entries via nodes.register()/unregister().
"""
from . import nodes, operators, ui


def register():
    nodes.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    nodes.unregister()
