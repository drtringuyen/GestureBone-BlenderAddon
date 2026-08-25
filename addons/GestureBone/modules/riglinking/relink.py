"""
riglinking/relink.py — Repair GestureBone's custom object pointers on library
overrides.

Blender's library-override system remaps *managed* pointers (constraints,
modifiers, parenting) to the local override / made-local datablocks, but it does
NOT remap custom ``PropertyGroup`` ID pointers. So after a rig is linked and
overridden, these keep pointing at the linked library datablocks:

    * gesture_arm.gesturebone_props.plotting_rig  -> linked MetaPlot
    * chain.gesture_rig                           -> linked GESTURE rig
    * chain.gesture_spline                         -> linked (non-editable) curve

That breaks chain resolution (``chain.gesture_rig == gesture_arm`` is False) and
drawing (edit mode on a linked curve raises "Cannot edit library linked ...").

``relink_override_rigs()`` rebuilds those pointers to the local equivalents. It
is idempotent and cheap, so it is safe to call from the Localize operator and
from a ``load_post`` handler on every file open.
"""
import bpy


def _override_of(linked_id):
    """Return the local override object whose reference is *linked_id*, or None."""
    if linked_id is None:
        return None
    for o in bpy.data.objects:
        ol = o.override_library
        if ol is not None and ol.reference == linked_id:
            return o
    return None


def _local_twin(linked_obj):
    """Return a fully-local object sharing *linked_obj*'s name, or None.

    A made-local curve and its linked namesake coexist (the linked ID is
    namespaced by its library), so match on name + local status.
    """
    if linked_obj is None:
        return None
    for o in bpy.data.objects:
        if o.library is None and o.override_library is None and o.name == linked_obj.name:
            return o
    return None


def relink_override_rigs():
    """Fix cross-boundary pointers on every override GESTURE rig in the file.

    Returns the number of pointers changed (0 means everything was already
    consistent — the common case for a purely local scene).
    """
    changed = 0
    for g in bpy.data.objects:
        if g.type != 'ARMATURE':
            continue
        gp = g.gesturebone_props
        if gp.rig_type != 'GESTURE' or g.override_library is None:
            continue

        # 1. plotting_rig: linked MetaPlot -> its local override
        pr = gp.plotting_rig
        if pr is not None and pr.library is not None:
            ov = _override_of(pr)
            if ov is not None and ov != pr:
                gp.plotting_rig = ov
                pr = ov
                changed += 1
        if pr is None:
            continue

        # 2. chain pointers on the (override) MetaPlot
        for chain in pr.gesturebone_props.chains:
            # gesture_rig: linked GESTURE rig -> this override rig (match by ref)
            cgr = chain.gesture_rig
            if (cgr is not None and cgr.library is not None
                    and g.override_library.reference == cgr):
                chain.gesture_rig = g
                changed += 1

            # gesture_spline: linked curve -> local made-local twin
            gs = chain.gesture_spline
            if gs is not None and gs.library is not None:
                twin = _local_twin(gs)
                if twin is not None:
                    chain.gesture_spline = twin
                    changed += 1
    return changed
