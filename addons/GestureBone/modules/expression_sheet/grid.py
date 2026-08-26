"""
expression_sheet/grid.py — shared GPU sprite-grid widget.

Both tools in this module draw the *same* modal grid: a sprite sheet sliced
into ``grid_count**2`` square cells, placed at the mouse and picked by click.
The sprite-cell selector (``ops_cell``) and the pose-expression picker
(``ops_pose_expr``) were originally two standalone scripts that duplicated all
of this code; it now lives here once. Subclasses of :class:`_SpriteGridBase`
override only the three hooks that differ — which PropertyGroup holds the grid
settings, how the initial highlight is seeded, and what a pick commits.
"""
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader


# ── GPU draw helpers ──────────────────────────────────────────────────────────

def _quad(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]


def _fill_rect(shader, x0, y0, x1, y1, color):
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'TRIS', {"pos": _quad(x0, y0, x1, y1)}).draw(shader)


def _border_rect(shader, x0, y0, x1, y1, color, t):
    _fill_rect(shader, x0, y0, x1, y0 + t, color)          # bottom
    _fill_rect(shader, x0, y1 - t, x1, y1, color)          # top
    _fill_rect(shader, x0, y0, x0 + t, y1, color)          # left
    _fill_rect(shader, x1 - t, y0, x1, y1, color)          # right


# ── Shared modal grid operator ────────────────────────────────────────────────

class _SpriteGridBase(bpy.types.Operator):
    """Modal operator: draw the sprite grid, resolve a clicked cell.

    Abstract — never registered directly. Subclasses supply ``bl_idname`` /
    ``bl_label`` and implement:

    * ``_grid_props(context)``  -> PropertyGroup with grid_size/grid_count/sheet_image
    * ``_seed_chosen(context)`` -> int   initial highlighted cell, or -1
    * ``_commit(context, idx)`` -> None  apply the chosen cell index

    Optionally ``_prepare(context) -> bool`` runs before the grid opens; return
    ``False`` to cancel.
    """
    bl_options = {'REGISTER'}

    # ---- hooks (override) ----------------------------------------------

    def _grid_props(self, context):
        raise NotImplementedError

    def _seed_chosen(self, context):
        return -1

    def _commit(self, context, idx):
        raise NotImplementedError

    def _prepare(self, context):
        return True

    # ---- geometry ------------------------------------------------------

    def _cell_rect(self, idx):
        """Screen rect of cell *idx*. UV order: row 0 = bottom (y is up)."""
        x0, y0, _, _ = self._rect
        col = idx %  self._gc
        row = idx // self._gc
        cx0 = x0 + self._pad + col * (self._cell + self._gap)
        cy0 = y0 + self._pad + row * (self._cell + self._gap)
        return cx0, cy0, cx0 + self._cell, cy0 + self._cell

    def _pick(self, rx, ry):
        for idx in range(self._gc * self._gc):
            cx0, cy0, cx1, cy1 = self._cell_rect(idx)
            if cx0 <= rx <= cx1 and cy0 <= ry <= cy1:
                return idx
        return -1

    # ---- lifecycle -----------------------------------------------------

    def invoke(self, context, event):
        area = context.area
        if area is None or area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Open from a 3D View")
            return {'CANCELLED'}
        self._region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if self._region is None:
            return {'CANCELLED'}
        if not self._prepare(context):
            return {'CANCELLED'}

        props = self._grid_props(context)
        ui = context.preferences.system.ui_scale
        self._ui   = ui
        self._gc   = props.grid_count
        self._cell = int(props.grid_size * ui)
        self._pad  = int(6 * ui)
        self._gap  = int(2 * ui)
        side = (self._gc * self._cell
                + (self._gc - 1) * self._gap
                + 2 * self._pad)

        # place the grid at the click, clamped inside the 3D view region
        rx = event.mouse_x - self._region.x
        ry = event.mouse_y - self._region.y
        x1 = max(side + 4, min(rx, self._region.width  - 4))
        y1 = max(side + 4, min(ry, self._region.height - 4))
        self._rect = (x1 - side, y1 - side, x1, y1)

        img = props.sheet_image
        self._tex    = gpu.texture.from_image(img) if img is not None else None
        self._chosen = self._seed_chosen(context)
        self._hover  = -1

        self._handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_px, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        self._region.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handler, 'WINDOW')
        self._region.tag_redraw()
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()
        return {'FINISHED'}

    def modal(self, context, event):
        rx = event.mouse_x - self._region.x
        ry = event.mouse_y - self._region.y

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            hov = self._pick(rx, ry)
            if hov != self._hover:
                self._hover = hov
                self._region.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            idx = self._pick(rx, ry)
            if idx >= 0:
                self._commit(context, idx)
                return self._finish(context)
            x0, y0, x1, y1 = self._rect
            if not (x0 <= rx <= x1 and y0 <= ry <= y1):
                return self._finish(context)          # click outside: cancel, no changes
            return {'RUNNING_MODAL'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            return self._finish(context)              # cancel: no changes

        return {'RUNNING_MODAL'}

    # ---- drawing -------------------------------------------------------

    def _draw_px(self, context):
        if context.region != self._region:
            return                                    # other 3D views: skip

        gpu.state.blend_set('ALPHA')
        col_sh = gpu.shader.from_builtin('UNIFORM_COLOR')

        # background panel (fills the whole popup area)
        x0, y0, x1, y1 = self._rect
        _fill_rect(col_sh, x0, y0, x1, y1, (0.08, 0.08, 0.09, 0.97))
        _border_rect(col_sh, x0, y0, x1, y1, (0.25, 0.25, 0.27, 1.0), 1)

        gc = self._gc
        for idx in range(gc * gc):
            cx0, cy0, cx1, cy1 = self._cell_rect(idx)

            if self._tex is not None:
                # full-bleed image slice: cell quad textured with its UV subrect
                img_sh = gpu.shader.from_builtin('IMAGE')
                u0 = (idx %  gc) / gc
                v0 = (idx // gc) / gc
                u1 = u0 + 1.0 / gc
                v1 = v0 + 1.0 / gc
                batch = batch_for_shader(img_sh, 'TRIS', {
                    "pos":      _quad(cx0, cy0, cx1, cy1),
                    "texCoord": [(u0, v0), (u1, v0), (u1, v1),
                                 (u0, v0), (u1, v1), (u0, v1)],
                })
                img_sh.bind()
                img_sh.uniform_sampler("image", self._tex)
                batch.draw(img_sh)
            else:
                _fill_rect(col_sh, cx0, cy0, cx1, cy1, (0.22, 0.22, 0.23, 1.0))
                txt = str(idx)
                blf.size(0, int(13 * self._ui))
                tw, th = blf.dimensions(0, txt)
                blf.position(0, (cx0 + cx1) / 2 - tw / 2,
                                (cy0 + cy1) / 2 - th / 2, 0)
                blf.color(0, 0.85, 0.85, 0.85, 1.0)
                blf.draw(0, txt)

            if idx == self._chosen:
                _border_rect(col_sh, cx0, cy0, cx1, cy1,
                             (0.25, 0.55, 1.0, 1.0), max(2, int(2 * self._ui)))
            elif idx == self._hover:
                _border_rect(col_sh, cx0, cy0, cx1, cy1,
                             (1.0, 1.0, 1.0, 0.7), max(1, int(1 * self._ui)))

        gpu.state.blend_set('NONE')
