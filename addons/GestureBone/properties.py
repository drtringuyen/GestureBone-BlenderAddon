import bpy
from bpy.props import BoolProperty, StringProperty, PointerProperty


class GESTUREBONEProperties(bpy.types.PropertyGroup):
    debug_mode: BoolProperty(
        name="Debug Mode",
        description="Show extra-info-label and debug information",
        default=False
    )
    last_build_time: StringProperty(default="Never")
    addon_version: StringProperty(default="0.0.1")

    main_armature: PointerProperty(
        name="Main Armature",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE',
    )
    main_gp: PointerProperty(
        name="Main GP",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'GREASEPENCIL',
    )


def register():
    bpy.utils.register_class(GESTUREBONEProperties)
    bpy.types.Scene.gesturebone_props = PointerProperty(type=GESTUREBONEProperties)


def unregister():
    del bpy.types.Scene.gesturebone_props
    bpy.utils.unregister_class(GESTUREBONEProperties)
