"""
ops_steps.py — Steps 1, 2, 7, 8, 9, 10, 11: main workflow operators.
"""
import bpy
from .utils import (
    _p, _meta_rig, _atomic_coll, _rig_target_colls, _all_objects,
    _bones_in_bone_coll, _deep_copy_coll, _delete_coll, _ensure_child_coll,
    _move_obj_to_coll, _ensure_object_mode, _clean, _rename_coll_tree,
    _all_bone_colls,
)


# ─── STEP 1 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_DuplicateAtomicChain(bpy.types.Operator):
    bl_idname      = "gesturebone.duplicate_atomic_chain"
    bl_label       = "Duplicate and Rename"
    bl_description = "Copy the template collection and rename every token to the selected MetaBone name"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _p(context)
        props.completed_step = 0

        bone_name     = props.active_meta_bone
        meta_rig_name = props.meta_rig

        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        # Resolve template: per-bone setting overrides the global Registration template
        entry      = props.bone_settings.get(bone_name)
        per_bone   = getattr(entry, 'atomic_chain', 'NONE') if entry else 'NONE'
        token      = per_bone if (per_bone and per_bone != 'NONE') else props.atomic_chain
        props.wip_token = token   # store so Steps 2-9 use the same token without re-reading

        if not token or token == 'NONE':
            self.report({'ERROR'}, "No template selected — set one in Registration or per-bone")
            return {'CANCELLED'}

        src = _atomic_coll(props)   # now reads wip_token
        if not src:
            self.report({'ERROR'}, f"Template collection '{token}' not found")
            return {'CANCELLED'}

        target_colls = _rig_target_colls(props)
        if not target_colls:
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found or not in any collection")
            return {'CANCELLED'}

        _ensure_object_mode(context)

        existing = bpy.data.collections.get(props.wip_coll)
        if existing:
            _delete_coll(existing)
        props.wip_coll  = ''
        props.wip_empty = ''

        # Pre-delete any objects whose target name would conflict (prevents .001 duplicates)
        template_obj_set = set(_all_objects(src))
        for template_obj in template_obj_set:
            target_name = f"{meta_rig_name}-{_clean(template_obj.name, token, bone_name)}"
            conflict = bpy.data.objects.get(target_name)
            if conflict and conflict not in template_obj_set:
                bpy.data.objects.remove(conflict, do_unlink=True)

        new_coll = _deep_copy_coll(src, target_colls[0])

        count = 0
        for obj in _all_objects(new_coll):
            # Object & data names get <RigName>- prefix + token→bone_name substitution
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
                    eb.name = _clean(eb.name, token, bone_name)  # no prefix for bone names
                bpy.ops.object.mode_set(mode='OBJECT')
                # Rename ALL bone collections including nested children
                for bc in _all_bone_colls(obj.data):
                    new_bc_name = _clean(bc.name, token, bone_name)  # no prefix for bone collections
                    if new_bc_name != bc.name:
                        bc.name = new_bc_name
            count += 1

        _rename_coll_tree(new_coll, token, bone_name)
        props.wip_coll = new_coll.name

        # Alignment empty now has the RigName prefix too
        alignment_name = f"{meta_rig_name}-{bone_name}-Alignment"
        for obj in _all_objects(new_coll):
            if obj.type == 'EMPTY' and obj.name == alignment_name:
                props.wip_empty = obj.name
                break
        if not props.wip_empty:
            self.report({'ERROR'},
                f"'{alignment_name}' empty not found in template -- "
                "ensure your template has a '<TOKEN>-Alignment' empty")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Duplicated '{src.name}' -> {count} objects renamed ('{token}' -> '{meta_rig_name}-{bone_name}')")
        props.last_step      = self.bl_idname
        props.completed_step = 1
        return {'FINISHED'}


# ─── STEP 2 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RebindConstraintsGeonodes(bpy.types.Operator):
    bl_idname      = "gesturebone.rebind_constraints_geonodes"
    bl_label       = "Rebind Constraints & Geonodes"
    bl_description = "Fix constraint targets and Geometry Node socket inputs still pointing to template token objects"
    bl_options     = {'REGISTER', 'UNDO'}

    def _fix_obj_ref(self, owner, attr, token, bone_name, meta_rig_name):
        ref = getattr(owner, attr, None)
        if ref and token in ref.name:
            # Try <RigName>- prefixed name first (objects renamed in Step 1)
            new_obj = bpy.data.objects.get(f"{meta_rig_name}-{_clean(ref.name, token, bone_name)}")
            if not new_obj:
                # Fall back to unprefixed form (older template style)
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
                # Try <RigName>- prefixed name first (objects renamed in Step 1)
                new_obj = bpy.data.objects.get(f"{meta_rig_name}-{_clean(value.name, token, bone_name)}")
                if not new_obj:
                    new_obj = bpy.data.objects.get(value.name.replace(token, bone_name))
                if new_obj:
                    mod[item.identifier] = new_obj
            elif isinstance(value, str) and token in value:
                mod[item.identifier] = value.replace(token, bone_name)

    def execute(self, context):
        props         = _p(context)
        bone_name     = props.active_meta_bone
        token         = props.wip_token or props.atomic_chain
        meta_rig_name = props.meta_rig

        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        wip = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection -- run Step 1 first")
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


# ─── STEP 7 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RefreshRigs(bpy.types.Operator):
    bl_idname      = "gesturebone.refresh_rigs"
    bl_label       = "Refresh Gesture & Plot Rigs"
    bl_description = "Create MetaRig.Rig and MetaRig.Gesture armatures if missing; strip stale bones for the active MetaBone"
    bl_options     = {'REGISTER', 'UNDO'}

    def _strip_bones(self, context, arm_target, meta_arm, meta_coll_name, token, bone_name):
        """Enter edit mode on arm_target and remove:
        - All bones already in MetaRig (META collection + previously merged rounds)
        - Token-named bones (template placeholder leftovers)
        - bone_name bones (stale bones from a previous run of this same part)

        The key fix for round 2+: when .Rig is recreated as a MetaRig copy it
        inherits all previously-merged bones (e.g. Arms in round 2). Those must
        be stripped here or Step 10 will double-merge them into MetaRig.
        """
        # Collect every bone name currently in MetaRig — this covers both
        # META-collection bones and any bones merged in previous rounds.
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
        props     = _p(context)
        arm_obj   = _meta_rig(props)
        bone_name = props.active_meta_bone
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        rig_name     = f"{arm_obj.name}.Rig"
        gesture_name = f"{arm_obj.name}.Gesture"
        target_colls = _rig_target_colls(props)
        token        = props.wip_token or props.atomic_chain
        _ensure_object_mode(context)

        # .Rig: create if missing, then always strip stale bones
        rig_obj = bpy.data.objects.get(rig_name)
        if not rig_obj:
            rig_obj           = arm_obj.copy()
            rig_obj.data      = arm_obj.data.copy()
            rig_obj.name      = rig_name
            rig_obj.data.name = rig_name
            for coll in target_colls:
                coll.objects.link(rig_obj)

        self._strip_bones(context, rig_obj, arm_obj, props.meta_collection, token, bone_name)

        # .Gesture: create if missing; strip stale bones if it already exists
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


# ─── STEP 8 ───────────────────────────────────────────────────────────────────

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
        props       = _p(context)
        meta_name   = props.meta_rig
        gest_target = bpy.data.objects.get(f"{meta_name}.Gesture")
        rig_target  = bpy.data.objects.get(f"{meta_name}.Rig")

        if not gest_target or not rig_target:
            self.report({'ERROR'}, "Run Step 7 (Refresh Gesture & Plot Rigs) first")
            return {'CANCELLED'}

        wip = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection -- run Step 1 first")
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

        self.report({'INFO'}, f"Rebound -> '{gest_target.name}' / '{rig_target.name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 8
        return {'FINISHED'}


# ─── STEP 9 ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_FinishMerging(bpy.types.Operator):
    bl_idname      = "gesturebone.finish_merging"
    bl_label       = "Merge & Clean"
    bl_description = (
        "Join working armatures into .Rig/.Gesture, apply transforms to all objects, "
        "move curves to Splines, meshes to SampleMesh, delete DUPLICATED alignment empties"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def _purge_bone_collection(self, context, target, bone_name, token=''):
        """Delete all bone collections (and their bones) whose name contains bone_name or token.

        Uses _all_bone_colls() to catch nested children that arm_data.collections skips.
        Also matches 'token' (the template placeholder, e.g. '<PART>') so MetaRig-copy
        collections inherited from the source armature are cleaned up before merging.
        """
        if not target or not bone_name or bone_name == 'NONE':
            return
        if not target.users_collection:
            context.scene.collection.objects.link(target)

        # Walk ALL collections including nested children
        all_bc  = _all_bone_colls(target.data)
        to_purge = [
            bc for bc in all_bc
            if (bone_name in bc.name) or (token and token in bc.name)
        ]
        if not to_purge:
            return

        # Collect all bones assigned to these collections
        bones_to_delete = set()
        for bc in to_purge:
            try:
                for b in bc.bones:
                    bones_to_delete.add(b.name)
            except Exception:
                pass

        # Delete bones in edit mode
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

        # Remove the now-empty bone collections (nested ones too)
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
        props       = _p(context)
        meta_name   = props.meta_rig
        bone_name   = props.active_meta_bone
        rig_target  = bpy.data.objects.get(f"{meta_name}.Rig")
        gest_target = bpy.data.objects.get(f"{meta_name}.Gesture")

        if not rig_target or not gest_target:
            self.report({'ERROR'}, "Run Step 7 first")
            return {'CANCELLED'}

        target_colls = _rig_target_colls(props)
        token        = props.wip_token or props.atomic_chain
        _ensure_object_mode(context)

        wip      = bpy.data.collections.get(props.wip_coll)
        wip_objs = set(_all_objects(wip)) if wip else set()

        rig_sources = [
            o for o in wip_objs
            if o.type == 'ARMATURE' and o.name.endswith('.Rig') and o is not rig_target
        ]
        gest_sources = [
            o for o in wip_objs
            if o.type == 'ARMATURE' and o.name.endswith('.Gesture') and o is not gest_target
        ]

        # Purge stale bone collections BEFORE joining (also clears MetaRig-copy <PART>_* collections)
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

        meta_prefix = f"{props.meta_rig}-"
        for obj in list(bpy.data.objects):
            if obj.type != 'EMPTY' or not obj.name.endswith('-Alignment'):
                continue
            if not obj.name.startswith(meta_prefix):
                continue  # template or foreign empty — never touch it
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
            sample_coll           = _ensure_child_coll("SampleMesh", target_colls[0])
            for obj in _all_objects(wip):
                if obj.type == 'CURVE':
                    if obj.name.endswith('.PlottingSpline'):
                        _move_obj_to_coll(obj, plotting_splines_coll)
                    else:
                        _move_obj_to_coll(obj, gesture_splines_coll)
                elif obj.type == 'MESH':
                    _move_obj_to_coll(obj, sample_coll)
            _delete_coll(wip)
            props.wip_coll = ''

        # Post-merge validation: sweep merged armatures for null/stale constraint targets
        stale = 0
        for arm_obj in (rig_target, gest_target):
            if not arm_obj or arm_obj.type != 'ARMATURE':
                continue
            for pb in arm_obj.pose.bones:
                for con in pb.constraints:
                    target_ref = getattr(con, 'target', None)
                    if target_ref is not None:
                        # If object was removed (WIP copy), Blender returns None on access
                        try:
                            _ = target_ref.name
                        except ReferenceError:
                            con.target = None
                            stale += 1

        bpy.ops.object.select_all(action='DESELECT')
        stale_msg = f"  ({stale} stale constraint(s) cleared)" if stale else ""
        self.report({'INFO'},
            f"Joined {len(rig_sources)} -> '{rig_target.name}', "
            f"{len(gest_sources)} -> '{gest_target.name}'. "
            f"Curves -> Splines, Meshes -> SampleMesh.{stale_msg}")
        props.last_step      = self.bl_idname
        props.completed_step = 9
        return {'FINISHED'}


# ─── STEP 10 ──────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_MergeRigIntoMetaRig(bpy.types.Operator):
    bl_idname      = "gesturebone.merge_rig_into_metarig"
    bl_label       = "Merge .Rig into MetaRig"
    bl_description = (
        "Redirect all GN armature inputs from .Rig -> MetaRig, "
        "then join .Rig bones into MetaRig and remove the .Rig object"
    )
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
        props   = _p(context)
        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        rig_name = f"{arm_obj.name}.Rig"
        rig_obj  = bpy.data.objects.get(rig_name)
        if not rig_obj:
            self.report({'ERROR'}, f"'{rig_name}' not found -- run Steps 7-9 first")
            return {'CANCELLED'}

        _ensure_object_mode(context)
        arm_obj.hide_set(False)

        for scene_obj in list(bpy.data.objects):
            for mod in scene_obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_ref(mod, rig_obj, arm_obj)
                elif mod.type == 'ARMATURE' and mod.object is rig_obj:
                    mod.object = arm_obj

        arm_colls = set(arm_obj.users_collection)
        rig_colls = set(rig_obj.users_collection)
        if not (arm_colls & rig_colls):
            next(iter(arm_colls)).objects.link(rig_obj)

        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        rig_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.join()

        leftover = bpy.data.objects.get(rig_name)
        if leftover and leftover is not arm_obj:
            bpy.data.objects.remove(leftover, do_unlink=True)

        self.report({'INFO'}, f"'{rig_name}' merged into '{arm_obj.name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 10
        return {'FINISHED'}


# ─── STEP 11 ──────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RebindArmatureDeform(bpy.types.Operator):
    bl_idname      = "gesturebone.rebind_armature_deform"
    bl_label       = "Rebind Armature Deform"
    bl_description = (
        "Re-parent skin meshes to MetaRig with empty vertex groups; "
        "also rebind GN 'Deform Armature' inputs to MetaRig. Then hide MetaRig"
    )
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
        props   = _p(context)
        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        _ensure_object_mode(context)
        arm_obj.hide_set(False)

        all_objs = []
        for coll in arm_obj.users_collection:
            all_objs.extend(_all_objects(coll))
        mesh_objs = [o for o in all_objs if o.type == 'MESH']

        token   = props.wip_token or props.atomic_chain
        count   = 0
        skipped = 0
        for obj in mesh_objs:
            has_arm_mod = any(m.type == 'ARMATURE' for m in obj.modifiers)

            for mod in obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_to_final(mod, arm_obj)

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
                arm_obj.select_set(True)
                context.view_layer.objects.active = arm_obj
                bpy.ops.object.parent_set(type='ARMATURE_NAME', keep_transform=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not bind '{obj.name}': {e}")
                skipped += 1
                continue

            arm_mods = [m for m in obj.modifiers if m.type == 'ARMATURE']
            for extra in arm_mods[1:]:
                obj.modifiers.remove(extra)
            count += 1

        arm_obj.hide_set(True)

        msg = f"Bound {count} mesh(es) to '{arm_obj.name}'. MetaRig hidden."
        if skipped:
            msg += f" ({skipped} skipped.)"
        self.report({'INFO'}, msg)
        props.last_step      = self.bl_idname
        props.completed_step = 11
        return {'FINISHED'}


# ─── REGISTER ─────────────────────────────────────────────────────────────────

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
