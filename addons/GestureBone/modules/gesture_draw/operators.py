import bpy
from bpy.props import IntProperty, EnumProperty
from .utils import (
    _CONSTRAINT_NAME, _CONSTRAINT_TYPE,
    _arm, _mod_props, _get_chain, _bone_names,
    _apply_and_key_data,
    _mute_constraints, _unmute_constraints,
    _constraints_exist, _constraints_are_muted,
    _find_gn_modifier, _find_socket_id,
    _ensure_object_collections_visible,
    _mesh_edge_chains,
)


# ── Constraint operators ───────────────────────────────────────────────────────

class GESTUREBONE_OT_CreateBoneConstraints(bpy.types.Operator):
    """Add GP_copy Geometry Attribute constraints to all bones in this chain"""
    bl_idname = "gesturebone.create_bone_constraints"
    bl_label = "Create Bone Constraints"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}
        gp_obj = (mod_props.part_gp if mod_props else None) or context.scene.gesturebone_props.current_gp
        if not gp_obj:
            self.report({'ERROR'}, "GP object not set on this chain")
            return {'CANCELLED'}

        for i, bone_name in enumerate(_bone_names(chain)):
            if not bone_name:
                continue
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if not pose_bone:
                self.report({'WARNING'}, f"Bone not found: {bone_name}")
                continue

            for c in list(pose_bone.constraints):
                if c.type == _CONSTRAINT_TYPE:
                    pose_bone.constraints.remove(c)

            con = pose_bone.constraints.new(type=_CONSTRAINT_TYPE)
            con.name = _CONSTRAINT_NAME
            con.target = gp_obj
            con.apply_target_transform = True
            con.attribute_name = "instance_transform"
            con.data_type = 'FLOAT4X4'
            con.domain = 'INSTANCE'
            # GN processes layers from data[0] (visual bottom) first → chains[0] gets slots 0-4.
            # _sort_gp_layers keeps chains[0] at data[0], so chain_index matches GN processing order.
            con.sample_index = i + self.chain_index * 5
            con.mix_mode = 'REPLACE'
            con.influence = 1.0
            con.mute = True  # start muted; unmuted only during active drawing

        chain.is_bound = True
        return {'FINISHED'}


class GESTUREBONE_OT_DeleteBoneConstraints(bpy.types.Operator):
    """Remove all GP_copy constraints from bones in this chain"""
    bl_idname = "gesturebone.delete_bone_constraints"
    bl_label = "Delete Bone Constraints"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}

        for bone_name in _bone_names(chain):
            if not bone_name:
                continue
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if not pose_bone:
                continue
            for c in list(pose_bone.constraints):
                if c.name == _CONSTRAINT_NAME:
                    pose_bone.constraints.remove(c)

        chain.is_bound = False
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleConstraintActive(bpy.types.Operator):
    """Toggle GP_copy constraints on/off for this chain (creates them if absent)"""
    bl_idname = "gesturebone.toggle_constraint_active"
    bl_label = "Toggle Constraints"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}

        if not _constraints_exist(arm_obj, chain):
            bpy.ops.gesturebone.create_bone_constraints(chain_index=self.chain_index)
            _unmute_constraints(arm_obj, chain)
        elif _constraints_are_muted(arm_obj, chain):
            _unmute_constraints(arm_obj, chain)
        else:
            _mute_constraints(arm_obj, chain)

        return {'FINISHED'}


# ── Shared spline bake helper ─────────────────────────────────────────────────

def _bake_spline_to_gp(op, context, gesture_spline, gp_obj, chain, frame_num):
    """Evaluate gesture_spline with modifiers applied, write strokes into gp_obj.

    Pure data API — no bpy.ops calls.
    """
    if gesture_spline is None:
        op.report({'WARNING'}, "No gesture spline — nothing to bake")
        return
    if gesture_spline.type not in ('CURVE', 'MESH', 'SURFACE'):
        op.report({'WARNING'}, f"Gesture spline type '{gesture_spline.type}' cannot be converted to mesh")
        return
    if gp_obj is None:
        op.report({'WARNING'}, "No GP object — nothing to write strokes into")
        return
    if not hasattr(gp_obj.data, 'layers'):
        op.report({'WARNING'}, "GP object is not GP3 — cannot write strokes")
        return

    target_layer = next((l for l in gp_obj.data.layers if l.name == chain.part_layer), None)
    if target_layer is None:
        op.report({'WARNING'}, f"Layer '{chain.part_layer}' not found in GP object")
        return

    depsgraph = context.evaluated_depsgraph_get()
    mesh = None
    try:
        mesh = bpy.data.meshes.new_from_object(gesture_spline, depsgraph=depsgraph)
    except Exception as e:
        op.report({'WARNING'}, f"Could not evaluate gesture spline as mesh: {e}")
        return

    try:
        if not mesh or not mesh.edges:
            op.report({'WARNING'}, "Gesture spline produced an empty mesh — nothing to bake")
            return
        chains = _mesh_edge_chains(mesh)
    finally:
        if mesh is not None:
            bpy.data.meshes.remove(mesh)

    if not chains:
        op.report({'WARNING'}, "No edge chains found in evaluated mesh — nothing to write")
        return

    # Keep only the last drawn spline — discard any accidental earlier strokes
    chains = chains[-1:]

    target_frame = next((f for f in target_layer.frames if f.frame_number == frame_num), None)
    if target_frame is None:
        try:
            target_frame = target_layer.frames.new(frame_num)
        except Exception as e:
            op.report({'WARNING'}, f"Could not create frame {frame_num}: {e}")
            return

    dst_drawing = getattr(target_frame, 'drawing', None)
    if dst_drawing is None:
        op.report({'WARNING'}, "Target frame has no drawing — GP2 not supported")
        return

    mat_index = 0
    if chain.part_material:
        for i, slot in enumerate(gp_obj.material_slots):
            if slot.material == chain.part_material:
                mat_index = i
                break

    matrix = gesture_spline.matrix_world
    written = 0
    for verts in chains:
        if len(verts) < 2:
            continue
        try:
            dst_drawing.add_strokes([len(verts)])
            stroke = dst_drawing.strokes[-1]
            stroke.material_index = mat_index
            for i, co in enumerate(verts):
                stroke.points[i].position = matrix @ co
            written += 1
        except Exception as e:
            op.report({'WARNING'}, f"Could not add stroke: {e}")

    if written == 0:
        op.report({'WARNING'}, "No strokes written — all chains may be too short")
    else:
        op.report({'INFO'}, f"Baked {written} stroke(s) → '{chain.part_layer}' frame {frame_num}")


# ── Shared enter-edit-mode helper ─────────────────────────────────────────────

def _enter_spline_edit_mode(op, context, mod_props, chain, arm_obj, tool):
    """Deactivate all other chains, then enter curve Edit mode on chain's gesture spline."""
    gesture_spline = chain.part_gesture_spline
    if not gesture_spline:
        op.report({'ERROR'}, "No gesture spline — refresh the chain first")
        return {'CANCELLED'}

    # Deactivate every other drawing chain
    for other in mod_props.chains:
        if other != chain and other.is_drawing:
            other.is_drawing = False
            other.drawing_frame = -1

    if context.active_object:
        chain.prev_active_object = context.active_object.name
        chain.prev_mode = context.active_object.mode

    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Clear existing splines when entering draw mode — fresh canvas
    if tool == 'DRAW' and gesture_spline.data.splines:
        gesture_spline.data.splines.clear()

    _ensure_object_collections_visible(context.view_layer, gesture_spline)
    gesture_spline.hide_set(False)

    bpy.ops.object.select_all(action='DESELECT')
    gesture_spline.select_set(True)
    context.view_layer.objects.active = gesture_spline
    bpy.ops.object.mode_set(mode='EDIT')

    tool_id = "builtin.draw" if tool == 'DRAW' else "builtin.select_box"
    bpy.ops.wm.tool_set_by_id(name=tool_id, space_type='VIEW_3D')

    chain.active_tool = tool
    chain.drawing_frame = context.scene.frame_current
    chain.is_drawing = True
    return {'FINISHED'}


# ── Drawing operators ──────────────────────────────────────────────────────────

class GESTUREBONE_OT_ActivateChain(bpy.types.Operator):
    """Enter curve Edit mode on this chain's gesture spline with the draw tool"""
    bl_idname = "gesturebone.activate_chain"
    bl_label = "Activate Chain"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if mod_props is None or chain is None:
            return {'CANCELLED'}
        arm_obj = _arm(context)
        return _enter_spline_edit_mode(self, context, mod_props, chain, arm_obj, 'DRAW')


class GESTUREBONE_OT_ToggleSplineTool(bpy.types.Operator):
    """Toggle between draw and edit-spline tools; activates the chain if not yet active"""
    bl_idname = "gesturebone.toggle_spline_tool"
    bl_label = "Toggle Spline Tool"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if mod_props is None or chain is None:
            return {'CANCELLED'}
        arm_obj = _arm(context)

        if not chain.is_drawing:
            # Not active — enter draw mode (clears existing splines)
            return _enter_spline_edit_mode(self, context, mod_props, chain, arm_obj, 'DRAW')

        gesture_spline = chain.part_gesture_spline
        in_edit = (gesture_spline
                   and context.active_object == gesture_spline
                   and context.mode == 'EDIT_CURVE')

        if chain.active_tool == 'DRAW':
            # Currently drawing — switch to edit/select tool (no clear)
            if in_edit:
                bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
            chain.active_tool = 'EDIT'
            return {'FINISHED'}
        else:
            # Currently editing — switch back to draw tool (clear and redraw)
            return _enter_spline_edit_mode(self, context, mod_props, chain, arm_obj, 'DRAW')


# ── Apply to bone ──────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ApplyToBone(bpy.types.Operator):
    """Exit spline edit mode, bake curve to GP, then key bone transforms for this chain"""
    bl_idname = "gesturebone.apply_to_bone"
    bl_label = "Apply to Bone"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None or mod_props is None:
            return {'CANCELLED'}
        if not _constraints_exist(arm_obj, chain):
            self.report({'ERROR'}, "No constraints — bind the chain first")
            return {'CANCELLED'}

        gesture_spline = chain.part_gesture_spline
        gp_obj = mod_props.part_gp
        frame_num = chain.drawing_frame if chain.drawing_frame >= 0 else context.scene.frame_current

        # Exit edit mode to finalise curve data
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Bake spline shape to GP layer
        if gesture_spline and gp_obj and chain.part_layer:
            _bake_spline_to_gp(self, context, gesture_spline, gp_obj, chain, frame_num)

        chain.is_drawing = False
        chain.drawing_frame = -1

        # Return to armature in Pose mode
        if arm_obj:
            bpy.ops.object.select_all(action='DESELECT')
            arm_obj.select_set(True)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='POSE')

        # Unmute constraints → evaluate → key bones → mute
        _unmute_constraints(arm_obj, chain)
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        _apply_and_key_data(arm_obj, chain, frame_num, depsgraph)
        _mute_constraints(arm_obj, chain)

        self.report({'INFO'}, f"Applied chain '{chain.part_name}' → frame {frame_num}")
        return {'FINISHED'}


# ── Load from bone ─────────────────────────────────────────────────────────────

class GESTUREBONE_OT_LoadFromBone(bpy.types.Operator):
    """Copy the evaluated plotting spline shape into the gesture spline and enter edit mode"""
    bl_idname = "gesturebone.load_from_bone"
    bl_label = "Load from Bone"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if chain is None or mod_props is None:
            return {'CANCELLED'}

        plotting_spline = chain.part_plotting_spline
        gesture_spline = chain.part_gesture_spline
        if not plotting_spline:
            self.report({'ERROR'}, "No plotting spline — refresh the chain first")
            return {'CANCELLED'}
        if not gesture_spline:
            self.report({'ERROR'}, "No gesture spline — refresh the chain first")
            return {'CANCELLED'}

        # Ensure object mode
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Find the GN modifier on the plotting spline
        plotting_mod = next((m for m in plotting_spline.modifiers if m.type == 'NODES'), None)
        if plotting_mod is None:
            self.report({'ERROR'}, "No Geometry Nodes modifier on plotting spline")
            return {'CANCELLED'}

        convert_socket_id = _find_socket_id(plotting_mod, "convert")
        if convert_socket_id is None:
            self.report({'ERROR'}, "No 'convert' socket found on plotting spline modifier")
            return {'CANCELLED'}

        # 1. Enable the convert toggle and force a full depsgraph evaluation
        plotting_mod[convert_socket_id] = True
        plotting_spline.update_tag()
        context.view_layer.update()

        # 2. Read the evaluated curve data directly — evaluated_get() gives us the GN output
        #    on the original Curve object, which preserves spline type and bezier handles.
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = plotting_spline.evaluated_get(depsgraph)

        # 3. Copy splines with full bezier handle data into the gesture spline
        gesture_spline.data.splines.clear()
        for src in eval_obj.data.splines:
            dst = gesture_spline.data.splines.new(type=src.type)
            if src.type == 'BEZIER':
                dst.bezier_points.add(len(src.bezier_points) - 1)
                for sp, dp in zip(src.bezier_points, dst.bezier_points):
                    dp.co = sp.co
                    dp.handle_left = sp.handle_left
                    dp.handle_right = sp.handle_right
                    dp.handle_left_type = sp.handle_left_type
                    dp.handle_right_type = sp.handle_right_type
                    dp.radius = sp.radius
                    dp.tilt = sp.tilt
            else:
                dst.points.add(len(src.points) - 1)
                for sp, dp in zip(src.points, dst.points):
                    dp.co = sp.co
                    dp.radius = sp.radius
                    dp.tilt = sp.tilt
                    dp.weight = sp.weight
            dst.use_cyclic_u = src.use_cyclic_u
            dst.resolution_u = src.resolution_u
            if src.type == 'NURBS':
                dst.order_u = src.order_u
                dst.use_endpoint_u = src.use_endpoint_u

        # 4. Turn the convert toggle back off
        plotting_mod[convert_socket_id] = False
        plotting_spline.update_tag()

        # 8. Re-enter edit mode on the gesture spline so the loaded shape is immediately editable
        return _enter_spline_edit_mode(self, context, mod_props, chain, arm_obj, 'EDIT')


# ── Visibility ────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ToggleGPVisibility(bpy.types.Operator):
    """Toggle the Invisible socket on this chain's GP geometry node modifier"""
    bl_idname = "gesturebone.toggle_gp_visibility"
    bl_label = "Toggle GP Visibility"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if not chain or not (mod_props and mod_props.part_gp):
            return {'CANCELLED'}
        gp_obj = mod_props.part_gp
        mod = _find_gn_modifier(gp_obj)
        if not mod:
            mod = gp_obj.modifiers.new(name="TOB-Gesture_drawing", type='NODES')
            self.report({'WARNING'}, "Added empty GeoNode modifier — assign the TOB-Gesture_drawing node group")
            return {'FINISHED'}
        socket_id = _find_socket_id(mod, "Invisible")
        if socket_id is None:
            self.report({'WARNING'}, f"Socket 'Invisible' not found in modifier '{mod.name}'")
            return {'CANCELLED'}
        mod[socket_id] = not mod[socket_id]
        gp_obj.update_tag()
        return {'FINISHED'}


class GESTUREBONE_OT_DebugConstraintState(bpy.types.Operator):
    """Print chain order, GP layer data order, and constraint sample_indices to the console"""
    bl_idname = "gesturebone.debug_constraint_state"
    bl_label = "Debug Constraint State"

    def execute(self, context):
        from .utils import _arm, _mod_props
        arm_obj = _arm(context)
        mod_props = _mod_props(context)
        if arm_obj is None or mod_props is None:
            self.report({'ERROR'}, "No armature")
            return {'CANCELLED'}

        gp_obj = mod_props.part_gp
        print("\n══════════ GestureBone Debug ══════════")
        print(f"Armature: {arm_obj.name}")

        if gp_obj:
            print(f"\nGP object: {gp_obj.name}")
            print("  GP layers (data order, [0] = first processed by GN modifier):")
            for i, l in enumerate(gp_obj.data.layers):
                active_tag = " ← ACTIVE" if l == gp_obj.data.layers.active else ""
                print(f"    data[{i}]  '{l.name}'{active_tag}")
        else:
            print("  No GP object assigned")

        print(f"\nChains (mod_props.chains order):")
        for ci, chain in enumerate(mod_props.chains):
            layer_data_idx = None
            if gp_obj:
                layer_data_idx = next(
                    (idx for idx, l in enumerate(gp_obj.data.layers) if l.name == chain.part_layer),
                    None,
                )
            expected_base = layer_data_idx * 5 if layer_data_idx is not None else f"?? (layer '{chain.part_layer}' not found)"
            print(f"  chains[{ci}]  name='{chain.part_name}'  layer='{chain.part_layer}'  "
                  f"layer_data_idx={layer_data_idx}  expected sample_index base={expected_base}")

            for entry in chain.part_control_bones:
                if not entry.bone:
                    continue
                pb = arm_obj.pose.bones.get(entry.bone)
                if pb:
                    for c in pb.constraints:
                        if c.name == 'GP_copy':
                            match = "✓" if layer_data_idx is not None and c.sample_index in range(layer_data_idx * 5, layer_data_idx * 5 + 5) else "✗ WRONG"
                            print(f"    bone '{entry.bone}'  sample_index={c.sample_index}  muted={c.mute}  {match}")
        print("═══════════════════════════════════════\n")
        self.report({'INFO'}, "Debug printed to console (Window → Toggle System Console)")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(GESTUREBONE_OT_CreateBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleConstraintActive)
    bpy.utils.register_class(GESTUREBONE_OT_ActivateChain)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleSplineTool)
    bpy.utils.register_class(GESTUREBONE_OT_ApplyToBone)
    bpy.utils.register_class(GESTUREBONE_OT_LoadFromBone)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleGPVisibility)
    bpy.utils.register_class(GESTUREBONE_OT_DebugConstraintState)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_DebugConstraintState)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleGPVisibility)
    bpy.utils.unregister_class(GESTUREBONE_OT_LoadFromBone)
    bpy.utils.unregister_class(GESTUREBONE_OT_ApplyToBone)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleSplineTool)
    bpy.utils.unregister_class(GESTUREBONE_OT_ActivateChain)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleConstraintActive)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.unregister_class(GESTUREBONE_OT_CreateBoneConstraints)
