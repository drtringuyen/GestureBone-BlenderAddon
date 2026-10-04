"""
export/optimize.py — "Blender Optimized": the B-Bone spans deform the mesh.

Sampler mode (curvechain default) keeps the template's STR→AXIS→SIZE→DEF
stack and 13 samplers per chain reading the hidden spans. Blender Optimized
deletes all of that and makes the spans themselves the deform bones:

    BDEF-{part}.001 … .00N   one B-Bone per span (deforming, collection BDEF)
    BDEF-{part}.EndL/.EndR   end caps: End.A → first point, last point → End.B
    MCH-{part}_{i}.dirA/B    handle directions (as before)
    MCH-{part}.Up            up-vector for the end caps

Kept from curvechain: the exact-bezier ease drivers, plane projection, Layer
Depth. Thickness: each span's Scale In/Out (X, Z) follows the .scale bones.
Weights: the Bone-weight-Linear node's BDEF- branch (export/weight_nodes.py)
— still live and adaptive; Bake mutes it again.

Conversion is destructive; it writes <file>_beforeBDEF.blend first.
"""
import os
import re
import bpy
from mathutils import Vector

from ..curvechain import builder as bd
from ..curvechain.builder import (
    TAG, MCH_COLLECTION, BBONE_SEGMENTS, UP_DISTANCE, WORLD_NORMAL_HINT,
    point_name, ha_name, hb_name, scale_name, dir_a_name, dir_b_name, tip_b_name,
    cmp_name, cmp_tip_name, up_name, chain_root, plane_normal_rest, missing_bones,
    _eb, _set_mode, _con, _driver, _v_dist, _v_scale_y, remove_drivers,
)
from ..shared.utils_gn import _find_socket_id, _get_gn_input, _set_gn_input
from . import weights as W, weight_nodes as WN

BDEF_COLLECTION = "BDEF"
MODE_SAMPLER, MODE_BBONE = 'SAMPLER', 'BBONE'


def bdef_name(part, k):     return f"BDEF-{part}.{k + 1:03d}"      # 1-based: matches the weight node
def bdef_end(part, side):   return f"BDEF-{part}.{side}"          # EndL / EndR
def end_handle(part, indices, side):
    return f"CTRL-{part}_{indices[0]}.End.{'A' if side == 'EndL' else 'B'}"


def deform_mode(arm):
    return getattr(arm.gesturebone_props, "deform_mode", MODE_SAMPLER)


def _doomed(arm, part):
    rx = re.compile(rf"^(STR|AXIS|SIZE|DEF)-{re.escape(part)}(\.|$)")
    return [b.name for b in arm.data.bones
            if rx.match(b.name) or b.name.startswith((f"MCH-{part}.", f"MCH-{part}_", f"BDEF-{part}."))]


def _delete_bones(arm, names):
    if not names:
        return 0
    dead = set(names)
    ad = arm.animation_data
    if ad:
        for fc in list(ad.drivers):
            pb = fc.data_path.split('"')[1] if fc.data_path.startswith('pose.bones["') else None
            refs = {t.bone_target for v in fc.driver.variables for t in v.targets if t.bone_target}
            refs |= {p.split('"')[1] for v in fc.driver.variables for t in v.targets
                     if t.data_path and t.data_path.startswith('pose.bones["') for p in [t.data_path]}
            if pb in dead or refs & dead:
                ad.drivers.remove(fc)
    _set_mode(arm, 'EDIT')
    try:
        ebs = arm.data.edit_bones
        for n in names:
            eb = ebs.get(n)
            if eb is not None:
                ebs.remove(eb)
    finally:
        _set_mode(arm, 'POSE')
    return len(dead)


def _old_rest(arm, name):
    b = arm.data.bones.get(name)
    return (b.head_local.copy(), b.tail_local.copy()) if b else None


# ── Build ─────────────────────────────────────────────────────────────────────

def build_bdef_chain(arm, part, indices, plane='ROOT', end_rest=None):
    """(Re)build one chain in Blender Optimized form. `end_rest` = {"EndL": (head, tail),
    "EndR": (head, tail)} from the old DEF end caps, else derived from the controls."""
    miss = missing_bones(arm, part, indices)
    if miss:
        raise RuntimeError(f"{part}: missing bones {miss}")
    root = chain_root(arm, part)
    bones = arm.data.bones
    flat = plane == 'ROOT' and root is not None
    normal = plane_normal_rest(arm, part) if plane == 'ROOT' else WORLD_NORMAL_HINT.copy()
    P = {i: bones[point_name(part, i)].head_local.copy() for i in indices}
    HA = {i: bones[ha_name(part, i)].head_local.copy() for i in indices[1:]}
    HB = {i: bones[hb_name(part, i)].head_local.copy() for i in indices[:-1]}
    spans = list(zip(indices, indices[1:]))
    chain_len = sum((P[b] - P[a]).length for a, b in spans) or 1.0
    ends = {}
    end_rest = dict(end_rest or {})
    for side in ("EndL", "EndR"):          # a rebuild keeps the current end caps' rest
        if not end_rest.get(side) and bones.get(bdef_end(part, side)):
            end_rest[side] = _old_rest(arm, bdef_end(part, side))
    for side in ("EndL", "EndR"):
        h = end_handle(part, indices, side)
        if end_rest.get(side):
            ends[side] = end_rest[side]
        elif bones.get(h):
            hp = bones[h].head_local.copy()
            ends[side] = (hp, P[indices[0]]) if side == "EndL" else (P[indices[-1]], hp)
    _delete_bones(arm, [n for n in _doomed(arm, part)])
    bones = arm.data.bones

    _set_mode(arm, 'EDIT')
    try:
        for k, (a, b) in enumerate(spans):
            L0 = max(((P[b] - P[a]).length or chain_len) * 0.25, 1e-3)
            db = (HB[a] - P[a]) if (HB[a] - P[a]).length > 1e-6 else (P[b] - P[a])
            da = (P[b] - HA[b]) if (P[b] - HA[b]).length > 1e-6 else (P[b] - P[a])
            _eb(arm, dir_b_name(part, a), P[a], db, normal, L0, root)
            _eb(arm, dir_a_name(part, b), P[b], da, normal, L0, root)
            if not flat:
                _eb(arm, tip_b_name(part, a), P[a] + db.normalized() * L0, db, normal, L0 * 0.2, dir_b_name(part, a))
                _eb(arm, cmp_name(part, k), P[a], da, normal, L0, root)
                _eb(arm, cmp_tip_name(part, k), P[a] + da.normalized() * L0, da, normal, L0 * 0.2, cmp_name(part, k))
            eb = _eb(arm, bdef_name(part, k), P[a], P[b] - P[a], normal, (P[b] - P[a]).length, root)
            eb.use_deform = True
            eb.bbone_segments = BBONE_SEGMENTS
            eb.bbone_easein = eb.bbone_easeout = 1.0
            eb.bbone_handle_type_start = 'TANGENT'
            eb.bbone_custom_handle_start = arm.data.edit_bones[dir_b_name(part, a)]
            eb.bbone_handle_type_end = 'TANGENT'
            eb.bbone_custom_handle_end = arm.data.edit_bones[dir_a_name(part, b)]
            eb.bbone_x = eb.bbone_z = chain_len * 0.01
            # map vertices along the CURVED rest shape (handles bend it), not the chord
            eb.bbone_mapping_mode = 'CURVED'
        rh = bones[root].head_local if root else P[indices[0]]
        _eb(arm, up_name(part), rh + normal * chain_len * UP_DISTANCE, normal, normal.orthogonal(),
            chain_len * 0.05, root if flat else None)
        for side, (h, t) in ends.items():
            d = (t - h) if (t - h).length > 1e-6 else Vector((0, 0, chain_len * 0.05))
            eb = _eb(arm, bdef_end(part, side), h, d, normal, max(d.length, 1e-3), root)
            eb.use_deform = True
    finally:
        _set_mode(arm, 'POSE')

    mch = arm.data.collections.get(MCH_COLLECTION) or arm.data.collections.new(MCH_COLLECTION)
    mch.is_visible = False
    bdc = arm.data.collections.get(BDEF_COLLECTION) or arm.data.collections.new(BDEF_COLLECTION)
    pbs = arm.pose.bones

    def own(name, coll):
        pb = pbs[name]
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        for c in list(pb.bone.collections):
            c.unassign(pb.bone)
        coll.assign(pb.bone)
        return pb

    def on_plane(pb):
        if flat:
            _con(pb, 'LIMIT_LOCATION', TAG + "Plane", None, "", owner_space='CUSTOM',
                 space_object=arm, space_subtarget=root,
                 use_min_y=True, use_max_y=True, min_y=0.0, max_y=0.0, use_transform_limit=False)

    def aim(pb, target, axis):
        if flat:
            _con(pb, 'LOCKED_TRACK', TAG + "Dir", arm, target, lock_axis='LOCK_X', track_axis=axis)
        else:
            _con(pb, 'DAMPED_TRACK', TAG + "Dir", arm, target, track_axis=axis)

    for k, (a, b) in enumerate(spans):
        pb = own(dir_b_name(part, a), mch)
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, point_name(part, a)); on_plane(pb)
        aim(pb, hb_name(part, a), 'TRACK_Y')
        pb = own(dir_a_name(part, b), mch)
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, point_name(part, b)); on_plane(pb)
        aim(pb, ha_name(part, b), 'TRACK_NEGATIVE_Y')
        if not flat:
            own(tip_b_name(part, a), mch)
            pb = own(cmp_name(part, k), mch)
            _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, dir_b_name(part, a))
            _con(pb, 'COPY_ROTATION', TAG + "Rot", arm, dir_a_name(part, b))
            own(cmp_tip_name(part, k), mch)
        sn = bdef_name(part, k)
        pb = own(sn, bdc)
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, point_name(part, a)); on_plane(pb)
        _con(pb, 'STRETCH_TO', TAG + "Span", arm, dir_a_name(part, b) if flat else point_name(part, b),
             volume='NO_VOLUME', keep_axis='PLANE_X', rest_length=pb.bone.length)
        for prop, pt, handle in (("bbone_easein", point_name(part, a), hb_name(part, a)),
                                 ("bbone_easeout", point_name(part, b), ha_name(part, b))):
            _, drv = _driver(arm, f'pose.bones["{sn}"].{prop}')
            _v_dist(drv, "h", arm, pt, handle)
            _v_dist(drv, "c", arm, point_name(part, a), point_name(part, b))
            if flat:
                # dir bones only turn about the plane normal: their rotation
                # difference IS the angle between the handle directions
                v = drv.variables.new(); v.name = "t"; v.type = 'ROTATION_DIFF'
                for tg, bn in zip(v.targets, (dir_b_name(part, a), dir_a_name(part, b))):
                    tg.id = arm; tg.bone_target = bn
                drv.expression = "h * 1.5 * (1 + cos(t / 2)) / max(c, 1e-9) - 1"
            else:
                _v_dist(drv, "d", arm, tip_b_name(part, a), cmp_tip_name(part, k))
                _v_dist(drv, "w", arm, cmp_name(part, k), cmp_tip_name(part, k))
                drv.expression = "h * 1.5 * (1 + sqrt(max(0, 1 - d * d / (4 * w * w)))) / max(c, 1e-9) - 1"
        # thickness: Scale In/Out X and Z follow the .scale bones' Y scale
        for prop, pt in (("bbone_scalein", a), ("bbone_scaleout", b)):
            for axis in (0, 2):
                _, drv = _driver(arm, f'pose.bones["{sn}"].{prop}', axis)
                _v_scale_y(drv, "r", arm, scale_name(part, pt))
                drv.expression = "r"
    own(up_name(part), mch)
    # end caps
    first_dir, last_dir = dir_b_name(part, indices[0]), dir_a_name(part, indices[-1])
    for side in ends:
        pb = own(bdef_end(part, side), bdc)
        handle = end_handle(part, indices, side)
        start, target = (handle, first_dir) if side == "EndL" else (last_dir, handle)
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, start); on_plane(pb)
        _con(pb, 'STRETCH_TO', TAG + "Span", arm, target, volume='NO_VOLUME', keep_axis='PLANE_X',
             rest_length=pb.bone.length)
        _con(pb, 'DAMPED_TRACK', TAG + "EndUp", arm, up_name(part), track_axis='TRACK_X')
        _con(pb, 'LOCKED_TRACK', TAG + "EndAim", arm, target, lock_axis='LOCK_X', track_axis='TRACK_Y')
        _con(pb, 'TRANSFORM', TAG + "Radius", arm, scale_name(part, indices[0] if side == "EndL" else indices[-1]),
             target_space='POSE', owner_space='POSE', map_from='SCALE', map_to='SCALE',
             map_to_x_from='Y', map_to_y_from='Y', map_to_z_from='Y',
             from_min_y_scale=0.0, from_max_y_scale=1.0,
             to_min_x_scale=0.0, to_max_x_scale=1.0, to_min_y_scale=1.0, to_max_y_scale=1.0,
             to_min_z_scale=0.0, to_max_z_scale=1.0,
             mix_mode_scale='MULTIPLY', use_motion_extrapolate=True)
    return {"part": part, "spans": len(spans), "ends": sorted(ends)}


def apply_layer_depth(arm, part, indices, depth):
    """Blender Optimized version of Layer Depth: each control point's projected
    position is pushed toward the camera by depth × (point index / last)."""
    n = len(indices) - 1 or 1
    done = 0
    for j, i in enumerate(indices):
        d = depth * j / n
        for name in (dir_b_name(part, i), dir_a_name(part, i)):
            pb = arm.pose.bones.get(name)
            c = pb.constraints.get(TAG + "Plane") if pb else None
            if c:
                c.min_y = c.max_y = d
                done += 1
        if j < len(indices) - 1:
            pb = arm.pose.bones.get(bdef_name(part, j))
            c = pb.constraints.get(TAG + "Plane") if pb else None
            if c:
                c.min_y = c.max_y = d
                done += 1
    for side, d in (("EndL", 0.0), ("EndR", depth)):
        pb = arm.pose.bones.get(bdef_end(part, side))
        c = pb.constraints.get(TAG + "Plane") if pb else None
        if c:
            c.min_y = c.max_y = d
            done += 1
    return done


# ── Weights ───────────────────────────────────────────────────────────────────

def _module_of(md):
    sid = _find_socket_id(md, "Module_name")
    return _get_gn_input(md, sid) if sid else None


def retarget_weights(arm, part, nspan):
    """Switch the chain meshes of `part` to the weight node's BDEF- branch."""
    hits = []
    for ob in W.chain_meshes(arm):
        md = W.weight_modifier(ob, arm)
        if _module_of(md) != part:
            continue
        WN.ensure_for_modifier(md)
        _set_gn_input(md, _find_socket_id(md, "Bone_prefix"), WN.PREFIX)
        _set_gn_input(md, _find_socket_id(md, "Bone Count"), nspan)
        rx = re.compile(rf"^(STR|AXIS|SIZE|DEF)-{re.escape(part)}(\.|$)")
        for vg in list(ob.vertex_groups):
            if rx.match(vg.name):
                ob.vertex_groups.remove(vg)
        # Geometry Nodes only writes a weight into a vertex group that already
        # exists on the mesh — otherwise it lands in a plain attribute the
        # Armature modifier ignores
        for name in [bdef_name(part, k) for k in range(nspan)] + [bdef_end(part, s) for s in ("EndL", "EndR")]:
            if ob.vertex_groups.get(name) is None:
                ob.vertex_groups.new(name=name)
        hits.append(ob.name)
    return hits


# ── Convert ───────────────────────────────────────────────────────────────────

def convert(arm, backup=True):
    report = {"errors": [], "chains": [], "meshes": [], "backup": None}
    props = arm.gesturebone_props
    if props.rig_type != 'UNIFIED':
        report["errors"].append("not a single rig — convert to Single Rig first")
        return report
    if arm.library is not None or arm.override_library is not None:
        report["errors"].append("linked/overridden rig — convert it in the CHR file")
        return report
    if deform_mode(arm) == MODE_BBONE:
        report["errors"].append("already Blender Optimized")
        return report
    if backup:
        path = bpy.data.filepath
        if not path:
            report["errors"].append("save the file first (a backup is written next to it)")
            return report
        root, ext = os.path.splitext(path)
        report["backup"] = f"{root}_beforeBDEF{ext}"
        bpy.ops.wm.save_as_mainfile(filepath=report["backup"], copy=True)
    was_baked = [ob.name for ob in W.chain_meshes(arm) if W.is_baked(ob)]
    for name in was_baked:
        W.live(bpy.data.objects[name])
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = arm
    for chain in props.chains:
        part = chain.part_name
        idx = bd.chain_indices(chain)
        # end caps rest exactly as their constraints aim them (End.A → first
        # point, last point → End.B); the old DEF end bones don't
        rep = build_bdef_chain(arm, part, idx, chain.plane_space)
        apply_layer_depth(arm, part, idx, chain.layer_depth if chain.plane_space == 'ROOT' else 0.0)
        report["chains"].append(rep)
        report["meshes"] += retarget_weights(arm, part, len(idx) - 1)
    props.deform_mode = MODE_BBONE
    report["rebake"] = was_baked
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    return report
