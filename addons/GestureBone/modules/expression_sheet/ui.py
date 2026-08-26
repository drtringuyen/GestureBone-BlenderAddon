"""
expression_sheet/ui.py -- single combined "Expression Sheet" panel.

Sections (was 3 separate panels before the spritesheet+expression_sheet
module merge): grid settings + sprite-cell picker, pose-mode expression key
hint, and a pointer to the Shader Editor node that reads exp_index back.
"""
import bpy

from .ops_cell import cell_index


class GESTUREBONE_PT_ExpressionSheet(bpy.types.Panel):
    bl_label       = "Expression Sheet"
    bl_idname      = "GESTUREBONE_PT_expression_sheet"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_parent_id   = "GESTUREBONE_PT_main"
    bl_order       = 10
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        props  = context.scene.gesturebone_spritesheet
        layout = self.layout

        # -- Grid settings + sprite-cell picker --------------------------
        col = layout.column(align=True)
        col.label(text="Sprite Grid", icon='IMGDISPLAY')
        row = col.row(align=True)
        row.prop(props, "grid_size")
        row.prop(props, "grid_count")
        col.prop(props, "sheet_image", text="")

        ob    = context.active_object
        owner = ob.name if ob is not None else ""
        op = col.operator(
            "gesturebone.spritesheet_select",
            text="Cell " + str(cell_index(props, owner)),
            icon='SNAP_VERTEX',
        )
        op.owner = owner

        layout.separator()

        # -- Pose-mode expression grid ------------------------------------
        col = layout.column(align=True)
        col.label(text="Pose Expression", icon='POSE_HLT')
        col.label(text="Press E in Pose Mode to open the grid", icon='INFO')

        obj = context.active_object
        if obj and obj.type == 'ARMATURE' and obj.mode == 'POSE':
            active_pb = context.active_pose_bone
            if active_pb:
                col.label(text="Active bone exp_index: "
                          + str(active_pb.get('exp_index', '-')))

        layout.separator()

        # -- Shader node pointer -------------------------------------------
        col = layout.column(align=True)
        col.label(text="Shader Editor > Add:", icon='NODETREE')
        col.label(text="- UV From Bone (Shared)", icon='UV')


def register():
    bpy.utils.register_class(GESTUREBONE_PT_ExpressionSheet)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_ExpressionSheet)
