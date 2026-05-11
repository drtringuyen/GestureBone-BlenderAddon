from . import local_props, operators, ui


def register():
    local_props.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    local_props.unregister()
