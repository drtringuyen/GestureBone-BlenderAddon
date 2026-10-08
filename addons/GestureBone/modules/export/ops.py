"""
export/ops.py — Operators for the Export section.
"""
import re
import bpy
from bpy.props import EnumProperty, BoolProperty

from ..shared.utils import _arm
from . import weights as W, optimize as O, gamerig as G


def _rig(context):
    arm = _arm(context)
    if arm is None or arm.gesturebone_props.rig_type != 'UNIFIED':
        return None
    return arm


class _RigOp:
    @classmethod
    def poll(cls, context):
        return _rig(context) is not None


class GESTUREBONE_OT_ExportBakeWeights(_RigOp, bpy.types.Operator):
    """Write the weight node's result into vertex groups and mute it (fast playback).
    Use Live to tweak the node again"""
    bl_idname = "gesturebone.export_bake_weights"
    bl_label = "Bake Weights"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rep = W.bake_all(_rig(context))
        done = [n for n, (ok, _) in rep.items() if ok]
        for n, (ok, msg) in rep.items():
            if not ok:
                self.report({'WARNING'}, f"{n}: {msg}")
        self.report({'INFO'}, f"Baked {len(done)} of {len(rep)} chain mesh(es)")
        return {'FINISHED'}


class GESTUREBONE_OT_ExportLiveWeights(_RigOp, bpy.types.Operator):
    """Unmute the weight node so weights are computed live (tweak and preview)"""
    bl_idname = "gesturebone.export_live_weights"
    bl_label = "Live Weights"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        names = W.live_all(_rig(context))
        self.report({'INFO'}, f"{len(names)} mesh(es) back on live weights")
        return {'FINISHED'}


class GESTUREBONE_OT_ExportOptimize(_RigOp, bpy.types.Operator):
    """Make the B-Bone spans the deform bones (BDEF-) and delete the STR/AXIS/SIZE/DEF stack.
    Writes <file>_beforeBDEF.blend first"""
    bl_idname = "gesturebone.export_optimize"
    bl_label = "Convert to Blender Optimized"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Convert to Blender Optimized?",
            message="Deletes the template deform stack; a backup file is written first. "
                    "Do this in the CHR file, then use Repair ANIM File in each shot.",
            confirm_text="Convert")

    def execute(self, context):
        arm = _rig(context)
        rep = O.convert(arm)
        for e in rep["errors"]:
            self.report({'ERROR'}, e)
        if rep["errors"]:
            return {'CANCELLED'}
        msg = f"Blender Optimized: {len(rep['chains'])} chains, backup {rep['backup']}"
        if rep.get("rebake"):
            msg += " — weights are live again, Bake when happy"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class GESTUREBONE_OT_ExportPreview(_RigOp, bpy.types.Operator):
    """Build (or rebuild) the temporary game-export rig and mesh copies and show them.
    The weight node stays live on the copies: tweak it, change Segments per Span, update"""
    bl_idname = "gesturebone.export_preview"
    bl_label = "Preview Game Rig"
    bl_options = {'REGISTER', 'UNDO'}

    clear: BoolProperty(default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        arm = _rig(context)
        if self.clear:
            n = G.clear(arm)
            self.report({'INFO'}, f"Game preview removed ({n} objects)")
            return {'FINISHED'}
        try:
            rep = G.build(context, arm)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Game rig: {rep['bones']} bones ({rep['segment_bones']} span segments), "
                              f"{len(rep['meshes'])} mesh copies")
        return {'FINISHED'}


class GESTUREBONE_OT_ExportGame(_RigOp, bpy.types.Operator):
    """Bake the game rig's animation and write the file, then remove the temporary objects"""
    bl_idname = "gesturebone.export_game"
    bl_label = "Export"
    bl_options = {'REGISTER'}

    target: EnumProperty(items=[('FBX', "Unity (FBX)", ""), ('GLB', "Godot (glTF)", "")], default='FBX')

    def execute(self, context):
        arm = _rig(context)
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            path = G.export(context, arm, self.target)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        context.view_layer.objects.active = arm
        self.report({'INFO'}, f"Exported {path}")
        return {'FINISHED'}


# ── Repair ANIM file ──────────────────────────────────────────────────────────

RENAMES = ((".hL", ".hA"), (".hR", ".hB"), (".End.L", ".End.A"), (".End.R", ".End.B"))
_rx = re.compile(r'pose\.bones\["([^"]+)"\]')


def _local_actions(ob):
    ad = ob.animation_data
    acts = []
    if ad:
        if ad.action:
            acts.append(ad.action)
        for tr in ad.nla_tracks:
            for st in tr.strips:
                if st.action:
                    acts.append(st.action)
    return [a for a in dict.fromkeys(acts) if a.library is None]


def _fcurves(action):
    fcs = getattr(action, "fcurves", None)
    if fcs is not None:
        return list(fcs)
    return [f for l in action.layers for st in l.strips for cb in st.channelbags for f in cb.fcurves]


def repair_handle_names(arm):
    """Rename keys on the old handle names in this file's local actions of `arm`.
    Only renames when the old bone no longer exists on the rig and the new one
    does. Returns {action: count}."""
    bones = arm.data.bones
    out = {}
    for act in _local_actions(arm):
        n = 0
        for fc in _fcurves(act):
            m = _rx.match(fc.data_path)
            if not m or bones.get(m.group(1)) is not None:
                continue
            old = m.group(1)
            for a, b in RENAMES:
                if old.endswith(a) and bones.get(old[: -len(a)] + b) is not None:
                    new = old[: -len(a)] + b
                    fc.data_path = fc.data_path.replace(f'["{old}"]', f'["{new}"]', 1)
                    if fc.group and fc.group.name == old:
                        fc.group.name = new
                    n += 1
                    break
        if n:
            out[act.name] = n
    return out


def stale_handle_keys(arm):
    n = 0
    bones = arm.data.bones
    for act in _local_actions(arm):
        for fc in _fcurves(act):
            m = _rx.match(fc.data_path)
            if m and bones.get(m.group(1)) is None and m.group(1).endswith(tuple(a for a, _ in RENAMES)):
                n += 1
    return n


class GESTUREBONE_OT_RepairAnimFile(_RigOp, bpy.types.Operator):
    """Point keys made on the old handle names (.hL/.hR, .End.L/.End.R) at the renamed
    bones (.hA/.hB, .End.A/.End.B) in this file's local actions"""
    bl_idname = "gesturebone.repair_anim_file"
    bl_label = "Repair ANIM File"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rep = repair_handle_names(_rig(context))
        total = sum(rep.values())
        self.report({'INFO'}, f"Repaired {total} key channel(s) in {len(rep)} action(s)" if total
                    else "Nothing to repair")
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_ExportBakeWeights,
    GESTUREBONE_OT_ExportLiveWeights,
    GESTUREBONE_OT_ExportOptimize,
    GESTUREBONE_OT_ExportPreview,
    GESTUREBONE_OT_ExportGame,
    GESTUREBONE_OT_RepairAnimFile,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
