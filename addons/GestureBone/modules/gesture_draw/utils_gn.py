import bpy


def _find_gn_modifier(gp_obj):
    """Find the TOB-Gesture_drawing geonode modifier; fall back to first NODES modifier."""
    if not gp_obj:
        return None
    for mod in gp_obj.modifiers:
        if mod.type == 'NODES' and mod.node_group and mod.node_group.name == "TOB-Gesture_drawing":
            return mod
    for mod in gp_obj.modifiers:
        if mod.type == 'NODES':
            return mod
    return None


def _find_socket_id(mod, socket_name):
    """Return the identifier of a GN modifier input socket by display name.

    Tries interface.items_tree (Blender 4.0+) then ng.inputs (older fallback).
    """
    if not mod or not mod.node_group:
        return None
    ng = mod.node_group
    try:
        for item in ng.interface.items_tree:
            if item.name != socket_name:
                continue
            if not hasattr(item, 'identifier'):
                continue
            in_out = str(getattr(item, 'in_out', 'INPUT'))
            if 'OUTPUT' in in_out:
                continue
            return item.identifier
    except Exception:
        pass
    try:
        for inp in ng.inputs:
            if inp.name == socket_name and hasattr(inp, 'identifier'):
                return inp.identifier
    except Exception:
        pass
    return None


def _ensure_object_collections_visible(view_layer, obj):
    """Ensure all collections containing obj are not excluded from the view layer."""
    def _set_visible(layer_coll, target_coll):
        if layer_coll.collection == target_coll:
            layer_coll.exclude = False
            return True
        for child in layer_coll.children:
            if _set_visible(child, target_coll):
                return True
        return False
    for coll in obj.users_collection:
        _set_visible(view_layer.layer_collection, coll)
