from . import curve_bone_chain, local_props, operators, ui


def register():
    curve_bone_chain.register()
    local_props.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    local_props.unregister()
    curve_bone_chain.unregister()
