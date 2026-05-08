import os
import bpy

ESSENTIALS_BLEND = os.path.join(os.path.dirname(__file__), "essentials.blend")


def ensure_node_group(name: str):
    """Return a node group by name, appending from essentials.blend if absent."""
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    if not os.path.exists(ESSENTIALS_BLEND):
        print(f"[GestureBone] essentials.blend not found: {ESSENTIALS_BLEND}")
        return None
    with bpy.data.libraries.load(ESSENTIALS_BLEND, link=False) as (src, dst):
        if name in src.node_groups:
            dst.node_groups = [name]
        else:
            print(f"[GestureBone] Node group '{name}' not found in essentials.blend")
            return None
    return bpy.data.node_groups.get(name)


def ensure_asset(data_type: str, name: str):
    """Load any named datablock from essentials.blend if not already in bpy.data.

    data_type: 'node_groups', 'materials', 'objects', 'meshes', etc.
    Returns the datablock or None if not found.
    """
    collection = getattr(bpy.data, data_type, None)
    if collection is None:
        return None
    if name in collection:
        return collection[name]
    if not os.path.exists(ESSENTIALS_BLEND):
        print(f"[GestureBone] essentials.blend not found: {ESSENTIALS_BLEND}")
        return None
    with bpy.data.libraries.load(ESSENTIALS_BLEND, link=False) as (src, dst):
        src_col = getattr(src, data_type, [])
        if name in src_col:
            setattr(dst, data_type, [name])
        else:
            print(f"[GestureBone] '{name}' not found in essentials.blend ({data_type})")
            return None
    return collection.get(name)
