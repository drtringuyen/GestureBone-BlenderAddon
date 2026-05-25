import bpy


def _resize_collection(coll, count):
    while len(coll) < count:
        coll.add()
    while len(coll) > count:
        coll.remove(len(coll) - 1)


def _find_arm_collection(arm, scene):
    """Return the first non-root collection that contains the armature, or scene root."""
    for coll in arm.users_collection:
        if coll != scene.collection:
            return coll
    return scene.collection


def _ensure_child_collection(name, parent_coll):
    """Return a collection named *name* that is a child of parent_coll, creating if needed."""
    if name in bpy.data.collections:
        coll = bpy.data.collections[name]
    else:
        coll = bpy.data.collections.new(name)
    if name not in {c.name for c in parent_coll.children}:
        try:
            parent_coll.children.link(coll)
        except Exception:
            pass
    return coll


def _move_object_to_collection(obj, target_coll):
    """Move obj into target_coll, unlinking it from all other collections."""
    for coll in list(obj.users_collection):
        if coll.name != target_coll.name:
            try:
                coll.objects.unlink(obj)
            except Exception:
                pass
    if obj.name not in target_coll.objects:
        try:
            target_coll.objects.link(obj)
        except Exception:
            pass


def _ensure_chain_objects(arm, chain, context):
    """Find or create gesture/plotting spline curve objects for this chain.

    Sorts them into <MetaRig>.GestureSplines and <MetaRig>.PlottingSplines collections.
    Safe to call from update callbacks.
    """
    if arm is None or not chain.part_name:
        return
    arm_name  = arm.name
    part_name = chain.part_name
    scene = getattr(context, 'scene', None)
    if scene is None:
        return

    # Strip ".Gesture" suffix to get the MetaRig base name
    meta_name = arm_name[:-len(".Gesture")] if arm_name.endswith(".Gesture") else arm_name

    arm_coll      = _find_arm_collection(arm, scene)
    gesture_coll  = _ensure_child_collection(f"{meta_name}.GestureSplines",  arm_coll)
    plotting_coll = _ensure_child_collection(f"{meta_name}.PlottingSplines", arm_coll)

    gesture_name = f"{meta_name}-{part_name}.GestureSpline"
    if gesture_name in bpy.data.objects:
        chain.part_gesture_spline = bpy.data.objects[gesture_name]
    elif not chain.part_gesture_spline:
        curve_data = bpy.data.curves.new(gesture_name, 'CURVE')
        curve_data.dimensions = '3D'
        obj = bpy.data.objects.new(gesture_name, curve_data)
        gesture_coll.objects.link(obj)
        chain.part_gesture_spline = obj
    if chain.part_gesture_spline:
        _move_object_to_collection(chain.part_gesture_spline, gesture_coll)

    plotting_name = f"{meta_name}-{part_name}.PlottingSpline"
    if plotting_name in bpy.data.objects:
        chain.part_plotting_spline = bpy.data.objects[plotting_name]
    elif not chain.part_plotting_spline:
        curve_data = bpy.data.curves.new(plotting_name, 'CURVE')
        curve_data.dimensions = '3D'
        obj = bpy.data.objects.new(plotting_name, curve_data)
        plotting_coll.objects.link(obj)
        chain.part_plotting_spline = obj
    if chain.part_plotting_spline:
        _move_object_to_collection(chain.part_plotting_spline, plotting_coll)


def _cleanup_orphan_splines(arm, mod_props, scene):
    """Delete CURVE objects in the spline collections not referenced by any chain.

    Checks both <MetaRig>.GestureSplines and <MetaRig>.PlottingSplines.
    """
    arm_name  = arm.name
    meta_name = arm_name[:-len(".Gesture")] if arm_name.endswith(".Gesture") else arm_name

    active = set()
    for chain in mod_props.chains:
        if chain.part_gesture_spline:
            active.add(chain.part_gesture_spline.name)
        if chain.part_plotting_spline:
            active.add(chain.part_plotting_spline.name)

    for coll_name in (f"{meta_name}.GestureSplines", f"{meta_name}.PlottingSplines"):
        splines_coll = bpy.data.collections.get(coll_name)
        if splines_coll is None:
            continue
        for obj in list(splines_coll.objects):
            if obj.type != 'CURVE':
                continue
            if obj.name not in active:
                print(f"GestureBone: removing orphan spline '{obj.name}'")
                try:
                    bpy.data.objects.remove(obj, do_unlink=True)
                except Exception as e:
                    print(f"GestureBone: could not remove '{obj.name}': {e}")


def _refresh_bone_lists(chain):
    """Resize control bone collection to match the count field."""
    _resize_collection(chain.part_control_bones, chain.part_control_point_count)
