import bpy
import bpy.utils.previews
from bpy.props import IntProperty

GRID_ROWS = 4
GRID_COLS = 4

# ── Preview cache ──────────────────────────────────────────────────────────────
_pcoll       = None
_pcoll_icons = []   # index = r*GRID_COLS + c  (r=0 = UV bottom row)
_pcoll_key   = None # (image name, W, H) invalidation key


def _ms_props(context):
    arm = context.active_object
    if arm is None or arm.type != 'ARMATURE':
        arm = context.scene.gesturebone_props.current_armature
    if arm is None:
        return None
    return getattr(arm, 'gesturebone_mesh_spritesheet_props', None)


def _build_cell_icons(img):
    global _pcoll, _pcoll_icons, _pcoll_key

    key = (img.name, img.size[0], img.size[1]) if img else None
    if key == _pcoll_key and _pcoll_icons:
        return  # still valid

    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None
    _pcoll_icons = []
    _pcoll_key   = None

    if not img or not img.has_data:
        return

    W, H = img.size[0], img.size[1]
    if W <= 0 or H <= 0:
        return

    cell_w = max(1, W // GRID_COLS)
    cell_h = max(1, H // GRID_ROWS)

    try:
        import numpy as np
        pixels = np.array(img.pixels[:]).reshape(H, W, 4)
    except Exception:
        return

    _pcoll = bpy.utils.previews.new()

    for r in range(GRID_ROWS):          # r=0 = UV bottom
        for c in range(GRID_COLS):
            y0, y1 = r * cell_h, min(r * cell_h + cell_h, H)
            x0, x1 = c * cell_w, min(c * cell_w + cell_w, W)
            cell_px = pixels[y0:y1, x0:x1].flatten().tolist()
            prev = _pcoll.new(f"c{r}_{c}")
            prev.image_size         = (x1 - x0, y1 - y0)
            prev.image_pixels_float = cell_px
            _pcoll_icons.append(prev.icon_id)   # index = r*4 + c

    _pcoll_key = key


# ── Menu (auto-closes on any item click) ──────────────────────────────────────

class GESTUREBONE_MT_SpritesheetPicker(bpy.types.Menu):
    bl_idname = "GESTUREBONE_MT_spritesheet_picker"
    bl_label  = "Spritesheet"

    def draw(self, context):
        ms = _ms_props(context)
        if ms is None:
            return

        layout = self.layout

        # panel_size=1 → 25px per cell, panel_size=3 → 75px per cell.
        # Blender: 1 UI unit = 20px (logical, DPI-independent).
        # Default row height ≈ 20px, so scale_y = cell_u gives square rows.
        CELL_PX   = 25.0
        UI_UNIT   = 20.0
        cell_u    = ms.panel_size * CELL_PX / UI_UNIT  # UI units per cell edge

        layout.ui_units_x = GRID_COLS * cell_u

        col         = layout.column(align=True)
        col.scale_y = cell_u

        # Draw r=3 at visual top, r=0 at visual bottom (UV convention: 0=bottom)
        for r in range(GRID_ROWS - 1, -1, -1):
            row = col.row(align=True)
            for c in range(GRID_COLS):
                idx    = r * GRID_COLS + c
                is_sel = idx == ms.selected_cell

                sub = row.row(align=True)
                if not ms.use_border_style:
                    sub.active = is_sel

                icon_val = 0
                if ms.show_bg and _pcoll_icons and idx < len(_pcoll_icons):
                    icon_val = _pcoll_icons[idx]

                op            = sub.operator(
                    "gesturebone.select_spritesheet_cell",
                    text="",
                    icon_value=icon_val,
                    depress=is_sel,
                    emboss=True,
                )
                op.cell_index = idx


# ── Trigger operator (builds icons then opens the menu) ───────────────────────

class GESTUREBONE_OT_OpenSpritesheetSelection(bpy.types.Operator):
    bl_idname  = "gesturebone.open_spritesheet_selection"
    bl_label   = "Select Spritesheet Cell"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        ms = _ms_props(context)
        if ms is None:
            return {'CANCELLED'}
        if ms.show_bg and ms.spritesheet:
            _build_cell_icons(ms.spritesheet)
        bpy.ops.wm.call_menu(name="GESTUREBONE_MT_spritesheet_picker")
        return {'FINISHED'}

    def execute(self, context):
        return {'FINISHED'}


# ── Cell selection (menu closes automatically after this runs) ────────────────

class GESTUREBONE_OT_SelectSpritesheetCell(bpy.types.Operator):
    bl_idname  = "gesturebone.select_spritesheet_cell"
    bl_label   = ""
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    cell_index: IntProperty()

    def execute(self, context):
        ms = _ms_props(context)
        if ms is None:
            return {'CANCELLED'}
        ms.selected_cell = self.cell_index
        return {'FINISHED'}


classes = [
    GESTUREBONE_MT_SpritesheetPicker,
    GESTUREBONE_OT_OpenSpritesheetSelection,
    GESTUREBONE_OT_SelectSpritesheetCell,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None
    for cls in classes:
        bpy.utils.unregister_class(cls)
