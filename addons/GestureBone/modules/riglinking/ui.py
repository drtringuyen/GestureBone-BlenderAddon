"""
riglinking/ui.py — "Rig Linking" sub-panel.

Surfaces the Localize / Relink actions and a short status. The panel only shows
its actions when the file actually contains an overridden GESTURE rig, so it
stays out of the way in ordinary local scenes.
"""
import bpy
from . import relink
from .operators import _gesture_override_rigs, _linked_gesture_splines


class GESTUREBONE_PT_Riglinking(bpy.types.Panel):
    bl_label       = "Rig Linking"
    bl_idname      = "GESTUREBONE_PT_riglinking"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_parent_id   = "GESTUREBONE_PT_main"
    bl_order       = 0

    def draw(self, context):
        layout = self.layout
        override_rigs = _gesture_override_rigs()

        if not override_rigs:
            col = layout.column()
            col.enabled = False
            col.label(text="No linked/overridden rig", icon='LINKED')
            col.label(text="Use for rigs linked from another file.")
            return

        pending = _linked_gesture_splines()

        box = layout.box()
        box.label(text=f"Overridden rig(s): {len(override_rigs)}", icon='LIBRARY_DATA_OVERRIDE')
        if pending:
            row = box.row()
            row.alert = True
            row.label(text=f"{len(pending)} spline(s) still linked", icon='ERROR')
        else:
            box.label(text="Gesture splines local", icon='CHECKMARK')

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("gesturebone.localize_for_drawing", icon='LINKED')
        col.operator("gesturebone.relink_overrides", text="Relink Only", icon='FILE_REFRESH')
        col.operator("gesturebone.clear_linked_action", text="Clear Linked Action", icon='TRASH')

        # ── Create Action: name field + button on one row ─────────────────────
        act_row = layout.row(align=True)
        act_row.prop(context.scene, "gesturebone_action_name", text="")
        act_row.operator("gesturebone.create_action", text="Create Action", icon='ACTION')


def register():
    bpy.utils.register_class(GESTUREBONE_PT_Riglinking)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_Riglinking)
