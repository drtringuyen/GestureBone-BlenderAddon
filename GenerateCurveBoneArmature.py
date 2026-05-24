"""
GenerateCurveBoneArmature.py
Standalone Blender script — open in Scripting Editor and press Run Script.
Re-run after edits to reload. Panel appears in 3D View > Sidebar > GestureBone tab.
"""
import bpy
import re
from mathutils import Matrix, Vector

# ─── ALIGNMENT HANDLER STATE ───────────────────────────────────────────────────
_ALIGN_STATE = {}   # keys: 'arm', 'bone', 'empty'


def _alignment_scale_handler(scene, depsgraph):
    """
    depsgraph_update_post: keeps the alignment empty's scale equal to the
    active MetaBone's CURRENT world-space length (live during pose adjustment).
    Only fires when an OBJECT is updated.
    """
    if not _ALIGN_STATE:
        return
    if not depsgraph.id_type_updated('OBJECT'):
        return
    try:
        empty_obj = bpy.data.objects.get(_ALIGN_STATE['empty'])
        arm_obj   = bpy.data.objects.get(_ALIGN_STATE['arm'])
        bone_name = _ALIGN_STATE['bone']
        if not empty_obj or not arm_obj:
            return
        arm_eval = arm_obj.evaluated_get(depsgraph)
        pb = arm_eval.pose.bones.get(bone_name)
        if not pb:
            return
        head_w = arm_eval.matrix_world @ pb.head
        tail_w = arm_eval.matrix_world @ pb.tail
        length = (tail_w - head_w).length
        if abs(empty_obj.scale[0] - length) > 1e-6:
            empty_obj.scale = (length, length, length)
    except Exception:
        pass


def _register_align_handler():
    if _alignment_scale_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_alignment_scale_handler)


def _unregister_align_handler():
    if _alignment_scale_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_alignment_scale_handler)


# ─── HELPERS ──────────────────────────────────────────────────────────────────

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
    objs = list(coll.objects)
    for child in coll.children:
        objs.extend(_all_objects(child))
    return objs


def _bones_in_bone_coll(arm_data, coll_name):
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


def _copy_coll_tree(src, parent_coll, obj_map):
    dst = bpy.data.collections.new(src.name)
    parent_coll.children.link(dst)
    for obj in src.objects:
        new_obj      = obj.copy()
        new_obj.data = obj.data.copy() if obj.data else None
        dst.objects.link(new_obj)
        obj_map[obj] = new_obj
    for child in src.children:
        _copy_coll_tree(child, dst, obj_map)
    return dst


def _deep_copy_coll(src, parent_coll):
    """Copy collection and re-wire internal parent-child relationships."""
    obj_map = {}
    dst = _copy_coll_tree(src, parent_coll, obj_map)
    for orig, copy in obj_map.items():
        if orig.parent and orig.parent in obj_map:
            copy.parent = obj_map[orig.parent]
            copy.matrix_parent_inverse = orig.matrix_parent_inverse.copy()
    return dst


def _delete_coll(coll):
    for child in list(coll.children):
        _delete_coll(child)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)


def _ensure_child_coll(name, parent_coll):
    existing = parent_coll.children.get(name)
    if existing:
        return existing
    new_coll = bpy.data.collections.new(name)
    parent_coll.children.link(new_coll)
    return new_coll


def _move_obj_to_coll(obj, dst_coll):
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    dst_coll.objects.link(obj)


def _ensure_object_mode(context):
    ao = context.active_object
    if ao and ao.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


_BLENDER_SUFFIX = re.compile(r'(\.\d{3})+$')


def _clean(s, token, bone_name):
    return _BLENDER_SUFFIX.sub('', s).replace(token, bone_name)


def _rename_coll_tree(coll, token, bone_name):
    coll.name = _clean(coll.name, token, bone_name)
    for child in coll.children:
        _rename_coll_tree(child, token, bone_name)


# ─── ENUM ITEM CALLBACKS ───────────────────────────────────────────────────────

def _collection_items(self, context):
    if not context:
        return [('NONE', '(no context)', '')]
    items = [(c.name, c.name, '') for c in bpy.data.collections]
    return items if items else [('NONE', 'No collections found', '')]


# ── StringProperty search callbacks (stable — unaffected by new objects) ──────

def _armature_name_search(self, context, edit_text):
    """
    Autocomplete for meta_rig.
    Blender seeds edit_text with the currently stored value when the field is first
    opened — at that point we show ALL armatures so the picker is always useful.
    Filtering kicks in only when the user has typed something different.
    """
    all_arms = [o.name for o in bpy.data.objects if o.type == 'ARMATURE']
    if not edit_text or edit_text == self.meta_rig:
        return all_arms
    lo = edit_text.lower()
    return [n for n in all_arms if lo in n.lower()]


def _bone_coll_name_search(self, context, edit_text):
    """Autocomplete for meta_collection: lists bone collections of the current MetaRig."""
    arm = bpy.data.objects.get(self.meta_rig)
    if not arm or arm.type != 'ARMATURE':
        return []
    all_colls = [bc.name for bc in arm.data.collections]
    if not edit_text or edit_text == self.meta_collection:
        return all_colls
    lo = edit_text.lower()
    return [n for n in all_colls if lo in n.lower()]


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
    # Template collection picker — collection name IS the replacement token
    atomic_chain:    bpy.props.EnumProperty(  name="Template",       items=_collection_items)
    # StringProperty + search: value is stable even when new objects enter the scene
    meta_rig:        bpy.props.StringProperty(name="Meta Rig",        default="MetaRig",
                                              search=_armature_name_search)
    meta_collection: bpy.props.StringProperty(name="Meta Collection", default="MetaCollection",
                                              search=_bone_coll_name_search)
    active_meta_bone: bpy.props.EnumProperty( name="Meta Bone",       items=_metabone_items)
    wip_coll:         bpy.props.StringProperty(options={'HIDDEN'})
    wip_empty:        bpy.props.StringProperty(options={'HIDDEN'})
    last_step:        bpy.props.StringProperty(options={'HIDDEN'})
    is_aligning:      bpy.props.BoolProperty(options={'HIDDEN'})
    # Tracks sequential progress 0→11; resets to 0 when Step 1 is clicked
    completed_step:   bpy.props.IntProperty(default=0, options={'HIDDEN'})


# ─── STEP 1 ─ Duplicate and Rename ────────────────────────────────────────────

class GCBA_OT_DuplicateAtomicChain(bpy.types.Operator):
    bl_idname      = "gcba.duplicate_atomic_chain"
    bl_label       = "Duplicate and Rename"
    bl_description = "Copy the template collection and rename every token to the selected MetaBone name"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _p(context)
        # Reset per-MetaBone progress so a new MetaBone can start fresh
        props.completed_step = 0

        bone_name = props.active_meta_bone
        token     = props.atomic_chain

        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}
        if not token or token == 'NONE':
            self.report({'ERROR'}, "Select a template collection first")
            return {'CANCELLED'}

        src = _atomic_coll(props)
        if not src:
            self.report({'ERROR'}, f"Collection '{token}' not found")
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

        count = 0
        for obj in _all_objects(new_coll):
            obj.name = _clean(obj.name, token, bone_name)
            if obj.data:
                obj.data.name = _clean(obj.data.name, token, bone_name)
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
                for bc in obj.data.collections:
                    new_bc_name = _clean(bc.name, token, bone_name)
                    if new_bc_name != bc.name:
                        bc.name = new_bc_name
            count += 1

        _rename_coll_tree(new_coll, token, bone_name)
        props.wip_coll = new_coll.name

        alignment_name = f"{bone_name}-Alignment"
        for obj in _all_objects(new_coll):
            if obj.type == 'EMPTY' and obj.name == alignment_name:
                props.wip_empty = obj.name
                break
        if not props.wip_empty:
            self.report({'WARNING'},
                f"Duplicated OK but '{alignment_name}' empty not found — "
                "ensure your template has a '<TOKEN>-Alignment' empty")

        self.report({'INFO'}, f"Duplicated '{src.name}' → {count} objects renamed ('{token}' → '{bone_name}')")
        props.last_step     = self.bl_idname
        props.completed_step = 1
        return {'FINISHED'}


# ─── STEP 2 ─ Rebind Constraints & Geonodes ───────────────────────────────────

class GCBA_OT_RebindConstraintsGeonodes(bpy.types.Operator):
    bl_idname      = "gcba.rebind_constraints_geonodes"
    bl_label       = "Rebind Constraints & Geonodes"
    bl_description = "Fix constraint targets and Geometry Node socket inputs still pointing to template token objects"
    bl_options     = {'REGISTER', 'UNDO'}

    def _fix_obj_ref(self, owner, attr, token, bone_name):
        ref = getattr(owner, attr, None)
        if ref and token in ref.name:
            new_obj = bpy.data.objects.get(ref.name.replace(token, bone_name))
            if new_obj:
                setattr(owner, attr, new_obj)

    def _fix_str(self, owner, attr, token, bone_name):
        val = getattr(owner, attr, None)
        if isinstance(val, str) and token in val:
            setattr(owner, attr, val.replace(token, bone_name))

    def _rebind_constraint(self, con, token, bone_name):
        self._fix_obj_ref(con, 'target',      token, bone_name)
        self._fix_str    (con, 'subtarget',   token, bone_name)
        self._fix_obj_ref(con, 'pole_target', token, bone_name)

    def _rebind_gn_mod(self, mod, token, bone_name):
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
                new_obj = bpy.data.objects.get(value.name.replace(token, bone_name))
                if new_obj:
                    mod[item.identifier] = new_obj
            elif isinstance(value, str) and token in value:
                mod[item.identifier] = value.replace(token, bone_name)

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        token     = props.atomic_chain

        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        wip = bpy.data.collections.get(props.wip_coll)
        if not wip:
            self.report({'ERROR'}, "No working collection — run Step 1 first")
            return {'CANCELLED'}

        for obj in _all_objects(wip):
            for con in obj.constraints:
                self._rebind_constraint(con, token, bone_name)
            for mod in obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_mod(mod, token, bone_name)
            if obj.type == 'ARMATURE':
                for pb in obj.pose.bones:
                    for con in pb.constraints:
                        self._rebind_constraint(con, token, bone_name)

        self.report({'INFO'}, f"Rebound constraints & geonodes in '{wip.name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 2
        return {'FINISHED'}


# ─── STEP 3 ─ Scale Empty to Rest Pose Length ─────────────────────────────────

class GCBA_OT_ScaleEmptyToRestPose(bpy.types.Operator):
    bl_idname      = "gcba.scale_empty_to_rest_pose"
    bl_label       = "Scale Empty to Rest Pose"
    bl_description = "Set the alignment empty's uniform scale to the MetaBone's rest-pose world-space length"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found — run Step 1 first")
            return {'CANCELLED'}

        data_bone = arm_obj.data.bones.get(bone_name)
        if not data_bone:
            self.report({'ERROR'}, f"Bone '{bone_name}' not found in MetaRig")
            return {'CANCELLED'}

        # World-space rest length (accounts for armature object scale)
        head_w = arm_obj.matrix_world @ Vector(data_bone.head_local)
        tail_w = arm_obj.matrix_world @ Vector(data_bone.tail_local)
        world_length = (tail_w - head_w).length

        empty_obj.scale = (world_length, world_length, world_length)

        self.report({'INFO'}, f"Empty scaled to rest-pose length {world_length:.4f}")
        props.last_step      = self.bl_idname
        props.completed_step = 3
        return {'FINISHED'}


# ─── STEP 4 ─ Add Copy Location & Copy Rotation Constraints ───────────────────

class GCBA_OT_AddAlignConstraints(bpy.types.Operator):
    bl_idname      = "gcba.add_align_constraints"
    bl_label       = "Add Copy Loc & Rot Constraints"
    bl_description = "Add Copy Location and Copy Rotation constraints on the alignment empty targeting the MetaBone"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found — run Step 1 first")
            return {'CANCELLED'}

        # Clear any leftover constraints
        for con in list(empty_obj.constraints):
            empty_obj.constraints.remove(con)

        con_loc           = empty_obj.constraints.new('COPY_LOCATION')
        con_loc.name      = "GCBA_CopyLoc"
        con_loc.target    = arm_obj
        con_loc.subtarget = bone_name

        con_rot           = empty_obj.constraints.new('COPY_ROTATION')
        con_rot.name      = "GCBA_CopyRot"
        con_rot.target    = arm_obj
        con_rot.subtarget = bone_name

        self.report({'INFO'}, f"Copy Location + Copy Rotation added → '{bone_name}'")
        props.last_step      = self.bl_idname
        props.completed_step = 4
        return {'FINISHED'}


# ─── STEP 5 ─ Edit Alignment in Meta Rig ──────────────────────────────────────

class GCBA_OT_EditAlignmentInMetaRig(bpy.types.Operator):
    bl_idname      = "gcba.edit_alignment_in_metarig"
    bl_label       = "Edit Alignment in Meta Rig"
    bl_description = (
        "Enter Pose Mode on MetaRig; the alignment empty follows the bone live. "
        "Adjust the MetaBone pose, then click Step 6 to confirm"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        bone_name = props.active_meta_bone
        if not bone_name or bone_name == 'NONE':
            self.report({'ERROR'}, "Select a MetaBone first")
            return {'CANCELLED'}

        arm_obj = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found — run Step 1 first")
            return {'CANCELLED'}

        _ALIGN_STATE.clear()
        _ALIGN_STATE.update({
            'arm':   arm_obj.name,
            'bone':  bone_name,
            'empty': empty_obj.name,
        })
        _register_align_handler()

        _ensure_object_mode(context)
        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.hide_set(False)
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        props.is_aligning    = True
        props.last_step      = self.bl_idname
        props.completed_step = 5
        self.report({'INFO'}, "Adjust MetaBone in Pose Mode — then click Step 6 Accept & Bind")
        return {'FINISHED'}


# ─── STEP 6 ─ Accept & Bind ───────────────────────────────────────────────────

class GCBA_OT_AcceptAndBind(bpy.types.Operator):
    bl_idname      = "gcba.accept_and_bind"
    bl_label       = "Accept & Bind"
    bl_description = (
        "Bake the alignment empty's constraints, apply transforms to all children, "
        "unparent them keeping world position, then delete the empty"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props     = _p(context)
        empty_obj = bpy.data.objects.get(props.wip_empty)
        if not empty_obj:
            self.report({'ERROR'}, "Alignment empty not found — run Step 1 first")
            return {'CANCELLED'}

        _unregister_align_handler()
        _ALIGN_STATE.clear()
        _ensure_object_mode(context)

        # ── 1. Bake the empty's constraints into its stored transform ──────
        # Read evaluated world matrix BEFORE removing constraints
        evaluated_matrix = empty_obj.matrix_world.copy()

        # Remove constraints (empty would jump back to its original stored position)
        for con in list(empty_obj.constraints):
            empty_obj.constraints.remove(con)

        # Restore the evaluated position as its new stored transform
        empty_obj.matrix_world = evaluated_matrix

        # ── 2. Store children, unparent keeping world position ─────────────
        children = list(empty_obj.children)
        child_world_mats = {}
        for child in children:
            child_world_mats[child] = child.matrix_world.copy()

        for child in children:
            child.parent       = None
            child.matrix_world = child_world_mats[child]

        # ── 3. Apply transforms to every former child (mesh, armature, etc.) ──
        for child in children:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                child.hide_set(False)
                child.select_set(True)
                context.view_layer.objects.active = child
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            except Exception as e:
                self.report({'WARNING'}, f"Could not apply transforms to '{child.name}': {e}")

        # ── 4. Delete the empty ───────────────────────────────────────────
        bpy.data.objects.remove(empty_obj, do_unlink=True)
        props.wip_empty      = ''
        props.is_aligning    = False
        props.last_step      = self.bl_idname
        props.completed_step = 6

        self.report({'INFO'}, f"Bound {len(children)} children — alignment empty removed")
        return {'FINISHED'}


# ─── STEP 7 ─ Refresh Gesture & Plot Rigs ─────────────────────────────────────

class GCBA_OT_RefreshRigs(bpy.types.Operator):
    bl_idname      = "gcba.refresh_rigs"
    bl_label       = "Refresh Gesture & Plot Rigs"
    bl_description = "Create MetaRig.Rig and MetaRig.Gesture armatures if missing; leave them untouched if they already exist"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props    = _p(context)
        arm_obj  = _meta_rig(props)
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"MetaRig '{props.meta_rig}' not found")
            return {'CANCELLED'}

        rig_name     = f"{arm_obj.name}.Rig"
        gesture_name = f"{arm_obj.name}.Gesture"
        target_colls = _rig_target_colls(props)
        token        = props.atomic_chain
        _ensure_object_mode(context)

        rig_obj = bpy.data.objects.get(rig_name)
        if not rig_obj:
            rig_obj           = arm_obj.copy()
            rig_obj.data      = arm_obj.data.copy()
            rig_obj.name      = rig_name
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
                if token in eb.name:
                    rig_obj.data.edit_bones.remove(eb)
            bpy.ops.object.mode_set(mode='OBJECT')

        gesture_obj = bpy.data.objects.get(gesture_name)
        if not gesture_obj:
            gesture_data = bpy.data.armatures.new(gesture_name)
            gesture_obj  = bpy.data.objects.new(gesture_name, gesture_data)
            for coll in target_colls:
                coll.objects.link(gesture_obj)

        self.report({'INFO'}, f"'{rig_name}' and '{gesture_name}' ready")
        props.last_step      = self.bl_idname
        props.completed_step = 7
        return {'FINISHED'}


# ─── STEP 8 ─ Rebind Final Armatures ──────────────────────────────────────────

class GCBA_OT_RebindFinalArmatures(bpy.types.Operator):
    bl_idname      = "gcba.rebind_final_armatures"
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


# ─── STEP 9 ─ Merge & Clean ───────────────────────────────────────────────────

class GCBA_OT_FinishMerging(bpy.types.Operator):
    bl_idname      = "gcba.finish_merging"
    bl_label       = "Merge & Clean"
    bl_description = (
        "Join working armatures into .Rig/.Gesture, apply transforms to all objects, "
        "move curves to Splines, meshes to SampleMesh, delete DUPLICATED alignment empties "
        "(the original template empty is preserved)"
    )
    bl_options     = {'REGISTER', 'UNDO'}

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
        props       = _p(context)
        meta_name   = props.meta_rig
        rig_target  = bpy.data.objects.get(f"{meta_name}.Rig")
        gest_target = bpy.data.objects.get(f"{meta_name}.Gesture")

        if not rig_target or not gest_target:
            self.report({'ERROR'}, "Run Step 7 first")
            return {'CANCELLED'}

        target_colls = _rig_target_colls(props)
        token        = props.atomic_chain
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

        # Identify template objects to EXCLUDE from cleanup
        template_coll = _atomic_coll(props)
        template_objs = set(_all_objects(template_coll)) if template_coll else set()

        # Delete DUPLICATED alignment empties only (not the original in the template)
        for obj in list(bpy.data.objects):
            if obj.type != 'EMPTY':
                continue
            if not obj.name.endswith('-Alignment'):
                continue
            if obj in template_objs:
                continue  # preserve the original template empty

            # Apply transforms to all children before unparenting
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
            "Curves → Splines, Meshes → SampleMesh.")
        props.last_step      = self.bl_idname
        props.completed_step = 9
        return {'FINISHED'}


# ─── STEP 10 ─ Merge .Rig into MetaRig ────────────────────────────────────────

class GCBA_OT_MergeRigIntoMetaRig(bpy.types.Operator):
    bl_idname      = "gcba.merge_rig_into_metarig"
    bl_label       = "Merge .Rig into MetaRig"
    bl_description = (
        "Redirect all GN armature inputs from .Rig → MetaRig, "
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
            self.report({'ERROR'}, f"'{rig_name}' not found — run Steps 7–9 first")
            return {'CANCELLED'}

        _ensure_object_mode(context)
        arm_obj.hide_set(False)

        # Redirect all GN armature inputs from .Rig → MetaRig BEFORE the join
        for scene_obj in list(bpy.data.objects):
            for mod in scene_obj.modifiers:
                if mod.type == 'NODES':
                    self._rebind_gn_ref(mod, rig_obj, arm_obj)
                elif mod.type == 'ARMATURE' and mod.object is rig_obj:
                    mod.object = arm_obj

        # join() requires both objects in the same collection
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


# ─── STEP 11 ─ Rebind Armature Deform ─────────────────────────────────────────

class GCBA_OT_RebindArmatureDeform(bpy.types.Operator):
    bl_idname      = "gcba.rebind_armature_deform"
    bl_label       = "Rebind Armature Deform"
    bl_description = (
        "Re-parent skin meshes to MetaRig with empty vertex groups; "
        "also rebind GN 'Deform Armature' inputs to MetaRig. Then hide MetaRig"
    )
    bl_options     = {'REGISTER', 'UNDO'}

    def _rebind_gn_to_final(self, mod, arm_obj):
        """Update any GN armature-type object input that isn't MetaRig → MetaRig."""
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
                # Dead reference (old .Rig was deleted) — check input name for hint
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

        all_objs  = []
        for coll in arm_obj.users_collection:
            all_objs.extend(_all_objects(coll))
        mesh_objs = [o for o in all_objs if o.type == 'MESH']

        token   = props.atomic_chain
        count   = 0
        skipped = 0
        for obj in mesh_objs:
            has_arm_mod = any(m.type == 'ARMATURE' for m in obj.modifiers)

            # Always rebind GN inputs regardless of whether armature mod exists
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


# ─── PANEL HELPER ─────────────────────────────────────────────────────────────

def _step(col, props, idname, icon, step_num, label, always_enabled=False):
    """
    Draw one numbered workflow button.
    Rule: only the step immediately after the last completed one is enabled.
    Step 1 passes always_enabled=True so the user can always restart a MetaBone.
    """
    row = col.row()
    if not always_enabled:
        row.enabled = (props.completed_step == step_num - 1)
    row.operator(idname, text=label, icon=icon, depress=props.last_step == idname)


# ─── PANEL ────────────────────────────────────────────────────────────────────

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

        # ── Registration ─────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Registration", icon='PROPERTIES')
        col = box.column(align=True)
        col.prop(props, "atomic_chain")    # collection name = token
        col.prop(props, "meta_rig")        # armature object dropdown
        col.prop(props, "meta_collection") # bone collection dropdown

        layout.separator()

        # ── Generate Rig ─────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Generate Rig", icon='ARMATURE_DATA')
        col = box.column(align=False)
        col.prop(props, "active_meta_bone", text="MetaBone")
        col.separator()

        # ── Per-MetaBone steps (1-6) ──────────────────────────────────────
        # Step 1 is always clickable — starting a new MetaBone resets progress
        _step(col, props, "gcba.duplicate_atomic_chain",      'MOD_THICKNESS',    1, "1.  Duplicate and Rename",        always_enabled=True)
        _step(col, props, "gcba.rebind_constraints_geonodes", 'CON_SPLINEIK',     2, "2.  Rebind Constraints & Geonodes")

        col.separator()
        col.label(text="  Align Chain to Bone:", icon='EMPTY_AXIS')

        _step(col, props, "gcba.scale_empty_to_rest_pose",    'FULLSCREEN_ENTER', 3, "3.  Scale Empty to Rest Pose")
        _step(col, props, "gcba.add_align_constraints",       'CON_LOCLIKE',      4, "4.  Add Copy Loc & Rot")

        _step(col, props, "gcba.edit_alignment_in_metarig",   'POSE_HLT',         5, "5.  Edit Alignment in Meta Rig")
        if props.is_aligning:
            hint = col.row()
            hint.enabled = False
            hint.label(text="     Adjust pose → then Step 6", icon='INFO')

        _step(col, props, "gcba.accept_and_bind",             'CHECKMARK',        6, "6.  Accept & Bind")

        col.separator()

        # ── Global / finalization steps (7-11) ────────────────────────────
        _step(col, props, "gcba.refresh_rigs",           'CON_ROTLIKE',           7,  "7.  Refresh Gesture & Plot Rigs")
        _step(col, props, "gcba.rebind_final_armatures", 'OUTLINER_OB_ARMATURE',  8,  "8.  Rebind Final Armatures")
        _step(col, props, "gcba.finish_merging",         'OUTLINER_DATA_ARMATURE',9,  "9.  Merge & Clean")
        _step(col, props, "gcba.merge_rig_into_metarig", 'ARMATURE_DATA',         10, "10. Merge .Rig into MetaRig")

        col.separator()

        _step(col, props, "gcba.rebind_armature_deform", 'MOD_ARMATURE',          11, "11. Rebind Armature Deform")


# ─── REGISTER / UNREGISTER ────────────────────────────────────────────────────

_classes = [
    GCBA_PG_Props,
    GCBA_OT_DuplicateAtomicChain,
    GCBA_OT_RebindConstraintsGeonodes,
    GCBA_OT_ScaleEmptyToRestPose,
    GCBA_OT_AddAlignConstraints,
    GCBA_OT_EditAlignmentInMetaRig,
    GCBA_OT_AcceptAndBind,
    GCBA_OT_RefreshRigs,
    GCBA_OT_RebindFinalArmatures,
    GCBA_OT_FinishMerging,
    GCBA_OT_MergeRigIntoMetaRig,
    GCBA_OT_RebindArmatureDeform,
    GCBA_PT_Panel,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gcba_props = bpy.props.PointerProperty(type=GCBA_PG_Props)


def unregister():
    _unregister_align_handler()
    _ALIGN_STATE.clear()
    del bpy.types.Scene.gcba_props
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()
