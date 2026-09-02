"""
expression_sheet/props.py — sprite-grid settings and per-bone resolution.

Grid settings now live in two places and are merged by :func:`resolve_grid`:

  * per bone   — ``arm.gesturebone_props.expression_bones[...]`` (shared/arm_props.py),
                 saved on the rig so it travels through linking
  * scene-wide — ``context.scene.gesturebone_spritesheet``, the fallback for
                 bones that aren't registered, plus the default cell size

Only the scene half is registered/unregistered with the module; the per-bone
registry is rig DATA and lives in ``shared`` so toggling the module off in a
downstream file doesn't discard it.
"""
import bpy
from bpy.props import IntProperty, PointerProperty
from bpy.types import PropertyGroup


class GESTUREBONE_PG_Spritesheet(PropertyGroup):
    """Scene-level defaults, used for bones with no registry entry of their own
    and as the source of the default cell size."""

    grid_size: IntProperty(
        name="Cell Size",
        description="Pixel size of each square grid cell",
        default=96, min=25, max=200,
    )
    grid_count: IntProperty(
        name="Grid Count",
        description="Number of cells per row/column",
        default=4, min=2, max=8,
    )
    sheet_image: PointerProperty(
        name="Sheet",
        description="Sprite-sheet image shown when a bone has no sheet of its own",
        type=bpy.types.Image,
    )


# ── Per-bone resolution ───────────────────────────────────────────────────────

# Plain tuple rather than a PropertyGroup: the grid widget only ever reads these
# three values, and a resolved snapshot can blend per-bone and scene sources
# without either having to know about the other.
class GridSettings(tuple):
    """(cell_px, grid_count, image) — what the grid widget needs to draw."""
    __slots__ = ()

    def __new__(cls, cell_px, grid_count, image):
        return super().__new__(cls, (cell_px, grid_count, image))

    cell_px    = property(lambda self: self[0])
    grid_count = property(lambda self: self[1])
    image      = property(lambda self: self[2])

    @property
    def max_index(self):
        return self.grid_count ** 2 - 1


def find_entry(arm_obj, bone_name):
    """This bone's expression entry, or None if it isn't registered.

    Matches on ``entry.bone`` rather than the collection key so an entry whose
    ``name`` drifted out of sync (hand-edited, or an old file) still resolves.
    """
    if arm_obj is None or not bone_name:
        return None
    for entry in arm_obj.gesturebone_props.expression_bones:
        if entry.bone == bone_name:
            return entry
    return None


def scene_props(context=None):
    return (context or bpy.context).scene.gesturebone_spritesheet


def resolve_grid(arm_obj, bone_name, context=None):
    """Grid settings for *bone_name* on *arm_obj* — entry first, scene fallback.

    A per-bone ``grid_size`` of 0 (the default) means "use the scene's cell
    size": that value is a viewing preference tied to the monitor, not to the
    rig, so forcing every entry to carry one would bake a bad number into the
    linked file.
    """
    scn = scene_props(context)
    entry = find_entry(arm_obj, bone_name)
    if entry is None:
        return GridSettings(scn.grid_size, scn.grid_count, scn.sheet_image)
    return GridSettings(entry.grid_size or scn.grid_size,
                        entry.grid_count,
                        entry.sheet_image or scn.sheet_image)


def register():
    bpy.utils.register_class(GESTUREBONE_PG_Spritesheet)
    bpy.types.Scene.gesturebone_spritesheet = PointerProperty(type=GESTUREBONE_PG_Spritesheet)


def unregister():
    del bpy.types.Scene.gesturebone_spritesheet
    bpy.utils.unregister_class(GESTUREBONE_PG_Spritesheet)
