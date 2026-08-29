"""
shared/utils_gn.py — Geometry Nodes modifier helpers.
Moved from gesture_draw/utils_gn.py, no logic changes.
"""
import bpy


def _find_gn_modifier(obj):
    """Find TOB-Gesture_drawing modifier; fall back to first NODES modifier."""
    if not obj:
        return None
    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group and mod.node_group.name == "TOB-Gesture_drawing":
            return mod
    for mod in obj.modifiers:
        if mod.type == 'NODES':
            return mod
    return None


def _find_socket_id(mod, socket_name):
    """Return identifier of a GN modifier input socket by display name."""
    if not mod or not mod.node_group:
        return None
    ng = mod.node_group
    try:
        for item in ng.interface.items_tree:
            if item.name != socket_name:
                continue
            if not hasattr(item, 'identifier'):
                continue
            if 'OUTPUT' in str(getattr(item, 'in_out', 'INPUT')):
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


def _gn_socket(mod, socket_id):
    """Return the Blender 5.2+ modifier input wrapper for socket_id, else None.

    Panel items in interface.items_tree carry an int identifier — those are
    never sockets, so reject any non-str id up front.
    """
    if not isinstance(socket_id, str):
        return None
    props = getattr(mod, "properties", None)
    inputs = getattr(props, "inputs", None) if props else None
    if inputs is None:
        return None
    return getattr(inputs, socket_id, None)


def _get_gn_input(mod, socket_id, default=None):
    """Read a GN modifier input by socket identifier.

    Blender 5.2 moved modifier inputs off plain ID-properties
    (mod["Socket_X"]) onto mod.properties.inputs.Socket_X.value; older
    versions still use the ID-property form. Sockets that carry no value
    (Geometry) and unknown ids return `default`.
    """
    socket = _gn_socket(mod, socket_id)
    if socket is not None:
        return getattr(socket, "value", default)
    try:
        return mod[socket_id]
    except (KeyError, TypeError):
        return default


def _set_gn_input(mod, socket_id, value):
    """Set a GN modifier input by socket identifier. Returns True if written."""
    socket = _gn_socket(mod, socket_id)
    if socket is not None:
        if not hasattr(socket, "value"):
            return False
        socket.value = value
        return True
    try:
        mod[socket_id] = value
        return True
    except (KeyError, TypeError):
        return False


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


def _sync_gesture_spline_gn(chain):
    """Ensure gesture spline has TOB-Gesture_drawing modifier with correct sockets."""
    spline = chain.gesture_spline
    if spline is None:
        return
    ng = bpy.data.node_groups.get("TOB-Gesture_drawing")
    if ng is None:
        return
    mod = next((m for m in spline.modifiers if m.type == 'NODES' and m.node_group == ng), None)
    if mod is None:
        mod = spline.modifiers.new(name="GeometryNodes", type='NODES')
        mod.node_group = ng
    _set_gn_input(mod, "Socket_10", chain.control_point_count)
    _set_gn_input(mod, "Socket_8", 2)
    _set_gn_input(mod, "Socket_6", chain.bone_handle_smoothness)
