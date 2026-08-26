"""
spritesheet/ui.py — Spritesheet module panels.

Two collapsed sub-panels under the GestureBone N-tab:
  * Spritesheet    — shared grid settings + the sprite-cell picker button
  * Pose Expression — E-key hint + the active bone's current exp_index
"""
import bpy

from .ops_cell import cell_index


class GESTUREBONE_PT_Spritesheet(bpy.types.Panel):
    bl_label       = "Spritesheet"
    bl_idname      = "GESTUREBONE_PT_spritesheet"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_parent_id   = "GESTUREBONE_PT_main"
    bl_order       = 10
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        props  = context.scene.gesturebone_spritesheet
        layout = self.layout

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(props, "grid_size")
        row.prop(props, "grid_count")
        col.prop(props, "sheet_image", text="")

        ob    = context.active_object
        owner = ob.name if ob is not None else ""
        op = layout.operator(
            "gesturebone.spritesheet_select",
            text="Cell " + str(cell_index(props, owner)),
            icon='SNAP_VERTEX',
        )
        op.owner = owner


class GESTUREBONE_PT_PoseExpr(bpy.types.Panel):
    bl_label       = "Pose Expression"
    bl_idname      = "GESTUREBONE_PT_pose_expr"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_parent_id   = "GESTUREBONE_PT_main"
    bl_order       = 11
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Press E in Pose Mode to open the grid", icon='INFO')

        obj = context.active_object
        if obj and obj.type == 'ARMATURE' and obj.mode == 'POSE':
            active_pb = context.active_pose_bone
            if active_pb:
                layout.label(text="Active bone exp_index: "
                             + str(active_pb.get('exp_index', '-')))


_classes = (
    GESTUREBONE_PT_Spritesheet,
    GESTUREBONE_PT_PoseExpr,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
