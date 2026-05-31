"""
plotting/ops_create.py — AppendEssentials and CreateRig operators.
"""
import bpy
import os
from .utils import _active_plotting_arm, _ensure_object_mode, _default_template
from ..shared.utils import _delete_coll, _bones_in_bone_coll

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── APPEND ESSENTIALS ─────────────────────────────────────────────────────────

class GESTUREBONE_OT_AppendEssentials(bpy.types.Operator):
    bl_idname      = "gesturebone.append_essentials"
    bl_label       = "Load Essentials"
    bl_description = "Append all data from essentials.blend and make any linked data local"
    bl_options     = {'REGISTER', 'UNDO'}

    _TEMPLATE_COLL = "Atomic Chains"

    def execute(self, context):
        essentials_path = os.path.join(_ADDON_DIR, "essentials.blend")
        if not os.path.exists(essentials_path):
            self.report({'ERROR'}, f"essentials.blend not found: {essentials_path}")
            return {'CANCELLED'}

        _ensure_object_mode(context)

        with bpy.data.libraries.load(essentials_path, link=False) as (src, _):
            src_ngs    = list(src.node_groups)
            src_has_ac = self._TEMPLATE_COLL in src.collections

        old_coll = bpy.data.collections.get(self._TEMPLATE_COLL)
        if old_coll:
            _delete_coll(old_coll)

        for ng_name in src_ngs:
            ng = bpy.data.node_groups.get(ng_name)
            if ng:
                bpy.data.node_groups.remove(ng)

        bpy.ops.outliner.orphans_purge(do_linked_ids=True, do_recursive=True)

        appended_ngs = []
        with bpy.data.libraries.load(essentials_path, link=False) as (src, dst):
            if src_has_ac:
                dst.collections = [self._TEMPLATE_COLL]
            dst.node_groups = list(src.node_groups)
            appended_ngs    = list(src.node_groups)

        coll = bpy.data.collections.get(self._TEMPLATE_COLL)
        if coll and self._TEMPLATE_COLL not in {c.name for c in context.scene.collection.children}:
            context.scene.collection.children.link(coll)

        def _hide_recursive(c):
            c.hide_viewport = True
            for child in c.children:
                _hide_recursive(child)

        def _find_lc(lc, name):
            if lc.name == name:
                return lc
            for child in lc.children:
                found = _find_lc(child, name)
                if found:
                    return found
            return None

        if coll:
            _hide_recursive(coll)
            lc = _find_lc(context.view_layer.layer_collection, self._TEMPLATE_COLL)
            if lc:
                lc.hide_viewport = True

        outliner = next((a for a in context.screen.areas if a.type == 'OUTLINER'), None)
        if outliner:
            region = next((r for r in outliner.regions if r.type == 'WINDOW'), None)
            if region:
                with context.temp_override(area=outliner, region=region):
                    for _ in range(6):
                        bpy.ops.outliner.show_one_level(open=False)

        parts = []
        if src_has_ac:
            parts.append(f"'{self._TEMPLATE_COLL}' replaced")
        if appended_ngs:
            parts.append(f"{len(appended_ngs)} node group(s) replaced")
        self.report({'INFO'}, f"Load Essentials: {', '.join(parts) or 'done'}")
        return {'FINISHED'}


# ── CREATE RIG ────────────────────────────────────────────────────────────────

def _rig_preset_items(self, context):
    items = [
        (o.name, o.name, '')
        for o in bpy.data.objects
        if o.type == 'ARMATURE' and (
            o.gesturebone_props.rig_type == 'PRESET'
            or 'gesturebone_rig_preset' in o  # backward compat
        )
    ]
    return items if items else [('NONE', 'No presets found', '')]


class GESTUREBONE_OT_CreateRig(bpy.types.Operator):
    bl_idname      = "gesturebone.create_rig"
    bl_label       = "Create Rig"
    bl_description = "Duplicate a Rig Preset into a new named armature tagged as PLOTTING"
    bl_options     = {'REGISTER', 'UNDO'}

    new_rig_name: bpy.props.StringProperty(name="New Rig Name", default="MyRig")
    rig_preset:   bpy.props.EnumProperty(name="Rig Preset", items=_rig_preset_items)

    def invoke(self, context, event):
        presets = [
            o for o in bpy.data.objects
            if o.type == 'ARMATURE' and (
                o.gesturebone_props.rig_type == 'PRESET'
                or 'gesturebone_rig_preset' in o
            )
        ]
        if not presets:
            self.report({'ERROR'}, "No armature tagged as Rig Preset found")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "rig_preset")
        layout.prop(self, "new_rig_name")

    def execute(self, context):
        name = self.new_rig_name.strip()
        if not name:
            self.report({'ERROR'}, "New rig name cannot be empty")
            return {'CANCELLED'}
        if self.rig_preset == 'NONE':
            self.report({'ERROR'}, "No Rig Preset selected")
            return {'CANCELLED'}

        sample = bpy.data.objects.get(self.rig_preset)
        if sample is None or sample.type != 'ARMATURE':
            self.report({'ERROR'}, f"Rig Preset '{self.rig_preset}' not found")
            return {'CANCELLED'}

        _ensure_object_mode(context)

        existing = bpy.data.objects.get(name)
        if existing and existing not in context.scene.objects.values():
            bpy.data.objects.remove(existing, do_unlink=True)

        new_data      = sample.data.copy()
        new_data.name = name
        new_obj       = bpy.data.objects.new(name, new_data)
        context.scene.collection.objects.link(new_obj)
        context.view_layer.update()

        for key, val in sample.items():
            new_obj[key] = val

        for src_pb in (sample.pose.bones if sample.pose else []):
            dst_pb = new_obj.pose.bones.get(src_pb.name)
            if dst_pb is None:
                continue
            dst_pb.custom_shape                = src_pb.custom_shape
            dst_pb.custom_shape_scale_xyz      = src_pb.custom_shape_scale_xyz[:]
            dst_pb.custom_shape_translation    = src_pb.custom_shape_translation[:]
            dst_pb.custom_shape_rotation_euler = src_pb.custom_shape_rotation_euler[:]
            dst_pb.use_custom_shape_bone_size  = src_pb.use_custom_shape_bone_size
            dst_pb.color.palette               = src_pb.color.palette
            dst_pb.rotation_mode               = src_pb.rotation_mode
            dst_pb.location                    = src_pb.location[:]
            dst_pb.scale                       = src_pb.scale[:]
            if src_pb.rotation_mode == 'QUATERNION':
                dst_pb.rotation_quaternion = src_pb.rotation_quaternion[:]
            elif src_pb.rotation_mode == 'AXIS_ANGLE':
                dst_pb.rotation_axis_angle = src_pb.rotation_axis_angle[:]
            else:
                dst_pb.rotation_euler = src_pb.rotation_euler[:]

        # Tag as PLOTTING (replaces gesturebone_gesture_rigged custom prop)
        new_obj.gesturebone_props.rig_type = 'PLOTTING'
        # Keep old prop for backward compat with scene_props.py dropdowns during transition
        new_obj["gesturebone_gesture_rigged"] = True
        if "gesturebone_rig_preset" in new_obj:
            del new_obj["gesturebone_rig_preset"]

        # Collection setup
        rig_coll = bpy.data.collections.get(name)
        if rig_coll is None:
            rig_coll = bpy.data.collections.new(name)
            context.scene.collection.children.link(rig_coll)
        for c in list(new_obj.users_collection):
            c.objects.unlink(new_obj)
        rig_coll.objects.link(new_obj)

        mesh_coll_name = f"{name}.Mesh"
        if bpy.data.collections.get(mesh_coll_name) is None:
            mesh_coll = bpy.data.collections.new(mesh_coll_name)
            rig_coll.children.link(mesh_coll)

        # Activate new_obj so _active_plotting_arm() resolves it correctly
        _ensure_object_mode(context)
        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj

        # Initialize chain list from META bones
        bpy.ops.gesturebone.sync_chains_from_meta_bones()

        # Enter Pose Mode and solo META
        _activate_in_pose_mode(context, new_obj)
        props = new_obj.gesturebone_props
        meta_coll = props.meta_collection
        if meta_coll:
            bc = new_obj.data.collections.get(meta_coll)
            if bc:
                from ..shared.utils import _all_bone_colls
                for c in _all_bone_colls(new_obj.data):
                    c.is_visible = (c.name == meta_coll)
                props.meta_solo_mode = True

        self.report({'INFO'}, f"Created PLOTTING rig '{name}'")
        return {'FINISHED'}


def _activate_in_pose_mode(context, arm_obj):
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return
    arm_obj.hide_set(False)
    arm_obj.hide_viewport = False
    _ensure_object_mode(context)
    bpy.ops.object.select_all(action='DESELECT')
    arm_obj.select_set(True)
    context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')


_classes = [
    GESTUREBONE_OT_AppendEssentials,
    GESTUREBONE_OT_CreateRig,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
