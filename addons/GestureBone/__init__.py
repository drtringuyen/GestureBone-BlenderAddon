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


def register():
    from . import properties, infos, panels
    properties.register()
    infos.register()
    panels.register()

    from . import module_manager
    module_manager.load_all()


def unregister():
    from . import module_manager
    module_manager.unload_all()

    from . import properties, infos, panels
    panels.unregister()
    infos.unregister()
    properties.unregister()
