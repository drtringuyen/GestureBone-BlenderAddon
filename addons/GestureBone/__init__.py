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
    """Set current_armature only when it is None (null situation).
    Never overrides an already-set armature so bindings are never lost
    when the active object switches to GP during drawing."""
    ctx = bpy.context
    obj = getattr(ctx, 'active_object', None)
    if obj and obj.type == 'ARMATURE':
        try:
            props = scene.gesturebone_props
            if props.current_armature is None:
                props.current_armature = obj
        except Exception:
            pass


def register():
    from . import properties, infos, panels
    properties.register()
    infos.register()
    panels.register()

    from . import module_manager
    module_manager.load_all()

    if _track_active_armature not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_track_active_armature)


def unregister():
    if _track_active_armature in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_track_active_armature)

    from . import module_manager
    module_manager.unload_all()

    from . import properties, infos, panels
    panels.unregister()
    infos.unregister()
    properties.unregister()
