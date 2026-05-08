import bpy
from bpy.props import CollectionProperty, IntProperty, PointerProperty
from .curve_bone_chain import GESTUREBONE_PG_CurveBoneChain


class GESTUREBONE_GESTUREDRAW_PG_Props(bpy.types.PropertyGroup):
    part_gp: PointerProperty(
        name="GP",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'GREASEPENCIL',
    )
    chains: CollectionProperty(type=GESTUREBONE_PG_CurveBoneChain)
    active_chain_index: IntProperty(default=0, min=0)


def register():
    bpy.utils.register_class(GESTUREBONE_GESTUREDRAW_PG_Props)
    bpy.types.Object.gesturebone_gesture_draw_props = PointerProperty(type=GESTUREBONE_GESTUREDRAW_PG_Props)


def unregister():
    del bpy.types.Object.gesturebone_gesture_draw_props
    bpy.utils.unregister_class(GESTUREBONE_GESTUREDRAW_PG_Props)
