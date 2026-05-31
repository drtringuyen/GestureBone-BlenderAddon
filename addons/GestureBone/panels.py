"""
panels.py — Main GestureBone panels.
GESTUREBONE_PT_MainPanel dispatches to plotting or gesture UI based on rig_type.
"""
import bpy
import os
import json


def _build_label():
    build_file = os.path.join(os.path.dirname(__file__), "build_info.json")
    if os.path.exists(build_file):
        try:
            with open(build_file, "r") as f:
                data = json.load(f)
            t = data.get("time", "")
            if len(t) >= 16:
                yyyy, mm, dd = t[0:4], t[5:7], t[8:10]
                hhmm = t[11:16]
                return "{}/{}/{} {}".format(dd, mm, yyyy[2:], hhmm)
        except Exception:
            pass
    return "Build"


def _gesture_arm_for_spline(curve_obj):
    """Return the GESTURE armature that owns curve_obj as a GestureSpline, or None."""
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE' or obj.gesturebone_props.rig_type != 'PLOTTING':
            continue
        for chain in obj.gesturebone_props.chains:
            if chain.gesture_spline == curve_obj and chain.gesture_rig:
                return chain.gesture_rig
    return None


class GESTUREBONE_PT_Infos(bpy.types.Panel):
    bl_label       = "Infos"
    bl_idname      = "GESTUREBONE_PT_infos"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_order       = 0
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props  = context.scene.gesturebone_props

        row = layout.row(align=True)
        row.operator("gesturebone.build",          text=_build_label(), icon='RESTRICT_VIEW_ON')
        row.operator("gesturebone.reload",         text="",             icon='FILE_REFRESH')
        sub = row.row(align=True)
        sub.active_default = props.debug_mode
        sub.operator("gesturebone.toggle_debug",   text="", icon='INFO')
        row.operator("gesturebone.toggle_console", text="", icon='CONSOLE')
        row.operator("gesturebone.clear_console",  text="", icon='TRASH')
        extra_sub = row.row(align=True)
        extra_sub.active_default = props.extra_infos_mode
        extra_sub.prop(props, "extra_infos_mode",  text="", icon='BOOKMARKS', toggle=True)

        if props.debug_mode:
            from . import module_manager
            row3 = layout.row(align=True)
            row3.label(text="Modules:")
            for m in module_manager.ALL_MODULES:
                sub = row3.row(align=True)
                sub.active_default = module_manager.is_loaded(m["name"])
                sub.operator(m["op"], text=m["name"].capitalize(), icon=m["icon"])
            layout.label(text="Version: " + props.addon_version)


class GESTUREBONE_PT_MainPanel(bpy.types.Panel):
    bl_label       = "GestureBone"
    bl_idname      = "GESTUREBONE_PT_main"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_order       = 1

    def draw(self, context):
        layout    = self.layout
        scene_gp  = context.scene.gesturebone_props

        active = context.active_object
        if active and active.type == 'ARMATURE' and active.gesturebone_props.rig_type == 'GESTURE':
            # GESTURE rig is directly selected
            arm = active
        elif active and active.type == 'CURVE':
            # Active object is a curve — check if it's a GestureSpline belonging to a GESTURE rig.
            # This keeps the GESTURE panel visible during the entire Activate Draw session.
            arm = _gesture_arm_for_spline(active) or scene_gp.current_armature
        else:
            arm = scene_gp.current_armature

        if arm is None:
            row = layout.row()
            row.alert = True
            row.label(text="Select a Plotting or Gesture rig", icon='ERROR')
            layout.operator("gesturebone.append_essentials",
                            text="Load Essentials", icon='FILE_REFRESH')
            layout.operator("gesturebone.create_rig",
                            text="Create Rig", icon='ADD')
            return

        arm_props = arm.gesturebone_props
        rig_type  = arm_props.rig_type

        # ── Armature name header ──────────────────────────────────────────────
        name_row = layout.row(align=True)
        name_row.label(text=arm.name, icon='ARMATURE_DATA')
        type_label = {
            'PLOTTING': "PLOTTING",
            'GESTURE':  "GESTURE",
            'PRESET':   "PRESET",
            'NONE':     "Untagged",
        }.get(rig_type, "Untagged")
        name_row.label(text=f"· {type_label}")

        layout.separator(factor=0.3)

        # ── Dispatch ─────────────────────────────────────────────────────────
        if rig_type == 'PLOTTING':
            try:
                from .modules.plotting.ui import draw_plotting_ui
                draw_plotting_ui(layout, context, arm)
            except ImportError:
                layout.label(text="plotting module not loaded", icon='ERROR')

        elif rig_type == 'GESTURE':
            try:
                from .modules.gesture.ui import draw_gesture_ui
                draw_gesture_ui(layout, context, arm)
            except ImportError:
                layout.label(text="gesture module not loaded", icon='ERROR')

        elif rig_type == 'PRESET':
            box = layout.box()
            box.label(text="Preset armature", icon='BOOKMARKS')
            box.label(text="Appears in the Create Rig dropdown", icon='INFO')

        else:  # NONE / untagged
            box = layout.box()
            box.label(text="Untagged armature", icon='INFO')
            box.label(text="Use Extra Infos panel to tag this rig")

        # ── Debug: armature override ──────────────────────────────────────────
        if scene_gp.debug_mode:
            layout.separator()
            col = layout.column(align=True)
            col.label(text="Overrides:", icon='TOOL_SETTINGS')
            col.prop(scene_gp, "current_armature", text="Armature")


def register():
    bpy.utils.register_class(GESTUREBONE_PT_Infos)
    bpy.utils.register_class(GESTUREBONE_PT_MainPanel)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_MainPanel)
    bpy.utils.unregister_class(GESTUREBONE_PT_Infos)
