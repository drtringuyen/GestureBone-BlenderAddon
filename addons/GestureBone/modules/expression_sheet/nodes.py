"""
expression_sheet/nodes.py -- Expression Sheet shader nodes (v1.9.2).

Adds two Shader Editor nodes driven live by an Armature bone's pose (via
drivers):
  * 'Bone Info'    -- like Geometry Nodes' Bone Info (pose/local/rest transforms)
  * 'UV From Bone' -- moves/rotates/scales a UV coordinate from a bone's local
                      pose, pivoting around a chosen point; also outputs the
                      bone's 'exp_index' custom property (see spritesheet module).

register()/unregister() below are called by this module's __init__.py, so the
node types + Add-menu entries come and go with the Expression Sheet module
toggle. This file was previously a standalone .blend Text datablock; it keeps
its own register()/unregister() so it stays runnable/loadable on its own too.
"""

import bpy
from bpy.types import ShaderNodeCustomGroup, Node
from bpy.props import PointerProperty, StringProperty, BoolProperty

NODE_GROUP_PREFIX = ".BoneInfo"

# ---------------------------------------------------------------------------
# Output layout: (key, socket label, kind)
#   kind 'VEC'   -> built from 3 driven/static Value nodes -> Combine XYZ
#   kind 'FLOAT' -> a single driven/static Value node
# ---------------------------------------------------------------------------
OUTPUTS = [
    ("pose_loc",   "Pose Location", "VEC"),
    ("pose_rot",   "Pose Rotation", "VEC"),
    ("pose_scale", "Pose Scale",    "VEC"),
    ("local_loc",   "Local Location", "VEC"),
    ("local_rot",   "Local Rotation", "VEC"),
    ("local_scale", "Local Scale",    "VEC"),
    ("rest_loc",   "Rest Location", "VEC"),
    ("rest_rot",   "Rest Rotation", "VEC"),
    ("rest_scale", "Rest Scale",    "VEC"),
    ("rest_length", "Rest Length",  "FLOAT"),
]

# Driver specs for the live (pose-dependent) outputs.
# key -> (transform_type_x/y/z, transform_space)
DRIVEN_SPECS = {
    # WORLD_SPACE, for a bone target, actually means "armature space" (includes
    # rest pose + parent chain + pose + constraints) -- verified empirically to
    # match pose_bone.matrix decomposed. This is what Geometry Nodes' Bone Info
    # calls "Pose" (Original transform space: relative to the armature object).
    "pose_loc":   (("LOC_X", "LOC_Y", "LOC_Z"), "WORLD_SPACE"),
    "pose_rot":   (("ROT_X", "ROT_Y", "ROT_Z"), "WORLD_SPACE"),
    "pose_scale": (("SCALE_X", "SCALE_Y", "SCALE_Z"), "WORLD_SPACE"),
    # LOCAL_SPACE matches pose_bone.location/rotation_euler/scale exactly
    # (relative to parent bone, post-constraints) -- this is "Local Pose".
    "local_loc":   (("LOC_X", "LOC_Y", "LOC_Z"), "LOCAL_SPACE"),
    "local_rot":   (("ROT_X", "ROT_Y", "ROT_Z"), "LOCAL_SPACE"),
    "local_scale": (("SCALE_X", "SCALE_Y", "SCALE_Z"), "LOCAL_SPACE"),
}
# rest_loc / rest_rot / rest_scale / rest_length are static (no driver),
# recomputed in Python whenever the armature/bone selection changes.

VALUE_NODE_FMT = "BI_{key}_{comp}"
COMPONENTS = ("x", "y", "z")


def is_armature(self, obj):
    return obj.type == 'ARMATURE'


def _value_node_name(key, comp):
    return VALUE_NODE_FMT.format(key=key, comp=comp)


def _clear_drivers(tree):
    for key in DRIVEN_SPECS:
        for comp in COMPONENTS:
            path = 'nodes["{}"].outputs[0].default_value'.format(_value_node_name(key, comp))
            tree.driver_remove(path)


def _add_transform_driver(tree, key, comp_index, armature_obj, bone_name, transform_type, space,
                           expression="bone"):
    """expression can reference the variable "bone" -- e.g. "-bone" to flip
    a location/rotation axis, or "2-bone" to mirror a scale axis around its
    identity value of 1 (so 1.2 <-> 0.8 instead of going negative)."""
    comp = COMPONENTS[comp_index]
    path = 'nodes["{}"].outputs[0].default_value'.format(_value_node_name(key, comp))
    tree.driver_remove(path)
    fcurve = tree.driver_add(path)
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = expression
    var = drv.variables.new()
    var.name = "bone"
    var.type = 'TRANSFORMS'
    tgt = var.targets[0]
    tgt.id = armature_obj
    tgt.bone_target = bone_name
    tgt.transform_type = transform_type
    tgt.transform_space = space
    tgt.rotation_mode = 'XYZ' if transform_type.startswith('ROT') else 'AUTO'


def _add_single_prop_driver(tree, key, comp_index, id_obj, data_path, expression="prop"):
    """Drive a Value node from a single custom property (e.g. a bone's
    integer custom prop) via a SINGLE_PROP driver variable. data_path is
    resolved relative to id_obj -- e.g. 'pose.bones["EXP-Eye.L"]["exp_index"]'
    on the armature object. This is the same live-driver technique the
    transform outputs use, just reading an arbitrary RNA path instead."""
    comp = COMPONENTS[comp_index]
    path = 'nodes["{}"].outputs[0].default_value'.format(_value_node_name(key, comp))
    tree.driver_remove(path)
    fcurve = tree.driver_add(path)
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = expression
    var = drv.variables.new()
    var.name = "prop"
    var.type = 'SINGLE_PROP'
    tgt = var.targets[0]
    tgt.id_type = 'OBJECT'
    tgt.id = id_obj
    tgt.data_path = data_path


def _set_static(tree, key, comp_index, value):
    comp = COMPONENTS[comp_index]
    tree.nodes[_value_node_name(key, comp)].outputs[0].default_value = value


def build_node_tree():
    """Create the internal node group: one Value node per vector component
    (+1 for Rest Length), Combine XYZ nodes, wired to Group Output sockets."""
    tree = bpy.data.node_groups.new(NODE_GROUP_PREFIX, 'ShaderNodeTree')
    # Deliberately NO fake user: the node instance that owns this group is
    # its real user, so the group lives exactly as long as a node uses it.
    # A fake user would pin orphaned groups in the .blend forever (that's
    # what caused the .UVFromBone.NNN pile-up); without it, a group with no
    # node users is auto-purged (see _purge_orphan_internal_trees).

    for key, label, kind in OUTPUTS:
        socket_type = 'NodeSocketFloat' if kind == 'FLOAT' else 'NodeSocketVector'
        tree.interface.new_socket(name=label, in_out='OUTPUT', socket_type=socket_type)

    group_out = tree.nodes.new('NodeGroupOutput')
    group_out.location = (400, 0)

    y = 0
    for key, label, kind in OUTPUTS:
        if kind == 'FLOAT':
            val = tree.nodes.new('ShaderNodeValue')
            val.name = _value_node_name(key, "x")
            val.label = label
            val.location = (0, y)
            tree.links.new(val.outputs[0], group_out.inputs[label])
        else:
            combine = tree.nodes.new('ShaderNodeCombineXYZ')
            combine.label = label
            combine.location = (200, y)
            for i, comp in enumerate(COMPONENTS):
                val = tree.nodes.new('ShaderNodeValue')
                val.name = _value_node_name(key, comp)
                val.label = "{} {}".format(label, comp.upper())
                val.location = (0, y - i * 40)
                tree.links.new(val.outputs[0], combine.inputs[i])
            tree.links.new(combine.outputs[0], group_out.inputs[label])
        y -= 160

    return tree


def refresh_bone_info(node):
    """(Re)connect drivers and recompute static rest values for one node."""
    tree = node.node_tree
    if tree is None:
        return

    _clear_drivers(tree)

    armature = node.armature_obj
    bone_name = node.bone_name
    valid = bool(
        armature and armature.type == 'ARMATURE'
        and bone_name and bone_name in armature.data.bones
    )

    if not valid:
        for key in ("pose_loc", "pose_rot", "local_loc", "local_rot"):
            for i in range(3):
                _set_static(tree, key, i, 0.0)
        for key in ("pose_scale", "local_scale"):
            for i in range(3):
                _set_static(tree, key, i, 1.0)
        for i in range(3):
            _set_static(tree, "rest_loc", i, 0.0)
            _set_static(tree, "rest_rot", i, 0.0)
            _set_static(tree, "rest_scale", i, 1.0)
        _set_static(tree, "rest_length", 0, 0.0)
        return

    for key, (types, space) in DRIVEN_SPECS.items():
        for i, ttype in enumerate(types):
            _add_transform_driver(tree, key, i, armature, bone_name, ttype, space)

    bone = armature.data.bones[bone_name]
    mat = bone.matrix_local
    loc, rot, scale = mat.decompose()
    eul = rot.to_euler('XYZ')
    for i, v in enumerate((loc.x, loc.y, loc.z)):
        _set_static(tree, "rest_loc", i, v)
    for i, v in enumerate((eul.x, eul.y, eul.z)):
        _set_static(tree, "rest_rot", i, v)
    for i, v in enumerate((scale.x, scale.y, scale.z)):
        _set_static(tree, "rest_scale", i, v)
    _set_static(tree, "rest_length", 0, bone.length)


def _on_target_updated(self, context):
    refresh_bone_info(self)


class ShaderNodeCustomBoneInfo(ShaderNodeCustomGroup):
    """Bone Info: live pose/rest transforms of an Armature bone, for use in shaders."""
    bl_idname = "ShaderNodeCustomBoneInfo"
    bl_label = "Bone Info"
    bl_icon = 'BONE_DATA'

    armature_obj: PointerProperty(
        name="Armature",
        type=bpy.types.Object,
        poll=is_armature,
        update=_on_target_updated,
    )
    bone_name: StringProperty(
        name="Bone",
        update=_on_target_updated,
    )

    def init(self, context):
        self.node_tree = build_node_tree()
        self.width = 220

    def copy(self, node):
        # Give the duplicated node its own private node tree + drivers.
        self.node_tree = build_node_tree()
        refresh_bone_info(self)

    def free(self):
        _free_private_tree(self)

    def draw_buttons(self, context, layout):
        layout.prop(self, "armature_obj", text="")
        if self.armature_obj and self.armature_obj.type == 'ARMATURE':
            layout.prop_search(self, "bone_name", self.armature_obj.data, "bones", text="")
        else:
            row = layout.row()
            row.enabled = False
            row.label(text="Select an Armature", icon='ERROR')

    def draw_label(self):
        return "Bone Info"


def _menu_draw(self, context):
    if getattr(context.space_data, "tree_type", None) == 'ShaderNodeTree':
        self.layout.separator()
        self.layout.operator(
            "node.add_node", text="Bone Info", icon='BONE_DATA'
        ).type = ShaderNodeCustomBoneInfo.bl_idname
        self.layout.operator(
            "node.add_node", text="UV From Bone", icon='UV'
        ).type = "ShaderNodeCustomUVFromBone"


# ---------------------------------------------------------------------------
# UV From Bone
#
# Moves/rotates/scales a UV coordinate using a bone's LOCAL pose (its delta
# from rest -- i.e. pose_bone.location/rotation_euler/scale). Local, not
# Pose/world, is deliberate: Local is (0,0,0)/(0,0,0)/(1,1,1) at rest no
# matter where the bone sits in the armature, so the UV is untouched until
# the bone is actually posed. Using world-space "Pose" instead would bake
# the bone's rest position in as a permanent UV offset -- wrong for this.
#
# Internally: UV Map -> subtract Pivot -> Mapping (Location/Rotation/Scale
# driven by the bone's local pose, same driver technique as Bone Info) ->
# add Pivot back -> Mix(original UV, transformed UV, factor = Amount).
# Mapping already treats Location=(0,0,0)/Rotation=(0,0,0)/Scale=(1,1,1) as
# a no-op, which is exactly the bone's rest state, so it lines up for free.
# ---------------------------------------------------------------------------

UV_DRIVEN_SPECS = {
    "local_loc":   (("LOC_X", "LOC_Y", "LOC_Z"), "LOCAL_SPACE"),
    "local_rot":   (("ROT_X", "ROT_Y", "ROT_Z"), "LOCAL_SPACE"),
    "local_scale": (("SCALE_X", "SCALE_Y", "SCALE_Z"), "LOCAL_SPACE"),
}

UV_GROUP_PREFIX = ".UVFromBone"
UVFB_UVMAP_NODE = "UVFB_UVMap"


def _uv_clear_drivers(tree):
    for key in UV_DRIVEN_SPECS:
        for comp in COMPONENTS:
            path = 'nodes["{}"].outputs[0].default_value'.format(_value_node_name(key, comp))
            tree.driver_remove(path)
    # mask_loc only ever drives X/Y (see build_uv_node_tree) -- no Z entry.
    for comp in ("x", "y"):
        path = 'nodes["{}"].outputs[0].default_value'.format(_value_node_name("mask_loc", comp))
        tree.driver_remove(path)
    # exp_index is a single-component custom-property output.
    tree.driver_remove('nodes["{}"].outputs[0].default_value'.format(_value_node_name("exp_index", "x")))


def _mix_socket(node, name, socket_type, in_out='INPUT'):
    sockets = node.inputs if in_out == 'INPUT' else node.outputs
    for s in sockets:
        if s.name == name and s.type == socket_type:
            return s
    raise KeyError((name, socket_type, in_out))


def build_uv_node_tree():
    tree = bpy.data.node_groups.new(UV_GROUP_PREFIX, 'ShaderNodeTree')
    # Deliberately NO fake user: the node instance that owns this group is
    # its real user, so the group lives exactly as long as a node uses it.
    # A fake user would pin orphaned groups in the .blend forever (that's
    # what caused the .UVFromBone.NNN pile-up); without it, a group with no
    # node users is auto-purged (see _purge_orphan_internal_trees).

    # UV Island Center: a 2D point (Z is meaningless for a UV coordinate) you
    # place manually in the UV editor -- the effect's pivot / rest anchor.
    # (Used to be settable from a UV selection via a "Set Pivot to UV Island
    # Center" button -- removed: with UV Sync Selection on, a seam vertex
    # can carry multiple UV coordinates across different islands, so "is
    # this vertex selected" doesn't reliably mean "this UV loop belongs to
    # the selected island", and the averaged result could get pulled toward
    # an unrelated island.)
    piv = tree.interface.new_socket(name="UV Island Center", in_out='INPUT', socket_type='NodeSocketVector')
    piv_id = piv.identifier
    piv.dimensions = 2
    # Setting `dimensions` invalidates this Python wrapper (its default_value
    # still expects the old 3-item shape until re-fetched). Blender 5.2
    # raises "sequences of dimension 0 should contain 3 items, not 2" if we
    # assign the 2-item value to the stale wrapper -- re-fetch it first.
    # (Same gotcha handled in _migrate_uv_tree_rename_and_resize_pivot.)
    piv = tree.interface.items_tree[piv_id]
    piv.default_value = (0.5, 0.5)
    amt = tree.interface.new_socket(name="Amount", in_out='INPUT', socket_type='NodeSocketFloat')
    amt.default_value = 1.0
    amt.min_value = 0.0
    amt.max_value = 1.0
    # Calibration: a direct multiplier on the bone's Location delta before
    # it reaches the UV -- no internal remap. 1.0 = unscaled (identity),
    # 0.0 = no location influence, up to 2.0 for exaggeration. Left as a
    # raw scale for now; a friendlier remap can be layered on top later
    # once the right working range is known from testing.
    calib = tree.interface.new_socket(name="Calibration", in_out='INPUT', socket_type='NodeSocketFloat')
    calib.default_value = 1.0
    calib.min_value = 0.0
    calib.max_value = 2.0
    # Mask Radius: how far (in UV units) the Mask output's falloff reaches
    # from the bone's current UV position before going fully black.
    mask_radius = tree.interface.new_socket(name="Mask Radius", in_out='INPUT', socket_type='NodeSocketFloat')
    mask_radius.default_value = 0.1
    mask_radius.min_value = 0.0
    mask_radius.max_value = 10.0
    # Mask Sharpness: exponent applied to the falloff curve after it's
    # normalized+clamped to 0-1. 1.0 = a plain linear ramp (identical to
    # pre-Sharpness behavior); >1 shrinks/sharpens the bright hot-spot;
    # <1 softens and widens it.
    mask_sharpness = tree.interface.new_socket(name="Mask Sharpness", in_out='INPUT', socket_type='NodeSocketFloat')
    mask_sharpness.default_value = 1.0
    mask_sharpness.min_value = 0.05
    mask_sharpness.max_value = 10.0
    tree.interface.new_socket(name="UV", in_out='OUTPUT', socket_type='NodeSocketVector')
    # Mask: 1.0 (white) exactly at the bone's current UV position, falling
    # off (shaped by Mask Sharpness) to 0.0 (black, clamped) at Mask Radius
    # away -- a radial spotlight centered on wherever the bone has moved
    # the effect to.
    tree.interface.new_socket(name="Mask", in_out='OUTPUT', socket_type='NodeSocketFloat')
    # Exp Index: the bone's chosen integer custom property (default name
    # "exp_index"), surfaced live via a SINGLE_PROP driver (wired in
    # refresh_uv_from_bone). Stays a static 0 until a bone that actually
    # carries that property is assigned.
    tree.interface.new_socket(name="Exp Index", in_out='OUTPUT', socket_type='NodeSocketFloat')

    group_in = tree.nodes.new('NodeGroupInput')
    group_in.location = (-800, 0)
    group_out = tree.nodes.new('NodeGroupOutput')
    group_out.location = (1000, 0)

    uvmap = tree.nodes.new('ShaderNodeUVMap')
    uvmap.name = UVFB_UVMAP_NODE
    uvmap.location = (-800, -200)

    y = -400
    combine_nodes = {}
    for key, label in (("local_loc", "Location"), ("local_rot", "Rotation"), ("local_scale", "Scale")):
        combine = tree.nodes.new('ShaderNodeCombineXYZ')
        combine.label = label
        combine.location = (-400, y)
        for i, comp in enumerate(COMPONENTS):
            val = tree.nodes.new('ShaderNodeValue')
            val.name = _value_node_name(key, comp)
            val.label = "{} {}".format(label, comp.upper())
            val.location = (-600, y - i * 40)
            tree.links.new(val.outputs[0], combine.inputs[i])
        combine_nodes[key] = combine
        y -= 160
    # scale defaults to identity (1,1,1) until driven
    for comp in COMPONENTS:
        tree.nodes[_value_node_name("local_scale", comp)].outputs[0].default_value = 1.0

    sub_pivot = tree.nodes.new('ShaderNodeVectorMath')
    sub_pivot.operation = 'SUBTRACT'
    sub_pivot.location = (-200, 200)
    tree.links.new(uvmap.outputs['UV'], sub_pivot.inputs[0])
    tree.links.new(group_in.outputs['UV Island Center'], sub_pivot.inputs[1])

    # Calibration scales the bone's Location delta (X/Y/Z) directly before
    # it reaches the Mapping node -- no remap. Rotation and Scale are left
    # unscaled/direct, as before. This chain (loc_scaled -> Mapping -> UV
    # output) is the visible UV shift; the Mask's own position controls
    # below are deliberately kept out of it.
    loc_scaled = tree.nodes.new('ShaderNodeVectorMath')
    loc_scaled.operation = 'SCALE'
    loc_scaled.label = "Location * Calibration"
    loc_scaled.location = (-200, -400)
    tree.links.new(combine_nodes["local_loc"].outputs[0], loc_scaled.inputs[0])
    tree.links.new(group_in.outputs['Calibration'], loc_scaled.inputs['Scale'])

    mapping = tree.nodes.new('ShaderNodeMapping')
    mapping.location = (400, 200)
    tree.links.new(sub_pivot.outputs[0], mapping.inputs['Vector'])
    tree.links.new(loc_scaled.outputs[0], mapping.inputs['Location'])
    tree.links.new(combine_nodes["local_rot"].outputs[0], mapping.inputs['Rotation'])
    tree.links.new(combine_nodes["local_scale"].outputs[0], mapping.inputs['Scale'])

    add_pivot = tree.nodes.new('ShaderNodeVectorMath')
    add_pivot.operation = 'ADD'
    add_pivot.location = (600, 200)
    tree.links.new(mapping.outputs['Vector'], add_pivot.inputs[0])
    tree.links.new(group_in.outputs['UV Island Center'], add_pivot.inputs[1])

    mix = tree.nodes.new('ShaderNodeMix')
    mix.data_type = 'VECTOR'
    mix.factor_mode = 'UNIFORM'
    mix.location = (800, 0)
    tree.links.new(group_in.outputs['Amount'], _mix_socket(mix, "Factor", 'VALUE'))
    tree.links.new(uvmap.outputs['UV'], _mix_socket(mix, "A", 'VECTOR'))
    tree.links.new(add_pivot.outputs[0], _mix_socket(mix, "B", 'VECTOR'))
    tree.links.new(_mix_socket(mix, "Result", 'VECTOR', 'OUTPUT'), group_out.inputs['UV'])

    # --- Mask: its own independent position feed, separate from the UV
    # shift above. mask_loc_x/y are driven independently (see
    # refresh_uv_from_bone) so the mask's own Invert / Local-World toggles
    # never touch loc_scaled or anything the visible UV shift depends on.
    # Z is intentionally never driven -- stays a static 0 -- since the mask
    # is a 2D UV-space effect; letting the bone's out-of-plane motion leak
    # into the DISTANCE calculation below would distort the falloff for no
    # benefit.
    mask_loc_combine = tree.nodes.new('ShaderNodeCombineXYZ')
    mask_loc_combine.label = "Mask Location"
    mask_loc_combine.location = (-400, -700)
    for i, comp in enumerate(("x", "y")):
        val = tree.nodes.new('ShaderNodeValue')
        val.name = _value_node_name("mask_loc", comp)
        val.label = "Mask Location {}".format(comp.upper())
        val.location = (-600, -700 - i * 40)
        tree.links.new(val.outputs[0], mask_loc_combine.inputs[i])
    mask_loc_combine.inputs[2].default_value = 0.0

    mask_loc_scaled = tree.nodes.new('ShaderNodeVectorMath')
    mask_loc_scaled.operation = 'SCALE'
    mask_loc_scaled.label = "Mask Location * Calibration"
    mask_loc_scaled.location = (-200, -700)
    tree.links.new(mask_loc_combine.outputs[0], mask_loc_scaled.inputs[0])
    tree.links.new(group_in.outputs['Calibration'], mask_loc_scaled.inputs['Scale'])

    # Where the bone currently sits in UV space is UV Island Center + the
    # calibrated mask-location delta. Distance from the raw UV to that
    # point, normalized by Mask Radius, inverted+clamped, and shaped by
    # Mask Sharpness gives a white-at-center radial falloff.
    bone_uv_pos = tree.nodes.new('ShaderNodeVectorMath')
    bone_uv_pos.operation = 'ADD'
    bone_uv_pos.label = "Bone UV Position"
    bone_uv_pos.location = (0, -700)
    tree.links.new(group_in.outputs['UV Island Center'], bone_uv_pos.inputs[0])
    tree.links.new(mask_loc_scaled.outputs[0], bone_uv_pos.inputs[1])

    dist = tree.nodes.new('ShaderNodeVectorMath')
    dist.operation = 'DISTANCE'
    dist.label = "Distance to Bone"
    dist.location = (200, -700)
    tree.links.new(uvmap.outputs['UV'], dist.inputs[0])
    tree.links.new(bone_uv_pos.outputs[0], dist.inputs[1])

    normalized = tree.nodes.new('ShaderNodeMath')
    normalized.operation = 'DIVIDE'
    normalized.label = "Distance / Mask Radius"
    normalized.location = (400, -700)
    tree.links.new(dist.outputs['Value'], normalized.inputs[0])
    tree.links.new(group_in.outputs['Mask Radius'], normalized.inputs[1])

    mask = tree.nodes.new('ShaderNodeMath')
    mask.operation = 'SUBTRACT'
    mask.label = "Mask (1 - falloff)"
    mask.use_clamp = True
    mask.location = (600, -700)
    mask.inputs[0].default_value = 1.0
    tree.links.new(normalized.outputs['Value'], mask.inputs[1])

    mask_pow = tree.nodes.new('ShaderNodeMath')
    mask_pow.operation = 'POWER'
    mask_pow.label = "Mask ^ Sharpness"
    mask_pow.location = (800, -700)
    tree.links.new(mask.outputs['Value'], mask_pow.inputs[0])
    tree.links.new(group_in.outputs['Mask Sharpness'], mask_pow.inputs[1])
    tree.links.new(mask_pow.outputs['Value'], group_out.inputs['Mask'])

    # Exp Index output: a lone Value node, wired straight to the Group
    # Output, whose value is driven (in refresh_uv_from_bone) from the
    # bone's custom property. Same pattern as the transform Value nodes.
    exp_val = tree.nodes.new('ShaderNodeValue')
    exp_val.name = _value_node_name("exp_index", "x")
    exp_val.label = "Exp Index"
    exp_val.location = (800, 200)
    tree.links.new(exp_val.outputs[0], group_out.inputs['Exp Index'])

    return tree


def _migrate_uv_tree_calibration_range(tree):
    """Upgrade a UV-From-Bone node tree to the current Calibration scheme:
    a direct 0-2 multiplier on the Location delta (1.0 = identity), no
    internal remap. Handles three starting states:
      - no Calibration socket at all (oldest, pre-1.4.0 trees)
      - the old 0-1-remapped-to-0-0.1 scheme (v1.4.0/v1.4.1)
      - already on the current scheme (no-op)

    build_uv_node_tree() only shapes brand-new nodes (init()/copy()) -- a
    node placed under an older scheme keeps it forever unless something
    goes back and retrofits its tree, which is what this does. Returns
    True if anything changed.
    """
    changed = False

    mapping = next((n for n in tree.nodes if n.bl_idname == 'ShaderNodeMapping'), None)
    group_in = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupInput'), None)
    if mapping is None or group_in is None:
        return False  # unrecognized topology -- don't guess, leave it alone

    calib_socket = next(
        (item for item in tree.interface.items_tree
         if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == "Calibration"),
        None,
    )
    if calib_socket is None:
        calib_socket = tree.interface.new_socket(name="Calibration", in_out='INPUT', socket_type='NodeSocketFloat')
        changed = True

    if calib_socket.min_value != 0.0 or calib_socket.max_value != 2.0:
        calib_socket.min_value = 0.0
        calib_socket.max_value = 2.0
        changed = True
    if calib_socket.default_value != 1.0:
        calib_socket.default_value = 1.0
        changed = True

    # Old remap node, if this tree still has one -- drop it once nothing
    # downstream needs it.
    remap_node = next(
        (n for n in tree.nodes if n.bl_idname == 'ShaderNodeMath' and n.label == "Calibration * 0.1"),
        None,
    )

    loc_input = mapping.inputs['Location']
    loc_scaled = loc_input.links[0].from_node if loc_input.links else None

    if loc_scaled is not None and loc_scaled.bl_idname == 'ShaderNodeVectorMath':
        scale_in = loc_scaled.inputs['Scale']
        already_direct = any(
            link.from_node is group_in and link.from_socket.name == 'Calibration'
            for link in scale_in.links
        )
        if not already_direct:
            for link in list(scale_in.links):
                tree.links.remove(link)
            tree.links.new(group_in.outputs['Calibration'], scale_in)
            changed = True
    else:
        # This tree never had Calibration wired in at all (pre-1.4.0) --
        # insert a scale node between the Location combine and Mapping.
        if loc_input.links:
            old_link = loc_input.links[0]
            combine_loc_socket = old_link.from_socket
            tree.links.remove(old_link)
            loc_scaled = tree.nodes.new('ShaderNodeVectorMath')
            loc_scaled.operation = 'SCALE'
            loc_scaled.label = "Location * Calibration"
            loc_scaled.location = (mapping.location.x - 600, mapping.location.y - 200)
            tree.links.new(combine_loc_socket, loc_scaled.inputs[0])
            tree.links.new(group_in.outputs['Calibration'], loc_scaled.inputs['Scale'])
            tree.links.new(loc_scaled.outputs[0], mapping.inputs['Location'])
            changed = True

    if remap_node is not None:
        tree.nodes.remove(remap_node)
        changed = True

    return changed


def _migrate_uv_tree_add_mask(tree):
    """Add the Mask Radius input and Mask output (a radial falloff mask
    centered on the bone's current calibrated UV position) to a tree that
    predates this feature. Returns True if the tree was changed."""
    names = {item.name for item in tree.interface.items_tree if item.item_type == 'SOCKET'}
    has_radius = "Mask Radius" in names
    has_mask_out = any(
        item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == "Mask"
        for item in tree.interface.items_tree
    )
    if has_radius and has_mask_out:
        return False

    group_in = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupInput'), None)
    group_out = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupOutput'), None)
    uvmap = tree.nodes.get(UVFB_UVMAP_NODE)
    loc_scaled = next(
        (n for n in tree.nodes if n.bl_idname == 'ShaderNodeVectorMath' and n.label == "Location * Calibration"),
        None,
    )
    if group_in is None or group_out is None or uvmap is None or loc_scaled is None:
        return False  # unrecognized topology -- don't guess, leave it alone

    if not has_radius:
        mask_radius = tree.interface.new_socket(name="Mask Radius", in_out='INPUT', socket_type='NodeSocketFloat')
        mask_radius.default_value = 0.1
        mask_radius.min_value = 0.0
        mask_radius.max_value = 10.0
    if not has_mask_out:
        tree.interface.new_socket(name="Mask", in_out='OUTPUT', socket_type='NodeSocketFloat')

    # Interface changes above regenerate Group Input/Output sockets, so
    # group_in.outputs['Mask Radius'] / group_out.inputs['Mask'] are only
    # valid to look up now, after both new_socket() calls.
    bone_uv_pos = tree.nodes.new('ShaderNodeVectorMath')
    bone_uv_pos.operation = 'ADD'
    bone_uv_pos.label = "Bone UV Position"
    bone_uv_pos.location = (loc_scaled.location.x, loc_scaled.location.y - 300)
    tree.links.new(group_in.outputs['Pivot'], bone_uv_pos.inputs[0])
    tree.links.new(loc_scaled.outputs[0], bone_uv_pos.inputs[1])

    dist = tree.nodes.new('ShaderNodeVectorMath')
    dist.operation = 'DISTANCE'
    dist.label = "Distance to Bone"
    dist.location = (bone_uv_pos.location.x + 200, bone_uv_pos.location.y)
    tree.links.new(uvmap.outputs['UV'], dist.inputs[0])
    tree.links.new(bone_uv_pos.outputs[0], dist.inputs[1])

    normalized = tree.nodes.new('ShaderNodeMath')
    normalized.operation = 'DIVIDE'
    normalized.label = "Distance / Mask Radius"
    normalized.location = (dist.location.x + 200, dist.location.y)
    tree.links.new(dist.outputs['Value'], normalized.inputs[0])
    tree.links.new(group_in.outputs['Mask Radius'], normalized.inputs[1])

    mask = tree.nodes.new('ShaderNodeMath')
    mask.operation = 'SUBTRACT'
    mask.label = "Mask (1 - falloff)"
    mask.use_clamp = True
    mask.location = (normalized.location.x + 200, normalized.location.y)
    mask.inputs[0].default_value = 1.0
    tree.links.new(normalized.outputs['Value'], mask.inputs[1])
    tree.links.new(mask.outputs['Value'], group_out.inputs['Mask'])

    return True


def _migrate_uv_tree_rename_and_resize_pivot(tree):
    """Rename the old "Pivot" interface socket to "UV Island Center" and
    shrink it from a 3D to a 2D vector (Z was always unused -- a UV
    coordinate only has X/Y). This mutates the existing interface item in
    place, so every internal link that already points at it (sub_pivot,
    add_pivot, bone_uv_pos) stays connected across both changes. Returns
    True if anything changed."""
    changed = False
    item = next(
        (it for it in tree.interface.items_tree
         if it.item_type == 'SOCKET' and it.in_out == 'INPUT' and it.name in ("Pivot", "UV Island Center")),
        None,
    )
    if item is None:
        return False  # unrecognized topology -- don't guess, leave it alone

    if item.name != "UV Island Center":
        item.name = "UV Island Center"
        changed = True
    if item.dimensions != 2:
        identifier = item.identifier
        old_default = tuple(item.default_value)
        item.dimensions = 2
        # Setting `dimensions` invalidates the Python wrapper we're holding
        # (its default_value still reports/expects the old 3-item shape
        # until re-fetched) -- grab a fresh reference before touching it.
        item = tree.interface.items_tree[identifier]
        item.default_value = old_default[:2]
        changed = True

    return changed


def _migrate_uv_tree_mask_independent_position(tree):
    """Give the Mask its own dedicated, independently-driven position feed
    (mask_loc_x/y) instead of reusing the UV shift's loc_scaled -- so the
    per-node mask Invert / Local-World toggles can differ from the UV
    shift's without touching the UV shift at all. Returns True if changed.
    """
    bone_uv_pos = next(
        (n for n in tree.nodes if n.bl_idname == 'ShaderNodeVectorMath' and n.label == "Bone UV Position"), None
    )
    group_in = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupInput'), None)
    pivot_socket_name = "UV Island Center" if any(
        it.item_type == 'SOCKET' and it.in_out == 'INPUT' and it.name == "UV Island Center"
        for it in tree.interface.items_tree
    ) else "Pivot"
    if bone_uv_pos is None or group_in is None:
        return False  # unrecognized topology -- don't guess, leave it alone

    loc_input = bone_uv_pos.inputs[1]
    feeding_node = loc_input.links[0].from_node if loc_input.links else None
    if feeding_node is not None and feeding_node.label == "Mask Location * Calibration":
        return False  # already on the independent scheme

    mask_loc_combine = tree.nodes.new('ShaderNodeCombineXYZ')
    mask_loc_combine.label = "Mask Location"
    mask_loc_combine.location = (bone_uv_pos.location.x - 600, bone_uv_pos.location.y)
    for i, comp in enumerate(("x", "y")):
        val = tree.nodes.new('ShaderNodeValue')
        val.name = _value_node_name("mask_loc", comp)
        val.label = "Mask Location {}".format(comp.upper())
        val.location = (mask_loc_combine.location.x - 200, mask_loc_combine.location.y - i * 40)
        tree.links.new(val.outputs[0], mask_loc_combine.inputs[i])
    mask_loc_combine.inputs[2].default_value = 0.0

    mask_loc_scaled = tree.nodes.new('ShaderNodeVectorMath')
    mask_loc_scaled.operation = 'SCALE'
    mask_loc_scaled.label = "Mask Location * Calibration"
    mask_loc_scaled.location = (bone_uv_pos.location.x - 300, bone_uv_pos.location.y)
    tree.links.new(mask_loc_combine.outputs[0], mask_loc_scaled.inputs[0])
    tree.links.new(group_in.outputs['Calibration'], mask_loc_scaled.inputs['Scale'])

    for link in list(loc_input.links):
        tree.links.remove(link)
    tree.links.new(mask_loc_scaled.outputs[0], loc_input)
    # Make sure bone_uv_pos.inputs[0] points at the (possibly just-renamed)
    # pivot socket -- a no-op if it's already wired correctly.
    for link in list(bone_uv_pos.inputs[0].links):
        tree.links.remove(link)
    tree.links.new(group_in.outputs[pivot_socket_name], bone_uv_pos.inputs[0])

    return True


def _migrate_uv_tree_add_mask_sharpness(tree):
    """Add the Mask Sharpness input (an exponent shaping the mask falloff
    curve) to a tree that predates it, inserting a Power node between the
    existing linear falloff and the Mask output. Returns True if changed.
    """
    has_sharpness = any(
        item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == "Mask Sharpness"
        for item in tree.interface.items_tree
    )
    mask = next(
        (n for n in tree.nodes if n.bl_idname == 'ShaderNodeMath' and n.label == "Mask (1 - falloff)"), None
    )
    group_in = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupInput'), None)
    group_out = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupOutput'), None)
    if mask is None or group_in is None or group_out is None:
        return False  # unrecognized topology -- don't guess, leave it alone

    already_wired = any(
        link.from_node.bl_idname == 'ShaderNodeMath' and link.from_node.label == "Mask ^ Sharpness"
        for link in group_out.inputs['Mask'].links
    )
    if has_sharpness and already_wired:
        return False

    if not has_sharpness:
        mask_sharpness = tree.interface.new_socket(name="Mask Sharpness", in_out='INPUT', socket_type='NodeSocketFloat')
        mask_sharpness.default_value = 1.0
        mask_sharpness.min_value = 0.05
        mask_sharpness.max_value = 10.0

    if not already_wired:
        mask_pow = tree.nodes.new('ShaderNodeMath')
        mask_pow.operation = 'POWER'
        mask_pow.label = "Mask ^ Sharpness"
        mask_pow.location = (mask.location.x + 200, mask.location.y)
        tree.links.new(mask.outputs['Value'], mask_pow.inputs[0])
        # Interface change above regenerates Group Input sockets, so this
        # lookup is only valid now, after new_socket() (if it ran).
        tree.links.new(group_in.outputs['Mask Sharpness'], mask_pow.inputs[1])
        tree.links.new(mask_pow.outputs['Value'], group_out.inputs['Mask'])

    return True


def _migrate_uv_tree_add_exp_index(tree):
    """Add the "Exp Index" output (a bone custom-property value, surfaced
    via a SINGLE_PROP driver) plus its backing Value node to a tree that
    predates this feature. Returns True if the tree was changed."""
    has_out = any(
        item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == "Exp Index"
        for item in tree.interface.items_tree
    )
    existing_val = tree.nodes.get(_value_node_name("exp_index", "x"))
    if has_out and existing_val is not None:
        return False

    group_out = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupOutput'), None)
    if group_out is None:
        return False  # unrecognized topology -- don't guess, leave it alone

    if not has_out:
        tree.interface.new_socket(name="Exp Index", in_out='OUTPUT', socket_type='NodeSocketFloat')

    val = existing_val
    if val is None:
        val = tree.nodes.new('ShaderNodeValue')
        val.name = _value_node_name("exp_index", "x")
        val.label = "Exp Index"
        val.location = (group_out.location.x - 200, group_out.location.y + 200)

    # Interface change above regenerates Group Output sockets, so this
    # lookup is only valid now, after new_socket() (if it ran).
    tree.links.new(val.outputs[0], group_out.inputs['Exp Index'])
    return True


def refresh_uv_from_bone(node):
    """(Re)connect drivers, honoring the per-axis Invert toggles.

    Why invert toggles exist at all: a bone that's mirrored (very common for
    an L/R pair in a facial rig -- one side is a mirrored duplicate of the
    other) has a rest matrix with a negative determinant. Decomposing that
    into location/rotation/scale is not a neutral operation -- Blender (like
    any decomposition) has to push the "flip" somewhere, and it can come out
    as a sign flip on a location or rotation axis, or as a negative-looking
    scale axis, depending on the specific mirror setup. There's no single
    universal fix that works for every rig, so instead of guessing, each
    axis gets its own toggle here -- tick whichever ones make the UV track
    the bone correctly for this particular bone.
    """
    tree = node.node_tree
    if tree is None:
        return

    _migrate_uv_tree_calibration_range(tree)
    _migrate_uv_tree_add_mask(tree)
    _migrate_uv_tree_rename_and_resize_pivot(tree)
    _migrate_uv_tree_mask_independent_position(tree)
    _migrate_uv_tree_add_mask_sharpness(tree)
    _migrate_uv_tree_add_exp_index(tree)

    # Amount is meant to be dialed in once (normally left at 1.0) and then
    # left alone -- hide its inline field so the node stays uncluttered.
    # This only hides the value widget; the socket and its wiring are
    # untouched, so it can still be linked into from elsewhere if needed.
    amount_input = node.inputs.get('Amount')
    if amount_input is not None:
        amount_input.hide_value = True
        if amount_input.default_value != 1.0:
            amount_input.default_value = 1.0

    # A freshly-migrated Mask Radius socket on an existing node instance can
    # come in at 0.0 (Blender doesn't always seed it from the interface's
    # default_value) -- that would divide-by-zero in the mask math below,
    # so nudge it up to something usable instead of leaving it degenerate.
    mask_radius_input = node.inputs.get('Mask Radius')
    if mask_radius_input is not None and mask_radius_input.default_value <= 0.0:
        mask_radius_input.default_value = 0.1

    # Same guard for a freshly-migrated Mask Sharpness -- 0 or negative
    # would make POWER degenerate (constant 1.0, or undefined for negative
    # bases), so fall back to 1.0 (the linear, pre-Sharpness behavior).
    mask_sharpness_input = node.inputs.get('Mask Sharpness')
    if mask_sharpness_input is not None and mask_sharpness_input.default_value <= 0.0:
        mask_sharpness_input.default_value = 1.0

    tree.nodes[UVFB_UVMAP_NODE].uv_map = node.uv_map_name

    _uv_clear_drivers(tree)

    armature = node.armature_obj
    bone_name = node.bone_name
    valid = bool(
        armature and armature.type == 'ARMATURE'
        and bone_name and bone_name in armature.data.bones
    )

    if not valid:
        for i in range(3):
            _set_static(tree, "local_loc", i, 0.0)
            _set_static(tree, "local_rot", i, 0.0)
            _set_static(tree, "local_scale", i, 1.0)
        for comp in ("x", "y"):
            tree.nodes[_value_node_name("mask_loc", comp)].outputs[0].default_value = 0.0
        _set_static(tree, "exp_index", 0, 0.0)
        return

    invert_loc = (node.invert_location_x, node.invert_location_y, False)
    invert_rot = (node.invert_rotation, node.invert_rotation, node.invert_rotation)
    invert_scale = (node.invert_scale_x, node.invert_scale_y, False)
    invert_map = {"local_loc": invert_loc, "local_rot": invert_rot, "local_scale": invert_scale}
    mirror_mode = {"local_loc": "negate", "local_rot": "negate", "local_scale": "mirror1"}

    for key, (types, space) in UV_DRIVEN_SPECS.items():
        flags = invert_map[key]
        mode = mirror_mode[key]
        for i, ttype in enumerate(types):
            if flags[i]:
                expr = "-bone" if mode == "negate" else "2-bone"
            else:
                expr = "bone"
            _add_transform_driver(tree, key, i, armature, bone_name, ttype, space, expression=expr)

    # Mask position: confirmed-correct as local-space, non-inverted --
    # independent of the UV shift's own invert_location_x/y (see the Mask
    # section of build_uv_node_tree() for why it has its own driven feed).
    # This used to be togglable per-node (Invert Mask Location / Mask Uses
    # World Space); both landed on their default (off/off) as the correct
    # setting after testing, so the toggles were removed and this is now
    # simply fixed.
    for i, ttype in enumerate(("LOC_X", "LOC_Y")):
        _add_transform_driver(tree, "mask_loc", i, armature, bone_name, ttype, 'LOCAL_SPACE', expression="bone")

    # Exp Index: drive the output Value node from the bone's custom property
    # (default "exp_index"), auto-following whatever bone this node targets.
    # Only wire the driver when the property actually exists on the pose
    # bone -- otherwise leave a clean static 0 instead of a broken driver
    # that spams evaluation errors in the console.
    prop_name = (node.index_prop_name or "exp_index").strip()
    pbone = armature.pose.bones.get(bone_name)
    if prop_name and pbone is not None and prop_name in pbone.keys():
        data_path = 'pose.bones["{}"]["{}"]'.format(bone_name, prop_name)
        _add_single_prop_driver(tree, "exp_index", 0, armature, data_path)
    else:
        _set_static(tree, "exp_index", 0, 0.0)


def _on_uv_target_updated(self, context):
    refresh_uv_from_bone(self)


class ShaderNodeCustomUVFromBone(ShaderNodeCustomGroup):
    """UV From Bone: shifts/rotates/scales a UV coordinate live from a
    bone's LOCAL pose (its delta from rest), pivoting around a chosen
    point in UV space. Good for e.g. driving an iris/pupil UV offset or
    a facial-gesture UV shift from a control bone."""
    bl_idname = "ShaderNodeCustomUVFromBone"
    bl_label = "UV From Bone"
    bl_icon = 'UV'

    armature_obj: PointerProperty(
        name="Armature",
        type=bpy.types.Object,
        poll=is_armature,
        update=_on_uv_target_updated,
    )
    bone_name: StringProperty(
        name="Bone",
        update=_on_uv_target_updated,
    )
    uv_map_name: StringProperty(
        name="UV Map",
        description="Leave empty to use the active UV map",
        update=_on_uv_target_updated,
    )
    index_prop_name: StringProperty(
        name="Index Property",
        description=(
            "Name of the custom property on the target bone to surface on the "
            "'Exp Index' output (e.g. exp_index -> pose.bones[bone][\"exp_index\"])"
        ),
        default="exp_index",
        update=_on_uv_target_updated,
    )

    # Default True: for this rig's mirrored L/R bone pairs, all five of
    # these came out needing inversion, so new nodes start there instead of
    # everyone re-discovering the same setting. The toggles themselves are
    # kept out of draw_buttons (declutter) but the properties still exist
    # -- editable from the N-panel/Python console if a future bone needs
    # something different.
    invert_location_x: BoolProperty(name="Invert Location X", default=True, update=_on_uv_target_updated)
    invert_location_y: BoolProperty(name="Invert Location Y", default=True, update=_on_uv_target_updated)
    invert_rotation: BoolProperty(name="Invert Rotation", default=True, update=_on_uv_target_updated)
    invert_scale_x: BoolProperty(name="Invert Scale X", default=True, update=_on_uv_target_updated)
    invert_scale_y: BoolProperty(name="Invert Scale Y", default=True, update=_on_uv_target_updated)

    def init(self, context):
        self.node_tree = build_uv_node_tree()
        self.width = 200

    def copy(self, node):
        self.node_tree = build_uv_node_tree()
        refresh_uv_from_bone(self)

    def free(self):
        _free_private_tree(self)

    def draw_buttons(self, context, layout):
        layout.prop(self, "armature_obj", text="")
        if self.armature_obj and self.armature_obj.type == 'ARMATURE':
            layout.prop_search(self, "bone_name", self.armature_obj.data, "bones", text="")
        else:
            row = layout.row()
            row.enabled = False
            row.label(text="Select an Armature", icon='ERROR')
        layout.prop(self, "uv_map_name", text="", icon='UV')
        layout.prop(self, "index_prop_name", text="", icon='RNA')

        # Shared-tree guard: two instances sharing one internal tree makes
        # their per-bone drivers collide (paste/duplicate can cause this
        # when Blender doesn't fire copy()). Show a warning + one-click fix
        # only while it's actually a problem, so a healthy node stays clean.
        if _uv_from_bone_tree_is_shared(self):
            box = layout.box()
            col = box.column(align=True)
            col.label(text="Shared internal tree", icon='ERROR')
            col.label(text="Drivers collide with another node")
            row = col.row()
            row.context_pointer_set("uvfb_node", self)
            row.operator("node.uvfb_make_unique", text="Make Unique", icon='DUPLICATE')

    def draw_label(self):
        return "UV From Bone"


class NODE_OT_uvfb_make_unique(bpy.types.Operator):
    """Give this UV From Bone node its own private internal node tree, so its
    bone drivers stop colliding with another node that shares the same tree"""
    bl_idname = "node.uvfb_make_unique"
    bl_label = "Make UV From Bone Tree Unique"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # The node is handed in via context_pointer_set("uvfb_node", self)
        # on the button's row -- avoids the ambiguity of resolving a node by
        # name across multiple materials/trees.
        node = getattr(context, "uvfb_node", None)
        if node is None or getattr(node, "bl_idname", None) != "ShaderNodeCustomUVFromBone":
            self.report({'WARNING'}, "No UV From Bone node in context")
            return {'CANCELLED'}
        if node.node_tree is None:
            self.report({'WARNING'}, "Node has no internal tree")
            return {'CANCELLED'}
        _give_private_tree(node)
        refresh_uv_from_bone(node)
        self.report({'INFO'}, "UV From Bone now has its own private tree")
        return {'FINISHED'}


classes = (
    ShaderNodeCustomBoneInfo,
    ShaderNodeCustomUVFromBone,
    NODE_OT_uvfb_make_unique,
)

# Custom nodes that build their sockets dynamically (like this one) don't
# appear in Blender's "drag a link and release to search" popup -- that
# popup only lists nodes with statically declared socket types. So this
# node is added directly to the Add menu instead, in two places for
# reliability across Blender versions: the root Add menu (always present,
# always searchable via the Shift+A search field) and, where it exists,
# the Input category submenu for a tidier location.
_MENU_TARGETS = ("NODE_MT_add", "NODE_MT_category_shader_input")


def _iter_all_uv_from_bone_nodes():
    """Yield every 'UV From Bone' node instance in the file, across both
    standalone node groups and material node trees.

    A node lives in exactly one tree, so iterating each container once
    already visits each node once -- do NOT dedup by id(n): bpy wrappers
    are transient and Python recycles their addresses, so an id()-keyed
    'seen' set silently drops nodes. Containers are deduped by as_pointer()
    instead (cheap, stable) in case two materials ever share a node tree."""
    seen_containers = set()
    containers = list(bpy.data.node_groups) + [
        m.node_tree for m in bpy.data.materials if m.node_tree is not None
    ]
    for cont in containers:
        cptr = cont.as_pointer()
        if cptr in seen_containers:
            continue
        seen_containers.add(cptr)
        for n in cont.nodes:
            if n.bl_idname == "ShaderNodeCustomUVFromBone":
                yield n


def _free_private_tree(node):
    """free() hook: when this node is deleted, drop its internal group -- but
    only if no OTHER node still references it.

    Uses a reference scan (excluding the node being freed) rather than the
    datablock user count: for custom group nodes that count is unreliable at
    free() time (a single live node reports the group as 2 users, and after
    deletion it lags), so a `users <= 1` test never fires and the group
    leaks. The scan is exact. Defensive try/except: if anything about the
    context makes removal unsafe, we bail and leave it for the reload-time
    _purge_orphan_internal_trees() backstop to sweep."""
    t = node.node_tree
    if t is None:
        return
    tptr = t.as_pointer()
    nptr = node.as_pointer()
    try:
        containers = list(bpy.data.node_groups) + [
            m.node_tree for m in bpy.data.materials if m.node_tree
        ]
        for cont in containers:
            for other in cont.nodes:
                if (other.as_pointer() != nptr
                        and other.bl_idname in ("ShaderNodeCustomUVFromBone", "ShaderNodeCustomBoneInfo")
                        and other.node_tree is not None
                        and other.node_tree.as_pointer() == tptr):
                    return  # still in use by another node -- keep it
        t.use_fake_user = False
        bpy.data.node_groups.remove(t)
    except Exception as e:
        print("Bone Info addon: _free_private_tree skipped:", e)


def _purge_orphan_internal_trees():
    """Remove Bone Info / UV From Bone internal groups that no live node
    references. These groups are meant to live exactly as long as the node
    that owns them; historically they were created with use_fake_user,
    which pinned orphans in the .blend and made them pile up. Returns the
    number removed. Only touches groups whose names carry our internal
    prefixes AND that nothing references -- never a group in use."""
    live = set()
    for cont in list(bpy.data.node_groups) + [m.node_tree for m in bpy.data.materials if m.node_tree]:
        for n in cont.nodes:
            if n.bl_idname in ("ShaderNodeCustomUVFromBone", "ShaderNodeCustomBoneInfo") and n.node_tree:
                live.add(n.node_tree.as_pointer())

    prefixes = (".UVFromBone", ".BoneInfo")
    removed = 0
    for g in list(bpy.data.node_groups):
        if g.bl_idname != 'ShaderNodeTree':
            continue
        if not any(g.name.startswith(p) for p in prefixes):
            continue
        if g.as_pointer() in live:
            continue
        g.use_fake_user = False
        bpy.data.node_groups.remove(g)
        removed += 1
    return removed


def _give_private_tree(node):
    """Replace node.node_tree with a private .copy() of itself, preserving
    this instance's per-node input socket values (UV Island Center, Amount,
    Calibration, Mask Radius/Sharpness) and their hide_value flags -- those
    live on the node instance, and reassigning node_tree can otherwise reset
    them to the interface defaults. Does NOT re-drive the tree; the caller
    must run refresh_uv_from_bone(node) afterwards to rebuild its drivers."""
    tree = node.node_tree
    if tree is None:
        return
    snap = {}
    for s in node.inputs:
        try:
            dv = s.default_value
            snap[s.identifier] = (list(dv) if hasattr(dv, "__len__") else dv, s.hide_value)
        except (AttributeError, TypeError):
            pass
    node.node_tree = tree.copy()
    for s in node.inputs:
        if s.identifier in snap:
            val, hv = snap[s.identifier]
            try:
                s.default_value = val
                s.hide_value = hv
            except (AttributeError, TypeError):
                pass


def _uv_from_bone_tree_is_shared(node):
    """True if this node's internal tree is referenced by more than one
    'UV From Bone' instance -- i.e. its per-bone drivers are colliding with
    another node's and it needs a Make Unique. Walks all instances (early
    out at the second hit); cheap for the handful of these in a scene.

    Compares datablocks by as_pointer(), NOT Python `is`: Blender returns a
    fresh wrapper object each time node.node_tree is accessed, so `is` can
    be False for two references to the very same datablock."""
    tree = node.node_tree
    if tree is None:
        return False
    ptr = tree.as_pointer()
    count = 0
    for n in _iter_all_uv_from_bone_nodes():
        if n.node_tree is not None and n.node_tree.as_pointer() == ptr:
            count += 1
            if count > 1:
                return True
    return False


def _dedup_uv_from_bone_trees():
    """Ensure every 'UV From Bone' node owns a PRIVATE internal node tree.

    Each instance's per-bone drivers live on its internal node tree, so if
    two instances that target different bones share one tree, only one bone
    can win -- the other silently reads whichever bone was written last
    (its UV shift, mask, and Exp Index all track the wrong bone). Instances
    can end up sharing a tree when they're duplicated by a path that
    doesn't fire the node's copy() (e.g. copy/pasting nodes between
    materials, or duplicating the material). This gives every extra sharer
    its own private copy. Returns the number of trees that were split off.
    """
    usage = {}
    for n in _iter_all_uv_from_bone_nodes():
        if n.node_tree is not None:
            usage.setdefault(n.node_tree, []).append(n)

    split = 0
    for tree, nodes in usage.items():
        if len(nodes) <= 1:
            continue
        # Keep nodes[0] on the shared tree; give every other sharer a copy.
        for n in nodes[1:]:
            _give_private_tree(n)
            split += 1
    return split


def _heal_one_uv_from_bone_node(n):
    # Enforce "all inversions on" -- this addon is currently only used on
    # this rig's mirrored bone pairs, where that's always been the right
    # setting; refresh_uv_from_bone() picks these up when rebuilding drivers.
    n.invert_location_x = True
    n.invert_location_y = True
    n.invert_rotation = True
    n.invert_scale_x = True
    n.invert_scale_y = True
    # refresh_uv_from_bone() also runs the tree migrations (Calibration
    # range, Mask) and hides/pins the Amount socket -- one call covers
    # everything a pre-existing node needs to catch up on.
    refresh_uv_from_bone(n)


def _heal_existing_uv_from_bone_nodes():
    """Run the migration + per-instance fixups against every 'UV From Bone'
    node already placed in this .blend, so re-running/reloading this
    script (the normal dev workflow here -- this file lives as a Text
    datablock, not an installed extension) automatically upgrades old
    nodes instead of silently leaving them stuck on an older schema."""
    # De-dup FIRST: split any shared internal trees so each node's own bone
    # drivers (rebuilt just below) can't clobber a sibling's on a shared tree.
    split = _dedup_uv_from_bone_trees()
    if split:
        print("Bone Info addon: split %d shared UV-From-Bone tree(s) into private copies" % split)
    for n in list(_iter_all_uv_from_bone_nodes()):
        try:
            _heal_one_uv_from_bone_node(n)
        except Exception as e:
            print("Bone Info addon: failed to heal", n.name, e)
    # Sweep up any internal groups nothing references any more (orphans from
    # deletions/duplication, or legacy fake-user groups from older versions).
    purged = _purge_orphan_internal_trees()
    if purged:
        print("Bone Info addon: purged %d orphan internal node group(s)" % purged)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for name in _MENU_TARGETS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(_menu_draw)
    _heal_existing_uv_from_bone_nodes()


def unregister():
    for name in _MENU_TARGETS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            try:
                menu.remove(_menu_draw)
            except Exception:
                pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)