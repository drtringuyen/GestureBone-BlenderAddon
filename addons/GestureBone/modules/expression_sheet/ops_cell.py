"""
expression_sheet/ops_cell.py — sprite-cell selector.

Merged from the standalone SpriteSheet script. Opens the shared sprite grid and
stores the picked cell index on the active object's custom property
(``spritesheet_index``), falling back to the scene-level ``chosen_index`` when
no owner object is given.
"""
import bpy
from bpy.props import StringProperty

from .grid import _SpriteGridBase

_CELL_PROP = "spritesheet_index"   # per-object custom property


def cell_index(props, owner):
    """Chosen cell index for *owner* (object name), clamped to the grid."""
    max_idx = props.grid_count ** 2 - 1
    if owner:
        ob = bpy.data.objects.get(owner)
        if ob is not None:
            return min(int(ob.get(_CELL_PROP, 0)), max_idx)
    return min(props.chosen_index, max_idx)


class GESTUREBONE_OT_SpritesheetSelect(_SpriteGridBase):
    """Open the sprite cell selection grid at the mouse"""
    bl_idname  = "gesturebone.spritesheet_select"
    bl_label   = "Select Sprite Cell"
    bl_options = {'REGISTER'}

    owner: StringProperty(
        name="Owner",
        description="Object that stores the chosen index; empty = scene-level",
        default="",
        options={'SKIP_SAVE'},
    )

    def _grid_props(self, context):
        return context.scene.gesturebone_spritesheet

    def _seed_chosen(self, context):
        return cell_index(context.scene.gesturebone_spritesheet, self.owner)

    def _commit(self, context, idx):
        if self.owner:
            ob = bpy.data.objects.get(self.owner)
            if ob is not None:
                ob[_CELL_PROP] = idx
        else:
            context.scene.gesturebone_spritesheet.chosen_index = idx


def register():
    bpy.utils.register_class(GESTUREBONE_OT_SpritesheetSelect)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_SpritesheetSelect)
