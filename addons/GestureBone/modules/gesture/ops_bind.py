"""
gesture/ops_bind.py — Chain loading, constraint management, spline direction, chain refresh.
"""
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, EnumProperty
from ..shared.utils import (
    _arm, _chains_for_gesture_rig, _ensure_chain_objects,
    _cleanup_orphan_splines, _resize_collection,
)
from ..shared.utils_constraints import (
    _CONSTRAINT_NAME, _CONSTRAINT_TYPE,
    _mute_constraints, _constraints_exist,
)
from ..shared.utils_gn import _sync_gesture_spline_gn
from ..shared.chain import CONTROL_MODE_COUNT, _ctrl_bone_indices

_GN_GESTURE_NAME = "TOB-Gesture_drawing"


def _resolve(context, part_name):
    """Return (gesture_arm, chain) from the current context and part_name.

    Works whether the active object is a GESTURE or PLOTTING rig.
    """
    arm = _arm(context)
    if arm is None:
        return None, None

    rtype = arm.gesturebone_props.rig_type

    if rtype == 'GESTURE':
        gesture_arm = arm
        plotting    = arm.gesturebone_props.plotting_rig
        if plotting is None:
            return arm, None
        chain = plotting.gesturebone_props.chains.get(part_name)
        return gesture_arm, chain

    if rtype == 'PLOTTING':
        chain       = arm.gesturebone_props.chains.get(part_name)
        gesture_arm = chain.gesture_rig if chain else None
        return gesture_arm, chain

    return None, None


# ── LOAD CHAINS ───────────────────────────────────────────────────────────────

class GESTUREBONE_OT_LoadChains(bpy.types.Operator):
    """Load chains from the plotting rig and link gesture splines + control bones."""
    bl_idname      = "gesturebone.load_chains"
    bl_label       = "Load Chains"
    bl_description = "Link gesture splines and control bones for all chains of this GESTURE rig"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Select a GESTURE rig first")
            return {'CANCELLED'}

        if arm.gesturebone_props.rig_type != 'GESTURE':
            self.report({'ERROR'}, f"'{arm.name}' is not tagged as a GESTURE rig")
            return {'CANCELLED'}

        plotting = arm.gesturebone_props.plotting_rig
        if plotting is None or plotting.gesturebone_props.rig_type != 'PLOTTING':
            self.report({'ERROR'}, "plotting_rig pointer is not set or not a PLOTTING rig")
            return {'CANCELLED'}

        # Clear stale drawing state
        from . import ops_bake as _ob
        _ob.clear_all_drawing_state()

        meta_name = plotting.name
        chains    = _chains_for_gesture_rig(arm)

        loaded = 0
        for chain in chains:
            part_name = chain.part_name

            # Link GestureSpline
            g_name = f"{meta_name}-{part_name}.GestureSpline"
            g_obj  = bpy.data.objects.get(g_name)
            if g_obj and g_obj.type == 'CURVE':
                chain.gesture_spline = g_obj

            # Link PlottingSpline
            p_name = f"{meta_name}-{part_name}.PlottingSpline"
            p_obj  = bpy.data.objects.get(p_name)
            if p_obj and p_obj.type == 'CURVE':
                chain.plotting_spline = p_obj

            # Populate control bones
            count = CONTROL_MODE_COUNT.get(chain.control_mode, 5)
            chain.control_point_count = count
            _resize_collection(chain.control_bones, count)
            indices = _ctrl_bone_indices(count)
            for i, entry in enumerate(chain.control_bones):
                if i < len(indices):
                    ctrl_name = f"CTRL-{part_name}_{indices[i]}"
                    entry.bone = ctrl_name if arm.data.bones.get(ctrl_name) else entry.bone

            # Auto-create/refresh constraints and sync GN modifier
            if chain.gesture_spline:
                _ensure_and_refresh_constraints(arm, chain)
                _sync_gesture_spline_gn(chain)

            loaded += 1

        self.report({'INFO'}, f"Loaded {loaded} chain(s) onto '{arm.name}'")
        return {'FINISHED'}


def _ensure_and_refresh_constraints(gesture_arm, chain):
    """Create or refresh GEOMETRY_ATTRIBUTE constraints on all CTRL bones.

    Always recreates — sample_index values can be stale when the template already
    carries Gesture_copy constraints with wrong indices (e.g. _3/_4 at 0 instead
    of 3/4). The inner function removes existing constraints before adding new ones.
    """
    _create_constraints_for_chain(gesture_arm, chain)


def _create_constraints_for_chain(gesture_arm, chain):
    """Internal: create muted GEOMETRY_ATTRIBUTE constraints on CTRL bones."""
    gesture_spline = chain.gesture_spline
    if not gesture_spline:
        return

    from ..shared.utils import bone_names as _bnames
    for i, bname in enumerate(_bnames(chain)):
        pb = gesture_arm.pose.bones.get(bname)
        if pb is None:
            continue
        for c in list(pb.constraints):
            if c.type == _CONSTRAINT_TYPE:
                pb.constraints.remove(c)
        con                       = pb.constraints.new(type=_CONSTRAINT_TYPE)
        con.name                  = _CONSTRAINT_NAME
        con.target                = gesture_spline
        con.apply_target_transform = True
        con.attribute_name        = "instance_transform"
        con.data_type             = 'FLOAT4X4'
        con.domain                = 'INSTANCE'
        con.sample_index          = i
        con.mix_mode              = 'REPLACE'
        con.influence             = 1.0
        con.mute                  = True
    chain.is_bound = True


# ── CREATE / DELETE CONSTRAINTS ───────────────────────────────────────────────

class GESTUREBONE_OT_CreateBoneConstraints(bpy.types.Operator):
    bl_idname      = "gesturebone.create_bone_constraints"
    bl_label       = "Bind"
    bl_description = "Add Gesture_copy GEOMETRY_ATTRIBUTE constraints to this chain's CTRL bones"
    bl_options     = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        gesture_arm, chain = _resolve(context, self.part_name)
        if gesture_arm is None or chain is None:
            self.report({'ERROR'}, "Could not resolve gesture arm / chain")
            return {'CANCELLED'}
        if not chain.gesture_spline:
            self.report({'ERROR'}, "No gesture spline — load chains first")
            return {'CANCELLED'}
        _create_constraints_for_chain(gesture_arm, chain)
        return {'FINISHED'}


class GESTUREBONE_OT_DeleteBoneConstraints(bpy.types.Operator):
    bl_idname      = "gesturebone.delete_bone_constraints"
    bl_label       = "Unbind"
    bl_description = "Remove Gesture_copy constraints from this chain's CTRL bones"
    bl_options     = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        gesture_arm, chain = _resolve(context, self.part_name)
        if gesture_arm is None or chain is None:
            return {'CANCELLED'}
        from ..shared.utils import bone_names as _bnames
        for bname in _bnames(chain):
            pb = gesture_arm.pose.bones.get(bname)
            if pb:
                for c in list(pb.constraints):
                    if c.name == _CONSTRAINT_NAME:
                        pb.constraints.remove(c)
        chain.is_bound = False
        return {'FINISHED'}


class GESTUREBONE_OT_ToggleConstraintActive(bpy.types.Operator):
    bl_idname      = "gesturebone.toggle_constraint_active"
    bl_label       = "Toggle Live Preview"
    bl_description = "Toggle Gesture_copy constraints on/off for live preview"
    bl_options     = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        from ..shared.utils_constraints import _unmute_constraints, _constraints_are_muted
        gesture_arm, chain = _resolve(context, self.part_name)
        if gesture_arm is None or chain is None:
            return {'CANCELLED'}
        if not _constraints_exist(gesture_arm, chain):
            _create_constraints_for_chain(gesture_arm, chain)
            _unmute_constraints(gesture_arm, chain)
        elif _constraints_are_muted(gesture_arm, chain):
            _unmute_constraints(gesture_arm, chain)
        else:
            _mute_constraints(gesture_arm, chain)
        return {'FINISHED'}


# ── SWITCH CURVE DIRECTION ────────────────────────────────────────────────────

def _switch_spline_direction(curve_obj):
    reversed_count = 0
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            pts  = spline.bezier_points
            n    = len(pts)
            snap = [(
                p.co.copy(),
                p.handle_left.copy(),  p.handle_right.copy(),
                p.handle_left_type,    p.handle_right_type,
                p.radius, p.tilt, p.weight_softbody,
            ) for p in pts]
            for i, p in enumerate(pts):
                co, hl, hr, ht_l, ht_r, rad, tilt, wsb = snap[n - 1 - i]
                p.co                = co
                p.handle_left       = hr
                p.handle_right      = hl
                p.handle_left_type  = ht_r
                p.handle_right_type = ht_l
                p.radius            = rad
                p.tilt              = tilt
                p.weight_softbody   = wsb
            reversed_count += 1
        elif spline.type in ('NURBS', 'POLY'):
            pts  = spline.points
            n    = len(pts)
            snap = [(p.co.copy(), p.radius, p.tilt, p.weight_softbody) for p in pts]
            for i, p in enumerate(pts):
                co, rad, tilt, wsb = snap[n - 1 - i]
                p.co              = co
                p.radius          = rad
                p.tilt            = tilt
                p.weight_softbody = wsb
            reversed_count += 1
    curve_obj.data.update_tag()
    return reversed_count


class GESTUREBONE_OT_SwitchCurveDirection(bpy.types.Operator):
    bl_idname      = "gesturebone.switch_curve_direction"
    bl_label       = "Switch Curve Direction"
    bl_description = "Reverse the gesture spline direction for this chain"
    bl_options     = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        _, chain = _resolve(context, self.part_name)
        if chain is None:
            return {'CANCELLED'}
        if not chain.gesture_spline:
            self.report({'WARNING'}, "No gesture spline assigned")
            return {'CANCELLED'}
        n = _switch_spline_direction(chain.gesture_spline)
        self.report({'INFO'}, f"Switched direction of '{chain.gesture_spline.name}' ({n} spline(s))")
        return {'FINISHED'}


# ── REFRESH ───────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_RefreshChain(bpy.types.Operator):
    bl_idname      = "gesturebone.refresh_chain"
    bl_label       = "Refresh Chain"
    bl_description = "Re-link spline, resize bone list, and sync GN modifier for this chain"
    bl_options     = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        gesture_arm, chain = _resolve(context, self.part_name)
        if chain is None:
            return {'CANCELLED'}
        plotting = gesture_arm.gesturebone_props.plotting_rig if gesture_arm else None
        if plotting:
            _ensure_chain_objects(plotting, chain, context)
        count = CONTROL_MODE_COUNT.get(chain.control_mode, 5)
        chain.control_point_count = count
        _resize_collection(chain.control_bones, count)
        if gesture_arm:
            indices = _ctrl_bone_indices(count)
            for i, entry in enumerate(chain.control_bones):
                if i < len(indices):
                    ctrl_name = f"CTRL-{chain.part_name}_{indices[i]}"
                    entry.bone = ctrl_name if gesture_arm.data.bones.get(ctrl_name) else entry.bone
        if chain.gesture_spline:
            _sync_gesture_spline_gn(chain)
        return {'FINISHED'}


class GESTUREBONE_OT_RefreshAllChains(bpy.types.Operator):
    bl_idname      = "gesturebone.refresh_all_chains"
    bl_label       = "Refresh All Chains"
    bl_description = "Refresh all chains and clean orphan splines"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _arm(context)
        if arm is None:
            self.report({'ERROR'}, "Select a GESTURE rig first")
            return {'CANCELLED'}

        chains = _chains_for_gesture_rig(arm) if arm.gesturebone_props.rig_type == 'GESTURE' else []
        plotting = arm.gesturebone_props.plotting_rig

        for chain in chains:
            if plotting:
                _ensure_chain_objects(plotting, chain, context)
            count = CONTROL_MODE_COUNT.get(chain.control_mode, 5)
            chain.control_point_count = count
            _resize_collection(chain.control_bones, count)
            if chain.gesture_spline:
                _sync_gesture_spline_gn(chain)
                _ensure_and_refresh_constraints(arm, chain)

        if plotting:
            _cleanup_orphan_splines(plotting, chains, context.scene)

        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_LoadChains,
    GESTUREBONE_OT_CreateBoneConstraints,
    GESTUREBONE_OT_DeleteBoneConstraints,
    GESTUREBONE_OT_ToggleConstraintActive,
    GESTUREBONE_OT_SwitchCurveDirection,
    GESTUREBONE_OT_RefreshChain,
    GESTUREBONE_OT_RefreshAllChains,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
