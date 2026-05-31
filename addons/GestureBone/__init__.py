bl_info = {
    "name": "GestureBone",
    "version": (0, 0, 1),
    "blender": (4, 0, 0),
    "category": "Rigging",
    "description": "Assist rigging & animation on bones aligned to curves or Grease Pencil",
    "author": "",
    "doc_url": "",
    "tracker_url": "",
}

import bpy


@bpy.app.handlers.persistent
def _track_active_armature(scene, depsgraph):
    """Keep current_armature in sync with the active armature.
    Only updates when the active object IS an armature — switching to GP or
    any non-armature leaves the pointer unchanged so operators keep working
    during drawing."""
    ctx = bpy.context
    obj = getattr(ctx, 'active_object', None)
    if obj and obj.type == 'ARMATURE':
        try:
            props = scene.gesturebone_props
            props.current_armature = obj
        except Exception:
            pass


def register():
    from . import properties, infos, panels, extra_infos
    properties.register()
    infos.register()
    panels.register()
    extra_infos.register()

    # shared must be registered before plotting and gesture modules
    from .modules import shared
    shared.register()

    from . import module_manager
    module_manager.load_all()

    if _track_active_armature not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_track_active_armature)


def unregister():
    if _track_active_armature in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_track_active_armature)

    from . import module_manager
    module_manager.unload_all()

    from .modules import shared
    shared.unregister()

    from . import properties, infos, panels, extra_infos
    extra_infos.unregister()
    panels.unregister()
    infos.unregister()
    properties.unregister()
