"""Info panel operators: Build popup, Reload, Debug toggle, Console toggle, Clear console."""
import bpy
import os
import json


def _read_build_info():
    build_file = os.path.join(os.path.dirname(__file__), "build_info.json")
    if os.path.exists(build_file):
        try:
            with open(build_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


class GESTUREBONE_OT_Build(bpy.types.Operator):
    bl_idname = "gesturebone.build"
    bl_label  = "Build"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.label(text="GestureBone", icon='ARMATURE_DATA')
        layout.separator()
        layout.label(text="Assist rigging & animation on bones aligned to curves or Grease Pencil")
        layout.separator()
        layout.label(text="Version: 0.0.1")
        layout.separator()
        build = _read_build_info()
        if build:
            layout.label(text="Last built: " + build.get("time", "Unknown"), icon='TIME')
        else:
            layout.label(text="Not built yet — run install.py first", icon='ERROR')

    def execute(self, context):
        return {'FINISHED'}


def _deferred_addon_reload():
    """Disable→re-enable the addon from a timer, i.e. OUTSIDE any operator.

    Reloading from inside gesturebone.reload's execute() unregisters the very
    operator that is still mid-invoke; when it returns, Blender tries to build
    its report pystring against a freed RNA type and crashes (seen on 5.1.2).
    Running from a one-shot timer defers the disable until the operator has
    fully returned and been reported.
    """
    import sys
    addon = "GestureBone"
    try:
        bpy.ops.preferences.addon_disable(module=addon)
        for m in [k for k in list(sys.modules) if k == addon or k.startswith(addon + ".")]:
            del sys.modules[m]
        bpy.ops.preferences.addon_enable(module=addon)
    except Exception as e:
        print(f"GestureBone: deferred reload failed: {e}")
    return None  # one-shot: do not reschedule


class GESTUREBONE_OT_Reload(bpy.types.Operator):
    bl_idname = "gesturebone.reload"
    bl_label  = "Reload Addon"
    bl_options = {'INTERNAL'}  # not REGISTER: Blender won't build a repr/report for it

    def execute(self, context):
        # Defer the actual disable/enable so it never runs while this operator
        # is still on the call stack (see _deferred_addon_reload docstring).
        if not bpy.app.timers.is_registered(_deferred_addon_reload):
            bpy.app.timers.register(_deferred_addon_reload, first_interval=0.01)
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleDebug(bpy.types.Operator):
    bl_idname = "gesturebone.toggle_debug"
    bl_label  = "Debug"

    def execute(self, context):
        props = context.scene.gesturebone_props
        props.debug_mode = not props.debug_mode
        self.report({'INFO'}, "Debug: " + ("ON" if props.debug_mode else "OFF"))
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleConsole(bpy.types.Operator):
    bl_idname = "gesturebone.toggle_console"
    bl_label  = "Console"

    def execute(self, context):
        import sys
        if sys.platform == "win32":
            try:
                bpy.ops.wm.console_toggle()
            except AttributeError:
                import subprocess
                subprocess.Popen('start cmd', shell=True, creationflags=subprocess.DETACHED_PROCESS)
        else:
            self.report({'INFO'}, "Use Window > Toggle System Console")
        return {'FINISHED'}


class GESTUREBONE_OT_ClearConsole(bpy.types.Operator):
    bl_idname = "gesturebone.clear_console"
    bl_label  = "Clear"

    def execute(self, context):
        import sys
        os.system("cls" if sys.platform == "win32" else "clear")
        return {'FINISHED'}


class GESTUREBONE_OT_TogglePlotting(bpy.types.Operator):
    bl_idname = "gesturebone.toggle_plotting"
    bl_label  = "Plotting"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("plotting")
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleGesture(bpy.types.Operator):
    bl_idname = "gesturebone.toggle_gesture"
    bl_label  = "Gesture"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("gesture")
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_Build,
    GESTUREBONE_OT_Reload,
    GESTUREBONE_OT_ToggleDebug,
    GESTUREBONE_OT_ToggleConsole,
    GESTUREBONE_OT_ClearConsole,
    GESTUREBONE_OT_TogglePlotting,
    GESTUREBONE_OT_ToggleGesture,
]



class GESTUREBONE_OT_ToggleRiglinking(bpy.types.Operator):
    """Toggle Riglinking module on/off"""
    bl_idname = "gesturebone.toggle_riglinking"
    bl_label = "Riglinking"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("riglinking")
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleExpressionSheet(bpy.types.Operator):
    """Toggle ExpressionSheet module on/off"""
    bl_idname = "gesturebone.toggle_expression_sheet"
    bl_label = "ExpressionSheet"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("expression_sheet")
        return {'FINISHED'}

def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleRiglinking)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleExpressionSheet)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleExpressionSheet)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleRiglinking)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
