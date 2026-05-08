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

    current_armature: PointerProperty(
        name="Current Armature",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE',
    )
    current_gp: PointerProperty(
        name="Current GP",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'GREASEPENCIL',
    )


def register():
    bpy.utils.register_class(GESTUREBONEProperties)
    bpy.types.Scene.gesturebone_props = PointerProperty(type=GESTUREBONEProperties)


def unregister():
    del bpy.types.Scene.gesturebone_props
    bpy.utils.unregister_class(GESTUREBONEProperties)
