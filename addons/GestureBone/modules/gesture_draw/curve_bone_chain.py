import bpy
from bpy.props import StringProperty, PointerProperty, BoolProperty, IntProperty


def _bone_search(self, context, edit_text):
    arm = context.active_object if context and context.active_object and context.active_object.type == 'ARMATURE' else None
    if arm:
        return [b.name for b in arm.data.bones if edit_text.lower() in b.name.lower()]
    return []


class GESTUREBONE_PG_CurveBoneChain(bpy.types.PropertyGroup):
    part_name: StringProperty(name="Name", default="Chain")
    part_material: PointerProperty(name="Material", type=bpy.types.Material)
    bone_0: StringProperty(name="1", search=_bone_search)
    bone_1: StringProperty(name="2", search=_bone_search)
    bone_2: StringProperty(name="3", search=_bone_search)
    bone_3: StringProperty(name="4", search=_bone_search)
    bone_4: StringProperty(name="5", search=_bone_search)

    is_bound: BoolProperty(name="Bound", default=False)
    is_drawing: BoolProperty(name="Drawing", default=False)
    bones_expanded: BoolProperty(name="Bones", default=False)

    prev_active_object: StringProperty(default="")
    prev_mode: StringProperty(default="OBJECT")

    last_baked_frame: IntProperty(name="Last Baked Frame", default=-1)
    stroke_count_cache: IntProperty(name="Stroke Count Cache", default=0)
    drawing_frame: IntProperty(name="Drawing Frame", default=-1)


def register():
    bpy.utils.register_class(GESTUREBONE_PG_CurveBoneChain)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PG_CurveBoneChain)
