"""
curvechain/ops.py — Operators for the single-armature rig.

    gesturebone.cc_convert   GESTURE + PLOTTING pair → one UNIFIED armature
    gesturebone.cc_draw      arm the Annotate tool on this chain's layer (stays in Pose mode)
    gesturebone.cc_apply     fit the latest stroke on this frame, key the chain
    gesturebone.cc_flip      reverse the latest stroke (when auto-orient guesses wrong)
    gesturebone.cc_clear     delete the chain's strokes on this frame
    gesturebone.cc_delete_keys  remove this chain's keys on the current frame
    gesturebone.cc_rebuild   rebuild the hidden B-Bone machinery (after a plane change)
"""
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty

from . import builder as bd, fit, convert as cv
from ..shared.utils import _arm


def _unified(context):
    arm = _arm(context)
    if arm is None or arm.gesturebone_props.rig_type != cv.UNIFIED:
        return None
    return arm


def _chain_by_part(arm, part):
    for c in arm.gesturebone_props.chains:
        if c.part_name == part:
            return c
    return None


class GESTUREBONE_OT_CCConvert(bpy.types.Operator):
    """Merge the Plotting rig into this Gesture rig, replace every Gesture/Plotting
    curve and its Geometry Nodes with B-Bone machinery inside the one armature"""
    bl_idname = "gesturebone.cc_convert"
    bl_label = "Convert to Single Rig"
    bl_options = {'REGISTER', 'UNDO'}

    keep_look: BoolProperty(
        name="Keep Existing Look", default=True,
        description="Face chains along the armature's front plane like the old rig did, so existing "
                    "animation deforms the same. Off: chains follow their root bone")
    spacing: EnumProperty(
        name="Spacing", default='UNIFORM',
        items=[('UNIFORM', "Even", "Deform samples stay evenly spaced along the whole chain (like the old rig)"),
               ('FIXED', "Per Span", "Samples are fixed per span — cheaper, but bunch up when spans stretch unevenly")])

    @classmethod
    def poll(cls, context):
        arm = _arm(context)
        return arm is not None and arm.gesturebone_props.rig_type == 'GESTURE'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        plan = cv.collect(_arm(context))
        col = self.layout.column(align=True)
        col.label(text=f"{plan['gesture']}  ←  {plan['plotting']}", icon='ARMATURE_DATA')
        col.label(text=f"{len(plan['chains'])} chains, {len(plan['meshes'])} meshes, "
                       f"{len(plan['splines'])} curves removed")
        for e in plan["errors"]:
            r = col.row(); r.alert = True; r.label(text=e, icon='ERROR')
        self.layout.prop(self, "keep_look")
        self.layout.prop(self, "spacing", expand=True)

    def execute(self, context):
        arm = _arm(context)
        plan = cv.convert(arm, spacing=self.spacing, plane='ARMATURE' if self.keep_look else 'ROOT')
        if plan["errors"]:
            for e in plan["errors"]:
                self.report({'ERROR'}, e)
            return {'CANCELLED'} if not plan.get("built") else {'FINISHED'}
        for chain in arm.gesturebone_props.chains:
            chain.plane_space = 'ARMATURE' if self.keep_look else 'ROOT'
        self.report({'INFO'}, f"Single rig: {len(plan['built'])} chains, {plan['renamed']} handle bones renamed")
        return {'FINISHED'}


class GESTUREBONE_OT_CCDraw(bpy.types.Operator):
    """Draw this chain with the Annotate tool (D + drag). Stays in Pose mode"""
    bl_idname = "gesturebone.cc_draw"
    bl_label = "Draw Chain"
    bl_options = {'REGISTER'}

    part_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return _unified(context) is not None

    def execute(self, context):
        arm = _unified(context)
        chain = _chain_by_part(arm, self.part_name)
        if chain is None:
            return {'CANCELLED'}
        for other in arm.gesturebone_props.chains:
            other.is_drawing = other == chain
        lay = fit.chain_layer(context.scene, chain.part_name, create=True)
        ann = fit.scene_annotation(context.scene)
        ann.layers.active_index = list(ann.layers).index(lay)
        ts = context.scene.tool_settings
        ts.annotation_stroke_placement_view3d = 'CURSOR'
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.annotate", space_type='VIEW_3D')
        except RuntimeError:
            pass
        chain.drawing_frame = context.scene.frame_current
        self.report({'INFO'}, f"Draw '{chain.part_name}', then Apply")
        return {'FINISHED'}


class GESTUREBONE_OT_CCApply(bpy.types.Operator):
    """Snap this chain's control points and handles to the latest stroke and key them"""
    bl_idname = "gesturebone.cc_apply"
    bl_label = "Apply Stroke"
    bl_options = {'REGISTER', 'UNDO'}

    part_name: StringProperty()
    clear_stroke: BoolProperty(name="Clear Stroke", default=True,
                               description="Remove the chain's strokes on this frame after applying")
    auto_direction: BoolProperty(name="Auto Direction", default=True,
                                 description="Start the chain at whichever stroke end is nearer its first point")

    @classmethod
    def poll(cls, context):
        return _unified(context) is not None

    def execute(self, context):
        arm = _unified(context)
        chain = _chain_by_part(arm, self.part_name)
        if chain is None:
            return {'CANCELLED'}
        fr, stroke = fit.latest_stroke(context.scene, chain.part_name, context.scene.frame_current)
        if stroke is None or len(stroke.points) < 2:
            self.report({'WARNING'}, f"No stroke on layer '{fit.layer_name(chain.part_name)}' at this frame")
            return {'CANCELLED'}
        pts = [p.co.copy() for p in stroke.points]
        if context.object and context.object.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='POSE')
        try:
            rep = fit.apply_fit(context, arm, chain, pts, view=fit.view_from_context(context),
                                auto_direction=self.auto_direction)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if self.clear_stroke:
            fit.clear_frame(context.scene, chain.part_name, fr)
        chain.is_drawing = False
        self.report({'INFO'}, f"'{chain.part_name}' keyed on frame {rep['frame']}"
                              + (" (stroke reversed)" if rep["reversed"] else ""))
        return {'FINISHED'}


class GESTUREBONE_OT_CCFlip(bpy.types.Operator):
    """Reverse the latest stroke of this chain (use with Auto Direction off)"""
    bl_idname = "gesturebone.cc_flip"
    bl_label = "Flip Stroke"
    bl_options = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        _, stroke = fit.latest_stroke(context.scene, self.part_name, context.scene.frame_current)
        if stroke is None:
            return {'CANCELLED'}
        cos = [p.co.copy() for p in stroke.points]
        for p, co in zip(stroke.points, reversed(cos)):
            p.co = co
        return {'FINISHED'}


class GESTUREBONE_OT_CCClear(bpy.types.Operator):
    """Delete this chain's strokes on the current frame"""
    bl_idname = "gesturebone.cc_clear"
    bl_label = "Clear Strokes"
    bl_options = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    def execute(self, context):
        fr, _ = fit.latest_stroke(context.scene, self.part_name, context.scene.frame_current)
        if fr is None:
            return {'CANCELLED'}
        fit.clear_frame(context.scene, self.part_name, fr)
        return {'FINISHED'}


class GESTUREBONE_OT_CCDeleteKeys(bpy.types.Operator):
    """Remove this chain's keys (points and handles) on the current frame"""
    bl_idname = "gesturebone.cc_delete_keys"
    bl_label = "Delete Chain Keys"
    bl_options = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return _unified(context) is not None

    def execute(self, context):
        arm = _unified(context)
        chain = _chain_by_part(arm, self.part_name)
        if chain is None:
            return {'CANCELLED'}
        f = context.scene.frame_current
        n = 0
        for bname in fit.chain_bones(arm, chain):
            pb = arm.pose.bones[bname]
            for path in ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale"):
                try:
                    if pb.keyframe_delete(path, frame=f):
                        n += 1
                except RuntimeError:
                    pass
        self.report({'INFO'}, f"Removed {n} key channel(s) on frame {f}")
        return {'FINISHED'}


class GESTUREBONE_OT_CCRebuild(bpy.types.Operator):
    """Rebuild this chain's hidden B-Bone machinery (after changing its plane)"""
    bl_idname = "gesturebone.cc_rebuild"
    bl_label = "Rebuild Chain"
    bl_options = {'REGISTER', 'UNDO'}

    part_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return _unified(context) is not None

    def execute(self, context):
        arm = _unified(context)
        chain = _chain_by_part(arm, self.part_name)
        if chain is None:
            return {'CANCELLED'}
        idx = bd.chain_indices(chain)
        bd.build_chain(arm, chain.part_name, idx, chain.plane_space)
        samplers = bd.samplers_of(arm, chain.part_name)
        if samplers:
            bd.bind_samplers(arm, chain.part_name, idx, samplers, bd.spacing_of(arm, chain.part_name))
            bd.apply_layer_depth(arm, chain.part_name, chain.layer_depth)
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_CCConvert,
    GESTUREBONE_OT_CCDraw,
    GESTUREBONE_OT_CCApply,
    GESTUREBONE_OT_CCFlip,
    GESTUREBONE_OT_CCClear,
    GESTUREBONE_OT_CCDeleteKeys,
    GESTUREBONE_OT_CCRebuild,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
