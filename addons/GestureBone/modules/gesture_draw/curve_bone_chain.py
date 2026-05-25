import bpy
from bpy.props import (
    StringProperty, BoolProperty,
    IntProperty, FloatProperty, CollectionProperty, EnumProperty, PointerProperty,
)
from .utils import _resize_collection, _ensure_chain_objects


def _ctrl_bone_indices(count):
    """Map control-point count to the 0-based bone index list.

    Template bones are CTRL-{bone}_0 … CTRL-{bone}_4 (five slots).
    After rig generation:
      PT_5 (5 pts) → _0, _1, _2, _3, _4   (stride 1)
      PT_3 (3 pts) → _0, _2, _4            (stride 2)
      PT_2 (2 pts) → _0, _2, _4            (stride 2, count=3)
    """
    if count <= 1:
        return [0]
    max_idx = 4
    stride  = max_idx / (count - 1)
    return [round(i * stride) for i in range(count)]


# ── Mode → bone-count mappings ─────────────────────────────────────────────────

CONTROL_MODES = [
    ('PT_5', "5 Points", "5 control points"),
    ('PT_3', "3 Points", "3 control points"),
    ('PT_2', "2 Points", "2 control points"),
]
CONTROL_MODE_COUNT = {
    'PT_5': 5,
    'PT_3': 3,
    'PT_2': 3,  # 2 gesture points but 3 bones: _0 (start), _2 (handle), _4 (end)
}

PLOTTING_MODES = [
    ('SYM_10', "10 Symmetry", "10 plotting points — symmetric (one side, 10 bones)"),
    ('LIN_10', "10 Linear",   "10 plotting points — linear, full chain (20 bones)"),
]
PLOTTING_MODE_COUNT = {
    'SYM_10': 10,
    'LIN_10': 20,
}

# Default geometry node group name per spline type — change here to remap globally
SPLINE_GEONODE_DEFAULTS = {
    'gesture': 'Snap_to_bones',
    'plotting': 'Curve_Armature_Symetry_5',
}


# ── Search callbacks ───────────────────────────────────────────────────────────

def _bone_search(self, context, edit_text):
    arm = context.active_object if context and context.active_object and context.active_object.type == 'ARMATURE' else None
    if arm:
        return [b.name for b in arm.data.bones if edit_text.lower() in b.name.lower()]
    return []


# ── Update callbacks ───────────────────────────────────────────────────────────

def _on_part_name_update(self, context):
    if context is None:
        return
    arm = None
    if context.active_object and context.active_object.type == 'ARMATURE':
        arm = context.active_object
    else:
        arm = getattr(getattr(context.scene, 'gesturebone_props', None), 'current_armature', None)
    _ensure_chain_objects(arm, self, context)


def _on_control_mode_update(self, context):
    count = CONTROL_MODE_COUNT.get(self.part_control_mode, 5)
    self.part_control_point_count = count
    _resize_collection(self.part_control_bones, count)

    # Auto-repopulate control bone names based on new indices
    if context is not None:
        rig_gen = getattr(getattr(context, 'scene', None), 'gesturebone_rig_generation_props', None)
        if rig_gen is not None:
            import bpy as _bpy
            gesture_arm_name = f"{rig_gen.meta_rig}.Gesture"
            gesture_arm = _bpy.data.objects.get(gesture_arm_name)
            if gesture_arm and gesture_arm.type == 'ARMATURE':
                indices = _ctrl_bone_indices(count)
                for i, entry in enumerate(self.part_control_bones):
                    if i < len(indices):
                        ctrl_name = f"CTRL-{self.part_name}_{indices[i]}"
                        entry.bone = ctrl_name if gesture_arm.data.bones.get(ctrl_name) else ""

            # Sync to Rig Generation bone_settings
            entry = rig_gen.bone_settings.get(self.part_name)
            if entry and entry.control_mode != self.part_control_mode:
                entry.control_mode = self.part_control_mode


def _on_plotting_mode_update(self, context):
    count = PLOTTING_MODE_COUNT.get(self.part_plotting_mode, 10)
    self.part_plotting_point_count = count
    _resize_collection(self.part_plotting_bones, count)


def _on_handle_smoothness_update(self, context):
    """Live-drive Socket_6 (Bone Handle Smoothness) on the gesture spline's GN modifier."""
    spline = self.part_gesture_spline
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


# ── Property groups ────────────────────────────────────────────────────────────

class GESTUREBONE_PG_BoneName(bpy.types.PropertyGroup):
    bone: StringProperty(name="Bone", search=_bone_search)


class GESTUREBONE_PG_CurveBoneChain(bpy.types.PropertyGroup):
    # ── Core identity ──────────────────────────────────────────────────────────
    part_name: StringProperty(name="Name", default="Chain", update=_on_part_name_update)
    active_tool: EnumProperty(
        name="Active Tool",
        items=[('DRAW', 'Draw', ''), ('EDIT', 'Edit', '')],
        default='DRAW',
    )

    # ── Gesture (control) spline ───────────────────────────────────────────────
    part_gesture_spline: PointerProperty(
        name="Gesture Spline",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE',
    )
    part_control_mode: EnumProperty(
        name="Control Mode",
        items=CONTROL_MODES,
        default='PT_5',
        update=_on_control_mode_update,
    )
    bone_handle_smoothness: FloatProperty(
        name="Bone Handle Smoothness",
        description="Drives the 'Bone Handle Smoothness' socket on the gesture spline's TOB-Gesture_drawing modifier",
        default=1.0,
        min=1.0,
        max=3.0,
        update=_on_handle_smoothness_update,
    )
    part_control_point_count: IntProperty(
        name="Control Points",
        default=5,
        min=1,
        options={'HIDDEN'},
    )
    part_control_bones: CollectionProperty(type=GESTUREBONE_PG_BoneName)
    control_bones_expanded: BoolProperty(name="Control Bones", default=False)

    # ── Plotting spline ────────────────────────────────────────────────────────
    part_plotting_spline: PointerProperty(
        name="Plotting Spline",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE',
    )
    part_plotting_mode: EnumProperty(
        name="Plotting Mode",
        items=PLOTTING_MODES,
        default='SYM_10',
        update=_on_plotting_mode_update,
    )
    part_plotting_point_count: IntProperty(
        name="Plotting Points",
        default=10,
        min=1,
        options={'HIDDEN'},
    )
    part_plotting_bones: CollectionProperty(type=GESTUREBONE_PG_BoneName)
    plotting_bones_expanded: BoolProperty(name="Plotting Bones", default=False)

    # ── Runtime state ──────────────────────────────────────────────────────────
    is_bound: BoolProperty(name="Bound", default=False)
    is_drawing: BoolProperty(name="Drawing", default=False)
    bones_expanded: BoolProperty(name="Bones", default=False)

    last_baked_frame: IntProperty(name="Last Baked Frame", default=-1)
    drawing_frame: IntProperty(name="Drawing Frame", default=-1)


def register():
    bpy.utils.register_class(GESTUREBONE_PG_BoneName)
    bpy.utils.register_class(GESTUREBONE_PG_CurveBoneChain)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PG_CurveBoneChain)
    bpy.utils.unregister_class(GESTUREBONE_PG_BoneName)
