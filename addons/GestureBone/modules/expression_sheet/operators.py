"""
expression_sheet/operators.py -- Shader Editor driver-cleanup operator.

Renames the active 'UV From Bone (Shared)' node's driver property keys and
feed-node labels from the generic node name to the bone it's wired to. See
nodes.py's tidy_expression_node_and_driver() / _instance_key_ident() for the
actual work and why it's careful not to touch node.name or any satellite's
own tree identity.
"""
import bpy

from . import nodes as node_defs


def _active_uv_from_bone_node(context):
    space = context.space_data
    if space is None or space.type != 'NODE_EDITOR' or space.tree_type != 'ShaderNodeTree':
        return None
    tree = space.edit_tree
    if tree is None:
        return None
    node = tree.nodes.active
    if node is None or node.bl_idname != node_defs.NODE_ID:
        return None
    return node


class GESTUREBONE_OT_tidy_expression_node_driver(bpy.types.Operator):
    bl_idname = "gesturebone.tidy_expression_node_driver"
    bl_label = "Tidy Expression Node & Driver"
    bl_description = ("Rename this node's driver property keys and feed-node "
                       "labels from the generic node name to the bone they "
                       "are wired to")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_uv_from_bone_node(context) is not None

    def execute(self, context):
        node = _active_uv_from_bone_node(context)
        result = node_defs.tidy_expression_node_and_driver(node)
        if result is None:
            self.report({'WARNING'},
                        "Select an Armature and Bone on this node first "
                        "(and make sure it isn't in a linked library tree)")
            return {'CANCELLED'}
        self.report({'INFO'}, "Tidied to '{}'".format(result))
        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_tidy_expression_node_driver)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_tidy_expression_node_driver)
