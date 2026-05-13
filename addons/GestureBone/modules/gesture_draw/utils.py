import bpy

_CONSTRAINT_NAME = "GP_copy"
_CONSTRAINT_TYPE = "GEOMETRY_ATTRIBUTE"


# ── Context helpers ────────────────────────────────────────────────────────────

def _arm(context):
    obj = context.active_object
    if obj and obj.type == 'ARMATURE':
        return obj
    fallback = context.scene.gesturebone_props.current_armature
    return fallback if fallback and fallback.type == 'ARMATURE' else None


def _mod_props(context):
    obj = _arm(context)
    return obj.gesturebone_gesture_draw_props if obj else None


def _get_chain(context, index):
    props = _mod_props(context)
    return props.chains[index] if props and 0 <= index < len(props.chains) else None


def _bone_names(chain):
    return [entry.bone for entry in chain.part_control_bones if entry.bone]


# ── Chain setup helpers ────────────────────────────────────────────────────────

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

    Only fires when part_gp is not yet assigned — never overwrites a manual assignment.
    Places the new object in the same collection as the armature.
    """
    if mod_props.part_gp is not None:
        return
    scene = getattr(context, 'scene', None)
    if scene is None:
        return

    gp_name = f"{arm.name}_IntermediateGP"

    # Re-use existing object if it already exists in the file
    if gp_name in bpy.data.objects:
        candidate = bpy.data.objects[gp_name]
        if candidate.type == 'GREASEPENCIL':
            mod_props.part_gp = candidate
            return

    # Create a new GP3 object
    try:
        gp_data = bpy.data.grease_pencils.new(gp_name)
        gp_obj = bpy.data.objects.new(gp_name, gp_data)
        arm_coll = _find_arm_collection(arm, scene)
        arm_coll.objects.link(gp_obj)
        mod_props.part_gp = gp_obj
        print(f"GestureBone: created '{gp_name}' in '{arm_coll.name}'")
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
    gesture_coll = _ensure_child_collection(f"{arm_name}_Gesture_Splines", arm_coll)
    plotting_coll = _ensure_child_collection(f"{arm_name}_Plotting_Splines", arm_coll)

    # Gesture spline
    gesture_name = f"{arm_name}_{part_name}_GestureSpline"
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

    # Plotting spline
    plotting_name = f"{arm_name}_{part_name}_PlottingSpline"
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
    # Forward iteration + 'TOP' (= index 0 = visual bottom in GP3):
    # moving each chain layer to idx 0 in order [0..N] leaves chains[-1] at idx 0
    # and chains[0] at the highest index = visual top. Equivalent to a stable sort.
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
    The blank frame uses the chain's material index so later drawing lands on the right material.
    Safe to call multiple times — all operations are idempotent.
    """
    gp_obj = mod_props.part_gp if mod_props else None
    if not gp_obj:
        return

    # Create animation data block if missing
    if not gp_obj.animation_data:
        gp_obj.animation_data_create()
    anim = gp_obj.animation_data

    # Find or create the action
    action_name = f"{gp_obj.name}_Action"
    action = anim.action
    if action is None:
        if action_name in bpy.data.actions:
            action = bpy.data.actions[action_name]
        else:
            action = bpy.data.actions.new(action_name)
        anim.action = action

    # Blender 4.4+ action slot system
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

    # Ensure each chain layer has at least a blank frame at 0
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


# ── F-curve compatibility ──────────────────────────────────────────────────────

def _get_fcurve_store(arm_obj):
    """Return the F-curve collection for this armature's action.

    Handles both Blender < 4.4 (action.fcurves) and Blender 4.4+ slotted actions
    (action.layers[].strips[].channelbag(slot).fcurves).
    Returns None if no action or access fails.
    """
    anim = arm_obj.animation_data
    if not anim or not anim.action:
        return None
    action = anim.action
    if hasattr(action, 'fcurves'):
        return action.fcurves
    try:
        slot = getattr(anim, 'action_slot', None)
        if slot is None and action.slots:
            slot = action.slots[0]
        if slot is None:
            return None
        for layer in action.layers:
            for strip in layer.strips:
                for method_name in ('channelbag', 'channelbag_for_slot'):
                    cb_fn = getattr(strip, method_name, None)
                    if cb_fn:
                        try:
                            cb = cb_fn(slot)
                            if cb and hasattr(cb, 'fcurves'):
                                return cb.fcurves
                        except Exception:
                            pass
    except Exception:
        pass
    return None


# ── Constraint helpers ─────────────────────────────────────────────────────────

def _mute_constraints(arm_obj, chain):
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if not pb:
            continue
        for c in pb.constraints:
            if c.name == _CONSTRAINT_NAME:
                c.mute = True


def _unmute_constraints(arm_obj, chain):
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if not pb:
            continue
        for c in pb.constraints:
            if c.name == _CONSTRAINT_NAME:
                c.mute = False


def _constraints_exist(arm_obj, chain):
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if pb and any(c.name == _CONSTRAINT_NAME for c in pb.constraints):
            return True
    return False


def _constraints_are_muted(arm_obj, chain):
    """Return True if the GP_copy constraints exist and are currently muted."""
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pb = arm_obj.pose.bones.get(bone_name)
        if pb:
            for c in pb.constraints:
                if c.name == _CONSTRAINT_NAME:
                    return c.mute
    return True


# ── Bake helpers ───────────────────────────────────────────────────────────────

def _apply_and_key_data(arm_obj, chain, frame, depsgraph):
    """Bake visual transform to local space and insert keyframes — no mode switching."""
    arm_eval = arm_obj.evaluated_get(depsgraph)
    for bone_name in _bone_names(chain):
        if not bone_name:
            continue
        pose_bone = arm_obj.pose.bones.get(bone_name)
        pose_bone_eval = arm_eval.pose.bones.get(bone_name)
        if not pose_bone or not pose_bone_eval:
            continue
        pose_bone.matrix_basis = arm_obj.convert_space(
            pose_bone=pose_bone,
            matrix=pose_bone_eval.matrix,
            from_space='POSE',
            to_space='LOCAL',
        )
        pose_bone.keyframe_insert(data_path="location", frame=frame)
        if pose_bone.rotation_mode == 'QUATERNION':
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        elif pose_bone.rotation_mode == 'AXIS_ANGLE':
            pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        else:
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        pose_bone.keyframe_insert(data_path="scale", frame=frame)
    chain.last_baked_frame = max(chain.last_baked_frame, frame)


def _count_strokes_at_frame(chain, gp_obj, frame_num):
    """Count strokes matching part_material at a specific GP frame number."""
    mat = chain.part_material
    if not gp_obj:
        return 0
    count = 0
    try:
        for layer in gp_obj.data.layers:
            for gp_frame in layer.frames:
                if gp_frame.frame_number != frame_num:
                    continue
                strokes = _frame_strokes(gp_frame)
                if strokes is None:
                    continue
                for stroke in strokes:
                    if mat is None or (
                        stroke.material_index < len(gp_obj.material_slots) and
                        gp_obj.material_slots[stroke.material_index].material == mat
                    ):
                        count += 1
    except Exception:
        pass
    return count


# ── GP2 / GP3 stroke compatibility ────────────────────────────────────────────

def _frame_strokes(gp_frame):
    """Return the strokes collection for a GP frame (GP2: frame.strokes, GP3: frame.drawing.strokes)."""
    if hasattr(gp_frame, 'strokes'):
        return gp_frame.strokes
    drawing = getattr(gp_frame, 'drawing', None)
    if drawing is not None:
        return getattr(drawing, 'strokes', None)
    return None


def _remove_matching_strokes(gp_frame, gp_obj, mat):
    """Remove strokes matching mat from a GP frame. Handles GP2 and GP3.

    GP3 (Blender 4.3+): drawing.remove_strokes(indices=[...])
    GP2            : strokes.remove(stroke) iterated in reverse
    """
    drawing = getattr(gp_frame, 'drawing', None)
    if drawing is not None and hasattr(drawing, 'remove_strokes'):
        indices = [
            i for i, s in enumerate(drawing.strokes)
            if mat is None or (
                s.material_index < len(gp_obj.material_slots) and
                gp_obj.material_slots[s.material_index].material == mat
            )
        ]
        if indices:
            drawing.remove_strokes(indices=indices)
        return
    # GP2 path
    strokes = _frame_strokes(gp_frame)
    if strokes is None:
        return
    to_remove = [
        s for s in strokes
        if mat is None or (
            s.material_index < len(gp_obj.material_slots) and
            gp_obj.material_slots[s.material_index].material == mat
        )
    ]
    for stroke in reversed(to_remove):
        strokes.remove(stroke)


def _copy_last_frame_strokes(chain, gp_obj, frame_num):
    """Copy strokes matching part_material from the nearest previous GP frame to frame_num.

    Only copies if the target frame has no matching strokes yet.
    Supports both GP2 (Blender < 4.3, frame.strokes) and GP3 (Blender 4.3+, frame.drawing).
    """
    mat = chain.part_material
    if not gp_obj:
        return

    def _stroke_matches(stroke):
        return (mat is None or (
            stroke.material_index < len(gp_obj.material_slots) and
            gp_obj.material_slots[stroke.material_index].material == mat
        ))

    for layer in gp_obj.data.layers:
        # Skip if the target frame already has matching strokes
        target_frame = next((f for f in layer.frames if f.frame_number == frame_num), None)
        if target_frame is not None:
            existing = _frame_strokes(target_frame)
            if existing and any(_stroke_matches(s) for s in existing):
                continue

        # Find the nearest frame before frame_num that has matching strokes
        src_frame = None
        for f in sorted(layer.frames, key=lambda f: f.frame_number, reverse=True):
            if f.frame_number >= frame_num:
                continue
            strokes = _frame_strokes(f)
            if strokes and any(_stroke_matches(s) for s in strokes):
                src_frame = f
                break

        if src_frame is None:
            continue

        # Create the target frame if it doesn't exist yet
        if target_frame is None:
            try:
                target_frame = layer.frames.new(frame_num)
            except Exception:
                continue

        # ── GP3 path (Blender 4.3+ / 5.x): drawing.add_strokes() ─────────────
        src_drawing = getattr(src_frame, 'drawing', None)
        dst_drawing = getattr(target_frame, 'drawing', None)
        if src_drawing is not None and dst_drawing is not None and hasattr(dst_drawing, 'add_strokes'):
            for src in src_drawing.strokes:
                if not _stroke_matches(src):
                    continue
                try:
                    dst_drawing.add_strokes([len(src.points)])
                    dst = dst_drawing.strokes[-1]
                    for attr in ('material_index', 'cyclic', 'softness',
                                 'start_cap', 'end_cap', 'fill_opacity', 'fill_color', 'hide_stroke'):
                        try:
                            setattr(dst, attr, getattr(src, attr))
                        except Exception:
                            pass
                    for src_pt, dst_pt in zip(src.points, dst.points):
                        for pattr in ('position', 'radius', 'opacity', 'vertex_color', 'rotation'):
                            try:
                                setattr(dst_pt, pattr, getattr(src_pt, pattr))
                            except Exception:
                                pass
                except Exception:
                    pass
            continue  # GP3 handled — skip GP2 path for this layer

        # ── GP2 path (Blender < 4.3): frame.strokes.new() ────────────────────
        if hasattr(target_frame, 'strokes') and hasattr(target_frame.strokes, 'new'):
            src_strokes = _frame_strokes(src_frame)
            if src_strokes is None:
                continue
            for src in src_strokes:
                if not _stroke_matches(src):
                    continue
                try:
                    dst = target_frame.strokes.new()
                    dst.material_index = src.material_index
                    for attr in ('line_width', 'use_cyclic'):
                        try:
                            setattr(dst, attr, getattr(src, attr))
                        except Exception:
                            pass
                    dst.points.add(len(src.points))
                    for i, pt in enumerate(src.points):
                        dst.points[i].co = pt.co
                        for pattr in ('pressure', 'strength'):
                            try:
                                setattr(dst.points[i], pattr, getattr(pt, pattr))
                            except Exception:
                                pass
                except Exception:
                    pass


# ── Geometry Nodes helpers ─────────────────────────────────────────────────────

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
    Relaxed matching: no strict in_out enum comparison.
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
