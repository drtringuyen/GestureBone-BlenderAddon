import bpy


def _active_arm(context):
    obj = context.active_object
    if obj and obj.type == 'ARMATURE':
        return obj
    fallback = context.scene.gesturebone_props.current_armature
    return fallback if fallback and fallback.type == 'ARMATURE' else None


class GESTUREBONE_PT_MeshSpritesheet(bpy.types.Panel):
    bl_label = "Mesh Spritesheet"
    bl_idname = "GESTUREBONE_PT_mesh_spritesheet"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_main"
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        arm = _active_arm(context)
        if arm is None:
            row = layout.row()
            row.alert = True
            row.label(text="Select an armature", icon='ERROR')
            return
        gd = getattr(arm, 'gesturebone_gesture_draw_props', None)
        if gd is None:
            return
        ms = getattr(arm, 'gesturebone_mesh_spritesheet_props', None)
        if ms is None:
            return

        row = layout.row(align=True)
        row.operator("gesturebone.open_spritesheet_selection", text="", icon='LONGDISPLAY')
        style_icon = 'SHADING_BBOX' if ms.use_border_style else 'SHADING_RENDERED'
        row.prop(ms, "use_border_style", text="", toggle=True, icon=style_icon)
        bg_icon = 'IMAGE_DATA' if ms.show_bg else 'IMAGE_BACKGROUND'
        row.prop(ms, "show_bg", text="", toggle=True, icon=bg_icon)
        row.prop(ms, "spritesheet", text="")
        row.prop(ms, "panel_size", text="")


def register():
    bpy.utils.register_class(GESTUREBONE_PT_MeshSpritesheet)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_MeshSpritesheet)
