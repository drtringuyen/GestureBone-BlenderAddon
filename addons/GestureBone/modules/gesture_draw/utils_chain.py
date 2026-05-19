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
    """Rename the chain's existing GP layer to match part_name, or create it if absent.

    Must be called from an operator execute(), NOT from a property update callback.
    """
    mod_props = getattr(arm, 'gesturebone_gesture_draw_props', None)
    if not (mod_props and mod_props.part_gp and chain.part_name):
        return
    gp_data = mod_props.part_gp.data
    new_name = chain.part_name
    if not hasattr(gp_data, 'layers'):
        return
    try:
        # If the chain already points to a layer, rename it rather than orphaning it
        old_layer = next((l for l in gp_data.layers if l.name == chain.part_layer), None) if chain.part_layer else None
        if old_layer is not None:
            old_layer.name = new_name
            chain.part_layer = new_name
        elif next((l for l in gp_data.layers if l.name == new_name), None) is None:
            gp_data.layers.new(new_name)
            chain.part_layer = new_name
        else:
            chain.part_layer = new_name
    except Exception as e:
        print(f"GestureBone: could not ensure GP layer '{new_name}': {e}")


def _sort_gp_layers(mod_props, chains):
    """Reorder GP layers to match chain list order visually.

    In Blender 5.x GP3: data[0] = visual bottom, data[N-1] = visual top.
    GN processes layers from data[0] first (slots 0-4), then data[1] (slots 5-9), etc.
    So chains[0] must land at data[0], chains[1] at data[1], to match sample_index = i + chain_idx*5.
    Uses insertion sort with 'DOWN' (decrease index) / 'UP' (increase index).
    Only touches layers that belong to a chain; orphan layers are left untouched.
    """
    if not mod_props.part_gp:
        return
    gp_data = mod_props.part_gp.data
    if not hasattr(gp_data, 'layers'):
        return

    for chain_idx, chain in enumerate(chains):
        if not chain.part_name:
            continue
        # chains[0] → data[0] (GN processes first → slots 0-4), chains[1] → data[1], …
        target_idx = chain_idx
        current_idx = next((i for i, l in enumerate(gp_data.layers) if l.name == chain.part_name), None)
        if current_idx is None:
            continue
        try:
            while current_idx > target_idx:
                gp_data.layers.move(gp_data.layers[current_idx], 'DOWN')
                current_idx -= 1
            while current_idx < target_idx:
                gp_data.layers.move(gp_data.layers[current_idx], 'UP')
                current_idx += 1
        except Exception as e:
            print(f"GestureBone: could not sort layer '{chain.part_name}': {e}")


def _sync_gp_layers(arm, mod_props):
    """Full one-shot sync: remove orphan layers, ensure each chain has a layer, reorder.

    Safe to call from RefreshAllChains and after any structural change (add/remove/move chain).
    """
    if not mod_props.part_gp:
        return
    gp_data = mod_props.part_gp.data
    if not hasattr(gp_data, 'layers'):
        return

    chain_names = {c.part_name for c in mod_props.chains if c.part_name}

    # Remove layers that no longer have a matching chain
    for layer in list(gp_data.layers):
        if layer.name not in chain_names:
            try:
                gp_data.layers.remove(layer)
            except Exception as e:
                print(f"GestureBone: could not remove orphan layer '{layer.name}': {e}")

    # Ensure every chain has a correctly named layer
    for chain in mod_props.chains:
        _ensure_gp_layer(arm, chain)

    # Reorder layers to match chain list order
    _sort_gp_layers(mod_props, mod_props.chains)


def _cleanup_orphan_splines(arm, mod_props, scene):
    """Delete CURVE objects in the <arm>_Splines_GP collection not referenced by any chain.

    Only removes objects of type CURVE that live inside the managed collection and are
    not assigned as part_gesture_spline or part_plotting_spline on any current chain.
    The GP object and any non-curve objects are never touched.
    """
    coll_name = f"{arm.name}_Splines_GP"
    splines_coll = bpy.data.collections.get(coll_name)
    if splines_coll is None:
        return

    # Build the set of curve objects still in use
    active = set()
    for chain in mod_props.chains:
        if chain.part_gesture_spline:
            active.add(chain.part_gesture_spline.name)
        if chain.part_plotting_spline:
            active.add(chain.part_plotting_spline.name)

    for obj in list(splines_coll.objects):
        if obj.type != 'CURVE':
            continue
        if obj.name not in active:
            print(f"GestureBone: removing orphan spline '{obj.name}'")
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception as e:
                print(f"GestureBone: could not remove '{obj.name}': {e}")


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
