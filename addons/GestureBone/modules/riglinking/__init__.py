"""
riglinking/__init__.py — Rig Linking module.

Keeps GestureBone working when a rig is linked from another .blend and library-
overridden. Provides:
  * Localize / Relink operators (operators.py)
  * A UI section (ui.py)
  * A persistent load_post handler that re-applies the pointer relink on every
    file open (relink.py) — this is what makes drawing survive reopening.
"""
import bpy
from bpy.app.handlers import persistent

from . import operators, ui, relink


@persistent
def _relink_on_load(_dummy):
    """Rebuild override rig pointers after the file loads."""
    try:
        n = relink.relink_override_rigs()
        if n:
            print(f"GestureBone/RigLinking: relinked {n} override pointer(s) on load")
    except Exception as e:
        print(f"GestureBone/RigLinking: relink on load failed: {e!r}")


def register():
    operators.register()
    ui.register()
    if _relink_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_relink_on_load)
    # Also repair the file that is already open when the module is enabled.
    try:
        relink.relink_override_rigs()
    except Exception:
        pass


def unregister():
    if _relink_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_relink_on_load)
    ui.unregister()
    operators.unregister()
