"""Reload GestureBone addon. Run this from Blender's Text Editor after install.py."""
import bpy
import importlib
import sys

ADDON_NAME = "GestureBone"


def reload_addon():
    # Reload all submodules so changes are picked up
    mods = [m for m in sys.modules if m == ADDON_NAME or m.startswith(ADDON_NAME + ".")]
    for mod_name in sorted(mods, reverse=True):
        importlib.reload(sys.modules[mod_name])
        print(f"  reloaded: {mod_name}")

    # Disable then re-enable to re-run register()
    bpy.ops.preferences.addon_disable(module=ADDON_NAME)
    bpy.ops.preferences.addon_enable(module=ADDON_NAME)
    print(f"[OK] {ADDON_NAME} reloaded")


reload_addon()
