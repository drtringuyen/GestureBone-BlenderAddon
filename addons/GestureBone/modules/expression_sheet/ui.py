import bpy


class GESTUREBONE_PT_ExpressionSheet(bpy.types.Panel):
    bl_label = "ExpressionSheet"
    bl_idname = "GESTUREBONE_PT_expression_sheet"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_main"
    bl_order = 11

    def draw(self, context):
        # This module ships shader nodes rather than 3D-view tools, so the
        # panel is just a pointer to where the nodes live.
        col = self.layout.column(align=True)
        col.label(text="Shader Editor > Add:", icon='NODETREE')
        col.label(text="- UV From Bone (Shared)", icon='UV')


def register():
    bpy.utils.register_class(GESTUREBONE_PT_ExpressionSheet)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_ExpressionSheet)
