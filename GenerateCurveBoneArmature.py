"""
GenerateCurveBoneArmature.py
Standalone Blender script — open in Scripting Editor and press Run Script.
Re-run after edits to reload. Panel appears in 3D View > Sidebar > GestureBone tab.
"""
import bpy
import math
import re
from mathutils import Matrix

# ─── CONSTANTS (override via UI after running) ────────────────────────────────
ATOMIC_CHAIN_COLL = "AtomicChain"
META_RIG_NAME     = "MetaRig"
META_BONE_COLL    = "MetaCollection"


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _p(context):
    return context.scene.gcba_props


def _meta_rig(props):
    return bpy.data.objects.get(props.meta_rig)


def _atomic_coll(props):
    return bpy.data.collections.get(props.atomic_chain)


def _rig_target_colls(props):
    arm = _meta_rig(props)
    return list(arm.users_collection) if arm else []


def _all_objects(coll):
    """Recursively collect all objects in a collection and its children."""
    objs = list(coll.objects)
    for child in coll.children:
        objs.extend(_all_objects(child))
    return objs


def _bones_in_bone_coll(arm_data, coll_name):
    """Return bone names belonging to a named bone collection (Blender 4+)."""
    bc = arm_data.collections.get(coll_name)
    if not bc:
        return []
    try:
        return [b.name for b in bc.bones]
    except AttributeError:
        result = []
        for b in arm_data.bones:
            try:
                if any(c.name == coll_name for c in b.collections):
                    result.append(b.name)
            except Exception:
                pass
        return result


def _deep_copy_coll(src, parent_coll):
    """Recursively duplicate a collection (objects + their data) under parent_coll."""
    dst = bpy.data.collections.new(src.name)
    parent_coll.children.link(dst)
    for obj in src.objects:
        new_obj      = obj.copy()
        new_obj.data = obj.data.copy() if obj.data else None
        dst.objects.link(new_obj)
    for child in src.children:
        _deep_copy_coll(child, dst)
    return dst


def _delete_coll(coll):
    """Recursively delete a collection and all its objects from bpy.data."""
    for child in list(coll.children):
        _delete_coll(child)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)


def _ensure_child_coll(name, parent_coll):
    """Find or create a named collection directly under parent_coll."""
    existing = parent_coll.children.get(name)
    if existing:
        return existing
    new_coll = bpy.data.collections.new(name)
    parent_coll.children.link(new_coll)
    return new_coll


def _move_obj_to_coll(obj, dst_coll):
    """Unlink obj from every collection it currently belongs to, then link to dst_coll."""
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    dst_coll.objects.link(obj)


def _ensure_object_mode(context):
    ao = context.active_object
    if ao and ao.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def _rename(s, bone_name):
    return s.replace('<PART>', bone_name)


# Strips Blender's auto-appended .001 / .002 … deduplication suffixes.
_BLENDER_SUFFIX = re.compile(r'(\.\d{3})+$')


def _clean(s, bone_name):
    """Strip .NNN suffix then replace <PART> with bone_name."""
    return _rename(_BLENDER_SUFFIX.sub('', s), bone_name)


def _rename_coll_tree(coll, bone_name):
    coll.name = _clean(coll.name, bone_name)
    for child in coll.children:
        _rename_coll_tree(child, bone_name)


def _metabone_items(self, context):
    if not context:
        return [('NONE', '(no context)', '')]
    props = _p(context)
    arm   = _meta_rig(props)
    if not arm or arm.type != 'ARMATURE':
        return [('NONE', 'MetaRig not found', '')]
    names = _bones_in_bone_coll(arm.data, props.meta_collection)
    return [(n, n, '') for n in names] if names else [('NONE', f'No bones in "{props.meta_collection}"', '')]


# ─── PROPERTY GROUP ───────────────────────────────────────────────────────────

class GCBA_PG_Props(bpy.types.PropertyGroup):
    atomic_chain:     bpy.props.StringProperty(name="Atomic Chain",    default=ATOMIC_CHAIN_COLL)
    meta_rig:         bpy.props.StringProperty(name="Meta Rig",        default=META_RIG_NAME)
    meta_collection:  bpy.props.StringProperty(name="Meta Collection", default=META_BONE_COLL)
    active_meta_bone: bpy.props.EnumProperty(  name="Meta Bone",       items=_metabone_items)
    wip_coll:         bpy.props.StringProperty(options={'HIDDEN'})
    wip_empty:        bpy.props.StringProperty(options={'HIDDEN'})
    last_step:        bpy.props.StringProperty(options={'HIDDEN'})


# ─── OPERATOR 1 ─ Duplicate and Rename Atomic Chain ─────────────────────────

class GCBA_OT_DuplicateAtomicChain(bpy.types.Operator):
    bl_idname  = "gcba.duplicate_atomic_chain"
    bl_label   = "Duplicate and Rename Atomic Chain"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        src = _atomic_coll(props)
        if not src:
            self.report({'ERROR'}, f"Collection '{props.atomic_chain}' not found")
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

        new_coll = _deep_copy_coll(src, target_colls[0])

        # ── Batch rename: strip .NNN suffix + replace <PART> with bone name ──
        count = 0
        for obj in _all_objects(new_coll):
            obj.name = _clean(obj.name, bone_name)
            if obj.data:
                obj.data.name = _clean(obj.data.name, bone_name)
            if obj.type == 'ARMATURE':
                bpy.ops.object.select_all(action='DESELECT')
                try:
                    obj.select_set(True)
                except Exception:
                    pass
                context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='EDIT')
                for eb in obj.data.edit_bones:
                    eb.name = _clean(eb.name, bone_name)
                bpy.ops.object.mode_set(mode='OBJECT')
                # Rename bone collections (e.g. <PART>_DEF → ArmR_DEF)
                for bc in obj.data.collections:
                    new_bc_name = _clean(bc.name, bone_name)
                    if new_bc_name != bc.name:
                        bc.name = new_bc_name
            count += 1

        _rename_coll_tree(new_coll, bone_name)
        props.wip_coll = new_coll.name

        self.report({'INFO'}, f"Duplicated '{src.name}' and renamed {count} objects (<PART> → '{bone_name}')")
        props.last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 2 ─ Rebind Constraints & Geonodes ──────────────────────────────

class GCBA_OT_RebindConstraintsGeonodes(bpy.types.Operator):
    bl_idname  = "gcba.rebind_constraints_geonodes"
    bl_label   = "Rebind Constraints & Geonodes"
    bl_options = {'REGISTER', 'UNDO'}

    def _fix_obj_ref(self, owner, attr, bone_name):
        """Redirect an Object pointer whose name contains <PART>."""
        ref = getattr(owner, attr, None)
        if ref and '<PART>' in ref.name:
            new_obj = bpy.data.objects.get(ref.name.replace('<PART>', bone_name))
            if new_obj:
                setattr(owner, attr, new_obj)

    def _fix_str(self, owner, attr, bone_name):
        """Replace <PART> inside a plain string attribute."""
        val = getattr(owner, attr, None)
        if isinstance(val, str) and '<PART>' in val:
            setattr(owner, attr, val.replace('<PART>', bone_name))

    def _rebind_constraint(self, con, bone_name):
        self._fix_obj_ref(con, 'target',      bone_name)
        self._fix_str    (con, 'subtarget',   bone_name)
        self._fix_obj_ref(con, 'pole_target', bone_name)

    def _rebind_gn_mod(self, mod, bone_name):
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
                if value and '<PART>' in value.name:
                    new_obj = bpy.data.objects.get(value.name.replace('<PART>', bone_name))
                    if new_obj:
                        mod[item.identifier] = new_obj
            elif isinstance(value, str) and '<PART>' in value:
                mod[item.identifier] = value.replace('<PART>', bone_name)

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        wip = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection — run Step 1 first")
            return {'CANCELLED'}

        for obj in _all_objects(wip):
            # Object-level constraints
            for con in obj.constraints:
                self._rebind_constraint(con, bone_name)
            # Geometry Node modifiers
            for mod in obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_mod(mod, bone_name)
            # Pose bone constraints (armatures only)
            if obj.type == 'ARMATURE':
                for pb in obj.pose.bones:
                    for con in pb.constraints:
                        self._rebind_constraint(con, bone_name)

        self.report({'INFO'}, f"Rebound constraints & geonodes in '{wip.name}'")
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 3 ─ Transform Atomic Chain ─────────────────────────────────────

class GCBA_OT_TransformAtomicChain(bpy.types.Operator):
    bl_idname  = "gcba.transform_atomic_chain"
    bl_label   = "Transform Atomic Chain"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _p(context)
        wip   = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection — run Step 1 first")
            return {'CANCELLED'}

        objects = _all_objects(wip)
        if not objects:
            self.report({'WARNING'}, "Working collection is empty")
            return {'FINISHED'}

        _ensure_object_mode(context)

        rot     = Matrix.Rotation(math.radians(90), 4, 'Z')
        skipped = []

        for obj in objects:
            # Clear all transform locks so transform_apply cannot be blocked
            obj.lock_location = (False, False, False)
            obj.lock_rotation = (False, False, False)
            obj.lock_scale    = (False, False, False)
            if hasattr(obj, 'lock_rotation_w'):
                obj.lock_rotation_w = False
            obj.matrix_world = rot @ obj.matrix_world

        # Apply per-object individually so a single invisible object cannot
        # silently block the rest of the batch
        for obj in objects:
            bpy.ops.object.select_all(action='DESELECT')
            try:
                obj.select_set(True)
                context.view_layer.objects.active = obj
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            except Exception as e:
                skipped.append(f"{obj.name} ({e})")

        bpy.ops.object.select_all(action='DESELECT')
        msg = f"Rotated 90° Z, applied transforms on {len(objects) - len(skipped)} objects"
        if skipped:
            msg += f" — skipped: {', '.join(skipped)}"
        self.report({'INFO'}, msg)
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 3 ─ Parent to Empty ────────────────────────────────────────────

class GCBA_OT_ParentToEmpty(bpy.types.Operator):
    bl_idname  = "gcba.parent_to_empty"
    bl_label   = "Parent to Empty"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _p(context)
        wip   = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection — run Step 1 first")
            return {'CANCELLED'}

        target_colls = _rig_target_colls(props)
        if not target_colls:
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        _ensure_object_mode(context)

        old_empty = bpy.data.objects.get(props.wip_empty)
        if old_empty:
            bpy.data.objects.remove(old_empty, do_unlink=True)

        empty                    = bpy.data.objects.new("Alignment_<PART>", None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.1
        target_colls[0].objects.link(empty)
        props.wip_empty = empty.name

        objects = _all_objects(wip)
        for obj in objects:
            obj.parent                  = empty
            obj.matrix_parent_inverse   = Matrix.Identity(4)

        self.report({'INFO'}, f"Created '{empty.name}', parented {len(objects)} objects under it")
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 4 ─ Align <PART> to Bone ───────────────────────────────────────

class GCBA_OT_AlignPartToBone(bpy.types.Operator):
    bl_idname  = "gcba.align_part_to_bone"
    bl_label   = "Align <PART> to Bone"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from mathutils import Vector

        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found or not an armature")
            return {'CANCELLED'}

        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment Empty not found — run Step 2 first")
            return {'CANCELLED'}

        # ── 3a: Set MetaBone roll = 0 permanently ────────────────────────
        arm_obj.hide_set(False)   # unhide in case Step 9 hid it
        _ensure_object_mode(context)
        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm_obj.data.edit_bones.get(bone_name)
        if not eb:
            bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'ERROR'}, f"Edit bone '{bone_name}' not found in MetaRig")
            return {'CANCELLED'}
        eb.roll = 0.0
        bpy.ops.object.mode_set(mode='OBJECT')

        # ── 3b: Align empty to bone world matrix ─────────────────────────
        pose_bone = arm_obj.pose.bones.get(bone_name)
        if not pose_bone:
            self.report({'ERROR'}, f"Bone '{bone_name}' not found in MetaRig pose")
            return {'CANCELLED'}
        world_mat = arm_obj.matrix_world @ pose_bone.matrix

        # ── 3c: Bone world-space length → uniform scale on the empty ─────
        data_bone   = arm_obj.data.bones.get(bone_name)
        head_world  = arm_obj.matrix_world @ Vector(data_bone.head_local)
        tail_world  = arm_obj.matrix_world @ Vector(data_bone.tail_local)
        bone_length = (tail_world - head_world).length

        loc, rot, _ = world_mat.decompose()
        empty_obj.matrix_world = Matrix.LocRotScale(loc, rot, Vector((bone_length,) * 3))

        self.report({'INFO'}, f"Aligned '{empty_obj.name}' to '{bone_name}' (length={bone_length:.4f})")
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 6 ─ Refresh Gesture & Plot Rigs ────────────────────────────────

class GCBA_OT_RefreshRigs(bpy.types.Operator):
    bl_idname  = "gcba.refresh_rigs"
    bl_label   = "Refresh Gesture & Plot Rigs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props    = _p(context)
        arm_obj  = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found or not an armature")
            return {'CANCELLED'}

        rig_name     = f"{arm_obj.name}.Rig"
        gesture_name = f"{arm_obj.name}.Gesture"
        target_colls = _rig_target_colls(props)

        _ensure_object_mode(context)

        # ── <MetaRig>.Rig — create only on first iteration ───────────────
        # If it already exists (bones accumulated from prior MetaBone merges),
        # leave it untouched so Step 8 can keep joining into it.
        rig_obj = bpy.data.objects.get(rig_name)
        if not rig_obj:
            rig_obj      = arm_obj.copy()
            rig_obj.data = arm_obj.data.copy()
            rig_obj.name = rig_name
            rig_obj.data.name = rig_name
            for coll in target_colls:
                coll.objects.link(rig_obj)

            bpy.ops.object.select_all(action='DESELECT')
            rig_obj.select_set(True)
            context.view_layer.objects.active = rig_obj
            bpy.ops.object.mode_set(mode='EDIT')
            for bname in _bones_in_bone_coll(arm_obj.data, props.meta_collection):
                eb = rig_obj.data.edit_bones.get(bname)
                if eb:
                    rig_obj.data.edit_bones.remove(eb)
            for eb in list(rig_obj.data.edit_bones):
                if '<PART>' in eb.name:
                    rig_obj.data.edit_bones.remove(eb)
            bpy.ops.object.mode_set(mode='OBJECT')

        # ── <MetaRig>.Gesture — create only on first iteration ───────────
        gesture_obj = bpy.data.objects.get(gesture_name)
        if not gesture_obj:
            gesture_data = bpy.data.armatures.new(gesture_name)
            gesture_obj  = bpy.data.objects.new(gesture_name, gesture_data)
            for coll in target_colls:
                coll.objects.link(gesture_obj)

        self.report({'INFO'}, f"'{rig_name}' and '{gesture_name}' ready (created if missing)")
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 7 ─ Rebind Final Armatures ─────────────────────────────────────

class GCBA_OT_RebindFinalArmatures(bpy.types.Operator):
    bl_idname  = "gcba.rebind_final_armatures"
    bl_label   = "Rebind Final Armatures"
    bl_options = {'REGISTER', 'UNDO'}

    def _redirect(self, ref, gest_target, rig_target):
        """Return the correct final armature if ref needs redirecting, else None."""
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
            self.report({'ERROR'}, "Run Step 6 (Refresh Gesture & Plot Rigs) first")
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

        self.report({'INFO'}, f"Rebound armature refs → '{gest_target.name}' / '{rig_target.name}'")
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 8 ─ Merge & Clean Empty ────────────────────────────────────────

class GCBA_OT_FinishMerging(bpy.types.Operator):
    bl_idname  = "gcba.finish_merging"
    bl_label   = "Merge & Clean Empty"
    bl_options = {'REGISTER', 'UNDO'}

    def _join_into(self, context, target, sources):
        if not sources:
            return
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
        props      = _p(context)
        meta_name  = props.meta_rig
        rig_target = bpy.data.objects.get(f"{meta_name}.Rig")
        gest_target = bpy.data.objects.get(f"{meta_name}.Gesture")

        if not rig_target or not gest_target:
            self.report({'ERROR'}, "Run Step 6 (Refresh Gesture & Plot Rigs) first")
            return {'CANCELLED'}

        target_colls = _rig_target_colls(props)
        _ensure_object_mode(context)

        # Scope to wip_coll only — prevents orphan template armatures
        # (e.g. <PART>.Rig not in any collection) from being accidentally joined.
        wip = bpy.data.collections.get(props.wip_coll)
        wip_objs = set(_all_objects(wip)) if wip else set()

        rig_sources = [
            o for o in wip_objs
            if o.type == 'ARMATURE' and o.name.endswith('.Rig') and o is not rig_target
        ]
        gest_sources = [
            o for o in wip_objs
            if o.type == 'ARMATURE' and o.name.endswith('.Gesture') and o is not gest_target
        ]

        self._join_into(context, rig_target,  rig_sources)
        self._join_into(context, gest_target, gest_sources)

        # Scrub any leftover <PART> template bones from both merged armatures
        for arm_obj in (rig_target, gest_target):
            bpy.ops.object.select_all(action='DESELECT')
            arm_obj.select_set(True)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='EDIT')
            for eb in list(arm_obj.data.edit_bones):
                if '<PART>' in eb.name:
                    arm_obj.data.edit_bones.remove(eb)
            bpy.ops.object.mode_set(mode='OBJECT')

        # Delete Alignment empties, keep their children in world position
        for obj in list(bpy.data.objects):
            if obj.type == 'EMPTY' and obj.name.startswith('Alignment_'):
                for child in list(obj.children):
                    mw          = child.matrix_world.copy()
                    child.parent = None
                    child.matrix_world = mw
                bpy.data.objects.remove(obj, do_unlink=True)

        # ── Move curves → Splines, meshes → SampleMesh, delete wip_coll ──
        wip = bpy.data.collections.get(props.wip_coll)
        if wip and target_colls:
            splines_coll = _ensure_child_coll("Splines",    target_colls[0])
            sample_coll  = _ensure_child_coll("SampleMesh", target_colls[0])
            for obj in _all_objects(wip):
                if obj.type == 'CURVE':
                    _move_obj_to_coll(obj, splines_coll)
                elif obj.type == 'MESH':
                    _move_obj_to_coll(obj, sample_coll)
            _delete_coll(wip)
            props.wip_coll = ''

        bpy.ops.object.select_all(action='DESELECT')
        self.report({'INFO'},
            f"Joined {len(rig_sources)} → '{rig_target.name}', "
            f"{len(gest_sources)} → '{gest_target.name}'. "
            f"Empties deleted. Curves → Splines, Meshes → SampleMesh.")
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── OPERATOR 9 ─ Rebind Armature Deform ─────────────────────────────────────

class GCBA_OT_RebindArmatureDeform(bpy.types.Operator):
    bl_idname  = "gcba.rebind_armature_deform"
    bl_label   = "Rebind Armature Deform"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _p(context)
        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found or not an armature")
            return {'CANCELLED'}

        rig_target = bpy.data.objects.get(f"{arm_obj.name}.Rig")
        if not rig_target:
            self.report({'ERROR'}, f"'{arm_obj.name}.Rig' not found — run Steps 6–8 first")
            return {'CANCELLED'}

        _ensure_object_mode(context)

        # Gather all mesh objects in MetaRig's collections (recursive)
        all_objs = []
        for coll in arm_obj.users_collection:
            all_objs.extend(_all_objects(coll))
        mesh_objs = [o for o in all_objs if o.type == 'MESH']

        count   = 0
        skipped = 0
        for obj in mesh_objs:
            has_arm_mod = any(m.type == 'ARMATURE' for m in obj.modifiers)
            if not has_arm_mod:
                continue  # no armature modifier — skip

            # Remove <PART> vertex groups
            for vg in list(obj.vertex_groups):
                if '<PART>' in vg.name:
                    obj.vertex_groups.remove(vg)

            # Remove ALL existing Armature modifiers — parent_set will add a fresh one
            for mod in list(obj.modifiers):
                if mod.type == 'ARMATURE':
                    obj.modifiers.remove(mod)

            # "Armature Deform > With Empty Groups": adds modifier + creates per-bone vertex groups
            try:
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                rig_target.select_set(True)
                context.view_layer.objects.active = rig_target
                bpy.ops.object.parent_set(type='ARMATURE_NAME', keep_transform=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not bind '{obj.name}': {e}")
                skipped += 1
                continue

            # Safety check: remove duplicates if parent_set added more than one
            arm_mods = [m for m in obj.modifiers if m.type == 'ARMATURE']
            for extra in arm_mods[1:]:
                obj.modifiers.remove(extra)

            count += 1

        # Hide MetaRig
        arm_obj.hide_set(True)

        msg = f"Bound {count} mesh(es) to '{rig_target.name}' with empty groups. MetaRig hidden."
        if skipped:
            msg += f" ({skipped} skipped — check warnings)."
        self.report({'INFO'}, msg)
        _p(context).last_step = self.bl_idname
        return {'FINISHED'}


# ─── PANEL HELPER ────────────────────────────────────────────────────────────

def _step(col, props, idname, icon, description):
    """Draw one workflow button + a compact description line below it."""
    col.operator(idname, icon=icon, depress=props.last_step == idname)
    sub = col.column()
    sub.scale_y = 0.55
    sub.label(text=f"  {description}")


# ─── PANEL ───────────────────────────────────────────────────────────────────

class GCBA_PT_Panel(bpy.types.Panel):
    bl_label       = "Generate Curve Bone Armature"
    bl_idname      = "GCBA_PT_main"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_order       = 1

    def draw(self, context):
        layout = self.layout
        props  = _p(context)

        # ── Section 1: Registration ──────────────────────────────────────
        box = layout.box()
        box.label(text="Registration", icon='PROPERTIES')
        col = box.column(align=True)
        col.prop(props, "atomic_chain")
        col.prop(props, "meta_rig")
        col.prop(props, "meta_collection")

        layout.separator()

        # ── Section 2: Generate Rig ──────────────────────────────────────
        box = layout.box()
        box.label(text="Generate Rig", icon='ARMATURE_DATA')
        col = box.column(align=False)
        col.prop(props, "active_meta_bone", text="MetaBone")
        col.separator()
        _step(col, props, "gcba.duplicate_atomic_chain",      'MOD_THICKNESS',         "Copy template, rename <PART> → bone name")
        _step(col, props, "gcba.rebind_constraints_geonodes", 'CON_SPLINEIK',          "Fix constraint targets & GN socket inputs")
        _step(col, props, "gcba.transform_atomic_chain",      'PIVOT_CURSOR',          "Rotate 90° Z then apply all transforms")
        _step(col, props, "gcba.parent_to_empty",             'ORIENTATION_CURSOR',    "Group all objects under an alignment empty")
        _step(col, props, "gcba.align_part_to_bone",          'MOD_SIMPLIFY',          "Snap empty to MetaBone world pos & length")
        _step(col, props, "gcba.refresh_rigs",                'CON_ROTLIKE',           "Create .Rig and .Gesture armatures if missing")
        _step(col, props, "gcba.rebind_final_armatures",      'OUTLINER_OB_ARMATURE',  "Point .Rig/.Gesture refs to merged targets")
        _step(col, props, "gcba.finish_merging",              'OUTLINER_DATA_ARMATURE',"Join arms, sort curves/meshes, delete empties")
        col.separator()
        _step(col, props, "gcba.rebind_armature_deform",      'MOD_ARMATURE',          "Bind skin meshes to .Rig, hide MetaRig")


# ─── REGISTER / UNREGISTER ────────────────────────────────────────────────────

_classes = [
    GCBA_PG_Props,
    GCBA_OT_DuplicateAtomicChain,
    GCBA_OT_RebindConstraintsGeonodes,
    GCBA_OT_TransformAtomicChain,
    GCBA_OT_ParentToEmpty,
    GCBA_OT_AlignPartToBone,
    GCBA_OT_RefreshRigs,
    GCBA_OT_RebindFinalArmatures,
    GCBA_OT_FinishMerging,
    GCBA_OT_RebindArmatureDeform,
    GCBA_PT_Panel,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gcba_props = bpy.props.PointerProperty(type=GCBA_PG_Props)


def unregister():
    del bpy.types.Scene.gcba_props
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()
