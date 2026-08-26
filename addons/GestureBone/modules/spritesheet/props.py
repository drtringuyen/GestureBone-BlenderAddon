"""
spritesheet/props.py — unified grid settings for the Spritesheet module.

Both the sprite-cell selector and the pose-expression grid share one set of
grid settings, stored scene-level at ``context.scene.gesturebone_spritesheet``.
Registered/unregistered with the module, so it disappears when the module is
toggled off (matching the other GestureBone modules).
"""
import bpy
from bpy.props import IntProperty, PointerProperty
from bpy.types import PropertyGroup


def _on_grid_count_update(self, context):
    """Keep the scene-level fallback index inside the (new) grid bounds."""
    max_idx = self.grid_count ** 2 - 1
    if self.chosen_index > max_idx:
        self.chosen_index = max_idx


class GESTUREBONE_PG_Spritesheet(PropertyGroup):

    grid_size: IntProperty(
        name="Cell Size",
        description="Pixel size of each square grid cell",
        default=96, min=25, max=200,
    )
    grid_count: IntProperty(
        name="Grid Count",
        description="Number of cells per row/column",
        default=4, min=2, max=8,
        update=_on_grid_count_update,
    )
    chosen_index: IntProperty(
        name="Chosen Index",
        description="Scene-level fallback cell index (UV order: 0 = bottom-left)",
        default=0, min=0, max=63,
    )
    sheet_image: PointerProperty(
        name="Sheet",
        description="Sprite-sheet image to display on the grid",
        type=bpy.types.Image,
    )


def register():
    bpy.utils.register_class(GESTUREBONE_PG_Spritesheet)
    bpy.types.Scene.gesturebone_spritesheet = PointerProperty(type=GESTUREBONE_PG_Spritesheet)


def unregister():
    del bpy.types.Scene.gesturebone_spritesheet
    bpy.utils.unregister_class(GESTUREBONE_PG_Spritesheet)
