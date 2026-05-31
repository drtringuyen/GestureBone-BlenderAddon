"""
shared/chain.py — Unified ChainDefinition PropertyGroup.
Single source of truth for every chain: replaces both GESTUREBONE_PG_CurveBoneChain
(gesture_draw) and GESTUREBONE_PG_MetaBoneSettings (rig_generation).
"""
import bpy
import re
from bpy.props import (
    StringProperty, BoolProperty, IntProperty, FloatProperty,
    CollectionProperty, EnumProperty, PointerProperty,
)

# ── Mode constants ─────────────────────────────────────────────────────────────

CONTROL_MODES = [
    ('PT_5', "5 Points", "5 control points"),
    ('PT_3', "3 Points", "3 control points"),
    ('PT_2', "2 Points", "2 control points"),
]
CONTROL_MODE_COUNT = {
    'PT_5': 5,
    'PT_3': 3,
    'PT_2': 3,  # 2 gesture points, 3 bones: _0 (start), _2 (handle), _4 (end)
}
# GN integer value for "Control MODE" socket
CONTROL_MODE_GN_INT = {'PT_5': 0, 'PT_3': 1, 'PT_2': 2}

PLOTTING_MODES = [
    ('SYM_10', "10 Symmetry", "10 plotting points — symmetric"),
    ('LIN_10', "10 Linear",   "10 plotting points — linear, full chain (20 bones)"),
]
PLOTTING_MODE_COUNT = {
    'SYM_10': 10,
    'LIN_10': 20,
}

SPLINE_GEONODE_DEFAULTS = {
    'gesture':  'Snap_to_bones',
    'plotting': 'Curve_Armature_Symetry_5',
}

_BLENDER_SUFFIX = re.compile(r'(\.\d{3})+$')


def _ctrl_bone_indices(count):
    """Map control-point count to 0-based bone index list.
    Template bones: CTRL-{bone}_0…_4.
      PT_5 → [0,1,2,3,4]   PT_3 → [0,2,4]   PT_2 → [0,2,4] (3 bones)
    """
    if count <= 1:
        return [0]
    max_idx = 4
    stride  = max_idx / (count - 1)
    return [round(i * stride) for i in range(count)]


def _default_template():
    """First tagged collection containing '<4_Handles', else first tagged, else ''."""
    tagged = [c for c in bpy.data.collections if "gesturebone_template" in c]
    for c in tagged:
        if '<4_Handles' in c.name:
            return c.name
    return tagged[0].name if tagged else ""


# ── Search callbacks ───────────────────────────────────────────────────────────

def _bone_search(self, context, edit_text):
    """Search CTRL bones in the active armature (should be the GESTURE rig)."""
    arm = context.active_object if context and context.active_object and context.active_object.type == 'ARMATURE' else None
    if arm:
        return [b.name for b in arm.data.bones if edit_text.lower() in b.name.lower()]
    return []


def _collection_search(self, context, edit_text):
    tagged = [c.name for c in bpy.data.collections if "gesturebone_template" in c]
    pool   = tagged if tagged else [c.name for c in bpy.data.collections]
    if not edit_text:
        return pool
    lo = edit_text.lower()
    return [n for n in pool if lo in n.lower()]


def _mesh_object_poll(self, obj):
    if obj.type != 'MESH':
        return False
    atomic = bpy.data.collections.get("Atomic Chains")
    if atomic:
        def _in_coll(o, c):
            if o.name in c.objects:
                return True
            return any(_in_coll(o, ch) for ch in c.children)
        if _in_coll(obj, atomic):
            return False
    return True


# ── Update callbacks ───────────────────────────────────────────────────────────

def _on_control_mode_update(self, context):
    count = CONTROL_MODE_COUNT.get(self.control_mode, 5)
    self.control_point_count = count
    _resize_collection(self.control_bones, count)

    # Auto-fill control bone names from gesture_rig if already set
    gesture_arm = self.gesture_rig
    if gesture_arm and gesture_arm.type == 'ARMATURE':
        indices = _ctrl_bone_indices(count)
        for i, entry in enumerate(self.control_bones):
            if i < len(indices):
                ctrl_name = f"CTRL-{self.part_name}_{indices[i]}"
                entry.bone = ctrl_name if gesture_arm.data.bones.get(ctrl_name) else ""


def _on_plotting_mode_update(self, context):
    self.plotting_point_count = PLOTTING_MODE_COUNT.get(self.plotting_mode, 10)


def _on_handle_smoothness_update(self, context):
    spline = self.gesture_spline
    if spline is None:
        return
    for mod in spline.modifiers:
        if mod.type != 'NODES' or not mod.node_group:
            continue
        if mod.node_group.name == "TOB-Gesture_drawing":
            try:
                mod["Socket_6"] = self.bone_handle_smoothness
                spline.update_tag()
            except Exception:
                pass
            break


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resize_collection(coll, count):
    while len(coll) < count:
        coll.add()
    while len(coll) > count:
        coll.remove(len(coll) - 1)


def bone_names(chain):
    """Return list of non-empty control bone name strings for a chain."""
    return [entry.bone for entry in chain.control_bones if entry.bone]


# ── Property groups ────────────────────────────────────────────────────────────

class GESTUREBONE_PG_BoneName(bpy.types.PropertyGroup):
    bone: StringProperty(name="Bone", search=_bone_search)


class GESTUREBONE_PG_ChainDefinition(bpy.types.PropertyGroup):
    """Unified chain: identity + rig-gen config + gesture/draw config + state."""

    # ── Identity ──────────────────────────────────────────────────────────────
    part_name: StringProperty(name="Name", default="Chain")
    active_tool: EnumProperty(
        name="Active Tool",
        items=[('DRAW', 'Draw', ''), ('EDIT', 'Edit', '')],
        default='DRAW',
    )

    # ── Rig-generation config (was MetaBoneSettings) ─────────────────────────
    atomic_chain: StringProperty(
        name="Template",
        description="Template collection for this bone — leave empty to use the global fallback",
        search=_collection_search,
    )
    control_mode: EnumProperty(
        name="Control Mode",
        items=CONTROL_MODES,
        default='PT_5',
        update=_on_control_mode_update,
    )
    pivot_placement: EnumProperty(
        name="Pivot Placement",
        items=[
            ('ORIGIN', "At Origin",  "Keep Rotation/Pivot bones at template position", 'OBJECT_ORIGIN',  0),
            ('CENTER', "At Center",  "Slide to MetaBone midpoint",                     'SNAP_MIDPOINT', 1),
        ],
        default='ORIGIN',
    )
    bind_mesh: PointerProperty(
        type=bpy.types.Object,
        name="Bind to Mesh",
        description="Source mesh to copy into this bone's Sample Mesh",
        poll=_mesh_object_poll,
    )
    sample_mesh: PointerProperty(
        type=bpy.types.Object,
        name="Sample Mesh",
        description="Auto-set in Step 9 — the generated sample mesh for this bone",
    )

    # ── Gesture/draw config (was CurveBoneChain) ─────────────────────────────
    gesture_spline: PointerProperty(
        name="Gesture Spline",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE',
    )
    control_point_count: IntProperty(name="Control Points", default=5, min=1, options={'HIDDEN'})
    control_bones: CollectionProperty(type=GESTUREBONE_PG_BoneName)
    bone_handle_smoothness: FloatProperty(
        name="Bone Handle Smoothness",
        description="Drives 'Bone Handle Smoothness' socket on the gesture spline's TOB-Gesture_drawing modifier",
        default=1.0, min=0.1, max=5.0,
        update=_on_handle_smoothness_update,
    )
    control_bones_expanded: BoolProperty(name="Control Bones", default=False)

    plotting_spline: PointerProperty(
        name="Plotting Spline",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE',
    )
    plotting_mode: EnumProperty(
        name="Plotting Mode",
        items=PLOTTING_MODES,
        default='SYM_10',
        update=_on_plotting_mode_update,
    )
    plotting_point_count: IntProperty(name="Plotting Points", default=10, min=1, options={'HIDDEN'})

    # ── Workflow state ─────────────────────────────────────────────────────────
    gesture_rig: PointerProperty(
        name="Gesture Rig",
        type=bpy.types.Object,
        description="The GESTURE armature that owns this chain's CTRL bones",
    )
    rig_completed_step: IntProperty(
        name="Rig Step",
        default=0,
        description="Highest rig-generation step completed for this chain (0=none, 14=fully done)",
        options={'HIDDEN'},
    )
    is_bound: BoolProperty(name="Bound", default=False)
    is_drawing: BoolProperty(name="Drawing", default=False)
    drawing_frame: IntProperty(name="Drawing Frame", default=-1)

    # ── UI collapse state ──────────────────────────────────────────────────────
    ui_expanded: BoolProperty(name="Expanded", default=False)


def register():
    bpy.utils.register_class(GESTUREBONE_PG_BoneName)
    bpy.utils.register_class(GESTUREBONE_PG_ChainDefinition)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PG_ChainDefinition)
    bpy.utils.unregister_class(GESTUREBONE_PG_BoneName)
