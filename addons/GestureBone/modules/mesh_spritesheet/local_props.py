import bpy
from bpy.props import PointerProperty, FloatProperty, IntProperty, BoolProperty
from bpy.types import PropertyGroup


class GESTUREBONE_MeshSpritesheetProps(PropertyGroup):
    spritesheet:    PointerProperty(name="Spritesheet", type=bpy.types.Image)
    panel_size:     FloatProperty(name="Scale", min=1.0, max=3.0, default=2.0)
    selected_cell:  IntProperty(name="Selected Cell", min=0, max=15, default=0)
    use_border_style: BoolProperty(name="Border Style", default=False)
    show_bg:         BoolProperty(name="Show Image", default=False)


def register():
    bpy.utils.register_class(GESTUREBONE_MeshSpritesheetProps)
    bpy.types.Object.gesturebone_mesh_spritesheet_props = PointerProperty(
        type=GESTUREBONE_MeshSpritesheetProps
    )


def unregister():
    del bpy.types.Object.gesturebone_mesh_spritesheet_props
    bpy.utils.unregister_class(GESTUREBONE_MeshSpritesheetProps)
