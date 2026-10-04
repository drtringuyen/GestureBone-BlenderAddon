"""
export/weights.py — Bake the "Bone-weight-Linear" Geometry Nodes weights.

The node recomputes every chain mesh's skin weights on every evaluation
(LittlePig: ~10 of 12.6 ms per frame). Baking writes its output into ordinary
vertex groups once and MUTES the modifier, keeping it in place with all its
settings, so weights stay adaptive:

    Bake      evaluate the node, write its vertex groups, mute it
    Live      unmute it (weights are computed live again — tweak and preview)
    Rebake    Live + Bake

Only meshes that hold chain weight are touched: a NODES modifier running a
"Bone-weight-Linear*" group whose Deform Armature is the rig.

Two ways to bake, picked per mesh:
  * the node only writes weights → its vertex groups are written onto the
    mesh, nothing else changes;
  * the node also ADDS geometry (hand/feet sprite ends) → the evaluated mesh
    up to the node replaces the object's mesh; the original mesh is kept (fake
    user) and Live swaps it back, so sprites never double up.
Skipped, node left live, reason reported:
  * the node's inputs are driven or keyed (CHR_RU: Hand_L/R, Feet_L/R follow
    the hand/foot bones' exp_index) — its output changes over time, a bake
    would freeze the current sprite;
  * a geometry-changing node on a mesh with shape keys (they can't be carried
    onto the evaluated mesh).
"""
import bpy

from ..shared.utils_gn import _find_socket_id, _get_gn_input

WEIGHT_GROUP_PREFIX = "Bone-weight-Linear"
BAKED_PROP = "gb_weights_baked"     # on the mesh object: name of the muted modifier
SOURCE_PROP = "gb_weights_source"   # on the mesh object: original mesh datablock (geometry bakes)


def weight_modifier(ob, arm=None):
    """The chain-weight node modifier of `ob` (optionally: driven by `arm`)."""
    for md in getattr(ob, "modifiers", []):
        if md.type != 'NODES' or md.node_group is None or not md.node_group.name.startswith(WEIGHT_GROUP_PREFIX):
            continue
        if arm is None:
            return md
        sid = _find_socket_id(md, "Deform Armature")
        if sid and _get_gn_input(md, sid) == arm:
            return md
    return None


def chain_meshes(arm):
    return [ob for ob in bpy.data.objects if ob.type == 'MESH' and weight_modifier(ob, arm) is not None]


def is_baked(ob):
    md = weight_modifier(ob)
    return md is not None and not md.show_viewport and BAKED_PROP in ob


def _evaluate_up_to(ob, md):
    """Evaluated mesh with only the modifiers up to and including `md`."""
    saved = [(m, m.show_viewport) for m in ob.modifiers]
    hit = False
    for m in ob.modifiers:
        m.show_viewport = not hit
        if m == md:
            m.show_viewport = True
            hit = True
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ev = ob.evaluated_get(dg)
    return ev, saved


def animated_inputs(ob, md):
    """Driven or keyed inputs of the weight node (its output changes over time)."""
    prefix = f'modifiers["{md.name}"]'
    out = []
    ad = ob.animation_data
    if ad:
        out += [fc.data_path for fc in ad.drivers if fc.data_path.startswith(prefix)]
        act = ad.action
        if act is not None:
            fcs = getattr(act, "fcurves", None)
            if fcs is None:
                fcs = [f for l in act.layers for st in l.strips for cb in st.channelbags for f in cb.fcurves]
            out += [fc.data_path for fc in fcs if fc.data_path.startswith(prefix)]
    return out


def bake(ob, arm=None):
    """Bake one mesh. Returns (ok, message)."""
    md = weight_modifier(ob, arm)
    if md is None:
        return False, "no chain-weight node"
    anim = animated_inputs(ob, md)
    if anim:
        return False, (f"skipped: '{md.name}' has driven/keyed inputs ({len(anim)}) — its output changes "
                       "over time (e.g. hand/foot sprite swaps), a bake would freeze it")
    if ob.override_library is not None or ob.data.library is not None or ob.data.override_library is not None:
        return False, "skipped: linked/overridden mesh — bake it in the CHR file"
    if ob.data.users > 1:
        return False, f"skipped: mesh data '{ob.data.name}' is shared by {ob.data.users} objects"
    ev, saved = _evaluate_up_to(ob, md)
    geometry = False
    try:
        me = ev.to_mesh()
        try:
            if len(me.vertices) != len(ob.data.vertices):
                if ob.data.shape_keys:
                    return False, (f"skipped: '{md.name}' adds geometry ({len(ob.data.vertices)} → "
                                   f"{len(me.vertices)} verts) and the mesh has shape keys")
                geometry = True
                baked_mesh = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True,
                                                             depsgraph=bpy.context.evaluated_depsgraph_get())
            names = {g.index: g.name for g in ev.vertex_groups}
            weights = {}
            for v in me.vertices:
                for ge in v.groups:
                    if ge.weight > 0.0:
                        weights.setdefault(names[ge.group], []).append((v.index, ge.weight))
        finally:
            ev.to_mesh_clear()
    finally:
        for m, vis in saved:
            m.show_viewport = vis
    if geometry:
        src = ob.data
        src.use_fake_user = True
        baked_mesh.name = src.name + ".baked"
        ob.data = baked_mesh
        ob[SOURCE_PROP] = src
        md.show_viewport = False
        md.show_render = False
        ob[BAKED_PROP] = md.name
        return True, f"{len(weights)} groups + generated geometry (original mesh kept for Live)"
    allv = range(len(ob.data.vertices))
    for name, pairs in weights.items():
        vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
        vg.remove(list(allv))
        by_w = {}
        for i, w in pairs:
            by_w.setdefault(round(w, 6), []).append(i)
        for w, idx in by_w.items():
            vg.add(idx, w, 'REPLACE')
    md.show_viewport = False
    md.show_render = False
    ob[BAKED_PROP] = md.name
    return True, f"{len(weights)} groups"


def live(ob):
    md = weight_modifier(ob)
    if md is None:
        return False
    src = ob.get(SOURCE_PROP)
    if src is not None and isinstance(src, bpy.types.Mesh):
        baked = ob.data
        ob.data = src
        src.use_fake_user = False
        del ob[SOURCE_PROP]
        if baked.users == 0:
            bpy.data.meshes.remove(baked)
    md.show_viewport = True
    md.show_render = True
    if BAKED_PROP in ob:
        del ob[BAKED_PROP]
    return True


def bake_all(arm):
    report = {}
    for ob in chain_meshes(arm):
        if is_baked(ob):
            live(ob)
        report[ob.name] = bake(ob, arm)
    return report


def live_all(arm):
    return [ob.name for ob in chain_meshes(arm) if live(ob)]
