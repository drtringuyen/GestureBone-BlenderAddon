"""
expression_sheet/nodes.py -- Expression Sheet shader nodes (shared group).

Adds a 'UV From Bone (Shared)' Shader Editor node. ALL instances reuse ONE
internal node group, so creating/duplicating nodes adds no new groups.

SCHEMA v2 (packed): everything the bone contributes travels as ONE float4
custom property on the mesh objects -- (loc.x, loc.y, rot.z, uniform scale) --
plus a scalar exp index, read back by TWO ShaderNodeAttribute feeds instead of
v1's five. Location / Rotation / Scale / Mask Location are reconstructed
inside the shared group, where extra nodes cost nothing visually.

  * 6 satellite nodes per instance -> 3, two of them collapsed
  * 12 driver fcurves per mesh -> 5
  * the float4 maps 1:1 onto an engine-side float4 if this is ever exported

v1 files upgrade themselves in place on load (upgrade_shared_tree, preserving
authored socket values AND the user's downstream links). Instances whose group
is still v1 -- in practice ones living in a LINKED library saved by an older
addon, which cannot be upgraded from here -- keep being driven in the v1 shape
by _build_drivers_v1.

register()/unregister() are called by this module's __init__.py.
"""

import bpy
from bpy.types import ShaderNodeCustomGroup
from bpy.props import PointerProperty, StringProperty, BoolProperty
from bpy.app.handlers import persistent

SHARED_GROUP_NAME = ".UVFromBoneShared"
SHARED_GROUP_VERSION = 2
VERSION_KEY = "gb_uvfb_version"          # custom prop stamped on the group
NODE_ID = "ShaderNodeCustomUVFromBoneShared"
UVFB_UVMAP_SUFFIX = "__UVForBone"   # auto-created UV Map node name suffix

COMPONENTS = ("x", "y", "z")

# Authored per-instance socket values -- preserved across a schema upgrade.
USER_SOCKETS = ("UV Island Center", "Calibration", "Mask Radius", "Mask Sharpness")

# v1 driven input sockets (name -> transform spec). Still used to drive
# instances stuck on a linked v1 group; see _build_drivers_v1.
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

def _can_edit(id_block):
    """True when this datablock may be modified *and saved*.

    Linked (library) data is still writable through RNA in memory, but the
    change is never saved and silently diverges from the library -- so the
    group upgrade must never touch it. Instances living in a linked tree keep
    being driven in whatever format that library's own group expects; see
    _build_drivers_v1.
    """
    return id_block is not None and getattr(id_block, "library", None) is None


def _tree_version(tree):
    """Schema version of a shared group. Unstamped == the original v1 group."""
    if tree is None:
        return 0
    try:
        return int(tree[VERSION_KEY])
    except Exception:
        return 1


def _populate_shared_uv_tree(tree):
    """Fill an EMPTY ShaderNodeTree with the v2 UV-From-Bone graph.

    v2 packs everything the bone contributes into ONE float4 -- Bone UV .xyz =
    local (loc.x, loc.y, rot.z), Bone Scale = that float4's .w read off the
    Attribute node's Alpha output -- plus a scalar Exp Index. That is two
    ShaderNodeAttribute feeds per instance instead of v1's five, and 5 driver
    fcurves per mesh instead of 12.

    Location / Rotation / Scale / Mask Location are rebuilt in HERE, where
    extra nodes cost nothing visually. Mask Location is the same bone's raw
    local XY -- v1 drove it as its own vector purely because the invert flags
    are baked into the driver expression; here 'Mask Sign' (a static,
    never-driven socket the node writes from its own invert flags) undoes
    them, so no second transport is needed.
    """
    iface = tree.interface

    iface.new_socket(name="UV", in_out='INPUT', socket_type='NodeSocketVector')

    piv = iface.new_socket(name="UV Island Center", in_out='INPUT', socket_type='NodeSocketVector')
    piv_id = piv.identifier
    piv.dimensions = 2
    # Blender 5.2 invalidates the wrapper when dimensions changes -- re-fetch
    # before touching default_value or it rejects the 2-item value.
    piv = iface.items_tree[piv_id]
    piv.default_value = (0.5, 0.5)

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

    # --- driven / static per-instance inputs (hidden on the node) ---
    iface.new_socket(name="Bone UV", in_out='INPUT', socket_type='NodeSocketVector')
    bscale = iface.new_socket(name="Bone Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    bscale.default_value = 1.0
    iface.new_socket(name="Exp Index In", in_out='INPUT', socket_type='NodeSocketFloat')
    msign = iface.new_socket(name="Mask Sign", in_out='INPUT', socket_type='NodeSocketVector')
    msign.default_value = (1.0, 1.0, 1.0)

    iface.new_socket(name="UV", in_out='OUTPUT', socket_type='NodeSocketVector')
    iface.new_socket(name="Mask", in_out='OUTPUT', socket_type='NodeSocketFloat')
    iface.new_socket(name="Exp Index", in_out='OUTPUT', socket_type='NodeSocketFloat')

    gin = tree.nodes.new('NodeGroupInput')
    gin.location = (-1200, 0)
    gout = tree.nodes.new('NodeGroupOutput')
    gout.location = (1100, 0)

    # --- unpack the float4 back into the v1 vectors ---
    sep = tree.nodes.new('ShaderNodeSeparateXYZ')
    sep.label = "Unpack Bone float4"
    sep.location = (-950, -150)
    tree.links.new(gin.outputs['Bone UV'], sep.inputs['Vector'])

    loc_vec = tree.nodes.new('ShaderNodeCombineXYZ')
    loc_vec.label = "Location"
    loc_vec.location = (-750, -60)
    loc_vec.inputs['Z'].default_value = 0.0
    tree.links.new(sep.outputs['X'], loc_vec.inputs['X'])
    tree.links.new(sep.outputs['Y'], loc_vec.inputs['Y'])

    rot_vec = tree.nodes.new('ShaderNodeCombineXYZ')
    rot_vec.label = "Rotation"
    rot_vec.location = (-750, -240)
    rot_vec.inputs['X'].default_value = 0.0
    rot_vec.inputs['Y'].default_value = 0.0
    tree.links.new(sep.outputs['Z'], rot_vec.inputs['Z'])

    scl_vec = tree.nodes.new('ShaderNodeCombineXYZ')
    scl_vec.label = "Scale (uniform)"
    scl_vec.location = (-750, -420)
    scl_vec.inputs['Z'].default_value = 1.0
    tree.links.new(gin.outputs['Bone Scale'], scl_vec.inputs['X'])
    tree.links.new(gin.outputs['Bone Scale'], scl_vec.inputs['Y'])

    mask_loc = tree.nodes.new('ShaderNodeVectorMath')
    mask_loc.operation = 'MULTIPLY'
    mask_loc.label = "Mask Location (un-inverted)"
    mask_loc.location = (-500, -600)
    tree.links.new(loc_vec.outputs['Vector'], mask_loc.inputs[0])
    tree.links.new(gin.outputs['Mask Sign'], mask_loc.inputs[1])

    # --- UV shift chain (identical math to v1) ---
    sub_pivot = tree.nodes.new('ShaderNodeVectorMath')
    sub_pivot.operation = 'SUBTRACT'
    sub_pivot.location = (-200, 200)
    tree.links.new(gin.outputs['UV'], sub_pivot.inputs[0])
    tree.links.new(gin.outputs['UV Island Center'], sub_pivot.inputs[1])

    loc_scaled = tree.nodes.new('ShaderNodeVectorMath')
    loc_scaled.operation = 'SCALE'
    loc_scaled.label = "Location * Calibration"
    loc_scaled.location = (-200, -100)
    tree.links.new(loc_vec.outputs['Vector'], loc_scaled.inputs[0])
    tree.links.new(gin.outputs['Calibration'], loc_scaled.inputs['Scale'])

    mapping = tree.nodes.new('ShaderNodeMapping')
    mapping.location = (200, 200)
    tree.links.new(sub_pivot.outputs[0], mapping.inputs['Vector'])
    tree.links.new(loc_scaled.outputs[0], mapping.inputs['Location'])
    tree.links.new(rot_vec.outputs['Vector'], mapping.inputs['Rotation'])
    tree.links.new(scl_vec.outputs['Vector'], mapping.inputs['Scale'])

    add_pivot = tree.nodes.new('ShaderNodeVectorMath')
    add_pivot.operation = 'ADD'
    add_pivot.location = (450, 200)
    tree.links.new(mapping.outputs[0], add_pivot.inputs[0])
    tree.links.new(gin.outputs['UV Island Center'], add_pivot.inputs[1])
    # v1 ended in a Mix(factor=Amount) between the untouched UV and this.
    # Amount was pinned to 1.0 and hidden, which makes that Mix an identity
    # pass-through of B -- dropped here, along with the socket.
    tree.links.new(add_pivot.outputs[0], gout.inputs['UV'])

    # --- Mask chain (identical math to v1) ---
    mloc_scaled = tree.nodes.new('ShaderNodeVectorMath')
    mloc_scaled.operation = 'SCALE'
    mloc_scaled.label = "Mask Location * Calibration"
    mloc_scaled.location = (-200, -400)
    tree.links.new(mask_loc.outputs[0], mloc_scaled.inputs[0])
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

    tree[VERSION_KEY] = SHARED_GROUP_VERSION
    return tree


def build_shared_uv_tree():
    """Build THE one shared UV-From-Bone group (current schema)."""
    tree = bpy.data.node_groups.new(SHARED_GROUP_NAME, 'ShaderNodeTree')
    tree.use_fake_user = True   # shared singleton: keep even with 0 users
    return _populate_shared_uv_tree(tree)


def _is_managed_attr_feed(node_name, owner_name):
    """Our own auto-created Attribute feeds -- rebuilt from scratch, so links
    from them must NOT be restored after a group rebuild."""
    return any(node_name == owner_name + s for s in ALL_ATTR_SUFFIXES)


def _snapshot_instances(tree):
    """Record everything a group rebuild would destroy, before it happens.

    Removing an interface socket removes the matching socket on every node
    instance -- taking its default_value AND every link attached to it. That
    means an unguarded rebuild would silently (a) reset authored values like
    UV Island Center / Calibration / Mask Radius / Mask Sharpness and (b) tear
    out the user's own downstream wiring from UV / Mask / Exp Index. Both are
    real data in every existing file, so both are snapshotted here and put
    back by _restore_instances.

    Keyed by NAME throughout, never by pointer (a tree mutation invalidates
    every node pointer held in a stale list). Link endpoints on OTHER nodes
    are recorded by socket INDEX, because names there are not unique -- a Math
    node has two inputs both called 'Value'.
    """
    saved = []
    for c in _iter_shared_containers():
        if not _can_edit(c):
            continue
        for name in [n.name for n in c.nodes if n.bl_idname == NODE_ID]:
            nd = c.nodes.get(name)
            if nd is None or nd.node_tree != tree:
                continue
            vals = {}
            for sname in USER_SOCKETS:
                s = nd.inputs.get(sname)
                if s is None:
                    continue
                try:
                    v = s.default_value
                    vals[sname] = list(v) if hasattr(v, "__len__") else float(v)
                except Exception:
                    pass
            in_links = []
            for s in nd.inputs:
                for l in s.links:
                    src = l.from_node
                    if _is_managed_attr_feed(src.name, name):
                        continue
                    try:
                        idx = list(src.outputs).index(l.from_socket)
                    except ValueError:
                        continue
                    in_links.append((s.name, src.name, idx))
            out_links = []
            for s in nd.outputs:
                for l in s.links:
                    dst = l.to_node
                    try:
                        idx = list(dst.inputs).index(l.to_socket)
                    except ValueError:
                        continue
                    out_links.append((s.name, dst.name, idx))
            saved.append((c.name, name, vals, in_links, out_links))
    return saved


def _restore_instances(saved):
    by_container = {}
    for cname, nname, vals, in_links, out_links in saved:
        by_container.setdefault(cname, []).append((nname, vals, in_links, out_links))
    for c in _iter_shared_containers():
        for nname, vals, in_links, out_links in by_container.get(c.name, ()):
            nd = c.nodes.get(nname)
            if nd is None:
                continue
            for sname, v in vals.items():
                s = nd.inputs.get(sname)
                if s is None:
                    continue
                try:
                    if hasattr(s.default_value, "__len__"):
                        n = len(s.default_value)
                        s.default_value = tuple(v)[:n] if hasattr(v, "__len__") else (v,) * n
                    else:
                        s.default_value = v[0] if hasattr(v, "__len__") else v
                except Exception as e:
                    print("Expression Sheet: could not restore value", cname, nname, sname, e)
            for sname, src_name, idx in in_links:
                dst_sock = nd.inputs.get(sname)
                src = c.nodes.get(src_name)
                if dst_sock is None or src is None or idx >= len(src.outputs):
                    continue
                try:
                    c.links.new(src.outputs[idx], dst_sock)
                except Exception as e:
                    print("Expression Sheet: could not restore in-link", cname, nname, sname, e)
            for sname, dst_name, idx in out_links:
                src_sock = nd.outputs.get(sname)
                dst = c.nodes.get(dst_name)
                if src_sock is None or dst is None or idx >= len(dst.inputs):
                    continue
                try:
                    c.links.new(src_sock, dst.inputs[idx])
                except Exception as e:
                    print("Expression Sheet: could not restore out-link", cname, nname, sname, e)


def upgrade_shared_tree(tree):
    """Rebuild an old shared group in place at the current schema.

    In place, on the SAME datablock, so no instance has to be re-pointed and
    no old tree has to be deleted -- a custom-group node's user count is not a
    reliable basis for deletion, so avoiding the deletion avoids the problem.

    Refuses to touch a LINKED group: it belongs to a library that may still be
    running the old addon, and writing to it would diverge in memory without
    ever being saved. Instances in linked trees stay on the v1 transport.
    """
    if tree is None or _tree_version(tree) >= SHARED_GROUP_VERSION:
        return False
    if not _can_edit(tree):
        return False
    saved = _snapshot_instances(tree)
    tree.nodes.clear()
    for item in list(tree.interface.items_tree):
        try:
            tree.interface.remove(item)
        except Exception:
            pass
    _populate_shared_uv_tree(tree)
    tree.use_fake_user = True
    _restore_instances(saved)
    print("GestureBone/ExpressionSheet: upgraded {} to v{} ({} instance(s) preserved)".format(
        tree.name, SHARED_GROUP_VERSION, len(saved)))
    return True


def get_shared_uv_tree():
    """Return the one LOCAL shared group, building or upgrading as needed.

    Explicitly prefers a local datablock: a linked character drags its own
    '.UVFromBoneShared' in, and new nodes must never be pointed at that.
    """
    t = None
    for g in bpy.data.node_groups:
        if g.name == SHARED_GROUP_NAME and g.library is None:
            t = g
            break
    if t is None:
        return build_shared_uv_tree()
    upgrade_shared_tree(t)
    return t


# ---------------------------------------------------------------------------
# Per-instance drivers.
#
# IMPORTANT: these must NOT live on the material node tree. A material
# node-tree driver that targets an armature (via TRANSFORMS or SINGLE_PROP)
# hangs Blender's Library Override resolver on this rig's dependency web
# (bisected -- see the library-override-hang project memory). The fix is to
# drive OBJECT custom properties on the mesh(es) using the material instead
# (object-level drivers are override-safe), and have the material read them
# back with a passive ShaderNodeAttribute (attribute_type='OBJECT') wired
# into the node's own input sockets -- see _ensure_attr_feed below.
# ---------------------------------------------------------------------------

def _legacy_socket_path(node_name, socket_name):
    return 'nodes["{}"].inputs["{}"].default_value'.format(node_name, socket_name)


def _clear_legacy_socket_drivers(node):
    """Remove old-style drivers directly on this node's own input sockets
    (pre-fix Design B files). Safe/cheap no-op once migrated."""
    container = node.id_data
    if not _can_edit(container):
        return
    name = node.name
    for socket_name in ("Location", "Rotation", "Scale", "Mask Location"):
        for i in range(3):
            container.driver_remove(_legacy_socket_path(name, socket_name), i)
    container.driver_remove(_legacy_socket_path(name, "Exp Index In"))


def _instance_key_ident(node):
    """Base identifier baked into this instance's per-instance property keys
    and satellite feed-node labels. Defaults to node.name (today's behavior)
    until a Tidy pass (see tidy_expression_node_and_driver below) switches it
    to the bone name via a marker stored ON THE NODE -- never on node.name
    itself. Each satellite's own identity in the tree (node.name + a fixed
    suffix, what _ensure_attr_feed / _remove_attr_feeds / the orphan-sweep
    timer look it up by) is intentionally NOT derived from this and never
    moves, so a Tidy pass can't orphan-and-duplicate a feed node the way
    renaming node.name itself would."""
    try:
        v = node.get("_gb_key_ident")
    except Exception:
        v = None
    return v if v else node.name


def _prop_key(container, node, socket_name):
    """Unique custom-property name for one driven socket of one node
    instance, namespaced by the node tree so multiple materials on the same
    mesh object can't collide.

    Identity first, tree name second, socket last -- deliberately, not just
    for reading order: Blender's N-panel property list truncates long names
    in the MIDDLE, so whatever sits at the front and the back survives a
    truncation and the middle segment is what gets eaten. Putting the bone
    name up front and the socket at the back means the two things worth
    reading survive; the tree-name boilerplate is what disappears into the
    ellipsis. Nothing outside this module inspects this string's internal
    order -- _ensure_attr_feed only requires the socket to be the LAST
    segment (it does prop_key.rsplit("::", 1)[-1])."""
    return "{}::{}::{}".format(_instance_key_ident(node), container.name, socket_name)


def _materials_using_tree(tree):
    return [m for m in bpy.data.materials if m.node_tree == tree]


def _objects_using_material(mat):
    return [o for o in bpy.data.objects
            if o.type == 'MESH' and any(s.material == mat for s in o.material_slots)]


def _target_objects(node):
    """Mesh objects whose custom properties should carry this node's driven
    values -- every mesh currently using a material built on this node's
    containing tree. (If the tree isn't a material's own tree -- e.g. the
    node lives nested in a plain node group -- there is nothing to target;
    same limitation the old per-socket-driver design had.)"""
    container = node.id_data
    objs = []
    seen = set()
    for m in _materials_using_tree(container):
        for o in _objects_using_material(m):
            if o.name not in seen:
                seen.add(o.name)
                objs.append(o)
    return objs


def _resolve_driver_armature(armature, obj):
    """The armature a driver should actually sample for *obj*.

    On a linked+overridden character the node's `armature_obj` necessarily
    points at the LINKED armature (the node lives in linked material data).
    But the user poses the local library OVERRIDE of that armature, and the
    linked original never moves -- so drivers built against it are frozen and
    the expression never changes. Resolve to the local override instead.

    Only kicks in when the armature is linked AND a local override of it
    exists; plain local rigs are returned untouched.
    """
    if armature is None or not armature.library:
        return armature
    cands = [o for o in bpy.data.objects
             if o.type == 'ARMATURE' and o.override_library
             and o.override_library.reference == armature]
    if not cands:
        return armature
    if len(cands) == 1:
        return cands[0]
    # Several overridden copies of the same linked character in one scene:
    # pick the one sharing this mesh's override hierarchy, else its collections.
    obj_ov = getattr(obj, "override_library", None)
    root = getattr(obj_ov, "hierarchy_root", None) if obj_ov else None
    if root is not None:
        for c in cands:
            c_ov = getattr(c, "override_library", None)
            if c_ov is not None and getattr(c_ov, "hierarchy_root", None) == root:
                return c
    obj_colls = {c.name for c in obj.users_collection}
    for c in cands:
        if obj_colls & {cc.name for cc in c.users_collection}:
            return c
    return sorted(cands, key=lambda o: o.name)[0]


def _clear_instance_props_and_drivers(node):
    """Remove this node's driven custom properties (and their drivers) from
    EVERY mesh object, not just the current targets -- so a stale prop left
    behind by a since-changed material assignment doesn't linger.

    Matches BOTH key-segment orders (identity::tree:: and tree::identity::),
    not just whatever _prop_key currently emits: a file can carry properties
    built under an older ordering (e.g. before the identity-first reorder for
    N-panel readability), and this sweep must still find and remove them --
    otherwise a rebuild under the current order leaves the old one behind as
    a permanent duplicate instead of replacing it."""
    container = node.id_data
    ident = _instance_key_ident(node)
    prefixes = (
        "{}::{}::".format(ident, container.name),
        "{}::{}::".format(container.name, ident),
    )
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for key in [k for k in obj.keys() if k.startswith(prefixes)]:
            try:
                obj.driver_remove('["{}"]'.format(key))
            except Exception:
                pass
            try:
                del obj[key]
            except Exception:
                pass


def _ensure_prop(obj, key, size):
    """Create the custom property if missing (or wrong shape). size=None
    means a plain float scalar; an int means a float array of that length."""
    default = [0.0] * size if size else 0.0
    if key not in obj.keys():
        obj[key] = default
        return
    if size:
        try:
            if len(obj[key]) != size:
                obj[key] = default
        except TypeError:
            obj[key] = default


def _add_transform_driver_on_prop(obj, key, comp_index, armature, bone, ttype, space,
                                   expression="bone"):
    path = '["{}"]'.format(key)
    obj.driver_remove(path, comp_index)
    fcurve = obj.driver_add(path, comp_index)
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


def _add_singleprop_driver_on_prop(obj, key, armature, data_path, expression="prop"):
    path = '["{}"]'.format(key)
    obj.driver_remove(path)
    fcurve = obj.driver_add(path)
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


def _add_uniform_scale_driver(obj, key, comp_index, armature, bone, invert):
    """Uniform scale = the mean of the bone's local X and Y scale.

    One fcurve with two TRANSFORMS variables. Under a genuine uniform scale
    sx == sy so the mean is exact; if someone scales a single axis it still
    degrades to something sensible instead of ignoring that axis outright.
    """
    path = '["{}"]'.format(key)
    obj.driver_remove(path, comp_index)
    fcurve = obj.driver_add(path, comp_index)
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = "2-(sx+sy)/2" if invert else "(sx+sy)/2"
    for vname, ttype in (("sx", 'SCALE_X'), ("sy", 'SCALE_Y')):
        var = drv.variables.new()
        var.name = vname
        var.type = 'TRANSFORMS'
        tgt = var.targets[0]
        tgt.id = armature
        tgt.bone_target = bone
        tgt.transform_type = ttype
        tgt.transform_space = 'LOCAL_SPACE'
        tgt.rotation_mode = 'AUTO'


# ---------------------------------------------------------------------------
# Auto-created ShaderNodeAttribute feeds.
#
# v2 needs TWO of them per instance: one carrying the packed float4 (Vector =
# xyz, Alpha = w -- both verified to survive an OBJECT custom property in
# Cycles and EEVEE on 5.2) and one carrying the scalar Exp Index. v1 needed
# five, one per driven socket; those names are still listed so old feed nodes
# get swept out of migrated files and so instances stuck on a LINKED v1 group
# keep working.
#
# NOTE .Fac is the MEAN of xyz, not .x -- it is only ever correct on a scalar
# property, which is how Exp Index uses it. Never point Fac at a packed prop.
# ---------------------------------------------------------------------------

PACK_SOCKET = "BoneUV"          # custom-property suffix for the packed float4
EXP_SOCKET = "ExpIndex"         # custom-property suffix for the scalar index

PACK_ATTR_SUFFIX = "__ATTR_BoneUV"
EXP_ATTR_SUFFIX = "__ATTR_ExpIndex"

# v1 (legacy) feeds -- kept for the linked-library path and for cleanup.
LEGACY_ATTR_SUFFIX = {
    "Location": "__ATTR_Location",
    "Rotation": "__ATTR_Rotation",
    "Scale": "__ATTR_Scale",
    "Mask Location": "__ATTR_MaskLoc",
    "Exp Index In": "__ATTR_ExpIndex",
}
LEGACY_ATTR_OUTPUT = {
    "Location": "Vector",
    "Rotation": "Vector",
    "Scale": "Vector",
    "Mask Location": "Vector",
    "Exp Index In": "Fac",
}

ALL_ATTR_SUFFIXES = tuple(sorted(
    set(LEGACY_ATTR_SUFFIX.values()) | {PACK_ATTR_SUFFIX, EXP_ATTR_SUFFIX}))

# Every socket the node drives or sets itself, across BOTH schemas -- hidden
# on the node so the instance stays tidy.
HIDDEN_SOCKETS = ("Amount", "Location", "Rotation", "Scale", "Mask Location",
                  "Exp Index In", "Bone UV", "Bone Scale", "Mask Sign")


def _remove_attr_feeds(node, keep_suffixes=()):
    """Sweep away this instance's Attribute feed nodes.

    *keep_suffixes* -- normally the CURRENT schema's own suffixes -- are left
    completely untouched rather than deleted-and-about-to-be-recreated:
    _ensure_attr_feed already reuses a correctly-named/typed node in place,
    so destroying it here first only forces a fresh .location every refresh
    (including the automatic load-time self-heal every file open runs),
    stomping any position the user or a Tidy pass gave it. Only feed nodes
    from a genuinely DIFFERENT schema (e.g. v1 leftovers on a file that just
    upgraded to v2) need sweeping here."""
    container = node.id_data
    if not _can_edit(container):
        return
    for suffix in ALL_ATTR_SUFFIXES:
        if suffix in keep_suffixes:
            continue
        attr = container.nodes.get(node.name + suffix)
        if attr is not None:
            try:
                container.nodes.remove(attr)
            except Exception:
                pass


def _ensure_attr_feed(node, suffix, prop_key, wiring, y_offset, collapse=True):
    """Create/repoint one Attribute feed and wire its outputs into the node.

    *wiring* is a sequence of (attribute output name, node input socket name),
    so one Attribute node can serve several sockets -- v2 takes Vector and
    Alpha off the same node to move a whole float4 over two links.
    """
    container = node.id_data
    if not _can_edit(container):
        return
    attr_name = node.name + suffix
    attr = container.nodes.get(attr_name)
    just_created = attr is None or attr.bl_idname != 'ShaderNodeAttribute'
    if just_created:
        if attr is not None:
            try:
                container.nodes.remove(attr)
            except Exception:
                pass
        attr = container.nodes.new('ShaderNodeAttribute')
        attr.name = attr_name
    # Keep it in step with the owner's frame -- node.location is relative to
    # THIS parent, so reparenting before positioning (below, create-only) is
    # what keeps the x/y_offset math correct instead of scattering the pill
    # to a totally different part of the canvas the next time it needs
    # recreating (e.g. a genuine schema change -- see _remove_attr_feeds).
    if node.parent is not None:
        attr.parent = node.parent
    attr.label = "{} for {}".format(prop_key.rsplit("::", 1)[-1], _instance_key_ident(node))
    # Position ONLY on actual creation -- an already-existing node (the
    # normal case on every refresh, since _remove_attr_feeds no longer tears
    # this down every call) keeps whatever position it already has, whether
    # that's a user's manual arrangement or a Tidy pass's centered stack.
    if just_created:
        attr.location = (node.location.x - 240, node.location.y + y_offset)
    attr.attribute_type = 'OBJECT'
    attr.attribute_name = prop_key
    # Collapsed: the node shows nothing but a machine-generated property name,
    # so it draws as a small pill instead of a full box.
    attr.hide = collapse
    for out_name, socket_name in wiring:
        sock = node.inputs.get(socket_name)
        if sock is None:
            continue
        out_socket = attr.outputs.get(out_name)
        if out_socket is None:
            continue
        if sock.links and sock.links[0].from_socket == out_socket:
            continue
        container.links.new(out_socket, sock)


def _ensure_uv_map_feed(node):
    """Auto-create a UV Map node feeding this instance's 'UV' input when
    nothing feeds it. The layer is chosen on that UV Map node itself (empty =
    active UV), so there's no mirror string on this node.

    Re-uses an existing node of the expected name rather than making a second
    one: a group-schema upgrade drops the link (the socket is recreated), and
    blindly calling nodes.new() there would strand the user's chosen UV layer
    on an orphan named '...__UVForBone.001'.
    """
    container = node.id_data
    if not _can_edit(container):
        return
    uv_in = node.inputs.get("UV")
    if uv_in is None:
        return
    name = node.name + UVFB_UVMAP_SUFFIX
    uvmap = container.nodes.get(name)
    # Refresh the label every call (not just at creation) so a Tidy pass
    # (see _instance_key_ident) can relabel it even once it's already linked.
    # Same for .parent -- keep it grouped with its owner's Tidy frame even on
    # a call that doesn't recreate it (see the matching comment in
    # _ensure_attr_feed for why a freshly recreated one needs this too).
    if uvmap is not None and uvmap.bl_idname == 'ShaderNodeUVMap':
        uvmap.label = "UV for " + _instance_key_ident(node)
        if node.parent is not None:
            uvmap.parent = node.parent
    if uv_in.links:
        return
    if uvmap is None or uvmap.bl_idname != 'ShaderNodeUVMap':
        uvmap = container.nodes.new('ShaderNodeUVMap')
        uvmap.name = name
        uvmap.label = "UV for " + _instance_key_ident(node)
        if node.parent is not None:
            uvmap.parent = node.parent
        uvmap.location = (node.location.x - 240, node.location.y - 200)
        # Leave uvmap.uv_map = "" -> Blender uses the active UV layer.
    container.links.new(uvmap.outputs['UV'], uv_in)


def _exp_index_datapath(node, armature, bone, targets):
    """('pose.bones[..][..]', True) when the bone actually carries the index
    property, else (None, False). Checks the armature the drivers will really
    sample -- the override, when the rig is linked."""
    prop_name = (node.index_prop_name or "exp_index").strip()
    if not prop_name:
        return None, False
    check_arm = _resolve_driver_armature(armature, targets[0])
    pbone = check_arm.pose.bones.get(bone) or armature.pose.bones.get(bone)
    if pbone is None or prop_name not in pbone.keys():
        return None, False
    return 'pose.bones["{}"]["{}"]'.format(bone, prop_name), True


def _build_drivers_v2(node, targets, armature, bone):
    """Current transport: one float4 + one scalar, two Attribute feeds.

    float4 layout, chosen so it maps 1:1 onto an engine-side float4 later:
        x = local loc X   y = local loc Y   z = local rot Z   w = uniform scale
    """
    container = node.id_data
    key = _prop_key(container, node, PACK_SOCKET)
    specs = (
        (0, 'LOC_X', "-bone" if node.invert_location_x else "bone"),
        (1, 'LOC_Y', "-bone" if node.invert_location_y else "bone"),
        (2, 'ROT_Z', "-bone" if node.invert_rotation else "bone"),
    )
    for obj in targets:
        _ensure_prop(obj, key, 4)
        drv_arm = _resolve_driver_armature(armature, obj)
        for idx, ttype, expr in specs:
            _add_transform_driver_on_prop(obj, key, idx, drv_arm, bone, ttype,
                                          'LOCAL_SPACE', expr)
        _add_uniform_scale_driver(obj, key, 3, drv_arm, bone, node.invert_scale_x)
    _ensure_attr_feed(node, PACK_ATTR_SUFFIX, key,
                      (("Vector", "Bone UV"), ("Alpha", "Bone Scale")), -60)

    # Static, never driven: undoes the location inversion for the mask branch,
    # which wants the bone's RAW local XY. A plain default_value write -- it
    # must never become a driver on the node tree (see the note above).
    sign = node.inputs.get("Mask Sign")
    if sign is not None:
        sign.default_value = (-1.0 if node.invert_location_x else 1.0,
                              -1.0 if node.invert_location_y else 1.0,
                              1.0)

    data_path, ok = _exp_index_datapath(node, armature, bone, targets)
    if ok:
        exp_key = _prop_key(container, node, EXP_SOCKET)
        for obj in targets:
            _ensure_prop(obj, exp_key, None)
            _add_singleprop_driver_on_prop(obj, exp_key,
                                           _resolve_driver_armature(armature, obj),
                                           data_path)
        _ensure_attr_feed(node, EXP_ATTR_SUFFIX, exp_key,
                          (("Fac", "Exp Index In"),), -110)


def _build_drivers_v1(node, targets, armature, bone):
    """Legacy transport: five props, five Attribute feeds, 12 fcurves/mesh.

    Reached only by an instance whose group is still v1 -- in practice one
    that lives in a LINKED library saved by an older addon. That library's own
    Attribute nodes read these exact property names, so a local file has to
    keep feeding them in the old shape or the linked character freezes. Local
    groups are upgraded by upgrade_shared_tree() and never come through here.
    """
    container = node.id_data
    invert = {
        "Location": (node.invert_location_x, node.invert_location_y, False),
        "Rotation": (node.invert_rotation, node.invert_rotation, node.invert_rotation),
        "Scale":    (node.invert_scale_x, node.invert_scale_y, False),
    }
    y_off = -60
    for socket_name, (types, mode) in DRIVEN_VEC_INPUTS.items():
        flags = invert[socket_name]
        key = _prop_key(container, node, socket_name)
        for obj in targets:
            _ensure_prop(obj, key, 3)
            drv_arm = _resolve_driver_armature(armature, obj)
            for i, ttype in enumerate(types):
                if flags[i]:
                    expr = "-bone" if mode == "negate" else "2-bone"
                else:
                    expr = "bone"
                _add_transform_driver_on_prop(obj, key, i, drv_arm, bone, ttype,
                                              'LOCAL_SPACE', expr)
        _ensure_attr_feed(node, LEGACY_ATTR_SUFFIX[socket_name], key,
                          ((LEGACY_ATTR_OUTPUT[socket_name], socket_name),),
                          y_off, collapse=False)
        y_off -= 80

    mask_key = _prop_key(container, node, "Mask Location")
    for obj in targets:
        _ensure_prop(obj, mask_key, 3)
        drv_arm = _resolve_driver_armature(armature, obj)
        for i, ttype in enumerate(("LOC_X", "LOC_Y")):
            _add_transform_driver_on_prop(obj, mask_key, i, drv_arm, bone, ttype,
                                          'LOCAL_SPACE', "bone")
    _ensure_attr_feed(node, LEGACY_ATTR_SUFFIX["Mask Location"], mask_key,
                      ((LEGACY_ATTR_OUTPUT["Mask Location"], "Mask Location"),),
                      y_off, collapse=False)
    y_off -= 80

    data_path, ok = _exp_index_datapath(node, armature, bone, targets)
    if ok:
        exp_key = _prop_key(container, node, "Exp Index In")
        for obj in targets:
            _ensure_prop(obj, exp_key, None)
            _add_singleprop_driver_on_prop(obj, exp_key,
                                           _resolve_driver_armature(armature, obj),
                                           data_path)
        _ensure_attr_feed(node, LEGACY_ATTR_SUFFIX["Exp Index In"], exp_key,
                          ((LEGACY_ATTR_OUTPUT["Exp Index In"], "Exp Index In"),),
                          y_off, collapse=False)


def refresh_uv_from_bone_shared(node):
    if node.node_tree is None:
        node.node_tree = get_shared_uv_tree()

    version = _tree_version(node.node_tree)

    _ensure_uv_map_feed(node)

    # Hide the driven/internal input sockets so the node stays tidy. Amount
    # only exists on v1 and was always pinned to full effect.
    for hidden in HIDDEN_SOCKETS:
        s = node.inputs.get(hidden)
        if s is not None:
            s.hide = True
    amt = node.inputs.get("Amount")
    if amt is not None and amt.default_value != 1.0:
        amt.default_value = 1.0

    _clear_legacy_socket_drivers(node)
    _clear_instance_props_and_drivers(node)

    armature = node.armature_obj
    bone = node.bone_name
    valid = bool(armature and armature.type == 'ARMATURE'
                 and bone and bone in armature.data.bones)
    if not valid:
        return

    targets = _target_objects(node)
    if not targets:
        return  # no mesh uses this material (yet) -- nothing to drive

    # Only torn down once we know a rebuild follows immediately below --
    # _remove_attr_feeds used to run unconditionally up top, so a node with
    # no target mesh yet (nothing wrong with it, just not assigned to any
    # mesh in THIS file) had its feed nodes deleted on every refresh -- e.g.
    # every file load's automatic self-heal pass -- and never rebuilt, since
    # the "no targets" return above used to happen AFTER the deletion.
    #
    # keep_suffixes: the CURRENT schema's own feeds are left alone entirely
    # (_ensure_attr_feed reuses them in place, preserving position/parent) --
    # only a genuinely different schema's leftovers get swept here.
    current_suffixes = {PACK_ATTR_SUFFIX, EXP_ATTR_SUFFIX} if version >= 2 \
        else set(LEGACY_ATTR_SUFFIX.values())
    _remove_attr_feeds(node, keep_suffixes=current_suffixes)

    if version >= 2:
        _build_drivers_v2(node, targets, armature, bone)
    else:
        _build_drivers_v1(node, targets, armature, bone)


# ---------------------------------------------------------------------------
# Manual "Tidy" operator support (GESTUREBONE_OT_tidy_expression_node_driver
# in operators.py).
#
# Cosmetic pass, explicitly user-triggered: repoints this instance's property
# keys and satellite feed-node labels from the generic node name to the bone
# they're actually wired to, and groups the node + its own feed nodes into a
# dedicated frame labeled with the bone name. Deliberately NOT wired into
# _on_update -- see _instance_key_ident's docstring for why touching
# node.name itself (the obvious-looking approach) is unsafe here.
# ---------------------------------------------------------------------------

FRAME_SUFFIX = "__Frame"


def _own_upstream_feeders(node):
    """Upstream nodes whose ENTIRE output fan-out lands only on this node's
    own inputs -- i.e. small per-instance feed nodes (UV Map, Attribute)
    built for this instance specifically, regardless of which schema/suffix
    they happen to use. A feeder that also drives something else is shared
    and left alone, never swept into this node's frame."""
    feeders = []
    seen = set()
    for sock in node.inputs:
        for link in sock.links:
            src = link.from_node
            if src.name in seen:
                continue
            exclusive = all(l.to_node == node for out in src.outputs for l in out.links)
            if exclusive:
                seen.add(src.name)
                feeders.append(src)
    return feeders


def group_into_frame(node, bone):
    """Ensure this node + its own feed nodes sit in ONE dedicated frame
    labeled with the bone name -- creating it if missing, or just relabeling
    it if it's already there.

    Identified by a fixed name derived from node.name (node.name +
    FRAME_SUFFIX) -- stable tree identity, exactly like _instance_key_ident
    keeps satellite lookup stable -- never by "whatever frame the node
    happens to be parented to right now". A node can already be sitting in
    an unrelated, shared frame (a material author's own layout grouping);
    blindly adopting and relabeling THAT would corrupt it for everything
    else living in it. This only ever touches a frame it created itself."""
    container = node.id_data
    frame_name = node.name + FRAME_SUFFIX
    frame = container.nodes.get(frame_name)
    if frame is None or frame.bl_idname != 'NodeFrame':
        frame = container.nodes.new('NodeFrame')
        frame.name = frame_name
    frame.label = bone

    node.parent = frame
    feeders = _own_upstream_feeders(node)
    for feeder in feeders:
        feeder.parent = frame
        _set_satellite_display(feeder)

    _stack_satellites(node, feeders)
    return frame


def _set_satellite_display(feeder):
    """Attribute feeds collapse to a small pill (hide every socket with no
    link first, so an expanded view never shows unused rows either, then
    collapse the node itself) -- there's nothing on them worth looking at
    directly, just a machine-generated property name. The UV Map feed stays
    open: its UV-layer picker is the one thing on any of these satellites a
    user actually needs to reach without expanding it first."""
    if feeder.bl_idname == 'ShaderNodeUVMap':
        feeder.hide = False
        return
    for socket in list(feeder.inputs) + list(feeder.outputs):
        if not socket.links:
            socket.hide = True
    feeder.hide = True


# Fixed, not read off feeder.dimensions -- dimensions reflects the LAST
# drawn size, which is still the PRE-collapse box the instant after this
# same call changes .hide, so it can't be trusted here.
_PILL_HEIGHT = 40
_OPEN_UVMAP_HEIGHT = 110


def _stack_satellites(node, feeders):
    """Stack feeders vertically in a column to the left of the main node,
    the whole column vertically centered on the main node's own height.

    A node's .location is relative to its PARENT frame, not the tree's
    absolute space. Every feeder's location was originally computed as an
    absolute-space offset from the main node (see _ensure_attr_feed /
    _ensure_uv_map_feed), so the instant it gets re-parented in
    group_into_frame that same number is reinterpreted as frame-relative --
    which is why, unfixed, they all pile up on top of each other near the
    frame's origin instead of spreading out."""
    if not feeders:
        return
    gap = 16
    heights = [_OPEN_UVMAP_HEIGHT if f.bl_idname == 'ShaderNodeUVMap' else _PILL_HEIGHT
               for f in feeders]
    total = sum(heights) + gap * (len(feeders) - 1)
    node_h = max(node.dimensions.y, 200)
    x = node.location.x - 220
    y = node.location.y - (node_h - total) / 2
    for feeder, h in zip(feeders, heights):
        feeder.location = (x, y)
        y -= h + gap


def tidy_expression_node_and_driver(node):
    """Rename this node's driver property keys (and its UV Map / Attribute
    feed nodes' labels) from the generic node name to the bone this instance
    is wired to, and make sure it's grouped into its own dedicated frame
    labeled with that bone name. node.name itself is never touched, and
    neither is any satellite's own tree identity -- only
    _instance_key_ident's marker, the property key strings on target meshes,
    and display labels/frame membership change.

    Returns the new identity (the bone name) on success, or None if no valid
    Armature+Bone is set on the node yet."""
    if not _can_edit(node.id_data):
        return None  # linked/library tree -- a write here would never be saved

    armature = node.armature_obj
    bone = node.bone_name
    if not (armature and armature.type == 'ARMATURE'
            and bone and bone in armature.data.bones):
        return None

    if _instance_key_ident(node) != bone:
        # Tear down whatever is keyed under the CURRENT (about-to-be-stale)
        # identity before switching it, so nothing is left behind on the mesh.
        _clear_instance_props_and_drivers(node)

        node["_gb_key_ident"] = bone

        # Rebuild fresh under the new identity. Satellite nodes keep their
        # own tree identity (node.name + suffix) throughout, so this reuses
        # them in place rather than creating new ones.
        refresh_uv_from_bone_shared(node)

    # Framing is checked/fixed every run, independent of whether the naming
    # needed any work above -- re-clicking Tidy should always leave both in
    # a correct state, not just the first time.
    group_into_frame(node, bone)
    return bone


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
    """Shader node trees only -- our node type only ever lives in materials
    or the shared group. Scanning bpy.data.node_groups unfiltered would also
    walk Geometry Nodes / Compositor trees (GestureBone's rigs are full of
    GN modifier trees), and touching an unrelated node's .bl_idname there has
    been observed to crash Blender (EXCEPTION_ACCESS_VIOLATION reading a
    node's typeinfo) on some files -- see [[library-override-hang]]."""
    seen = set()
    shader_groups = [g for g in bpy.data.node_groups if isinstance(g, bpy.types.ShaderNodeTree)]
    for c in shader_groups + [m.node_tree for m in bpy.data.materials if m.node_tree]:
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
        # 1) refresh freshly-duplicated nodes (identified by pointer).
        #    Resolve pointers to NAMES first: refreshing mutates this tree and
        #    invalidates every other pointer in a stale snapshot (same
        #    use-after-free as in migrate_legacy_drivers below).
        if ptrs:
            names = [n.name for n in c.nodes
                     if n.bl_idname == "ShaderNodeCustomUVFromBoneShared"
                     and n.as_pointer() in ptrs]
            for name in names:
                n = c.nodes.get(name)
                if n is None:
                    continue
                try:
                    refresh_uv_from_bone_shared(n)
                except Exception as e:
                    print("Expression Sheet: deferred refresh failed:", e)
        # 2) remove orphaned auto UV Map / Attribute feeds (owner node deleted)
        #    and drivers pointing at nodes that no longer exist. Decide first,
        #    remove after: removing mid-iteration invalidates the remaining
        #    pointers in the snapshot (see migrate_legacy_drivers below).
        # Never restructure a linked tree: writes there are memory-only,
        # are never saved, and just churn the library's own graph.
        if not _can_edit(c):
            continue
        orphan_names = []
        for f in c.nodes:
            if (f.bl_idname == 'ShaderNodeUVMap' and f.name.endswith(UVFB_UVMAP_SUFFIX)
                    and f.outputs and not any(
                        l.to_node.bl_idname == "ShaderNodeCustomUVFromBoneShared"
                        for l in f.outputs[0].links)):
                orphan_names.append(f.name)
                continue
            if f.bl_idname == 'ShaderNodeAttribute':
                for suffix in ALL_ATTR_SUFFIXES:
                    if f.name.endswith(suffix):
                        if c.nodes.get(f.name[:-len(suffix)]) is None:
                            orphan_names.append(f.name)
                        break
        for name in orphan_names:
            f = c.nodes.get(name)
            if f is None:
                continue
            try:
                c.nodes.remove(f)
            except Exception:
                pass
        if c.animation_data:
            our_sockets = ("Location", "Rotation", "Scale", "Mask Location",
                           "Exp Index In", "Bone UV", "Bone Scale", "Mask Sign")
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
    bl_idname = NODE_ID
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
        # Drop this instance's drivers/props now (safe -- animation data and
        # object custom properties on OTHER datablocks, not nodes in this tree).
        try:
            _clear_legacy_socket_drivers(self)
        except Exception as e:
            print("UVFromBoneShared free() legacy driver-clear skipped:", e)
        try:
            _clear_instance_props_and_drivers(self)
        except Exception as e:
            print("UVFromBoneShared free() prop/driver-clear skipped:", e)
        # Removing the auto UV Map / Attribute feed nodes mutates the tree,
        # which is unsafe from inside the delete operator -- let the
        # deferred timer sweep orphans.
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


def migrate_legacy_drivers():
    """Force-refresh every UVFromBoneShared instance so any material node-tree
    drivers left over from the pre-fix design are stripped and rebuilt as
    override-safe object-property drivers (see [[library-override-hang]]).

    refresh_uv_from_bone_shared() only self-heals lazily when a node's own
    property changes, so a file opened (or linked) and immediately overridden
    without touching any node would still carry the hang-triggering material
    drivers. Called eagerly from a load_post handler below so every file is
    always safe before the user gets a chance to hit Make Library Override.
    """
    # Upgrade the shared group ONCE, before any instance is refreshed --
    # the rebuild snapshots and restores every instance's authored values and
    # links, so it must not run interleaved with per-instance work. Only a
    # LOCAL group is touched; a linked one belongs to its library.
    for g in bpy.data.node_groups:
        if g.name == SHARED_GROUP_NAME and g.library is None:
            try:
                upgrade_shared_tree(g)
            except Exception as e:
                print("Expression Sheet: shared-group upgrade failed:", e)
            break

    n = 0
    for c in _iter_shared_containers():
        # Snapshot NAMES, never node pointers. refresh_uv_from_bone_shared()
        # adds/removes feed nodes in this same tree, which invalidates the
        # other bNode pointers held in a stale list(c.nodes) -- reading
        # .bl_idname off one then crashes Blender (EXCEPTION_ACCESS_VIOLATION
        # in Node_bl_idname_length). Re-fetch by name each iteration instead.
        names = [nd.name for nd in c.nodes
                 if nd.bl_idname == "ShaderNodeCustomUVFromBoneShared"]
        for name in names:
            node = c.nodes.get(name)
            if node is None:
                continue
            try:
                refresh_uv_from_bone_shared(node)
                n += 1
            except Exception as e:
                print("Expression Sheet: legacy-driver migration failed for", name, e)
    return n


def _run_migration_deferred():
    try:
        n = migrate_legacy_drivers()
        if n:
            print(f"GestureBone/ExpressionSheet: checked {n} UV From Bone (Shared) node(s) for legacy drivers on load")
    except Exception as e:
        print(f"GestureBone/ExpressionSheet: legacy-driver migration on load failed: {e!r}")
    return None  # one-shot


@persistent
def _migrate_on_load(_dummy):
    # Defer off the synchronous load_post callback: node/typeinfo data isn't
    # guaranteed fully settled the instant a file finishes loading, and a
    # crash was observed here on real files (EXCEPTION_ACCESS_VIOLATION
    # reading a node's bl_idname) -- see [[library-override-hang]]. A 0-delay
    # timer runs once Blender is back to idle, same pattern already used for
    # copy()/free()'s deferred tree mutation above.
    if not bpy.app.timers.is_registered(_run_migration_deferred):
        bpy.app.timers.register(_run_migration_deferred, first_interval=0.0)


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
    if _migrate_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_migrate_on_load)
    # Also repair the file that is already open when the module is enabled
    # (deferred -- register() runs during addon-enable, which can't safely
    # touch bpy.data yet; same _RestrictData timing issue documented on
    # get_shared_uv_tree()/build_shared_uv_tree() elsewhere in this file).
    if not bpy.app.timers.is_registered(_run_migration_deferred):
        bpy.app.timers.register(_run_migration_deferred, first_interval=0.0)


def unregister():
    if _migrate_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_migrate_on_load)
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
