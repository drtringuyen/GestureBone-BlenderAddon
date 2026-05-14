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


def _ensure_gp_object(arm, mod_props, context):
    """Find or create <Armature>_IntermediateGP and assign it to mod_props.part_gp.

    Never overwrites a manual assignment. Always moves the GP into <Armature>_Splines_GP,
    even if it was already assigned (handles migration from old collection layout).
    """
    scene = getattr(context, 'scene', None)
    if scene is None:
        return

    arm_coll = _find_arm_collection(arm, scene)
    splines_gp_coll = _ensure_child_collection(f"{arm.name}_Splines_GP", arm_coll)

    if mod_props.part_gp is not None:
        _move_object_to_collection(mod_props.part_gp, splines_gp_coll)
        return

    gp_name = f"{arm.name}_IntermediateGP"

    if gp_name in bpy.data.objects:
        candidate = bpy.data.objects[gp_name]
        if candidate.type == 'GREASEPENCIL':
            mod_props.part_gp = candidate
            _move_object_to_collection(candidate, splines_gp_coll)
            return

    try:
        gp_data = bpy.data.grease_pencils.new(gp_name)
        gp_obj = bpy.data.objects.new(gp_name, gp_data)
        splines_gp_coll.objects.link(gp_obj)
        mod_props.part_gp = gp_obj
        print(f"GestureBone: created '{gp_name}' in '{splines_gp_coll.name}'")
    except Exception as e:
        print(f"GestureBone: could not create '{gp_name}': {e}")


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

    Also sorts them into named collections. Safe to call from update callbacks.
    GP layer creation is intentionally excluded — call _ensure_gp_layer() from
    operator execute() only, where GP data modification is allowed.
    """
    if arm is None or not chain.part_name:
        return
    arm_name = arm.name
    part_name = chain.part_name
    scene = getattr(context, 'scene', None)
    if scene is None:
        return

    arm_coll = _find_arm_collection(arm, scene)
    splines_gp_coll = _ensure_child_collection(f"{arm_name}_Splines_GP", arm_coll)

    gesture_name = f"{arm_name}_{part_name}_GestureSpline"
    if gesture_name in bpy.data.objects:
        chain.part_gesture_spline = bpy.data.objects[gesture_name]
    elif not chain.part_gesture_spline:
        curve_data = bpy.data.curves.new(gesture_name, 'CURVE')
        curve_data.dimensions = '3D'
        obj = bpy.data.objects.new(gesture_name, curve_data)
        splines_gp_coll.objects.link(obj)
        chain.part_gesture_spline = obj
    if chain.part_gesture_spline:
        _move_object_to_collection(chain.part_gesture_spline, splines_gp_coll)

    plotting_name = f"{arm_name}_{part_name}_PlottingSpline"
    if plotting_name in bpy.data.objects:
        chain.part_plotting_spline = bpy.data.objects[plotting_name]
    elif not chain.part_plotting_spline:
        curve_data = bpy.data.curves.new(plotting_name, 'CURVE')
        curve_data.dimensions = '3D'
        obj = bpy.data.objects.new(plotting_name, curve_data)
        splines_gp_coll.objects.link(obj)
        chain.part_plotting_spline = obj
    if chain.part_plotting_spline:
        _move_object_to_collection(chain.part_plotting_spline, splines_gp_coll)


def _ensure_gp_layer(arm, chain):
    """Find or create a GP layer named after chain.part_name.

    Must be called from an operator execute(), NOT from a property update callback.
    """
    mod_props = getattr(arm, 'gesturebone_gesture_draw_props', None)
    if not (mod_props and mod_props.part_gp and chain.part_name):
        return
    gp_data = mod_props.part_gp.data
    layer_name = chain.part_name
    if not hasattr(gp_data, 'layers'):
        return
    try:
        existing = [l.name for l in gp_data.layers]
        if layer_name not in existing:
            gp_data.layers.new(layer_name)
        chain.part_layer = layer_name
    except Exception as e:
        print(f"GestureBone: could not create GP layer '{layer_name}': {e}")


def _sort_gp_layers(mod_props, chains):
    """Reorder GP layers so their top-to-bottom order matches the chain list order.

    Algorithm: iterate chains in reverse and move each matching layer to TOP.
    This puts chains[0] at the visual top of the GP layer panel.
    Non-chain layers are left at the bottom, untouched.
    """
    if not mod_props.part_gp:
        return
    gp_data = mod_props.part_gp.data
    if not hasattr(gp_data, 'layers'):
        return
    layer_names = {l.name for l in gp_data.layers}
    for chain in list(chains):
        if chain.part_name and chain.part_name in layer_names:
            layer = next((l for l in gp_data.layers if l.name == chain.part_name), None)
            if layer:
                try:
                    gp_data.layers.move(layer, 'TOP')
                except Exception as e:
                    print(f"GestureBone: could not move layer '{chain.part_name}': {e}")


def _ensure_gp_animation(mod_props, chains):
    """Ensure the GP object has animation data, an action, and an action slot (Blender 4.4+).

    For each chain, inserts a blank frame at frame 0 on the chain's layer if no frame exists.
    Safe to call multiple times — all operations are idempotent.
    """
    gp_obj = mod_props.part_gp if mod_props else None
    if not gp_obj:
        return

    if not gp_obj.animation_data:
        gp_obj.animation_data_create()
    anim = gp_obj.animation_data

    action_name = f"{gp_obj.name}_Action"
    action = anim.action
    if action is None:
        if action_name in bpy.data.actions:
            action = bpy.data.actions[action_name]
        else:
            action = bpy.data.actions.new(action_name)
        anim.action = action

    if hasattr(action, 'slots'):
        slot = getattr(anim, 'action_slot', None)
        if slot is None:
            if action.slots:
                slot = action.slots[0]
            else:
                try:
                    slot = action.slots.new(id_type='GREASEPENCIL', name=gp_obj.name)
                except Exception:
                    try:
                        slot = action.slots.new(name=gp_obj.name)
                    except Exception:
                        pass
            if slot is not None:
                try:
                    anim.action_slot = slot
                except Exception:
                    pass

    gp_data = gp_obj.data
    if not hasattr(gp_data, 'layers'):
        return

    for chain in chains:
        if not chain.part_name:
            continue
        layer = next((l for l in gp_data.layers if l.name == chain.part_name), None)
        if layer is None:
            continue
        has_frame = any(f.frame_number == 0 for f in layer.frames)
        if not has_frame:
            try:
                layer.frames.new(0)
            except Exception as e:
                print(f"GestureBone: could not insert frame 0 on layer '{chain.part_name}': {e}")


def _refresh_bone_lists(chain):
    """Resize control/plotting bone collections to match their count fields."""
    _resize_collection(chain.part_control_bones, chain.part_control_point_count)
    _resize_collection(chain.part_plotting_bones, chain.part_plotting_point_count)
