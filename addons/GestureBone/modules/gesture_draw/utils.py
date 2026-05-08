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
    return [chain.bone_0, chain.bone_1, chain.bone_2, chain.bone_3, chain.bone_4]


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


def _count_strokes_at_frame(chain, frame_num):
    """Count strokes matching part_material at a specific GP frame number."""
    gp_obj = chain.part_gp
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


def _copy_last_frame_strokes(chain, frame_num):
    """Copy strokes matching part_material from the nearest previous GP frame to frame_num.

    Only copies if the target frame has no matching strokes yet.
    Supports both GP2 (Blender < 4.3, frame.strokes) and GP3 (Blender 4.3+, frame.drawing).
    """
    gp_obj = chain.part_gp
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
