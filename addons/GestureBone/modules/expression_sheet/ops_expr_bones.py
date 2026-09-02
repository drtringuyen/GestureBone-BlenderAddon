"""
expression_sheet/ops_expr_bones.py — the expression-bone registry.

Operators that maintain ``arm.gesturebone_props.expression_bones``: the explicit
list of which bones are expression bones, and which sheet each one picks from.

Before this list existed, "is this an expression bone?" meant "does this pose
bone happen to carry an exp_index key?" — which quietly accumulated false
positives, because the Pose-mode grid keys EVERY selected bone. (In
CHR_BongBong that left four DEF- bones carrying an index with no shader node
behind it.) Registering bones explicitly makes that visible and fixable.

Entries are keyed by bone NAME within the same Object that owns the pose bones,
so nothing here crosses a datablock boundary and library overrides need no
pointer repair — unlike the chain pointers riglinking/relink.py has to fix.
"""
import bpy
from bpy.props import StringProperty, IntProperty, EnumProperty, BoolProperty

from .grid import _SpriteGridBase
from .props import find_entry, resolve_grid, scene_props
from .ops_pose_expr import (
    _EXP_PROP, _ensure_exp_index, _force_constant, _bone_exp_fcurve,
    _key_expression_change, keying_blocked_reason,
)


def _armature(context):
    """The armature whose registry the panel/operators act on.

    getattr-guarded because poll() runs in whatever context Blender happens to
    be in — including restricted ones where `active_object` is simply absent,
    which raises AttributeError rather than returning None.
    """
    ob = getattr(context, "active_object", None) or getattr(context, "object", None)
    return ob if ob is not None and ob.type == 'ARMATURE' else None


def _add_entry(arm, bone_name):
    """Register *bone_name*, seeding the sheet from the scene fallback.

    Returns the entry, or None if it was already registered.
    """
    if find_entry(arm, bone_name) is not None:
        return None
    entry = arm.gesturebone_props.expression_bones.add()
    entry.name = bone_name          # what makes expression_bones["X"] resolve
    entry.bone = bone_name
    scn = scene_props()
    entry.sheet_image = scn.sheet_image
    entry.grid_count = scn.grid_count
    entry.grid_size = 0             # 0 = inherit the scene cell size
    return entry


# ── Registry maintenance ──────────────────────────────────────────────────────

class GESTUREBONE_OT_expression_bone_add(bpy.types.Operator):
    """Register the selected pose bones as expression bones"""
    bl_idname = "gesturebone.expression_bone_add"
    bl_label = "Add Expression Bone"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = _armature(context)
        return (arm is not None and arm.mode == 'POSE'
                and any(pb.select for pb in arm.pose.bones))

    def execute(self, context):
        arm = _armature(context)
        added = []
        for pb in [b for b in arm.pose.bones if b.select]:
            entry = _add_entry(arm, pb.name)
            if entry is None:
                continue
            _ensure_exp_index(pb, resolve_grid(arm, pb.name, context).max_index)
            added.append(pb.name)

        if not added:
            self.report({'INFO'}, "Already registered")
            return {'CANCELLED'}
        arm.gesturebone_props.active_expression_index = \
            len(arm.gesturebone_props.expression_bones) - 1
        self.report({'INFO'}, "Registered %d bone(s): %s"
                    % (len(added), ", ".join(added[:3])))
        return {'FINISHED'}


class GESTUREBONE_OT_expression_bone_remove(bpy.types.Operator):
    """Unregister this expression bone"""
    bl_idname = "gesturebone.expression_bone_remove"
    bl_label = "Remove Expression Bone"
    bl_options = {'REGISTER', 'UNDO'}

    # HIDDEN keeps the index out of the confirm dialog, which would otherwise
    # draw it as an editable number field next to the checkbox.
    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})
    purge_property: BoolProperty(
        name="Also Delete exp_index",
        description="Delete the bone's exp_index custom property too. Off by "
                    "default — drivers and keyframes reference it, and removing "
                    "it orphans their f-curves",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        arm = _armature(context)
        coll = arm.gesturebone_props.expression_bones
        idx = self.index if self.index >= 0 else \
            arm.gesturebone_props.active_expression_index
        if not (0 <= idx < len(coll)):
            self.report({'WARNING'}, "No such entry")
            return {'CANCELLED'}

        bone_name = coll[idx].bone
        if self.purge_property:
            pb = arm.pose.bones.get(bone_name)
            if pb is not None and _EXP_PROP in pb.keys():
                del pb[_EXP_PROP]

        coll.remove(idx)
        arm.gesturebone_props.active_expression_index = max(0, min(
            arm.gesturebone_props.active_expression_index, len(coll) - 1))
        self.report({'INFO'}, "Unregistered '%s'" % bone_name)
        return {'FINISHED'}


class GESTUREBONE_OT_expression_bone_move(bpy.types.Operator):
    """Reorder this expression bone in the list"""
    bl_idname = "gesturebone.expression_bone_move"
    bl_label = "Move Expression Bone"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})
    direction: EnumProperty(
        items=[('UP', "Up", ""), ('DOWN', "Down", "")],
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        arm = _armature(context)
        coll = arm.gesturebone_props.expression_bones
        idx = self.index
        new = idx - 1 if self.direction == 'UP' else idx + 1
        if not (0 <= idx < len(coll) and 0 <= new < len(coll)):
            return {'CANCELLED'}
        coll.move(idx, new)
        arm.gesturebone_props.active_expression_index = new
        return {'FINISHED'}


class GESTUREBONE_OT_expression_bone_sync(bpy.types.Operator):
    """Register every pose bone that already carries an exp_index property

    The migration path for rigs built before the registry existed. Deliberately
    a manual operator and not a load_post handler: an earlier auto-heal on file
    load (commit 0a0f369) shipped a crash-on-open and a mis-aimed driver, and
    this one has nothing time-critical to do.
    """
    bl_idname = "gesturebone.expression_bone_sync"
    bl_label = "Sync Expression Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        arm = _armature(context)
        added = []
        for pb in arm.pose.bones:
            if _EXP_PROP not in pb.keys():
                continue
            if _add_entry(arm, pb.name) is not None:
                added.append(pb.name)
            # Normalise the property's UI range even for bones that were
            # already registered — a rig built before the registry existed has
            # exp_index sitting on the full int range, so the N-panel slider
            # runs to 2^31 instead of the bone's own last cell.
            _ensure_exp_index(pb, resolve_grid(arm, pb.name, context).max_index)

        stale = [e.bone for e in arm.gesturebone_props.expression_bones
                 if e.bone not in arm.pose.bones]

        if not added and not stale:
            self.report({'INFO'}, "Already in sync")
            return {'CANCELLED'}

        msg = []
        if added:
            msg.append("registered %d bone(s)" % len(added))
        if stale:
            # Reported, never auto-removed: a bone rename should not silently
            # cost the user the sheet and grid they configured for it.
            msg.append("%d entry/entries point at missing bones (%s)"
                       % (len(stale), ", ".join(stale[:3])))
        self.report({'WARNING' if stale else 'INFO'}, "; ".join(msg))
        return {'FINISHED'}


# ── Per-bone cell picker ──────────────────────────────────────────────────────

class GESTUREBONE_OT_expression_cell_pick(_SpriteGridBase):
    """Open this bone's sprite grid and key the picked expression"""
    bl_idname = "gesturebone.expression_cell_pick"
    bl_label = "Pick Expression Cell"
    bl_options = {'REGISTER', 'UNDO'}

    bone: StringProperty(options={'SKIP_SAVE'})

    def _grid_settings(self, context):
        return resolve_grid(self._arm, self.bone, context)

    def _prepare(self, context):
        arm = _armature(context)
        if arm is None:
            return False
        pb = arm.pose.bones.get(self.bone)
        if pb is None:
            self.report({'ERROR'}, "Bone '%s' not found — re-sync the list"
                        % self.bone)
            return False

        blocked = keying_blocked_reason(arm)
        if blocked:
            self.report({'ERROR'}, blocked)
            return False

        self._arm = arm
        self._bones = [pb]
        _ensure_exp_index(pb, resolve_grid(arm, pb.name, context).max_index)
        _force_constant(_bone_exp_fcurve(arm, pb.name))
        return True

    def invoke(self, context, event):
        # _grid_settings runs inside the base invoke and needs _arm resolved
        # before _prepare would normally set it.
        self._arm = _armature(context)
        return super().invoke(context, event)

    def _seed_chosen(self, context):
        pb = self._arm.pose.bones.get(self.bone)
        settings = resolve_grid(self._arm, self.bone, context)
        return min(int(pb.get(_EXP_PROP, 0)), settings.max_index) if pb else -1

    def _commit(self, context, idx):
        # Always keys, exactly like the Pose-mode grid: on a library override an
        # unkeyed value silently reverts to the library's on reload (verified —
        # see docs/expression-bones-design.md), so writing without keying would
        # look like it worked and then lose the edit.
        failed = _key_expression_change(context, self._arm, self._bones, idx)
        if failed:
            self.report({'ERROR'},
                        "Could not key exp_index on '%s' — the action is not "
                        "editable" % failed[0])


_CLASSES = (
    GESTUREBONE_OT_expression_bone_add,
    GESTUREBONE_OT_expression_bone_remove,
    GESTUREBONE_OT_expression_bone_move,
    GESTUREBONE_OT_expression_bone_sync,
    GESTUREBONE_OT_expression_cell_pick,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
