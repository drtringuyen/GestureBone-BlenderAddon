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

        row = layout.row(align=True)
        row.operator("gesturebone.build", text=_build_label(), icon='RESTRICT_VIEW_ON')
        row.operator("gesturebone.reload", text="", icon='FILE_REFRESH')
        sub = row.row(align=True)
        sub.active_default = props.debug_mode
        sub.operator("gesturebone.toggle_debug", text="", icon='INFO')
        row.operator("gesturebone.toggle_console", text="", icon='CONSOLE')
        row.operator("gesturebone.clear_console", text="", icon='TRASH')

        if props.debug_mode:
            from . import module_manager
            row3 = layout.row(align=True)
            row3.label(text="Modules:", text_ctxt="extra-info-label")
            for m in module_manager.ALL_MODULES:
                sub = row3.row(align=True)
                sub.active_default = module_manager.is_loaded(m["name"])
                sub.operator(m["op"], text=m["name"].capitalize(), icon=m["icon"])
            layout.label(text="Version: " + props.addon_version,
                         text_ctxt="extra-info-label")


class GESTUREBONE_PT_MainPanel(bpy.types.Panel):
    """Main panel - shows active armature; modules register subpanels here"""
    bl_label = "GestureBone"
    bl_idname = "GESTUREBONE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        props = context.scene.gesturebone_props
        arm = props.current_armature

        if arm is None:
            row = layout.row()
            row.alert = True
            row.label(text="Select an Armature", icon='ERROR')
        else:
            layout.label(text=arm.name, icon='ARMATURE_DATA')
            mod_props = getattr(arm, 'gesturebone_gesture_draw_props', None)
            if mod_props:
                for chain in mod_props.chains:
                    if not chain.is_bound:
                        row = layout.row()
                        row.alert = True
                        row.label(text=f"Unbound: {chain.part_name}", icon='UNLINKED')

        if props.debug_mode:
            col = layout.column(align=True)
            col.label(text="Overrides:", text_ctxt="extra-info-label")
            col.prop(props, "current_armature", text="Armature")
            col.prop(props, "current_gp", text="GP")


def register():
    bpy.utils.register_class(GESTUREBONE_PT_Infos)
    bpy.utils.register_class(GESTUREBONE_PT_MainPanel)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_MainPanel)
    bpy.utils.unregister_class(GESTUREBONE_PT_Infos)
