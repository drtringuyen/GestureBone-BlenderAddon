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
    """Keep current_armature pointing at the user's PLOTTING rig.

    - PLOTTING rig selected → track it directly.
    - GESTURE rig selected → track its plotting_rig back-pointer.
    - NONE / PRESET / non-armature → leave current_armature unchanged so step
      operators (which temporarily activate generated rigs) still resolve the
      correct PLOTTING rig via the fallback in _active_plotting_arm().
    """
    ctx = bpy.context
    obj = getattr(ctx, 'active_object', None)
    if obj is None or obj.type != 'ARMATURE':
        return
    try:
        gp    = scene.gesturebone_props
        rtype = obj.gesturebone_props.rig_type
        if rtype == 'PLOTTING':
            gp.current_armature = obj
        elif rtype == 'GESTURE':
            plotting = obj.gesturebone_props.plotting_rig
            if plotting and plotting.type == 'ARMATURE':
                gp.current_armature = plotting
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
