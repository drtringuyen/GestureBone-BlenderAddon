from . import curve_bone_chain, local_props, operators_common, operators, operators_bake, ui


def register():
    curve_bone_chain.register()
    local_props.register()
    operators_common.register()
    operators.register()
    operators_bake.register()
    ui.register()


def unregister():
    ui.unregister()
    operators_bake.unregister()
    operators.unregister()
    operators_common.unregister()
    local_props.unregister()
    curve_bone_chain.unregister()
