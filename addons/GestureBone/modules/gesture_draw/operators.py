import bpy
from bpy.props import IntProperty
from .curve_bone_chain import SPLINE_GEONODE_DEFAULTS
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
from ... import assets


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
            # GN modifier processes layers from visual top → chains[0] gets slots 0-4.
            # _sort_gp_layers keeps chains[0] at data[-1] (visual top), so chain_index
            # matches the GN processing order.
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


# ── Drawing operators ──────────────────────────────────────────────────────────

class GESTUREBONE_OT_ToggleDrawing(bpy.types.Operator):
    """Toggle: enter Edit mode on gesture spline (ON) / convert to GP + copy strokes back (OFF)"""
    bl_idname = "gesturebone.toggle_drawing"
    bl_label = "Toggle Drawing"
    chain_index: IntProperty()

    def execute(self, context):
        mod_props = _mod_props(context)
        chain = _get_chain(context, self.chain_index)
        if mod_props is None or chain is None:
            return {'CANCELLED'}
        arm_obj = _arm(context)

        if chain.is_drawing:
            return self._toggle_off(context, mod_props, chain, arm_obj)
        else:
            return self._toggle_on(context, mod_props, chain, arm_obj)

    # ── Toggle ON ──────────────────────────────────────────────────────────────

    def _toggle_on(self, context, mod_props, chain, arm_obj):
        gesture_spline = chain.part_gesture_spline
        if not gesture_spline:
            self.report({'ERROR'}, "No gesture spline set — refresh the chain first")
            return {'CANCELLED'}
        gp_obj = mod_props.part_gp

        # Turn off any other chain that is currently drawing
        for j, other in enumerate(mod_props.chains):
            if j != self.chain_index and other.is_drawing:
                other.is_drawing = False
                other.drawing_frame = -1

        # Save current state for restoration
        if context.active_object:
            chain.prev_active_object = context.active_object.name
            chain.prev_mode = context.active_object.mode

        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Ensure the gesture spline's collection is visible in the view layer
        _ensure_object_collections_visible(context.view_layer, gesture_spline)
        gesture_spline.hide_set(False)

        # Select and enter Edit mode on the gesture spline
        bpy.ops.object.select_all(action='DESELECT')
        gesture_spline.select_set(True)
        context.view_layer.objects.active = gesture_spline
        bpy.ops.object.mode_set(mode='EDIT')

        # Switch to freehand draw tool
        bpy.ops.wm.tool_set_by_id(name="builtin.draw", space_type='VIEW_3D')

        # Set the active GP layer to the one registered in this chain
        if gp_obj and chain.part_layer:
            layer = next((l for l in gp_obj.data.layers if l.name == chain.part_layer), None)
            if layer:
                gp_obj.data.layers.active = layer

        chain.drawing_frame = context.scene.frame_current
        chain.is_drawing = True
        return {'FINISHED'}

    # ── Toggle OFF ─────────────────────────────────────────────────────────────

    def _toggle_off(self, context, mod_props, chain, arm_obj):
        gesture_spline = chain.part_gesture_spline
        gp_obj = mod_props.part_gp
        frame_num = chain.drawing_frame if chain.drawing_frame >= 0 else context.scene.frame_current

        # Exit edit mode so curve data is finalised
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if gesture_spline and gp_obj and chain.part_layer:
            self._bake_spline_to_gp(context, gesture_spline, gp_obj, chain, frame_num)

        chain.is_drawing = False
        chain.drawing_frame = -1

        # Return to armature in Pose mode
        if arm_obj:
            bpy.ops.object.select_all(action='DESELECT')
            arm_obj.select_set(True)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='POSE')

        return {'FINISHED'}

    def _bake_spline_to_gp(self, context, gesture_spline, gp_obj, chain, frame_num):
        """Evaluate gesture_spline with all modifiers applied, write strokes into gp_obj.

        Pure data API — no bpy.ops calls, no undo stack entries beyond the parent operator.
        Uses new_from_object() for a single depsgraph evaluation pass (replaces the old
        duplicate → convert-to-mesh → modifier_apply × N chain).
        """
        # ── Guards ────────────────────────────────────────────────────────────
        if gesture_spline is None:
            self.report({'WARNING'}, "No gesture spline — nothing to bake")
            return
        if gesture_spline.type not in ('CURVE', 'MESH', 'SURFACE'):
            self.report({'WARNING'}, f"Gesture spline type '{gesture_spline.type}' cannot be converted to mesh")
            return
        if gp_obj is None:
            self.report({'WARNING'}, "No GP object — nothing to write strokes into")
            return
        if not hasattr(gp_obj.data, 'layers'):
            self.report({'WARNING'}, "GP object is not GP3 — cannot write strokes")
            return

        target_layer = next((l for l in gp_obj.data.layers if l.name == chain.part_layer), None)
        if target_layer is None:
            self.report({'WARNING'}, f"Layer '{chain.part_layer}' not found in GP object")
            return

        # ── Evaluate mesh with modifiers applied — data API, no undo push ────
        depsgraph = context.evaluated_depsgraph_get()
        mesh = None
        try:
            mesh = bpy.data.meshes.new_from_object(gesture_spline, depsgraph=depsgraph)
        except Exception as e:
            self.report({'WARNING'}, f"Could not evaluate gesture spline as mesh: {e}")
            return

        try:
            if not mesh or not mesh.edges:
                self.report({'WARNING'}, "Gesture spline produced an empty mesh — nothing to bake")
                return

            # ── Extract stroke geometry from mesh edge chains ─────────────────
            chains = _mesh_edge_chains(mesh)
        finally:
            if mesh is not None:
                bpy.data.meshes.remove(mesh)

        if not chains:
            self.report({'WARNING'}, "No edge chains found in evaluated mesh — nothing to write")
            return

        # ── Target frame (create if absent) — data API ────────────────────────
        target_frame = next((f for f in target_layer.frames if f.frame_number == frame_num), None)
        if target_frame is None:
            try:
                target_frame = target_layer.frames.new(frame_num)
            except Exception as e:
                self.report({'WARNING'}, f"Could not create frame {frame_num}: {e}")
                return

        dst_drawing = getattr(target_frame, 'drawing', None)
        if dst_drawing is None:
            self.report({'WARNING'}, "Target frame has no drawing — GP2 not supported")
            return

        # ── Resolve material index ─────────────────────────────────────────────
        mat_index = 0
        if chain.part_material:
            for i, slot in enumerate(gp_obj.material_slots):
                if slot.material == chain.part_material:
                    mat_index = i
                    break

        # ── Write strokes — data API ──────────────────────────────────────────
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
                self.report({'WARNING'}, f"Could not add stroke: {e}")

        if written == 0:
            self.report({'WARNING'}, "No strokes written — all chains may be too short")
        else:
            self.report({'INFO'}, f"Baked {written} stroke(s) → '{chain.part_layer}' frame {frame_num}")


# ── Apply to bone ──────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ApplyToBone(bpy.types.Operator):
    """Unmute constraints, bake current frame pose to keyframes, then mute constraints"""
    bl_idname = "gesturebone.apply_to_bone"
    bl_label = "Apply to Bone"
    chain_index: IntProperty()

    def execute(self, context):
        arm_obj = _arm(context)
        chain = _get_chain(context, self.chain_index)
        if arm_obj is None or chain is None:
            return {'CANCELLED'}
        if not _constraints_exist(arm_obj, chain):
            self.report({'ERROR'}, "No constraints — bind the chain first")
            return {'CANCELLED'}

        frame_num = context.scene.frame_current
        _unmute_constraints(arm_obj, chain)
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        _apply_and_key_data(arm_obj, chain, frame_num, depsgraph)
        _mute_constraints(arm_obj, chain)
        self.report({'INFO'}, f"Baked chain '{chain.part_name}' → frame {frame_num}")
        return {'FINISHED'}


# ── Load from bone ─────────────────────────────────────────────────────────────

class GESTUREBONE_OT_LoadFromBone(bpy.types.Operator):
    """Select the gesture spline and ensure the Snap_to_bones GN modifier is applied"""
    bl_idname = "gesturebone.load_from_bone"
    bl_label = "Load from Bone"
    chain_index: IntProperty()

    def execute(self, context):
        chain = _get_chain(context, self.chain_index)
        if chain is None:
            return {'CANCELLED'}
        gesture_spline = chain.part_gesture_spline
        if not gesture_spline:
            self.report({'ERROR'}, "No gesture spline set — refresh the chain first")
            return {'CANCELLED'}

        # Ensure object mode before switching active
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        _ensure_object_collections_visible(context.view_layer, gesture_spline)
        gesture_spline.hide_set(False)

        bpy.ops.object.select_all(action='DESELECT')
        gesture_spline.select_set(True)
        context.view_layer.objects.active = gesture_spline

        # Add Snap_to_bones GN modifier if not already present
        node_name = SPLINE_GEONODE_DEFAULTS['gesture']
        ng = assets.ensure_node_group(node_name)
        if ng is None:
            self.report({'WARNING'}, f"Node group '{node_name}' not found in essentials.blend")
            return {'FINISHED'}

        existing = next(
            (m for m in gesture_spline.modifiers if m.type == 'NODES' and m.node_group == ng),
            None,
        )
        if existing is None:
            mod = gesture_spline.modifiers.new(name=node_name, type='NODES')
            mod.node_group = ng

        return {'FINISHED'}


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
    bpy.utils.register_class(GESTUREBONE_OT_ToggleDrawing)
    bpy.utils.register_class(GESTUREBONE_OT_ApplyToBone)
    bpy.utils.register_class(GESTUREBONE_OT_LoadFromBone)
    bpy.utils.register_class(GESTUREBONE_OT_ToggleGPVisibility)
    bpy.utils.register_class(GESTUREBONE_OT_DebugConstraintState)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_OT_DebugConstraintState)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleGPVisibility)
    bpy.utils.unregister_class(GESTUREBONE_OT_LoadFromBone)
    bpy.utils.unregister_class(GESTUREBONE_OT_ApplyToBone)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleDrawing)
    bpy.utils.unregister_class(GESTUREBONE_OT_ToggleConstraintActive)
    bpy.utils.unregister_class(GESTUREBONE_OT_DeleteBoneConstraints)
    bpy.utils.unregister_class(GESTUREBONE_OT_CreateBoneConstraints)
