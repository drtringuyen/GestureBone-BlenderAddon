"""
ops_actions.py — Compound actions: Rig Part, Auto Rig, and utility buttons.
"""
import bpy
import bmesh
import os
from bpy.props import StringProperty
from .utils import _p, _meta_rig, _bones_in_bone_coll, _ensure_object_mode, _delete_coll, _all_bone_colls
from .scene_props import CONTROL_MODE_GN_INT, _get_bone_settings, _collection_search


_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Steps run by RigPart (Step 5 is interactive — skipped)
_STEP_SEQUENCE = [
    ("gesturebone.duplicate_atomic_chain",       1),
    ("gesturebone.rebind_constraints_geonodes",  2),
    ("gesturebone.scale_empty_to_rest_pose",     3),
    ("gesturebone.add_align_constraints",        4),
    # Step 5 skipped (interactive pose editing)
    ("gesturebone.accept_and_bind",              6),
    ("gesturebone.refresh_rigs",                 7),
    ("gesturebone.rebind_final_armatures",       8),
    ("gesturebone.finish_merging",               9),
    ("gesturebone.merge_rig_into_metarig",       10),
    ("gesturebone.rebind_armature_deform",       11),
]


def _activate_in_pose_mode(context, arm_obj):
    """Make arm_obj the active object and enter Pose Mode (safe no-op if arm_obj is None)."""
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return
    arm_obj.hide_set(False)
    arm_obj.hide_viewport = False
    _ensure_object_mode(context)
    bpy.ops.object.select_all(action='DESELECT')
    arm_obj.select_set(True)
    context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')


def _invoke_op(idname):
    ns, name = idname.split('.', 1)
    return getattr(getattr(bpy.ops, ns), name)()


# ── Control MODE helpers ───────────────────────────────────────────────────────

def _apply_control_mode_to_plotting(plotting_obj, gn_int_value):
    """Set the 'Control MODE' GN socket on the PlottingSpline object."""
    if not plotting_obj:
        return False
    for mod in plotting_obj.modifiers:
        if mod.type != 'NODES' or not mod.node_group:
            continue
        try:
            items = mod.node_group.interface.items_tree
        except AttributeError:
            continue
        for item in items:
            if not hasattr(item, 'identifier'):
                continue
            if 'OUTPUT' in str(getattr(item, 'in_out', 'INPUT')):
                continue
            if item.name == 'Control MODE':
                try:
                    mod[item.identifier] = gn_int_value
                    return True
                except Exception:
                    pass
    return False


def _collect_bone_descendants(arm_data, root_name):
    """Return root bone name and all descendant names (object-mode safe)."""
    result = []
    queue  = [root_name]
    while queue:
        bname = queue.pop()
        bone  = arm_data.bones.get(bname)
        if bone:
            result.append(bname)
            for child in bone.children:
                queue.append(child.name)
    return result


def _delete_extra_ctrl_bones(context, gesture_obj, bone_name):
    """Delete CTRL-{bone_name}_1 and CTRL-{bone_name}_2 and all their children."""
    if not gesture_obj or gesture_obj.type != 'ARMATURE':
        return
    roots = [f"CTRL-{bone_name}_1", f"CTRL-{bone_name}_3"]
    to_delete = set()
    for root in roots:
        to_delete.update(_collect_bone_descendants(gesture_obj.data, root))
    if not to_delete:
        return
    _ensure_object_mode(context)
    bpy.ops.object.select_all(action='DESELECT')
    gesture_obj.hide_set(False)
    gesture_obj.select_set(True)
    context.view_layer.objects.active = gesture_obj
    bpy.ops.object.mode_set(mode='EDIT')
    for bname in to_delete:
        eb = gesture_obj.data.edit_bones.get(bname)
        if eb:
            gesture_obj.data.edit_bones.remove(eb)
    bpy.ops.object.mode_set(mode='OBJECT')


def _apply_control_mode(context, props, bone_name):
    """Apply the Control MODE for bone_name: set GN socket + delete extra ctrl bones."""
    settings     = _get_bone_settings(props, bone_name)
    mode         = settings.control_mode
    gn_int       = CONTROL_MODE_GN_INT.get(mode, 0)
    meta_rig_name = props.meta_rig

    plotting_name = f"{meta_rig_name}-{bone_name}.PlottingSpline"
    plotting_obj  = bpy.data.objects.get(plotting_name)
    _apply_control_mode_to_plotting(plotting_obj, gn_int)

    if mode in ('PT_2', 'PT_3'):
        gesture_name = f"{meta_rig_name}-{bone_name}.Gesture"
        gesture_obj  = bpy.data.objects.get(gesture_name)
        _delete_extra_ctrl_bones(context, gesture_obj, bone_name)


# ─── INIT BONE CONTROL MODE ───────────────────────────────────────────────────

class GESTUREBONE_OT_InitBoneControlMode(bpy.types.Operator):
    bl_idname      = "gesturebone.init_bone_control_mode"
    bl_label       = "Set Control Mode"
    bl_description = "Initialize Control Mode settings for the active MetaBone (default: 5 Points)"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}
        _get_bone_settings(props, bone_name)   # creates entry with default PT_5
        return {'FINISHED'}


# ─── RIG PART ─────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RigPart(bpy.types.Operator):
    bl_idname      = "gesturebone.rig_part"
    bl_label       = "Rig Part"
    bl_description = (
        "Run Steps 1-4, 6-11 automatically for the selected MetaBone "
        "(skips interactive Step 5 — alignment uses rest-pose position)"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        for idname, step_num in _STEP_SEQUENCE:
            try:
                result = _invoke_op(idname)
            except RuntimeError as e:
                self.report({'ERROR'}, f"Step {step_num} failed — {e}")
                return {'CANCELLED'}
            if 'CANCELLED' in result:
                self.report({'ERROR'}, f"Step {step_num} cancelled — '{idname}'")
                return {'CANCELLED'}

            # After Step 1 (duplicate & rename), apply Control MODE before continuing
            if step_num == 1:
                try:
                    _apply_control_mode(context, props, bone_name)
                except Exception as e:
                    self.report({'WARNING'}, f"Control MODE apply failed: {e}")

        self.report({'INFO'}, f"Rig Part complete for '{bone_name}'")
        return {'FINISHED'}


# ─── AUTO RIG ─────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_AutoRig(bpy.types.Operator):
    bl_idname      = "gesturebone.auto_rig"
    bl_label       = "Auto Rig"
    bl_description = "Automatically run Rig Part for every bone in the Meta Collection"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props   = _p(context)
        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        if not props.meta_collection:
            self.report({'ERROR'}, "Meta Collection not set")
            return {'CANCELLED'}

        bone_names = _bones_in_bone_coll(arm_obj.data, props.meta_collection)
        if not bone_names:
            self.report({'ERROR'}, f"No bones found in '{props.meta_collection}'")
            return {'CANCELLED'}

        # Clear any previous rig data before regenerating
        bpy.ops.gesturebone.clear_rig()

        total = len(bone_names)
        done  = 0
        for bone_name in bone_names:
            props.active_meta_bone = bone_name
            result = bpy.ops.gesturebone.rig_part()
            if 'CANCELLED' in result:
                self.report({'WARNING'}, f"Rig Part cancelled on '{bone_name}' — stopping ({done}/{total} done)")
                return {'CANCELLED'}
            done += 1

        self.report({'INFO'}, f"Auto Rig complete — {done}/{total} bones processed")

        # Switch to the Gesture armature in Pose Mode so it's ready to use
        gesture_arm_name = f"{props.meta_rig}.Gesture"
        gesture_arm = bpy.data.objects.get(gesture_arm_name)
        if gesture_arm and gesture_arm.type == 'ARMATURE':
            _ensure_object_mode(context)
            bpy.ops.object.select_all(action='DESELECT')
            gesture_arm.hide_set(False)
            gesture_arm.hide_viewport = False
            gesture_arm.select_set(True)
            context.view_layer.objects.active = gesture_arm
            bpy.ops.object.mode_set(mode='POSE')

        return {'FINISHED'}


# ─── CLEAR RIG ────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ClearRig(bpy.types.Operator):
    bl_idname      = "gesturebone.clear_rig"
    bl_label       = "Clear Rig"
    bl_description = (
        "Remove all generated rig data: Gesture armature, spline collections, "
        "and non-META bone collections (and their bones) from the MetaRig"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props         = _p(context)
        meta_rig_name = props.meta_rig
        removed       = []

        # 1. Delete legacy "Splines" collection (old hardcoded name)
        legacy = bpy.data.collections.get("Splines")
        if legacy:
            _delete_coll(legacy)
            removed.append("Splines")

        # 2. Delete legacy <MetaRig>.Gesture_Splines collection (old wrong naming)
        gs_name = f"{meta_rig_name}.Gesture_Splines"
        gs_coll = bpy.data.collections.get(gs_name)
        if gs_coll:
            _delete_coll(gs_coll)
            removed.append(gs_name)

        # 3. Delete <MetaRig>.GestureSplines collection
        gest_name = f"{meta_rig_name}.GestureSplines"
        gest_coll = bpy.data.collections.get(gest_name)
        if gest_coll:
            _delete_coll(gest_coll)
            removed.append(gest_name)

        # 4. Delete <MetaRig>.PlottingSplines collection
        plot_name = f"{meta_rig_name}.PlottingSplines"
        plot_coll = bpy.data.collections.get(plot_name)
        if plot_coll:
            _delete_coll(plot_coll)
            removed.append(plot_name)

        # 3. Delete SampleMesh collection
        sample = bpy.data.collections.get("SampleMesh")
        if sample:
            _delete_coll(sample)
            removed.append("SampleMesh")

        # 4. Delete <MetaRig>.Gesture armature object
        gesture_arm = bpy.data.objects.get(f"{meta_rig_name}.Gesture")
        if gesture_arm:
            bpy.data.objects.remove(gesture_arm, do_unlink=True)
            removed.append(f"{meta_rig_name}.Gesture")

        # 5. Delete non-META bone collections AND their generated bones from MetaRig
        arm_obj = _meta_rig(props)
        if arm_obj and arm_obj.type == 'ARMATURE':
            meta_coll_name = props.meta_collection
            meta_bones     = set(_bones_in_bone_coll(arm_obj.data, meta_coll_name))

            # Collect bones that live in non-META collections (but not in META)
            to_delete_bones = set()
            for bc in _all_bone_colls(arm_obj.data):
                if bc.name == meta_coll_name:
                    continue
                try:
                    for b in bc.bones:
                        if b.name not in meta_bones:
                            to_delete_bones.add(b.name)
                except AttributeError:
                    for b in arm_obj.data.bones:
                        if any(c.name == bc.name for c in getattr(b, 'collections', [])):
                            if b.name not in meta_bones:
                                to_delete_bones.add(b.name)

            if to_delete_bones:
                _ensure_object_mode(context)
                bpy.ops.object.select_all(action='DESELECT')
                arm_obj.hide_set(False)
                arm_obj.hide_viewport = False
                arm_obj.select_set(True)
                context.view_layer.objects.active = arm_obj
                bpy.ops.object.mode_set(mode='EDIT')
                for bname in list(to_delete_bones):
                    eb = arm_obj.data.edit_bones.get(bname)
                    if eb:
                        arm_obj.data.edit_bones.remove(eb)
                bpy.ops.object.mode_set(mode='OBJECT')
                removed.append(f"{len(to_delete_bones)} generated bone(s)")

            # Remove non-META bone collections (top-level; children cascade automatically)
            to_remove_bc = [bc for bc in arm_obj.data.collections
                            if bc.name != meta_coll_name]
            for bc in to_remove_bc:
                try:
                    arm_obj.data.collections.remove(bc)
                    removed.append(f"[BoneColl] {bc.name}")
                except Exception:
                    pass

        msg = f"Clear Rig: removed — {', '.join(removed)}" if removed else "Clear Rig: nothing to remove"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ─── DELETE SAMPLE FOLDER ─────────────────────────────────────────────────────

class GESTUREBONE_OT_DeleteSampleFolder(bpy.types.Operator):
    bl_idname      = "gesturebone.delete_sample_folder"
    bl_label       = "Delete Sample Folder"
    bl_description = "Delete the 'SampleMesh' collection and all objects inside it"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sample_coll = bpy.data.collections.get("SampleMesh")
        if not sample_coll:
            self.report({'WARNING'}, "'SampleMesh' collection not found")
            return {'CANCELLED'}
        obj_count = len(list(sample_coll.objects))
        _delete_coll(sample_coll)
        self.report({'INFO'}, f"Deleted 'SampleMesh' ({obj_count} object(s) removed)")
        return {'FINISHED'}


# ─── TOGGLE CONNECT SELECTABLE ────────────────────────────────────────────────

class GESTUREBONE_OT_ToggleConnectSelectable(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_connect_selectable"
    bl_label       = "Toggle CONNECT"
    bl_description = "Toggle the selectable (hide_select) state of all bones prefixed 'CONNECT' in the MetaRig"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _p(context)

        # CONNECT bones live in the .Gesture armature, fall back to MetaRig if not found
        gesture_name = f"{props.meta_rig}.Gesture"
        arm_obj = bpy.data.objects.get(gesture_name)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"Neither '{gesture_name}' nor MetaRig found")
            return {'CANCELLED'}

        connect_bones = [b for b in arm_obj.data.bones if b.name.startswith('CONNECT')]
        if not connect_bones:
            self.report({'WARNING'}, f"No bones with prefix 'CONNECT' found in '{arm_obj.name}'")
            return {'CANCELLED'}

        # Ensure bone collections that hold CONNECT bones are visible so the toggle is visible
        for bc in _all_bone_colls(arm_obj.data):
            if 'CONNECT' in bc.name.upper() and not bc.is_visible:
                bc.is_visible = True

        # Toggle based on majority state
        selectable_count = sum(1 for b in connect_bones if not b.hide_select)
        new_hide = selectable_count > len(connect_bones) // 2
        for b in connect_bones:
            b.hide_select = new_hide

        state = "non-selectable" if new_hide else "selectable"
        self.report({'INFO'}, f"{len(connect_bones)} CONNECT bone(s) in '{arm_obj.name}' → {state}")

        # Activate the .Gesture armature in Pose Mode
        gesture_arm = bpy.data.objects.get(f"{props.meta_rig}.Gesture")
        _activate_in_pose_mode(context, gesture_arm)
        return {'FINISHED'}


# ─── RESET ALL BONES STRETCH ──────────────────────────────────────────────────

class GESTUREBONE_OT_ResetAllBonesStretch(bpy.types.Operator):
    bl_idname      = "gesturebone.reset_all_bones_stretch"
    bl_label       = "Reset Stretch"
    bl_description = "Reset all Stretch To constraints on the MetaRig and Gesture armature to their current bone length"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props        = _p(context)
        arm_obj      = _meta_rig(props)
        gesture_obj  = bpy.data.objects.get(f"{props.meta_rig}.Gesture")

        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        targets = [arm_obj]
        if gesture_obj and gesture_obj.type == 'ARMATURE':
            targets.append(gesture_obj)

        _ensure_object_mode(context)
        count = 0
        for target in targets:
            bpy.ops.object.select_all(action='DESELECT')
            target.hide_set(False)
            target.select_set(True)
            context.view_layer.objects.active = target
            bpy.ops.object.mode_set(mode='POSE')
            for pbone in target.pose.bones:
                for con in pbone.constraints:
                    if con.type != 'STRETCH_TO':
                        continue
                    with context.temp_override(active_pose_bone=pbone):
                        bpy.ops.constraint.stretchto_reset(
                            constraint=con.name,
                            owner='BONE',
                        )
                    count += 1
            bpy.ops.object.mode_set(mode='OBJECT')

        names = arm_obj.name + (f" + '{gesture_obj.name}'" if gesture_obj else "")
        self.report({'INFO'}, f"Reset {count} Stretch To constraint(s) on {names}")

        # Activate the .Gesture armature in Pose Mode
        _activate_in_pose_mode(context, gesture_obj)
        return {'FINISHED'}


# ─── TOGGLE PIVOT-ROTATION COLLECTION ────────────────────────────────────────

class GESTUREBONE_OT_TogglePivotRotation(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_pivot_rotation"
    bl_label       = "Toggle PIVOT"
    bl_description = "Toggle visibility of the 'PIVOT-ROTATION' bone collection in the Gesture armature"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props        = _p(context)
        gesture_name = f"{props.meta_rig}.Gesture"
        arm_obj      = bpy.data.objects.get(gesture_name)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"Gesture armature '{gesture_name}' not found")
            return {'CANCELLED'}

        bc = arm_obj.data.collections.get('PIVOT-ROTATION')
        if not bc:
            self.report({'WARNING'}, f"'PIVOT-ROTATION' bone collection not found in '{gesture_name}'")
            return {'CANCELLED'}

        bc.is_visible = not bc.is_visible
        state = "visible" if bc.is_visible else "hidden"
        self.report({'INFO'}, f"'PIVOT-ROTATION' collection is now {state}")

        # Activate the .Gesture armature in Pose Mode
        _activate_in_pose_mode(context, arm_obj)
        return {'FINISHED'}


# ─── TOGGLE META COLLECTION ───────────────────────────────────────────────────

class GESTUREBONE_OT_ToggleMetaCollection(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_meta_collection"
    bl_label       = "Toggle META"
    bl_description = (
        "ON: unsolo META (show all bone collections) | "
        "OFF: solo META (hide all other collections) — always switches to Final Rig in Pose Mode"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props   = _p(context)
        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        meta_coll = props.meta_collection
        if not meta_coll:
            self.report({'WARNING'}, "Meta Collection not set")
            return {'CANCELLED'}

        bc = arm_obj.data.collections.get(meta_coll)
        if not bc:
            self.report({'WARNING'}, f"Bone collection '{meta_coll}' not found in MetaRig")
            return {'CANCELLED'}

        # Toggle solo state
        entering_solo = not props.meta_solo_mode
        props.meta_solo_mode = entering_solo

        if entering_solo:
            # Entering solo: show ONLY the META collection, hide everything else
            for coll in _all_bone_colls(arm_obj.data):
                coll.is_visible = (coll.name == meta_coll)
        else:
            # Leaving solo: show all collections EXCEPT META (mute meta bones)
            for coll in _all_bone_colls(arm_obj.data):
                coll.is_visible = (coll.name != meta_coll)

        # Always: make the Meta Rig the active object in Pose Mode
        _activate_in_pose_mode(context, arm_obj)

        state = "solo" if entering_solo else "unsolo (all visible)"
        self.report({'INFO'}, f"META '{meta_coll}': {state}")
        return {'FINISHED'}


# ─── BIND TO MESH ─────────────────────────────────────────────────────────────

class GESTUREBONE_OT_BindToMesh(bpy.types.Operator):
    bl_idname      = "gesturebone.bind_to_mesh"
    bl_label       = "Bind to Mesh"
    bl_description = "Copy geometry and materials from Bind_to_Mesh into this bone's Sample Mesh"
    bl_options     = {'REGISTER', 'UNDO'}

    bone_name: StringProperty()

    def execute(self, context):
        props = _p(context)
        entry = props.bone_settings.get(self.bone_name)
        if entry is None:
            self.report({'ERROR'}, f"No settings for bone '{self.bone_name}'")
            return {'CANCELLED'}

        bind_mesh = entry.bind_mesh
        if bind_mesh is None:
            return {'FINISHED'}   # silent no-op as specified

        sample_mesh = entry.sample_mesh
        if sample_mesh is None:
            self.report({'ERROR'}, "Sample Mesh not set — run Steps 1–9 first")
            return {'CANCELLED'}

        # 1. Ensure 'Mesh' collection; link source mesh there (never move/duplicate it)
        mesh_coll = bpy.data.collections.get("Mesh")
        if mesh_coll is None:
            mesh_coll = bpy.data.collections.new("Mesh")
            context.scene.collection.children.link(mesh_coll)
        if bind_mesh.name not in mesh_coll.objects:
            mesh_coll.objects.link(bind_mesh)

        # 2. Use bmesh API — no view-layer membership required for either object.
        #    Transform bind_mesh vertices from its world space into sample_mesh local
        #    space so the geometry lands at the correct world position after the copy.
        world_to_local = sample_mesh.matrix_world.inverted() @ bind_mesh.matrix_world
        bm = bmesh.new()
        bm.from_mesh(bind_mesh.data)
        bmesh.ops.transform(bm, matrix=world_to_local, verts=bm.verts)

        # 3. Write the transformed geometry onto sample_mesh, replacing old geometry.
        #    Vertex group NAMES on the sample_mesh object are left untouched — only
        #    the underlying geometry is swapped, so GN references by name still work.
        bm.to_mesh(sample_mesh.data)
        bm.free()
        sample_mesh.data.update()

        # 4. Materials: clear and copy from bind_mesh
        sample_mesh.data.materials.clear()
        for mat in bind_mesh.data.materials:
            sample_mesh.data.materials.append(mat)

        self.report({'INFO'}, f"Bound '{bind_mesh.name}' → '{sample_mesh.name}'")
        return {'FINISHED'}


# ─── CREATE RIG ───────────────────────────────────────────────────────────────

class GESTUREBONE_OT_CreateRig(bpy.types.Operator):
    bl_idname      = "gesturebone.create_rig"
    bl_label       = "Create Rig"
    bl_description = "Duplicate the MetaRig Template into a new named armature"
    bl_options     = {'REGISTER', 'UNDO'}

    new_rig_name:       StringProperty(name="New Rig Name", default="MyRig")
    new_rig_collection: StringProperty(name="Collection",   search=_collection_search)

    def invoke(self, context, event):
        props = _p(context)
        if not props.meta_rig_template:
            self.report({'ERROR'}, "Set a MetaRig Template first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "new_rig_name")
        col.prop(self, "new_rig_collection")
        coll_name = self.new_rig_collection.strip()
        if coll_name:
            exists = bpy.data.collections.get(coll_name) is not None
            info_row = col.row()
            info_row.label(
                text="Collection exists" if exists else "New collection will be created",
                icon='CHECKMARK' if exists else 'ADD',
            )

    def execute(self, context):
        props    = _p(context)
        template = bpy.data.objects.get(props.meta_rig_template)
        if not template or template.type != 'ARMATURE':
            self.report({'ERROR'}, f"Template '{props.meta_rig_template}' not found or not an armature")
            return {'CANCELLED'}

        name = self.new_rig_name.strip()
        if not name:
            self.report({'ERROR'}, "New rig name cannot be empty")
            return {'CANCELLED'}

        _ensure_object_mode(context)
        bpy.ops.object.select_all(action='DESELECT')
        template.hide_set(False)
        template.select_set(True)
        context.view_layer.objects.active = template
        bpy.ops.object.duplicate()

        new_obj      = context.active_object
        new_obj.name = name
        new_obj.data = new_obj.data.copy()
        new_obj.data.name = name

        coll_name = self.new_rig_collection.strip()
        if coll_name:
            target_coll = bpy.data.collections.get(coll_name)
            if target_coll is None:
                target_coll = bpy.data.collections.new(coll_name)
                context.scene.collection.children.link(target_coll)
            for c in list(new_obj.users_collection):
                c.objects.unlink(new_obj)
            target_coll.objects.link(new_obj)

        self.report({'INFO'}, f"Created rig '{name}'")
        return {'FINISHED'}


# ─── LOAD TEMPLATE RIG ────────────────────────────────────────────────────────

class GESTUREBONE_OT_LoadTemplateRig(bpy.types.Operator):
    bl_idname      = "gesturebone.load_template_rig"
    bl_label       = "Load Template Rig"
    bl_description = "Append the bundled MetaRig template from the addon assets folder"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        assets_path = os.path.join(_ADDON_DIR, "assets", "template_rig.blend")
        if not os.path.exists(assets_path):
            self.report({'ERROR'}, f"Template blend not found: {assets_path}")
            return {'CANCELLED'}

        with bpy.data.libraries.load(assets_path, link=False) as (data_from, data_to):
            data_to.objects = list(data_from.objects)

        appended = []
        for obj in data_to.objects:
            if obj and obj.type == 'ARMATURE':
                if obj.name not in context.scene.collection.objects:
                    context.scene.collection.objects.link(obj)
                appended.append(obj.name)

        if not appended:
            self.report({'WARNING'}, "No armature objects found in template blend")
            return {'CANCELLED'}

        props = _p(context)
        props.meta_rig_template = appended[0]
        self.report({'INFO'}, f"Loaded template: {', '.join(appended)}")
        return {'FINISHED'}


# ─── REGISTER ─────────────────────────────────────────────────────────────────

_classes = [
    GESTUREBONE_OT_InitBoneControlMode,
    GESTUREBONE_OT_RigPart,
    GESTUREBONE_OT_AutoRig,
    GESTUREBONE_OT_ClearRig,
    GESTUREBONE_OT_DeleteSampleFolder,
    GESTUREBONE_OT_ToggleConnectSelectable,
    GESTUREBONE_OT_ResetAllBonesStretch,
    GESTUREBONE_OT_TogglePivotRotation,
    GESTUREBONE_OT_ToggleMetaCollection,
    GESTUREBONE_OT_BindToMesh,
    GESTUREBONE_OT_CreateRig,
    GESTUREBONE_OT_LoadTemplateRig,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
