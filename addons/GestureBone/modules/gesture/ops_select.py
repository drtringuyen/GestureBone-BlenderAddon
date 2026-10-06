"""
gesture/ops_select.py — Pose-mode "Select Linked" for CTRL bones.

Blender's own select-linked walks parent/connected chains, which CTRL bones
don't have: they only share a ``CTRL-{part}`` name prefix. These operators
select every visible bone of the same part instead, and replace the default
Pose-mode bindings (L = pick under cursor, Shift+L = deselect, Ctrl+L = from
current selection).
"""
import bpy
from bpy.props import BoolProperty
from ..shared.utils import ctrl_group_key, ctrl_bone_side


def _known_parts(arm):
    """Chain part_names for this GESTURE rig (or its own chains for a PLOTTING rig)."""
    props = getattr(arm, "gesturebone_props", None)
    if props is None:
        return ()
    src = props.plotting_rig if props.rig_type == 'GESTURE' and props.plotting_rig else arm
    return tuple(c.part_name for c in src.gesturebone_props.chains)


def _pose_bone_visible(pb):
    if pb.hide or pb.bone.hide:
        return False
    colls = pb.bone.collections
    return not colls or any(c.is_visible_effectively for c in colls)


def _select_linked_ctrl(arm, seeds, same_side, deselect):
    """Expand ``seeds`` (pose bones) to every visible CTRL bone of the same part.

    Returns the number of CTRL groups matched; 0 means no seed was a CTRL bone.
    """
    parts = _known_parts(arm)
    targets = {}  # part key -> set of sides to include (None = all)
    for pb in seeds:
        key = ctrl_group_key(pb.name, parts)
        if key is None:
            continue
        side = ctrl_bone_side(pb.name) if same_side else None
        targets.setdefault(key, set()).add(side)

    if not targets:
        return 0

    for pb in arm.pose.bones:
        key = ctrl_group_key(pb.name, parts)
        if key not in targets:
            continue
        sides = targets[key]
        if same_side and None not in sides:
            # keep centre bones, drop the opposite side only
            side = ctrl_bone_side(pb.name)
            if side is not None and side not in sides:
                continue
        if not deselect and not _pose_bone_visible(pb):
            continue
        pb.select = not deselect
    return len(targets)


class GESTUREBONE_OT_PoseSelectLinkedCtrl(bpy.types.Operator):
    """Select all CTRL bones sharing the same part prefix as the selected bones"""
    bl_idname = "gesturebone.pose_select_linked_ctrl"
    bl_label = "Select Linked CTRL"
    bl_options = {'REGISTER', 'UNDO'}

    same_side: BoolProperty(
        name="Same Side Only",
        description="Only select bones on the same side (.L / .R) as the seed bones; "
                    "centre bones are always included",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'POSE' and context.active_object is not None

    def execute(self, context):
        arm = context.active_object
        seeds = [pb for pb in arm.pose.bones if pb.select]
        if not seeds:
            return {'CANCELLED'}
        if not _select_linked_ctrl(arm, seeds, self.same_side, deselect=False):
            # no CTRL bone in the selection — fall back to Blender's chain walk
            return bpy.ops.pose.select_linked()
        return {'FINISHED'}


class GESTUREBONE_OT_PoseSelectLinkedCtrlPick(bpy.types.Operator):
    """Select all CTRL bones sharing the part prefix of the bone under the cursor"""
    bl_idname = "gesturebone.pose_select_linked_ctrl_pick"
    bl_label = "Select Linked CTRL (Pick)"
    bl_options = {'REGISTER', 'UNDO'}

    same_side: BoolProperty(
        name="Same Side Only",
        description="Only select bones on the same side (.L / .R) as the picked bone; "
                    "centre bones are always included",
        default=False,
    )
    deselect: BoolProperty(
        name="Deselect",
        description="Remove the picked bone's group from the selection instead",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (context.mode == 'POSE' and context.active_object is not None
                and context.region is not None and context.region.type == 'WINDOW')

    def invoke(self, context, event):
        arm = context.active_object
        active_before = arm.data.bones.active

        # Let Blender pick the bone under the cursor (extend keeps the rest).
        res = bpy.ops.view3d.select(
            extend=True, location=(event.mouse_region_x, event.mouse_region_y))
        if 'FINISHED' not in res:
            return {'CANCELLED'}
        picked = arm.data.bones.active
        pb = arm.pose.bones.get(picked.name) if picked else None
        if pb is None or not pb.select:
            # click on empty space: view3d.select changed nothing
            return {'CANCELLED'}

        if ctrl_group_key(pb.name, _known_parts(arm)) is None:
            # not a CTRL bone — Blender's chain-based pick handles it
            return bpy.ops.pose.select_linked_pick(
                'INVOKE_DEFAULT', extend=not self.deselect)

        _select_linked_ctrl(arm, [pb], self.same_side, self.deselect)
        if self.deselect:
            pb.select = False
            arm.data.bones.active = active_before
        return {'FINISHED'}


# ── Keymap ────────────────────────────────────────────────────────────────────

_addon_keymaps = []

_KEYMAP_ITEMS = (
    # (idname, ctrl, shift, props)
    (GESTUREBONE_OT_PoseSelectLinkedCtrlPick.bl_idname, False, False, {}),
    (GESTUREBONE_OT_PoseSelectLinkedCtrlPick.bl_idname, False, True,  {"deselect": True}),
    (GESTUREBONE_OT_PoseSelectLinkedCtrl.bl_idname,     True,  False, {}),
)


def _menu_draw(self, context):
    layout = self.layout
    layout.separator()
    layout.operator(GESTUREBONE_OT_PoseSelectLinkedCtrl.bl_idname)


def register():
    bpy.utils.register_class(GESTUREBONE_OT_PoseSelectLinkedCtrl)
    bpy.utils.register_class(GESTUREBONE_OT_PoseSelectLinkedCtrlPick)
    bpy.types.VIEW3D_MT_select_pose.append(_menu_draw)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        # Addon keymaps take priority over Blender's defaults, so these shadow
        # pose.select_linked_pick (L / Shift+L) and pose.select_linked (Ctrl+L).
        km = kc.keymaps.new(name='Pose', space_type='EMPTY')
        for idname, ctrl, shift, props in _KEYMAP_ITEMS:
            kmi = km.keymap_items.new(idname, 'L', 'PRESS', ctrl=ctrl, shift=shift)
            for k, v in props.items():
                setattr(kmi.properties, k, v)
            _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    bpy.types.VIEW3D_MT_select_pose.remove(_menu_draw)
    bpy.utils.unregister_class(GESTUREBONE_OT_PoseSelectLinkedCtrlPick)
    bpy.utils.unregister_class(GESTUREBONE_OT_PoseSelectLinkedCtrl)


def get_keymap_item():
    """(km, kmi) for the L pick hotkey, editable via the UI, or None.

    Reads back through wm.keyconfigs.user so UI edits are reflected immediately.
    """
    if not _addon_keymaps:
        return None
    km_addon, kmi_addon = _addon_keymaps[0]
    wm = bpy.context.window_manager
    km_user = wm.keyconfigs.user.keymaps.get(km_addon.name)
    if km_user is None:
        return None
    for kmi in km_user.keymap_items:
        if kmi.idname == kmi_addon.idname and not kmi.properties.deselect:
            return km_user, kmi
    return None
