"""
expression_sheet/nodes.py -- Expression Sheet shader nodes (Option B: shared).

Adds a 'UV From Bone (Shared)' Shader Editor node. Unlike the per-instance
design, ALL instances reuse ONE internal node group (like a normal node
group) -- creating/duplicating nodes adds no new groups. Per-bone values are
driven on each node's own (hidden) input sockets instead of on Value nodes
inside a private group, and the UV coordinate is fed via an auto-created
per-instance UV Map node.

Validated prototype (see the CHR_LittlePig_OptionB.blend copy). Not yet
hardened: no old->shared migration and no reload-heal for renamed nodes --
those are a follow-up pass. register()/unregister() are called by this
module's __init__.py.
"""

import bpy
from bpy.types import ShaderNodeCustomGroup
from bpy.props import PointerProperty, StringProperty, BoolProperty

SHARED_GROUP_NAME = ".UVFromBoneShared"
UVFB_UVMAP_SUFFIX = "__UVForBone"   # auto-created UV Map node name suffix

COMPONENTS = ("x", "y", "z")

# Driven input sockets (name -> transform spec) built on the shared group and
# driven per-instance on the node. Scale defaults to identity.
DRIVEN_VEC_INPUTS = {
    "Location": (("LOC_X", "LOC_Y", "LOC_Z"), "negate"),
    "Rotation": (("ROT_X", "ROT_Y", "ROT_Z"), "negate"),
    "Scale":    (("SCALE_X", "SCALE_Y", "SCALE_Z"), "mirror1"),
}


def is_armature(self, obj):
    return obj.type == 'ARMATURE'


# ---------------------------------------------------------------------------
# Shared group: built once, reused by all instances.
# ---------------------------------------------------------------------------

def _mix_socket(node, name, socket_type, in_out='INPUT'):
    sockets = node.inputs if in_out == 'INPUT' else node.outputs
    for s in sockets:
        if s.name == name and s.type == socket_type:
            return s
    raise KeyError((name, socket_type, in_out))


def build_shared_uv_tree():
    """Build THE one shared UV-From-Bone group. Same internal math as the
    per-instance design, but every driven value and the UV coordinate are
    group INPUTS (driven / fed per instance) instead of internal Value/UVMap
    nodes -- so a single group can serve every instance."""
    tree = bpy.data.node_groups.new(SHARED_GROUP_NAME, 'ShaderNodeTree')
    tree.use_fake_user = True   # shared singleton: keep even with 0 users

    iface = tree.interface

    uv_in = iface.new_socket(name="UV", in_out='INPUT', socket_type='NodeSocketVector')

    piv = iface.new_socket(name="UV Island Center", in_out='INPUT', socket_type='NodeSocketVector')
    piv_id = piv.identifier
    piv.dimensions = 2
    piv = iface.items_tree[piv_id]
    piv.default_value = (0.5, 0.5)

    amt = iface.new_socket(name="Amount", in_out='INPUT', socket_type='NodeSocketFloat')
    amt.default_value = 1.0
    amt.min_value = 0.0
    amt.max_value = 1.0

    calib = iface.new_socket(name="Calibration", in_out='INPUT', socket_type='NodeSocketFloat')
    calib.default_value = 1.0
    calib.min_value = 0.0
    calib.max_value = 10.0

    mrad = iface.new_socket(name="Mask Radius", in_out='INPUT', socket_type='NodeSocketFloat')
    mrad.default_value = 0.1
    mrad.min_value = 0.0
    mrad.max_value = 10.0

    msharp = iface.new_socket(name="Mask Sharpness", in_out='INPUT', socket_type='NodeSocketFloat')
    msharp.default_value = 1.0
    msharp.min_value = 0.05
    msharp.max_value = 10.0

    # Driven-per-instance inputs (hidden on the node; set by drivers).
    loc_s = iface.new_socket(name="Location", in_out='INPUT', socket_type='NodeSocketVector')
    rot_s = iface.new_socket(name="Rotation", in_out='INPUT', socket_type='NodeSocketVector')
    scl_s = iface.new_socket(name="Scale", in_out='INPUT', socket_type='NodeSocketVector')
    scl_s.default_value = (1.0, 1.0, 1.0)
    mloc_s = iface.new_socket(name="Mask Location", in_out='INPUT', socket_type='NodeSocketVector')
    exp_s = iface.new_socket(name="Exp Index In", in_out='INPUT', socket_type='NodeSocketFloat')

    iface.new_socket(name="UV", in_out='OUTPUT', socket_type='NodeSocketVector')
    iface.new_socket(name="Mask", in_out='OUTPUT', socket_type='NodeSocketFloat')
    iface.new_socket(name="Exp Index", in_out='OUTPUT', socket_type='NodeSocketFloat')

    gin = tree.nodes.new('NodeGroupInput')
    gin.location = (-900, 0)
    gout = tree.nodes.new('NodeGroupOutput')
    gout.location = (1100, 0)

    # --- UV shift chain ---
    sub_pivot = tree.nodes.new('ShaderNodeVectorMath')
    sub_pivot.operation = 'SUBTRACT'
    sub_pivot.location = (-200, 200)
    tree.links.new(gin.outputs['UV'], sub_pivot.inputs[0])
    tree.links.new(gin.outputs['UV Island Center'], sub_pivot.inputs[1])

    loc_scaled = tree.nodes.new('ShaderNodeVectorMath')
    loc_scaled.operation = 'SCALE'
    loc_scaled.label = "Location * Calibration"
    loc_scaled.location = (-200, -100)
    tree.links.new(gin.outputs['Location'], loc_scaled.inputs[0])
    tree.links.new(gin.outputs['Calibration'], loc_scaled.inputs['Scale'])

    mapping = tree.nodes.new('ShaderNodeMapping')
    mapping.location = (200, 200)
    tree.links.new(sub_pivot.outputs[0], mapping.inputs['Vector'])
    tree.links.new(loc_scaled.outputs[0], mapping.inputs['Location'])
    tree.links.new(gin.outputs['Rotation'], mapping.inputs['Rotation'])
    tree.links.new(gin.outputs['Scale'], mapping.inputs['Scale'])

    add_pivot = tree.nodes.new('ShaderNodeVectorMath')
    add_pivot.operation = 'ADD'
    add_pivot.location = (450, 200)
    tree.links.new(mapping.outputs['Vector'], add_pivot.inputs[0])
    tree.links.new(gin.outputs['UV Island Center'], add_pivot.inputs[1])

    mix = tree.nodes.new('ShaderNodeMix')
    mix.data_type = 'VECTOR'
    mix.factor_mode = 'UNIFORM'
    mix.location = (700, 100)
    tree.links.new(gin.outputs['Amount'], _mix_socket(mix, "Factor", 'VALUE'))
    tree.links.new(gin.outputs['UV'], _mix_socket(mix, "A", 'VECTOR'))
    tree.links.new(add_pivot.outputs[0], _mix_socket(mix, "B", 'VECTOR'))
    tree.links.new(_mix_socket(mix, "Result", 'VECTOR', 'OUTPUT'), gout.inputs['UV'])

    # --- Mask chain ---
    mloc_scaled = tree.nodes.new('ShaderNodeVectorMath')
    mloc_scaled.operation = 'SCALE'
    mloc_scaled.label = "Mask Location * Calibration"
    mloc_scaled.location = (-200, -400)
    tree.links.new(gin.outputs['Mask Location'], mloc_scaled.inputs[0])
    tree.links.new(gin.outputs['Calibration'], mloc_scaled.inputs['Scale'])

    bone_uv_pos = tree.nodes.new('ShaderNodeVectorMath')
    bone_uv_pos.operation = 'ADD'
    bone_uv_pos.label = "Bone UV Position"
    bone_uv_pos.location = (50, -400)
    tree.links.new(gin.outputs['UV Island Center'], bone_uv_pos.inputs[0])
    tree.links.new(mloc_scaled.outputs[0], bone_uv_pos.inputs[1])

    dist = tree.nodes.new('ShaderNodeVectorMath')
    dist.operation = 'DISTANCE'
    dist.location = (300, -400)
    tree.links.new(gin.outputs['UV'], dist.inputs[0])
    tree.links.new(bone_uv_pos.outputs[0], dist.inputs[1])

    normalized = tree.nodes.new('ShaderNodeMath')
    normalized.operation = 'DIVIDE'
    normalized.location = (500, -400)
    tree.links.new(dist.outputs['Value'], normalized.inputs[0])
    tree.links.new(gin.outputs['Mask Radius'], normalized.inputs[1])

    mask = tree.nodes.new('ShaderNodeMath')
    mask.operation = 'SUBTRACT'
    mask.use_clamp = True
    mask.location = (700, -400)
    mask.inputs[0].default_value = 1.0
    tree.links.new(normalized.outputs['Value'], mask.inputs[1])

    mask_pow = tree.nodes.new('ShaderNodeMath')
    mask_pow.operation = 'POWER'
    mask_pow.location = (900, -400)
    tree.links.new(mask.outputs['Value'], mask_pow.inputs[0])
    tree.links.new(gin.outputs['Mask Sharpness'], mask_pow.inputs[1])
    tree.links.new(mask_pow.outputs['Value'], gout.inputs['Mask'])

    # --- Exp Index passthrough ---
    tree.links.new(gin.outputs['Exp Index In'], gout.inputs['Exp Index'])

    return tree


def get_shared_uv_tree():
    """Return the one shared group, building it if it doesn't exist yet."""
    t = bpy.data.node_groups.get(SHARED_GROUP_NAME)
    if t is None:
        t = build_shared_uv_tree()
    return t


# ---------------------------------------------------------------------------
# Per-instance drivers: live on the node's OWN input sockets, in whatever
# tree contains the node (usually a material).
# ---------------------------------------------------------------------------

def _socket_path(node_name, socket_name):
    return 'nodes["{}"].inputs["{}"].default_value'.format(node_name, socket_name)


def _clear_instance_drivers(node):
    container = node.id_data           # the node tree that holds this node
    name = node.name
    for socket_name in ("Location", "Rotation", "Scale", "Mask Location"):
        for i in range(3):
            container.driver_remove(_socket_path(name, socket_name), i)
    container.driver_remove(_socket_path(name, "Exp Index In"))


def _add_transform_driver_on_socket(container, node_name, socket_name, comp_index,
                                     armature, bone, ttype, space, expression="bone"):
    path = _socket_path(node_name, socket_name)
    container.driver_remove(path, comp_index)
    fcurve = container.driver_add(path, comp_index)
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = expression
    var = drv.variables.new()
    var.name = "bone"
    var.type = 'TRANSFORMS'
    tgt = var.targets[0]
    tgt.id = armature
    tgt.bone_target = bone
    tgt.transform_type = ttype
    tgt.transform_space = space
    tgt.rotation_mode = 'XYZ' if ttype.startswith('ROT') else 'AUTO'


def _add_singleprop_driver_on_socket(container, node_name, socket_name,
                                     armature, data_path, expression="prop"):
    path = _socket_path(node_name, socket_name)
    container.driver_remove(path)
    fcurve = container.driver_add(path)
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = expression
    var = drv.variables.new()
    var.name = "prop"
    var.type = 'SINGLE_PROP'
    tgt = var.targets[0]
    tgt.id_type = 'OBJECT'
    tgt.id = armature
    tgt.data_path = data_path


def _ensure_uv_map_feed(node):
    """Auto-create a small UV Map node wired into this instance's 'UV' input
    when nothing is feeding it. Cheap standard node (not a group). The layer
    is chosen on that UV Map node itself (empty = active UV), so there's no
    mirror string on this node. If the 'UV' input is already fed -- by our
    auto node or the user's own source -- leave it alone."""
    container = node.id_data
    uv_in = node.inputs.get("UV")
    if uv_in is None:
        return
    # Already fed (auto node or user-wired)? Don't touch it.
    if uv_in.links:
        return
    uvmap = container.nodes.new('ShaderNodeUVMap')
    uvmap.name = node.name + UVFB_UVMAP_SUFFIX
    uvmap.label = "UV for " + node.name
    uvmap.location = (node.location.x - 220, node.location.y - 120)
    # Leave uvmap.uv_map = "" -> Blender uses the active UV layer. The user
    # picks the layer on this UV Map node directly.
    container.links.new(uvmap.outputs['UV'], uv_in)


def refresh_uv_from_bone_shared(node):
    if node.node_tree is None:
        node.node_tree = get_shared_uv_tree()

    _ensure_uv_map_feed(node)

    # Hide the driven/internal input sockets so the node stays tidy. Amount is
    # fixed at 1.0 (full effect) and no longer exposed on the node.
    for hidden in ("Amount", "Location", "Rotation", "Scale", "Mask Location", "Exp Index In"):
        s = node.inputs.get(hidden)
        if s is not None:
            s.hide = True
    amt = node.inputs.get("Amount")
    if amt is not None and amt.default_value != 1.0:
        amt.default_value = 1.0

    _clear_instance_drivers(node)

    armature = node.armature_obj
    bone = node.bone_name
    valid = bool(armature and armature.type == 'ARMATURE'
                 and bone and bone in armature.data.bones)
    if not valid:
        return

    container = node.id_data
    invert = {
        "Location": (node.invert_location_x, node.invert_location_y, False),
        "Rotation": (node.invert_rotation, node.invert_rotation, node.invert_rotation),
        "Scale":    (node.invert_scale_x, node.invert_scale_y, False),
    }
    for socket_name, (types, mode) in DRIVEN_VEC_INPUTS.items():
        flags = invert[socket_name]
        for i, ttype in enumerate(types):
            if flags[i]:
                expr = "-bone" if mode == "negate" else "2-bone"
            else:
                expr = "bone"
            _add_transform_driver_on_socket(container, node.name, socket_name, i,
                                            armature, bone, ttype, 'LOCAL_SPACE', expr)

    # Mask Location: local-space, non-inverted, X/Y only (Z stays 0).
    for i, ttype in enumerate(("LOC_X", "LOC_Y")):
        _add_transform_driver_on_socket(container, node.name, "Mask Location", i,
                                        armature, bone, ttype, 'LOCAL_SPACE', "bone")

    # Exp Index: custom property on the pose bone, if present.
    prop_name = (node.index_prop_name or "exp_index").strip()
    pbone = armature.pose.bones.get(bone)
    if prop_name and pbone is not None and prop_name in pbone.keys():
        data_path = 'pose.bones["{}"]["{}"]'.format(bone, prop_name)
        _add_singleprop_driver_on_socket(container, node.name, "Exp Index In",
                                         armature, data_path)


def _on_update(self, context):
    refresh_uv_from_bone_shared(self)


# ---------------------------------------------------------------------------
# Deferred tree mutation.
#
# init()/copy()/free() run *inside* the add/duplicate/delete node operators.
# Adding or removing nodes in the CONTAINING tree from those callbacks (which
# is what refresh_uv_from_bone_shared -> _ensure_uv_map_feed and free's UV Map
# cleanup do) re-enters the operator and hangs Blender ("stall"). So copy()
# and free() only schedule the work; a 0-delay timer performs the tree
# mutation once the operator has returned and we're back in a normal context.
# ---------------------------------------------------------------------------

_pending_refresh_ptrs = set()


def _iter_shared_containers():
    seen = set()
    for c in list(bpy.data.node_groups) + [m.node_tree for m in bpy.data.materials if m.node_tree]:
        if c.as_pointer() in seen:
            continue
        seen.add(c.as_pointer())
        yield c


def _schedule_refresh(node):
    _pending_refresh_ptrs.add(node.as_pointer())
    if not bpy.app.timers.is_registered(_process_pending):
        bpy.app.timers.register(_process_pending, first_interval=0.0)


def _schedule_cleanup():
    # No node pointer to track (the node is being deleted) -- the timer scans
    # for orphans. Reuse the same one-shot timer.
    if not bpy.app.timers.is_registered(_process_pending):
        bpy.app.timers.register(_process_pending, first_interval=0.0)


def _process_pending():
    global _pending_refresh_ptrs
    ptrs = _pending_refresh_ptrs
    _pending_refresh_ptrs = set()
    for c in _iter_shared_containers():
        # 1) refresh freshly-duplicated nodes (identified by pointer)
        if ptrs:
            for n in list(c.nodes):
                if n.bl_idname == "ShaderNodeCustomUVFromBoneShared" and n.as_pointer() in ptrs:
                    try:
                        refresh_uv_from_bone_shared(n)
                    except Exception as e:
                        print("Expression Sheet: deferred refresh failed:", e)
        # 2) remove orphaned auto UV Map feeds (owner node deleted) and drivers
        #    pointing at nodes that no longer exist
        for f in list(c.nodes):
            if (f.bl_idname == 'ShaderNodeUVMap' and f.name.endswith(UVFB_UVMAP_SUFFIX)
                    and f.outputs and not any(
                        l.to_node.bl_idname == "ShaderNodeCustomUVFromBoneShared"
                        for l in f.outputs[0].links)):
                try:
                    c.nodes.remove(f)
                except Exception:
                    pass
        if c.animation_data:
            our_sockets = ("Location", "Rotation", "Scale", "Mask Location", "Exp Index In")
            for fc in list(c.animation_data.drivers):
                dp = fc.data_path
                if not (dp.startswith('nodes["') and '.inputs["' in dp):
                    continue
                parts = dp.split('"')
                node_name = parts[1] if len(parts) > 1 else ""
                socket_name = parts[3] if len(parts) > 3 else ""
                # Only our own orphaned socket drivers (node gone) -- never
                # touch unrelated drivers the user may have on other nodes.
                if socket_name in our_sockets and c.nodes.get(node_name) is None:
                    try:
                        c.animation_data.drivers.remove(fc)
                    except Exception:
                        pass
    return None  # one-shot


class ShaderNodeCustomUVFromBoneShared(ShaderNodeCustomGroup):
    """Option B: shifts/rotates/scales a UV from a bone's local pose, using
    ONE shared internal group across all instances. Per-bone values are
    driven on this node's own (hidden) input sockets."""
    bl_idname = "ShaderNodeCustomUVFromBoneShared"
    bl_label = "UV From Bone (Shared)"
    bl_icon = 'UV'

    armature_obj: PointerProperty(name="Armature", type=bpy.types.Object,
                                  poll=is_armature, update=_on_update)
    bone_name: StringProperty(name="Bone", update=_on_update)
    index_prop_name: StringProperty(name="Index Property", default="exp_index",
                                    update=_on_update)

    invert_location_x: BoolProperty(default=True, update=_on_update)
    invert_location_y: BoolProperty(default=True, update=_on_update)
    invert_rotation: BoolProperty(default=True, update=_on_update)
    invert_scale_x: BoolProperty(default=True, update=_on_update)
    invert_scale_y: BoolProperty(default=True, update=_on_update)

    def init(self, context):
        # Reference the shared group -- do NOT build a private one.
        self.node_tree = get_shared_uv_tree()
        self.width = 200

    def copy(self, node):
        # Reference the SAME shared group (no per-node group). DON'T rebuild
        # drivers / UV feed here: copy() runs inside the duplicate operator,
        # and mutating the containing tree from here hangs Blender. Defer it.
        self.node_tree = get_shared_uv_tree()
        _schedule_refresh(self)

    def free(self):
        # Drop this instance's drivers now (safe -- animation data, not nodes).
        try:
            _clear_instance_drivers(self)
        except Exception as e:
            print("UVFromBoneShared free() driver-clear skipped:", e)
        # Removing the auto UV Map node mutates the tree, which is unsafe from
        # inside the delete operator -- let the deferred timer sweep orphans.
        _schedule_cleanup()

    def draw_buttons(self, context, layout):
        layout.prop(self, "armature_obj", text="")
        if self.armature_obj and self.armature_obj.type == 'ARMATURE':
            layout.prop_search(self, "bone_name", self.armature_obj.data, "bones", text="")
        else:
            row = layout.row(); row.enabled = False
            row.label(text="Select an Armature", icon='ERROR')
        layout.prop(self, "index_prop_name", text="", icon='RNA')

    def draw_label(self):
        return "UV From Bone (Shared)"


def _menu_draw(self, context):
    if getattr(context.space_data, "tree_type", None) == 'ShaderNodeTree':
        self.layout.operator("node.add_node", text="UV From Bone (Shared)",
                             icon='UV').type = ShaderNodeCustomUVFromBoneShared.bl_idname


_MENU_TARGETS = ("NODE_MT_add", "NODE_MT_category_shader_input")


def register():
    # Idempotent: register() can run when the class is already registered
    # (prior module toggle, addon reload, or dev standalone run). Node classes
    # don't reliably surface via getattr(bpy.types, ...), so we catch the
    # "already registered" failure, drop the stale registration, and retry.
    try:
        bpy.utils.register_class(ShaderNodeCustomUVFromBoneShared)
    except Exception:
        try:
            bpy.utils.unregister_class(ShaderNodeCustomUVFromBoneShared)
        except Exception:
            pass
        existing = getattr(bpy.types, ShaderNodeCustomUVFromBoneShared.bl_idname, None)
        if existing is not None and existing is not ShaderNodeCustomUVFromBoneShared:
            try:
                bpy.utils.unregister_class(existing)
            except Exception:
                pass
        try:
            bpy.utils.register_class(ShaderNodeCustomUVFromBoneShared)
        except Exception as e:
            print("Expression Sheet: could not register UV From Bone (Shared)", e)
    for name in _MENU_TARGETS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            # Strip any stale _menu_draw first so re-register can't stack
            # duplicate Add-menu entries.
            funcs = getattr(getattr(menu, "draw", None), "_draw_funcs", None)
            if funcs:
                for f in list(funcs):
                    if getattr(f, "__name__", "") == "_menu_draw":
                        funcs.remove(f)
            menu.append(_menu_draw)


def unregister():
    if bpy.app.timers.is_registered(_process_pending):
        try:
            bpy.app.timers.unregister(_process_pending)
        except Exception:
            pass
    for name in _MENU_TARGETS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            try:
                menu.remove(_menu_draw)
            except Exception:
                pass
    try:
        bpy.utils.unregister_class(ShaderNodeCustomUVFromBoneShared)
    except Exception:
        pass
