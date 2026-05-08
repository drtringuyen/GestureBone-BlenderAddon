import bpy
import os
import json


def _build_label():
    """Return 'dd/mm/yy HH:MM' from build_info.json, or 'Build' if not built yet."""
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


class GESTUREBONE_PT_Infos(bpy.types.Panel):
    """Infos panel - build time, debug, console"""
    bl_label = "Infos"
    bl_idname = "GESTUREBONE_PT_infos"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.gesturebone_props

        split = layout.split(factor=0.75, align=True)
        split.operator("gesturebone.build", text=_build_label(), icon='RESTRICT_VIEW_ON')

        row = split.row(align=True)

        sub = row.row(align=True)
        sub.active_default = props.debug_mode
        sub.operator("gesturebone.toggle_debug", text="", icon='INFO')

        row.operator("gesturebone.toggle_console", text="", icon='CONSOLE')
        row.operator("gesturebone.clear_console", text="", icon='TRASH')

        # Modules row — label + toggle buttons in one line
        from . import module_manager
        row = layout.row(align=True)
        row.label(text="Modules:")
        for m in module_manager.ALL_MODULES:
            sub = row.row(align=True)
            sub.active_default = module_manager.is_loaded(m["name"])
            sub.operator(m["op"], text=m["name"].capitalize(), icon=m["icon"])

        if props.debug_mode:
            layout.label(text="Version: " + props.addon_version,
                         text_ctxt="extra-info-label")


class GESTUREBONE_PT_MainPanel(bpy.types.Panel):
    """Main panel - modules register subpanels here via bl_parent_id"""
    bl_label = "GestureBone"
    bl_idname = "GESTUREBONE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_order = 1

    def draw(self, context):
        props = context.scene.gesturebone_props
        layout = self.layout
        layout.prop(props, "main_armature", text="Armature")
        layout.prop(props, "main_gp", text="GP")


def register():
    bpy.utils.register_class(GESTUREBONE_PT_Infos)
    bpy.utils.register_class(GESTUREBONE_PT_MainPanel)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_MainPanel)
    bpy.utils.unregister_class(GESTUREBONE_PT_Infos)
