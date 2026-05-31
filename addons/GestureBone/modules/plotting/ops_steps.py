"""
plotting/ops_steps.py — Steps 1, 2, 7, 8, 9, 10, 11: main workflow operators.
Adapted from rig_generation/ops_steps.py; reads from arm.gesturebone_props.
"""
import bpy
from .utils import _active_plotting_arm, _ensure_object_mode
from ..shared.utils import (
    _all_objects, _bones_in_bone_coll, _deep_copy_coll, _delete_coll,
    _ensure_child_coll, _move_obj_to_coll, _rig_target_colls, _atomic_coll,
    _clean, _rename_coll_tree, _all_bone_colls,
)


def _p(context):
    """Return gesturebone_props of the active PLOTTING rig."""
    arm = _active_plotting_arm(context)
    return arm.gesturebone_props if arm else None


def _arm(context):
    return _active_plotting_arm(context)


# ── STEP 1 ────────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_DuplicateAtomicChain(bpy.types.Operator):
    bl_idname      = "gesturebone.duplicate_atomic_chain"
    bl_label       = "Duplicate and Rename"
    bl_description = "Copy the template collection and rename every token to the selected MetaBone name"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props = arm.gesturebone_props
        props.completed_step = 0

        bone_name     = props.active_bone_name
        meta_rig_name = arm.name

        if not bone_name:
            self.report({'ERROR'}, "No active MetaBone — run via RigPart or AutoRig")
            return {'CANCELLED'}

        # Resolve template from chain settings
        chain = props.chains.get(bone_name)
        token = (chain.atomic_chain if chain and chain.atomic_chain else '') or props.atomic_chain
        props.wip_token = token

        if not token:
            self.report({'ERROR'}, "No template selected — set one in the chain settings")
            return {'CANCELLED'}

        src = _atomic_coll(props)
        if not src:
            self.report({'ERROR'}, f"Template collection '{token}' not found")
            return {'CANCELLED'}

        target_colls = _rig_target_colls(arm)
        if not target_colls:
            self.report({'ERROR'}, f"MetaRig not in any collection")
            return {'CANCELLED'}

        _ensure_object_mode(context)

        existing = bpy.data.collections.get(props.wip_coll)
        if existing:
            _delete_coll(existing)
        props.wip_coll  = ''
        props.wip_empty = ''

        template_obj_set = set(_all_objects(src))
        for template_obj in template_obj_set:
            target_name = f"{meta_rig_name}-{_clean(template_obj.name, token, bone_name)}"
            conflict = bpy.data.objects.get(target_name)
            if conflict and conflict not in template_obj_set:
                bpy.data.objects.remove(conflict, do_unlink=True)

        new_coll = _deep_copy_coll(src, target_colls[0])

        count = 0
        for obj in _all_objects(new_coll):
            obj.name = f"{meta_rig_name}-{_clean(obj.name, token, bone_name)}"
            if obj.data:
                obj.data.name = f"{meta_rig_name}-{_clean(obj.data.name, token, bone_name)}"
            if obj.type == 'ARMATURE':
                bpy.ops.object.select_all(action='DESELECT')
                try:
                    obj.select_set(True)
                except Exception:
                    pass
                context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='EDIT')
                for eb in obj.data.edit_bones:
                    eb.name = _clean(eb.name, token, bone_name)
                bpy.ops.object.mode_set(mode='OBJECT')
                for bc in _all_bone_colls(obj.data):
                    new_bc_name = _clean(bc.name, token, bone_name)
                    if new_bc_name != bc.name:
                        bc.name = new_bc_name
            count += 1

        _rename_coll_tree(new_coll, token, bone_name)
        props.wip_coll = new_coll.name

        alignment_name = f"{meta_rig_name}-{bone_name}-Alignment"
        for obj in _all_objects(new_coll):
            if obj.type == 'EMPTY' and obj.name == alignment_name:
                props.wip_empty = obj.name
                break
        if not props.wip_empty:
            self.report({'ERROR'}, f"'{alignment_name}' empty not found in template")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Duplicated '{src.name}' → {count} objects renamed")
        props.last_step      = self.bl_idname
        props.completed_step = 1
        return {'FINISHED'}


# ── STEP 2 ────────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RebindConstraintsGeonodes(bpy.types.Operator):
    bl_idname      = "gesturebone.rebind_constraints_geonodes"
    bl_label       = "Rebind Constraints & Geonodes"
    bl_description = "Fix constraint targets and GN socket inputs still pointing to template token objects"
    bl_options     = {'REGISTER', 'UNDO'}

    def _fix_obj_ref(self, owner, attr, token, bone_name, meta_rig_name):
        ref = getattr(owner, attr, None)
        if ref and token in ref.name:
            new_obj = bpy.data.objects.get(f"{meta_rig_name}-{_clean(ref.name, token, bone_name)}")
            if not new_obj:
                new_obj = bpy.data.objects.get(ref.name.replace(token, bone_name))
            if new_obj:
                setattr(owner, attr, new_obj)

    def _fix_str(self, owner, attr, token, bone_name):
        val = getattr(owner, attr, None)
        if isinstance(val, str) and token in val:
            setattr(owner, attr, val.replace(token, bone_name))

    def _rebind_constraint(self, con, token, bone_name, meta_rig_name):
        self._fix_obj_ref(con, 'target',      token, bone_name, meta_rig_name)
        self._fix_str    (con, 'subtarget',   token, bone_name)
        self._fix_obj_ref(con, 'pole_target', token, bone_name, meta_rig_name)

    def _rebind_gn_mod(self, mod, token, bone_name, meta_rig_name):
        if not mod.node_group:
            return
        try:
            items = mod.node_group.interface.items_tree
        except AttributeError:
            return
        for item in items:
            if not hasattr(item, 'identifier'):
                continue
            if 'OUTPUT' in str(getattr(item, 'in_out', 'INPUT')):
                continue
            try:
                value = mod[item.identifier]
            except (KeyError, TypeError):
                continue
            if isinstance(value, bpy.types.Object) and value and token in value.name:
                new_obj = bpy.data.objects.get(f"{meta_rig_name}-{_clean(value.name, token, bone_name)}")
                if not new_obj:
                    new_obj = bpy.data.objects.get(value.name.replace(token, bone_name))
                if new_obj:
                    mod[item.identifier] = new_obj
            elif isinstance(value, str) and token in value:
                mod[item.identifier] = value.replace(token, bone_name)

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props         = arm.gesturebone_props
        bone_name     = props.active_bone_name
        token         = props.wip_token or props.atomic_chain
        meta_rig_name = arm.name

        if not bone_name:
            self.report({'ERROR'}, "No active MetaBone")
            return {'CANCELLED'}

        wip = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection — run Step 1 first")
            return {'CANCELLED'}

        for obj in _all_objects(wip):
            for con in obj.constraints:
                self._rebind_constraint(con, token, bone_name, meta_rig_name)
            for mod in obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_mod(mod, token, bone_name, meta_rig_name)
            if obj.type == 'ARMATURE':
                for pb in obj.pose.bones:
                    for con in pb.constraints:
                        self._rebind_constraint(con, token, bone_name, meta_rig_name)

        self.report({'INFO'}, f"Rebound constraints & geonodes in '{wip.name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 2
        return {'FINISHED'}


# ── STEP 7 ────────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RefreshRigs(bpy.types.Operator):
    bl_idname      = "gesturebone.refresh_rigs"
    bl_label       = "Refresh Gesture & Plot Rigs"
    bl_description = "Create MetaRig.Rig and MetaRig.Gesture armatures if missing; strip stale bones"
    bl_options     = {'REGISTER', 'UNDO'}

    def _strip_bones(self, context, arm_target, meta_arm, meta_coll_name, token, bone_name):
        all_meta_names = {b.name for b in meta_arm.data.bones}
        bpy.ops.object.select_all(action='DESELECT')
        arm_target.hide_set(False)
        arm_target.select_set(True)
        context.view_layer.objects.active = arm_target
        bpy.ops.object.mode_set(mode='EDIT')
        for eb in list(arm_target.data.edit_bones):
            if eb.name in all_meta_names or token in eb.name or bone_name in eb.name:
                arm_target.data.edit_bones.remove(eb)
        bpy.ops.object.mode_set(mode='OBJECT')

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props     = arm.gesturebone_props
        bone_name = props.active_bone_name
        if not arm or arm.type != 'ARMATURE':
            self.report({'ERROR'}, "MetaRig not found")
            return {'CANCELLED'}

        rig_name     = f"{arm.name}.Rig"
        gesture_name = f"{arm.name}.Gesture"
        target_colls = _rig_target_colls(arm)
        token        = props.wip_token or props.atomic_chain
        _ensure_object_mode(context)

        rig_obj = bpy.data.objects.get(rig_name)
        if not rig_obj:
            rig_obj           = arm.copy()
            rig_obj.data      = arm.data.copy()
            rig_obj.name      = rig_name
            rig_obj.data.name = rig_name
            # Must be NONE so the depsgraph handler does not mistake it for the
            # user's PLOTTING rig when _strip_bones makes it the active object.
            rig_obj.gesturebone_props.rig_type = 'NONE'
            for coll in target_colls:
                coll.objects.link(rig_obj)

        self._strip_bones(context, rig_obj, arm, props.meta_collection, token, bone_name)

        gesture_obj = bpy.data.objects.get(gesture_name)
        if not gesture_obj:
            gesture_data = bpy.data.armatures.new(gesture_name)
            gesture_obj  = bpy.data.objects.new(gesture_name, gesture_data)
            for coll in target_colls:
                coll.objects.link(gesture_obj)
        else:
            if not gesture_obj.users_collection:
                for coll in target_colls:
                    coll.objects.link(gesture_obj)
            bpy.ops.object.select_all(action='DESELECT')
            gesture_obj.hide_set(False)
            gesture_obj.select_set(True)
            context.view_layer.objects.active = gesture_obj
            bpy.ops.object.mode_set(mode='EDIT')
            for eb in list(gesture_obj.data.edit_bones):
                if bone_name in eb.name:
                    gesture_obj.data.edit_bones.remove(eb)
            bpy.ops.object.mode_set(mode='OBJECT')

        self.report({'INFO'}, f"'{rig_name}' and '{gesture_name}' ready")
        props.last_step      = self.bl_idname
        props.completed_step = 7
        return {'FINISHED'}


# ── STEP 8 ────────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RebindFinalArmatures(bpy.types.Operator):
    bl_idname      = "gesturebone.rebind_final_armatures"
    bl_label       = "Rebind Final Armatures"
    bl_description = "Redirect .Rig and .Gesture references in the working collection to the merged target armatures"
    bl_options     = {'REGISTER', 'UNDO'}

    def _redirect(self, ref, gest_target, rig_target):
        if not ref:
            return None
        if ref.name.endswith('.Gesture') and ref is not gest_target:
            return gest_target
        if ref.name.endswith('.Rig') and ref is not rig_target:
            return rig_target
        return None

    def _rebind_gn_mod(self, mod, gest_target, rig_target):
        if not mod.node_group:
            return
        try:
            items = mod.node_group.interface.items_tree
        except AttributeError:
            return
        for item in items:
            if not hasattr(item, 'identifier'):
                continue
            if 'OUTPUT' in str(getattr(item, 'in_out', 'INPUT')):
                continue
            try:
                value = mod[item.identifier]
            except (KeyError, TypeError):
                continue
            if isinstance(value, bpy.types.Object):
                new_ref = self._redirect(value, gest_target, rig_target)
                if new_ref:
                    mod[item.identifier] = new_ref

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props       = arm.gesturebone_props
        meta_name   = arm.name
        gest_target = bpy.data.objects.get(f"{meta_name}.Gesture")
        rig_target  = bpy.data.objects.get(f"{meta_name}.Rig")
        if not gest_target or not rig_target:
            self.report({'ERROR'}, "Run Step 7 first")
            return {'CANCELLED'}
        wip = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection — run Step 1 first")
            return {'CANCELLED'}
        for obj in _all_objects(wip):
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE':
                    new_ref = self._redirect(mod.object, gest_target, rig_target)
                    if new_ref:
                        mod.object = new_ref
                elif mod.type == 'NODES':
                    self._rebind_gn_mod(mod, gest_target, rig_target)
            if obj.type == 'ARMATURE':
                for pb in obj.pose.bones:
                    for con in pb.constraints:
                        if hasattr(con, 'target'):
                            new_ref = self._redirect(con.target, gest_target, rig_target)
                            if new_ref:
                                con.target = new_ref
        self.report({'INFO'}, f"Rebound → '{gest_target.name}' / '{rig_target.name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 8
        return {'FINISHED'}


# ── STEP 9 ────────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_FinishMerging(bpy.types.Operator):
    bl_idname      = "gesturebone.finish_merging"
    bl_label       = "Merge & Clean"
    bl_description = "Join working armatures into .Rig/.Gesture, apply transforms, move curves and meshes"
    bl_options     = {'REGISTER', 'UNDO'}

    def _purge_bone_collection(self, context, target, bone_name, token=''):
        if not target or not bone_name or bone_name == 'NONE':
            return
        if not target.users_collection:
            context.scene.collection.objects.link(target)
        all_bc   = _all_bone_colls(target.data)
        to_purge = [bc for bc in all_bc if (bone_name in bc.name) or (token and token in bc.name)]
        if not to_purge:
            return
        bones_to_delete = set()
        for bc in to_purge:
            try:
                for b in bc.bones:
                    bones_to_delete.add(b.name)
            except Exception:
                pass
        bpy.ops.object.select_all(action='DESELECT')
        target.hide_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.mode_set(mode='EDIT')
        for bname in bones_to_delete:
            eb = target.data.edit_bones.get(bname)
            if eb:
                target.data.edit_bones.remove(eb)
        bpy.ops.object.mode_set(mode='OBJECT')
        for bc in to_purge:
            try:
                target.data.collections.remove(bc)
            except Exception:
                pass

    def _join_into(self, context, target, sources):
        if not sources:
            return
        if not target.users_collection:
            context.scene.collection.objects.link(target)
        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        for src in sources:
            try:
                src.select_set(True)
            except Exception:
                pass
        context.view_layer.objects.active = target
        bpy.ops.object.join()

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props       = arm.gesturebone_props
        meta_name   = arm.name
        bone_name   = props.active_bone_name
        rig_target  = bpy.data.objects.get(f"{meta_name}.Rig")
        gest_target = bpy.data.objects.get(f"{meta_name}.Gesture")
        if not rig_target or not gest_target:
            self.report({'ERROR'}, "Run Step 7 first")
            return {'CANCELLED'}

        target_colls = _rig_target_colls(arm)
        token        = props.wip_token or props.atomic_chain
        _ensure_object_mode(context)

        wip      = bpy.data.collections.get(props.wip_coll)
        wip_objs = set(_all_objects(wip)) if wip else set()

        rig_sources  = [o for o in wip_objs if o.type == 'ARMATURE' and o.name.endswith('.Rig')     and o is not rig_target]
        gest_sources = [o for o in wip_objs if o.type == 'ARMATURE' and o.name.endswith('.Gesture') and o is not gest_target]

        self._purge_bone_collection(context, rig_target,  bone_name, token=token)
        self._purge_bone_collection(context, gest_target, bone_name, token=token)

        self._join_into(context, rig_target,  rig_sources)
        self._join_into(context, gest_target, gest_sources)

        for arm_obj in (rig_target, gest_target):
            bpy.ops.object.select_all(action='DESELECT')
            arm_obj.select_set(True)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='EDIT')
            for eb in list(arm_obj.data.edit_bones):
                if token in eb.name:
                    arm_obj.data.edit_bones.remove(eb)
            bpy.ops.object.mode_set(mode='OBJECT')

        meta_prefix = f"{arm.name}-"
        for obj in list(bpy.data.objects):
            if obj.type != 'EMPTY' or not obj.name.endswith('-Alignment'):
                continue
            if not obj.name.startswith(meta_prefix):
                continue
            for child in list(obj.children):
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    child.hide_set(False)
                    child.select_set(True)
                    context.view_layer.objects.active = child
                    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
                except Exception:
                    pass
            for child in list(obj.children):
                mw           = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = mw
            bpy.data.objects.remove(obj, do_unlink=True)

        wip = bpy.data.collections.get(props.wip_coll)
        if wip and target_colls:
            gesture_splines_coll  = _ensure_child_coll(f"{meta_name}.GestureSplines",  target_colls[0])
            plotting_splines_coll = _ensure_child_coll(f"{meta_name}.PlottingSplines", target_colls[0])
            sample_coll           = _ensure_child_coll(f"{meta_name}.Mesh", target_colls[0])
            for obj in _all_objects(wip):
                if obj.type == 'CURVE':
                    target_coll = plotting_splines_coll if obj.name.endswith('.PlottingSpline') else gesture_splines_coll
                    _move_obj_to_coll(obj, target_coll)
                elif obj.type == 'MESH':
                    _move_obj_to_coll(obj, sample_coll)
                    chain = props.chains.get(bone_name)
                    if chain:
                        chain.sample_mesh = obj
            _delete_coll(wip)
            props.wip_coll = ''

        stale = 0
        for arm_obj in (rig_target, gest_target):
            if not arm_obj or arm_obj.type != 'ARMATURE':
                continue
            for pb in arm_obj.pose.bones:
                for con in pb.constraints:
                    target_ref = getattr(con, 'target', None)
                    if target_ref is not None:
                        try:
                            _ = target_ref.name
                        except ReferenceError:
                            con.target = None
                            stale += 1

        bpy.ops.object.select_all(action='DESELECT')
        stale_msg = f"  ({stale} stale constraint(s) cleared)" if stale else ""
        self.report({'INFO'}, f"Merged → '{rig_target.name}', '{gest_target.name}'.{stale_msg}")
        props.last_step      = self.bl_idname
        props.completed_step = 9
        return {'FINISHED'}


# ── STEP 10 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_MergeRigIntoMetaRig(bpy.types.Operator):
    bl_idname      = "gesturebone.merge_rig_into_metarig"
    bl_label       = "Merge .Rig into MetaRig"
    bl_description = "Redirect GN armature inputs from .Rig → MetaRig, then join and remove .Rig"
    bl_options     = {'REGISTER', 'UNDO'}

    def _rebind_gn_ref(self, mod, from_obj, to_obj):
        if not mod.node_group:
            return
        try:
            items = mod.node_group.interface.items_tree
        except AttributeError:
            return
        for item in items:
            if not hasattr(item, 'identifier'):
                continue
            if 'OUTPUT' in str(getattr(item, 'in_out', 'INPUT')):
                continue
            try:
                value = mod[item.identifier]
            except (KeyError, TypeError):
                continue
            if isinstance(value, bpy.types.Object) and value is from_obj:
                mod[item.identifier] = to_obj

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props    = arm.gesturebone_props
        rig_name = f"{arm.name}.Rig"
        rig_obj  = bpy.data.objects.get(rig_name)
        if not rig_obj:
            self.report({'ERROR'}, f"'{rig_name}' not found — run Steps 7-9 first")
            return {'CANCELLED'}
        _ensure_object_mode(context)
        arm.hide_set(False)
        for scene_obj in list(bpy.data.objects):
            for mod in scene_obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_ref(mod, rig_obj, arm)
                elif mod.type == 'ARMATURE' and mod.object is rig_obj:
                    mod.object = arm
        arm_colls = set(arm.users_collection)
        rig_colls = set(rig_obj.users_collection)
        if not (arm_colls & rig_colls):
            next(iter(arm_colls)).objects.link(rig_obj)
        bpy.ops.object.select_all(action='DESELECT')
        arm.select_set(True)
        rig_obj.select_set(True)
        context.view_layer.objects.active = arm
        bpy.ops.object.join()
        leftover = bpy.data.objects.get(rig_name)
        if leftover and leftover is not arm:
            bpy.data.objects.remove(leftover, do_unlink=True)
        self.report({'INFO'}, f"'{rig_name}' merged into '{arm.name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 10
        return {'FINISHED'}


# ── STEP 11 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RebindArmatureDeform(bpy.types.Operator):
    bl_idname      = "gesturebone.rebind_armature_deform"
    bl_label       = "Rebind Armature Deform"
    bl_description = "Re-parent skin meshes to MetaRig; rebind GN Deform Armature inputs; hide MetaRig"
    bl_options     = {'REGISTER', 'UNDO'}

    def _rebind_gn_to_final(self, mod, arm_obj):
        if not mod.node_group:
            return
        try:
            items = mod.node_group.interface.items_tree
        except AttributeError:
            return
        for item in items:
            if not hasattr(item, 'identifier'):
                continue
            if 'OUTPUT' in str(getattr(item, 'in_out', 'INPUT')):
                continue
            try:
                value = mod[item.identifier]
            except (KeyError, TypeError):
                continue
            if isinstance(value, bpy.types.Object):
                if value is not arm_obj and value.type == 'ARMATURE':
                    mod[item.identifier] = arm_obj
            elif value is None:
                name_lower = getattr(item, 'name', '').lower()
                if any(kw in name_lower for kw in ('armature', 'rig', 'deform')):
                    mod[item.identifier] = arm_obj

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}
        props = arm.gesturebone_props
        _ensure_object_mode(context)
        arm.hide_set(False)
        all_objs  = []
        for coll in arm.users_collection:
            all_objs.extend(_all_objects(coll))
        mesh_objs = [o for o in all_objs if o.type == 'MESH']
        token     = props.wip_token or props.atomic_chain
        count = skipped = 0
        for obj in mesh_objs:
            has_arm_mod = any(m.type == 'ARMATURE' for m in obj.modifiers)
            for mod in obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_to_final(mod, arm)
            if not has_arm_mod:
                continue
            for vg in list(obj.vertex_groups):
                if token in vg.name:
                    obj.vertex_groups.remove(vg)
            for mod in list(obj.modifiers):
                if mod.type == 'ARMATURE':
                    obj.modifiers.remove(mod)
            try:
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                arm.select_set(True)
                context.view_layer.objects.active = arm
                bpy.ops.object.parent_set(type='ARMATURE_NAME', keep_transform=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not bind '{obj.name}': {e}")
                skipped += 1
                continue
            arm_mods = [m for m in obj.modifiers if m.type == 'ARMATURE']
            for extra in arm_mods[1:]:
                obj.modifiers.remove(extra)
            count += 1
        arm.hide_set(True)
        msg = f"Bound {count} mesh(es) to '{arm.name}'. MetaRig hidden."
        if skipped:
            msg += f" ({skipped} skipped.)"
        self.report({'INFO'}, msg)
        props.last_step      = self.bl_idname
        props.completed_step = 11
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_DuplicateAtomicChain,
    GESTUREBONE_OT_RebindConstraintsGeonodes,
    GESTUREBONE_OT_RefreshRigs,
    GESTUREBONE_OT_RebindFinalArmatures,
    GESTUREBONE_OT_FinishMerging,
    GESTUREBONE_OT_MergeRigIntoMetaRig,
    GESTUREBONE_OT_RebindArmatureDeform,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
