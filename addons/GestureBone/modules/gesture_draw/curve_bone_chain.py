import bpy
from bpy.props import (
    StringProperty, PointerProperty, BoolProperty,
    IntProperty, CollectionProperty, EnumProperty,
)
from .utils import _resize_collection, _ensure_chain_objects, _ensure_gp_layer


# ── Mode → bone-count mappings ─────────────────────────────────────────────────

CONTROL_MODES = [
    ('SYM_5', "5 Symmetry", "5 control points — symmetric rig (one side mirrored)"),
    ('LIN_5', "5 Linear",   "5 control points — linear, full chain"),
    ('LIN_3', "3 Linear",   "3 control points — linear, full chain"),
]
CONTROL_MODE_COUNT = {
    'SYM_5': 5,
    'LIN_5': 5,
    'LIN_3': 3,
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


def _layer_search(self, context, edit_text):
    arm = context.active_object if context and context.active_object and context.active_object.type == 'ARMATURE' else None
    if arm is None:
        arm = getattr(getattr(context.scene, 'gesturebone_props', None), 'current_armature', None)
    if arm:
        mod_props = getattr(arm, 'gesturebone_gesture_draw_props', None)
        if mod_props and mod_props.part_gp:
            gp_data = mod_props.part_gp.data
            if hasattr(gp_data, 'layers'):
                return [l.name for l in gp_data.layers if edit_text.lower() in l.name.lower()]
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
    _arm_ref = arm
    _chain_ref = self
    def _deferred_layer():
        _ensure_gp_layer(_arm_ref, _chain_ref)
        return None
    bpy.app.timers.register(_deferred_layer, first_interval=0.0)


def _on_control_mode_update(self, context):
    count = CONTROL_MODE_COUNT.get(self.part_control_mode, 5)
    self.part_control_point_count = count
    _resize_collection(self.part_control_bones, count)


def _on_plotting_mode_update(self, context):
    count = PLOTTING_MODE_COUNT.get(self.part_plotting_mode, 10)
    self.part_plotting_point_count = count
    _resize_collection(self.part_plotting_bones, count)


# ── Property groups ────────────────────────────────────────────────────────────

class GESTUREBONE_PG_BoneName(bpy.types.PropertyGroup):
    bone: StringProperty(name="Bone", search=_bone_search)


class GESTUREBONE_PG_CurveBoneChain(bpy.types.PropertyGroup):
    # ── Core identity ──────────────────────────────────────────────────────────
    part_name: StringProperty(name="Name", default="Chain", update=_on_part_name_update)
    part_layer: StringProperty(name="Layer", search=_layer_search)
    part_material: PointerProperty(name="Material", type=bpy.types.Material)
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
        default='SYM_5',
        update=_on_control_mode_update,
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

    prev_active_object: StringProperty(default="")
    prev_mode: StringProperty(default="OBJECT")

    last_baked_frame: IntProperty(name="Last Baked Frame", default=-1)
    stroke_count_cache: IntProperty(name="Stroke Count Cache", default=0)
    drawing_frame: IntProperty(name="Drawing Frame", default=-1)


def register():
    bpy.utils.register_class(GESTUREBONE_PG_BoneName)
    bpy.utils.register_class(GESTUREBONE_PG_CurveBoneChain)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PG_CurveBoneChain)
    bpy.utils.unregister_class(GESTUREBONE_PG_BoneName)
