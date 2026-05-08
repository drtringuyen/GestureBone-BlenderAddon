import bpy
from bpy.props import StringProperty, PointerProperty, BoolProperty


def _bone_search(self, context, edit_text):
    arm = self.part_armature
    if arm and arm.type == 'ARMATURE':
        return [b.name for b in arm.data.bones if edit_text.lower() in b.name.lower()]
    return []


class GESTUREBONE_PG_CurveBoneChain(bpy.types.PropertyGroup):
    part_name: StringProperty(name="Name", default="Chain")
    part_gp: PointerProperty(
        name="GP",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'GREASEPENCIL',
    )
    part_material: PointerProperty(name="Material", type=bpy.types.Material)
    part_armature: PointerProperty(
        name="Armature",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE',
    )
    bone_0: StringProperty(name="1", search=_bone_search)
    bone_1: StringProperty(name="2", search=_bone_search)
    bone_2: StringProperty(name="3", search=_bone_search)
    bone_3: StringProperty(name="4", search=_bone_search)
    bone_4: StringProperty(name="5", search=_bone_search)

    is_bound: BoolProperty(name="Bound", default=False)
    is_drawing: BoolProperty(name="Drawing", default=False)
    bones_expanded: BoolProperty(name="Bones", default=False)

    # Saved before entering draw mode so we can restore it on toggle-off
    prev_active_object: StringProperty(default="")
    prev_mode: StringProperty(default="OBJECT")


def register():
    bpy.utils.register_class(GESTUREBONE_PG_CurveBoneChain)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PG_CurveBoneChain)
