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
    calib.max_value = 2.0

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
    """Auto-create/keep a small UV Map node wired into this instance's 'UV'
    input, set to uv_map_name. Cheap standard node (not a group). Shared
    behavior parity with the old node's internal UVMap. If the user has
    wired their own UV source in, leave it alone."""
    container = node.id_data
    uv_in = node.inputs.get("UV")
    if uv_in is None:
        return
    # already fed by something the user (or we) wired? keep it, just sync map
    if uv_in.links:
        src = uv_in.links[0].from_node
        if src.bl_idname == 'ShaderNodeUVMap' and src.name.endswith(UVFB_UVMAP_SUFFIX):
            src.uv_map = node.uv_map_name
        return
    uvmap = container.nodes.new('ShaderNodeUVMap')
    uvmap.name = node.name + UVFB_UVMAP_SUFFIX
    uvmap.label = "UV for " + node.name
    uvmap.location = (node.location.x - 220, node.location.y - 120)
    uvmap.uv_map = node.uv_map_name
    container.links.new(uvmap.outputs['UV'], uv_in)


def refresh_uv_from_bone_shared(node):
    if node.node_tree is None:
        node.node_tree = get_shared_uv_tree()

    _ensure_uv_map_feed(node)

    # Hide the driven/internal input sockets so the node stays tidy.
    for hidden in ("Location", "Rotation", "Scale", "Mask Location", "Exp Index In"):
        s = node.inputs.get(hidden)
        if s is not None:
            s.hide = True
    # Amount pinned to 1.0 and hidden value (dialed once).
    amt = node.inputs.get("Amount")
    if amt is not None:
        amt.hide_value = True
        if amt.default_value != 1.0:
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
    uv_map_name: StringProperty(name="UV Map",
                                description="UV map for the auto-created UV feed",
                                update=_on_update)
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
        # Duplicate: reference the SAME shared group; only rebuild drivers.
        self.node_tree = get_shared_uv_tree()
        refresh_uv_from_bone_shared(self)

    def free(self):
        # Shared group is never removed on node delete. Just drop this
        # instance's drivers + its auto UV Map node.
        try:
            _clear_instance_drivers(self)
            container = self.id_data
            uvmap = container.nodes.get(self.name + UVFB_UVMAP_SUFFIX)
            if uvmap is not None:
                container.nodes.remove(uvmap)
        except Exception as e:
            print("UVFromBoneShared free() skipped:", e)

    def draw_buttons(self, context, layout):
        layout.prop(self, "armature_obj", text="")
        if self.armature_obj and self.armature_obj.type == 'ARMATURE':
            layout.prop_search(self, "bone_name", self.armature_obj.data, "bones", text="")
        else:
            row = layout.row(); row.enabled = False
            row.label(text="Select an Armature", icon='ERROR')
        layout.prop(self, "uv_map_name", text="", icon='UV')
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
