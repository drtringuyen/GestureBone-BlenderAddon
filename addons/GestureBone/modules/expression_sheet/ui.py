"""
expression_sheet/ui.py -- single combined "Expression Sheet" panel.

Sections: scene grid defaults, the per-bone expression-bone registry, the
pose-mode expression key hint, and a pointer to the Shader Editor node that
reads exp_index back.
"""
import bpy

from .ops_pose_expr import _EXP_PROP, get_keymap_item
from .props import find_entry


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

        # -- Scene defaults ------------------------------------------------
        # Fallback for bones with no entry, and the source of the default cell
        # size (a monitor-dependent viewing preference, so it stays scene-level
        # rather than being baked into the rig).
        col = layout.column(align=True)
        col.label(text="Sheet Defaults", icon='IMGDISPLAY')
        row = col.row(align=True)
        row.prop(props, "grid_size")
        row.prop(props, "grid_count")
        col.prop(props, "sheet_image", text="")

        layout.separator()

        self._draw_expression_bones(context, layout)

        layout.separator()

        # -- Pose-mode expression grid ------------------------------------
        col = layout.column(align=True)
        col.label(text="Pose Expression", icon='POSE_HLT')

        found = get_keymap_item()
        if found:
            _, kmi = found
            row = col.row(align=True)
            row.label(text="Hotkey (Pose Mode):")
            row.prop(kmi, "type", text="", full_event=True)
        else:
            col.label(text="Press E in Pose Mode to open the grid", icon='INFO')

        layout.separator()

        # -- Shader node pointer -------------------------------------------
        col = layout.column(align=True)
        col.label(text="Shader Editor > Add:", icon='NODETREE')
        col.label(text="- UV From Bone (Shared)", icon='UV')

    # -- Expression bone registry ------------------------------------------

    def _draw_expression_bones(self, context, layout):
        arm = context.active_object
        header = layout.row(align=True)
        header.label(text="Expression Bones", icon='BONE_DATA')

        if arm is None or arm.type != 'ARMATURE':
            layout.label(text="Select an armature", icon='INFO')
            return

        header.operator("gesturebone.expression_bone_add", text="", icon='ADD')
        header.operator("gesturebone.expression_bone_sync", text="",
                        icon='FILE_REFRESH')

        entries = arm.gesturebone_props.expression_bones
        if not entries:
            layout.label(text="Select bones in Pose mode, then +", icon='INFO')
            return

        # An unkeyed value on an override reverts to the library's on reload,
        # and the addon cannot mark a pose-bone custom property overridable
        # (Blender exposes no scriptable path — see the design doc). The picker
        # below always keys; a value typed straight into the field does not, so
        # say so rather than letting the edit quietly disappear.
        if arm.override_library is not None:
            warn = layout.box().column(align=True)
            warn.label(text="Linked override: type = lost on reload.",
                       icon='ERROR')
            warn.label(text="Use the Cell picker (it keys).")

        for i, entry in enumerate(entries):
            pb = arm.pose.bones.get(entry.bone)
            box = layout.box()

            row = box.row(align=True)
            row.prop(entry, "ui_expanded", text="",
                     icon='TRIA_DOWN' if entry.ui_expanded else 'TRIA_RIGHT',
                     emboss=False)

            name_sub = row.row(align=True)
            name_sub.alert = pb is None          # bone renamed or deleted
            name_sub.label(text=entry.bone or "(unset)",
                           icon='BONE_DATA' if pb else 'ERROR')

            # The live custom property, not a copy: this is the value the
            # shader-node drivers read, and drawing it directly keeps one
            # source of truth (and puts right-click > Insert Keyframe on it).
            if pb is not None and _EXP_PROP in pb.keys():
                row.prop(pb, '["%s"]' % _EXP_PROP, text="")
            else:
                row.label(text="no index")

            if len(entries) > 1:
                move = row.row(align=True)
                up = move.operator("gesturebone.expression_bone_move", text="",
                                   icon='TRIA_UP')
                up.index, up.direction = i, 'UP'
                dn = move.operator("gesturebone.expression_bone_move", text="",
                                   icon='TRIA_DOWN')
                dn.index, dn.direction = i, 'DOWN'

            rm = row.operator("gesturebone.expression_bone_remove", text="",
                              icon='X')
            rm.index = i

            if not entry.ui_expanded:
                continue

            body = box.column(align=True)
            if pb is None:
                body.label(text="Bone missing — rename or re-sync", icon='ERROR')

            body.prop(entry, "sheet_image", text="")
            grid_row = body.row(align=True)
            grid_row.prop(entry, "grid_count")
            grid_row.prop(entry, "grid_size")

            pick = body.row(align=True)
            pick.enabled = pb is not None
            op = pick.operator(
                "gesturebone.expression_cell_pick",
                text="Cell %s" % (pb.get(_EXP_PROP, 0) if pb else "-"),
                icon='SNAP_VERTEX',
            )
            op.bone = entry.bone


class GESTUREBONE_PT_ExpressionSheetNodeTools(bpy.types.Panel):
    bl_label       = "Expression Sheet"
    bl_idname      = "GESTUREBONE_PT_expression_sheet_node_tools"
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space.tree_type == 'ShaderNodeTree'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        tree = context.space_data.edit_tree
        node = tree.nodes.active if tree is not None else None

        if node is None or node.bl_idname != "ShaderNodeCustomUVFromBoneShared":
            col.label(text="Select a 'UV From Bone (Shared)' node", icon='INFO')
            return

        col.label(text=node.name, icon='UV')
        col.operator("gesturebone.tidy_expression_node_driver", icon='SORTALPHA')


def register():
    bpy.utils.register_class(GESTUREBONE_PT_ExpressionSheet)
    bpy.utils.register_class(GESTUREBONE_PT_ExpressionSheetNodeTools)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_ExpressionSheetNodeTools)
    bpy.utils.unregister_class(GESTUREBONE_PT_ExpressionSheet)
