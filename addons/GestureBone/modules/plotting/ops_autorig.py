"""
plotting/ops_autorig.py — AutoRig, RigPart, ReRigPart, ClearRig, and utility operators.
Adapted from rig_generation/ops_actions.py; reads from arm.gesturebone_props.
"""
import bpy
import bmesh
import os
from bpy.props import StringProperty
from .utils import _active_plotting_arm, _ensure_object_mode, _default_template
from ..shared.utils import (
    _bones_in_bone_coll, _all_bone_colls, _delete_coll, _rig_target_colls,
)
from ..shared.chain import CONTROL_MODE_COUNT, CONTROL_MODE_GN_INT, _ctrl_bone_indices


# Steps run by RigPart (Step 5 is interactive — skipped in auto mode)
_STEP_SEQUENCE = [
    ("gesturebone.duplicate_atomic_chain",       1),
    ("gesturebone.rebind_constraints_geonodes",  2),
    ("gesturebone.scale_empty_to_rest_pose",     3),
    ("gesturebone.add_align_constraints",        4),
    ("gesturebone.accept_and_bind",              6),
    ("gesturebone.refresh_rigs",                 7),
    ("gesturebone.rebind_final_armatures",       8),
    ("gesturebone.finish_merging",               9),
    ("gesturebone.merge_rig_into_metarig",       10),
    ("gesturebone.rebind_armature_deform",       11),
]


def _activate_in_pose_mode(context, arm_obj):
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


def _apply_control_mode_to_plotting(plotting_obj, gn_int_value):
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
    if not gesture_obj or gesture_obj.type != 'ARMATURE':
        return
    roots     = [f"CTRL-{bone_name}_1", f"CTRL-{bone_name}_3"]
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


def _apply_control_mode(context, arm, bone_name):
    chain = arm.gesturebone_props.chains.get(bone_name)
    if chain is None:
        return
    mode    = chain.control_mode
    gn_int  = CONTROL_MODE_GN_INT.get(mode, 0)
    meta_rig_name = arm.name

    plotting_name = f"{meta_rig_name}-{bone_name}.PlottingSpline"
    plotting_obj  = bpy.data.objects.get(plotting_name)
    _apply_control_mode_to_plotting(plotting_obj, gn_int)

    if mode in ('PT_2', 'PT_3'):
        gesture_name = f"{meta_rig_name}.Gesture"
        gesture_obj  = bpy.data.objects.get(gesture_name)
        _delete_extra_ctrl_bones(context, gesture_obj, bone_name)


# ── RIG PART ──────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RigPart(bpy.types.Operator):
    bl_idname      = "gesturebone.rig_part"
    bl_label       = "Rig Part"
    bl_description = "Run Steps 1-4, 6-11 automatically for the selected MetaBone"
    bl_options     = {'REGISTER', 'UNDO'}

    bone_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}

        props     = arm.gesturebone_props
        bone_name = self.bone_name or props.active_bone_name
        if not bone_name:
            self.report({'ERROR'}, "No bone name provided")
            return {'CANCELLED'}

        # Store the active bone so step operators can read it
        props.active_bone_name = bone_name

        for idname, step_num in _STEP_SEQUENCE:
            try:
                result = _invoke_op(idname)
            except RuntimeError as e:
                self.report({'ERROR'}, f"Step {step_num} failed — {e}")
                return {'CANCELLED'}
            if 'CANCELLED' in result:
                self.report({'ERROR'}, f"Step {step_num} cancelled — '{idname}'")
                return {'CANCELLED'}

            if step_num == 1:
                try:
                    _apply_control_mode(context, arm, bone_name)
                except Exception as e:
                    self.report({'WARNING'}, f"Control MODE apply failed: {e}")

        # Mark chain as fully rigged and set gesture_rig pointer
        gesture_arm = bpy.data.objects.get(f"{arm.name}.Gesture")
        chain = props.chains.get(bone_name)
        if chain and gesture_arm:
            chain.gesture_rig        = gesture_arm
            chain.rig_completed_step = 11  # steps 12a-c are bind mesh, done separately

        self.report({'INFO'}, f"Rig Part complete for '{bone_name}'")
        return {'FINISHED'}


# ── AUTO RIG ──────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_AutoRig(bpy.types.Operator):
    bl_idname      = "gesturebone.auto_rig"
    bl_label       = "Auto Rig"
    bl_description = "Run Rig Part for every bone in the META collection"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}

        props     = arm.gesturebone_props
        coll_name = props.meta_collection
        if not coll_name:
            self.report({'ERROR'}, "Meta Collection not set")
            return {'CANCELLED'}

        bone_names = _bones_in_bone_coll(arm.data, coll_name)
        if not bone_names:
            self.report({'ERROR'}, f"No bones found in '{coll_name}'")
            return {'CANCELLED'}

        # Sync chain list before generating
        bpy.ops.gesturebone.sync_chains_from_meta_bones()

        bpy.ops.gesturebone.clear_rig()

        total = len(bone_names)
        done  = 0
        for bone_name in bone_names:
            result = bpy.ops.gesturebone.rig_part(bone_name=bone_name)
            if 'CANCELLED' in result:
                self.report({'WARNING'}, f"Rig Part cancelled on '{bone_name}' ({done}/{total} done)")
                return {'CANCELLED'}
            bpy.ops.gesturebone.bind_to_mesh(bone_name=bone_name)
            done += 1

        bpy.ops.gesturebone.reset_all_bones_stretch()

        gesture_arm_name = f"{arm.name}.Gesture"
        gesture_arm      = bpy.data.objects.get(gesture_arm_name)
        if gesture_arm and gesture_arm.type == 'ARMATURE':
            for b in gesture_arm.data.bones:
                if b.name.startswith('CONNECT'):
                    b.hide_select = True
            pivot_bc = gesture_arm.data.collections.get('PIVOT-ROTATION')
            if pivot_bc:
                pivot_bc.is_visible = False

            # Tag the gesture rig and set back-pointer
            gesture_arm.gesturebone_props.rig_type    = 'GESTURE'
            gesture_arm.gesturebone_props.plotting_rig = arm

        props.meta_solo_mode      = False
        props.gesture_active      = True
        props.show_both_armatures = True

        # Final chain sync — writes gesture_rig pointer on each chain
        bpy.ops.gesturebone.sync_chains_from_meta_bones()

        # Automatically load chains onto the gesture rig
        if gesture_arm:
            _ensure_object_mode(context)
            bpy.ops.object.select_all(action='DESELECT')
            gesture_arm.select_set(True)
            context.view_layer.objects.active = gesture_arm
            bpy.ops.gesturebone.load_chains()

        _activate_in_pose_mode(context, gesture_arm)
        self.report({'INFO'}, f"Auto Rig complete — {done}/{total} bones processed")
        return {'FINISHED'}


# ── RE-RIG PART ───────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ReRigPart(bpy.types.Operator):
    bl_idname      = "gesturebone.rerig_part"
    bl_label       = "Re-Rig Part"
    bl_description = "Reset this chain and re-run Rig Part"
    bl_options     = {'REGISTER', 'UNDO'}

    bone_name: StringProperty()

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        chain = arm.gesturebone_props.chains.get(self.bone_name)
        if chain is None:
            self.report({'ERROR'}, f"Chain '{self.bone_name}' not found")
            return {'CANCELLED'}
        chain.rig_completed_step = 0
        chain.gesture_rig        = None
        return bpy.ops.gesturebone.rig_part(bone_name=self.bone_name)


# ── CLEAR RIG ─────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_ClearRig(bpy.types.Operator):
    bl_idname      = "gesturebone.clear_rig"
    bl_label       = "Clear Rig"
    bl_description = "Remove all generated rig data for this PLOTTING rig"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}

        props         = arm.gesturebone_props
        meta_rig_name = arm.name
        removed       = []

        for legacy_name in (
            "Splines",
            f"{meta_rig_name}.Gesture_Splines",
            f"{meta_rig_name}.GestureSplines",
            f"{meta_rig_name}.PlottingSplines",
            f"{meta_rig_name}.Mesh",
            "SampleMesh",
        ):
            coll = bpy.data.collections.get(legacy_name)
            if coll:
                _delete_coll(coll)
                removed.append(legacy_name)

        gesture_arm = bpy.data.objects.get(f"{meta_rig_name}.Gesture")
        if gesture_arm:
            bpy.data.objects.remove(gesture_arm, do_unlink=True)
            removed.append(f"{meta_rig_name}.Gesture")

        meta_coll_name = props.meta_collection
        meta_bones     = set(_bones_in_bone_coll(arm.data, meta_coll_name))

        to_delete_bones = set()
        for bc in _all_bone_colls(arm.data):
            if bc.name == meta_coll_name:
                continue
            try:
                for b in bc.bones:
                    if b.name not in meta_bones:
                        to_delete_bones.add(b.name)
            except AttributeError:
                for b in arm.data.bones:
                    if any(c.name == bc.name for c in getattr(b, 'collections', [])):
                        if b.name not in meta_bones:
                            to_delete_bones.add(b.name)

        if to_delete_bones:
            _ensure_object_mode(context)
            bpy.ops.object.select_all(action='DESELECT')
            arm.hide_set(False)
            arm.hide_viewport = False
            arm.select_set(True)
            context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode='EDIT')
            for bname in list(to_delete_bones):
                eb = arm.data.edit_bones.get(bname)
                if eb:
                    arm.data.edit_bones.remove(eb)
            bpy.ops.object.mode_set(mode='OBJECT')
            removed.append(f"{len(to_delete_bones)} generated bone(s)")

        to_remove_bc = [bc for bc in arm.data.collections if bc.name != meta_coll_name]
        for bc in to_remove_bc:
            try:
                arm.data.collections.remove(bc)
                removed.append(f"[BoneColl] {bc.name}")
            except Exception:
                pass

        # Reset chain state
        for chain in props.chains:
            chain.gesture_rig        = None
            chain.rig_completed_step = 0
            chain.is_bound           = False
            chain.gesture_spline     = None
            chain.plotting_spline    = None

        msg = f"Clear Rig: removed — {', '.join(removed)}" if removed else "Clear Rig: nothing to remove"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ── UTILITY OPERATORS (ported unchanged) ──────────────────────────────────────

class GESTUREBONE_OT_DeleteSampleFolder(bpy.types.Operator):
    bl_idname      = "gesturebone.delete_sample_folder"
    bl_label       = "Delete Sample Folder"
    bl_description = "Delete the '<MetaRig>.Mesh' collection and all objects inside it"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        coll_name   = f"{arm.name}.Mesh"
        sample_coll = bpy.data.collections.get(coll_name) or bpy.data.collections.get("SampleMesh")
        if not sample_coll:
            self.report({'WARNING'}, f"'{coll_name}' not found")
            return {'CANCELLED'}
        obj_count = len(list(sample_coll.objects))
        _delete_coll(sample_coll)
        self.report({'INFO'}, f"Deleted '{coll_name}' ({obj_count} object(s) removed)")
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleConnectSelectable(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_connect_selectable"
    bl_label       = "Toggle CONNECT"
    bl_description = "Toggle selectable state of all CONNECT-prefixed bones in the Gesture armature"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        gesture_name = f"{arm.name}.Gesture"
        arm_obj      = bpy.data.objects.get(gesture_name) or arm
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"Gesture armature not found")
            return {'CANCELLED'}
        connect_bones = [b for b in arm_obj.data.bones if b.name.startswith('CONNECT')]
        if not connect_bones:
            self.report({'WARNING'}, "No CONNECT bones found")
            return {'CANCELLED'}
        for bc in _all_bone_colls(arm_obj.data):
            if 'CONNECT' in bc.name.upper() and not bc.is_visible:
                bc.is_visible = True
        sel_count = sum(1 for b in connect_bones if not b.hide_select)
        new_hide  = sel_count > len(connect_bones) // 2
        for b in connect_bones:
            b.hide_select = new_hide
        _activate_in_pose_mode(context, arm_obj)
        state = "non-selectable" if new_hide else "selectable"
        self.report({'INFO'}, f"{len(connect_bones)} CONNECT bone(s) → {state}")
        return {'FINISHED'}


class GESTUREBONE_OT_ResetAllBonesStretch(bpy.types.Operator):
    bl_idname      = "gesturebone.reset_all_bones_stretch"
    bl_label       = "Reset Stretch"
    bl_description = "Reset all Stretch To constraints on MetaRig and Gesture armature"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        gesture_obj = bpy.data.objects.get(f"{arm.name}.Gesture")
        targets     = [arm]
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
                        bpy.ops.constraint.stretchto_reset(constraint=con.name, owner='BONE')
                    count += 1
            bpy.ops.object.mode_set(mode='OBJECT')
        _activate_in_pose_mode(context, gesture_obj)
        self.report({'INFO'}, f"Reset {count} Stretch To constraint(s)")
        return {'FINISHED'}


class GESTUREBONE_OT_TogglePivotRotation(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_pivot_rotation"
    bl_label       = "Toggle PIVOT"
    bl_description = "Toggle visibility of the PIVOT-ROTATION bone collection in the Gesture armature"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        gesture_name = f"{arm.name}.Gesture"
        arm_obj      = bpy.data.objects.get(gesture_name)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"'{gesture_name}' not found")
            return {'CANCELLED'}
        bc = arm_obj.data.collections.get('PIVOT-ROTATION')
        if not bc:
            self.report({'WARNING'}, "PIVOT-ROTATION collection not found")
            return {'CANCELLED'}
        bc.is_visible = not bc.is_visible
        _activate_in_pose_mode(context, arm_obj)
        self.report({'INFO'}, f"PIVOT-ROTATION: {'visible' if bc.is_visible else 'hidden'}")
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleMetaCollection(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_meta_collection"
    bl_label       = "Toggle META"
    bl_description = "Solo/unsolo the META bone collection"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props     = arm.gesturebone_props
        meta_coll = props.meta_collection
        bc        = arm.data.collections.get(meta_coll)
        if not bc:
            self.report({'WARNING'}, f"Bone collection '{meta_coll}' not found")
            return {'CANCELLED'}
        entering_solo = not props.meta_solo_mode
        props.meta_solo_mode = entering_solo
        for c in _all_bone_colls(arm.data):
            c.is_visible = (c.name == meta_coll) if entering_solo else (c.name != meta_coll)
        _activate_in_pose_mode(context, arm)
        self.report({'INFO'}, f"META '{meta_coll}': {'solo' if entering_solo else 'unsolo'}")
        return {'FINISHED'}


class GESTUREBONE_OT_SwitchArmature(bpy.types.Operator):
    bl_idname      = "gesturebone.switch_armature"
    bl_label       = "Switch Armature"
    bl_description = "Switch active armature between MetaRig and Gesture rig"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props       = arm.gesturebone_props
        gesture_obj = bpy.data.objects.get(f"{arm.name}.Gesture")
        if not arm or not gesture_obj:
            self.report({'ERROR'}, "Both MetaRig and Gesture armature must exist")
            return {'CANCELLED'}
        props.gesture_active = not props.gesture_active
        target = gesture_obj if props.gesture_active else arm
        other  = arm if props.gesture_active else gesture_obj
        if not props.show_both_armatures:
            other.hide_set(True)
            target.hide_set(False)
        _activate_in_pose_mode(context, target)
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleArmatureVisibility(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_armature_visibility"
    bl_label       = "Toggle Armature Visibility"
    bl_description = "Show both armatures, or solo the active one"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props       = arm.gesturebone_props
        gesture_obj = bpy.data.objects.get(f"{arm.name}.Gesture")
        if not gesture_obj:
            self.report({'ERROR'}, "Gesture armature must exist")
            return {'CANCELLED'}
        props.show_both_armatures = not props.show_both_armatures
        if props.show_both_armatures:
            arm.hide_set(False)
            gesture_obj.hide_set(False)
        else:
            active = gesture_obj if props.gesture_active else arm
            hidden = arm if props.gesture_active else gesture_obj
            hidden.hide_set(True)
            active.hide_set(False)
            _activate_in_pose_mode(context, active)
        state = "both visible" if props.show_both_armatures else "solo active"
        self.report({'INFO'}, f"Armature visibility: {state}")
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_RigPart,
    GESTUREBONE_OT_AutoRig,
    GESTUREBONE_OT_ReRigPart,
    GESTUREBONE_OT_ClearRig,
    GESTUREBONE_OT_DeleteSampleFolder,
    GESTUREBONE_OT_ToggleConnectSelectable,
    GESTUREBONE_OT_ResetAllBonesStretch,
    GESTUREBONE_OT_TogglePivotRotation,
    GESTUREBONE_OT_ToggleMetaCollection,
    GESTUREBONE_OT_SwitchArmature,
    GESTUREBONE_OT_ToggleArmatureVisibility,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
