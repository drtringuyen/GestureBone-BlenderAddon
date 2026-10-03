"""
curvechain/builder.py — Curve machinery that lives inside ONE armature.

Replaces the PlottingSpline + "Plotting_CurveChain_Linear3" GN pass. Per chain
(all MCH bones are hidden, non-deform, in the MCH-CurveChain bone collection):

    CTRL-{part}_{i}            point          (animator)
    CTRL-{part}_{i}.hA / .hB   in/out handle  (animator; were .hL/.hR)
    CTRL-{part}_{i}.scale      radius = Y scale (animator)

    MCH-{part}_{i}.dirB        Y = direction leaving point i   (P → hB)
    MCH-{part}_{i}.dirA        Y = direction arriving at i     (hA → P)
    MCH-{part}.SEG_{k}         B-Bone span P_k → P_k+1, TANGENT handles dirB/dirA
    MCH-{part}.SEG_{k}.q1..q3  points at 1/4, 1/2, 3/4 of the span (arc length)
    MCH-{part}.Up              far along the chain plane normal (sampler up-vector)
    MCH-{part}.rad_{s}         radius carrier for sampler s

Math, so the chain reproduces the old GN bezier exactly:
  * A B-Bone span with ease E has handle length E * chord / (1.5 * (1 + cos(θ/2)))
    (Blender's cubic_tangent_factor_circle_v3; θ = angle between the two handle
    directions). The SEG ease drivers invert that from the REAL handle
    distances, so span k is the cubic (P_k, hB_k, hA_k+1, P_k+1).
  * θ comes from positions only (two unit "tips" an L0 apart → 2·L0·sin(θ/2)),
    so it stays right when a chain bends out of its plane.
  * Span arc length = Richardson-corrected chord sum over q1..q3 (B-Bone
    segments are arc-length equalised, so head_tail is an arc fraction).
  * Samplers (the existing STR-* bones) are spread evenly by arc length over
    the whole chain, like Resample Curve did, by drivers on head_tail and on
    which span is active. Their X axis is the plane normal projected off the
    tangent (Locked Track on MCH-{part}.Up) — the old "3 Bones plane" frame —
    and their uniform scale is the radius interpolated along the chain.

Every driver is a simple expression (no Python evaluation, no auto-exec).
"""
import bpy
from mathutils import Vector, Matrix

from ..shared.chain import CONTROL_MODE_COUNT, _ctrl_bone_indices

MCH_COLLECTION = "MCH-CurveChain"
BBONE_SEGMENTS = 32
UP_DISTANCE = 1000.0                           # × chain length
WORLD_NORMAL_HINT = Vector((0.0, -1.0, 0.0))   # the old GN normal faced -Y
TAG = "CC_"

# name helpers — everything is looked up by NAME (blender-api-pitfalls #1)
def point_name(part, idx):  return f"CTRL-{part}_{idx}"
def ha_name(part, idx):     return f"CTRL-{part}_{idx}.hA"
def hb_name(part, idx):     return f"CTRL-{part}_{idx}.hB"
def scale_name(part, idx):  return f"CTRL-{part}_{idx}.scale"
def dir_a_name(part, idx):  return f"MCH-{part}_{idx}.dirA"
def dir_b_name(part, idx):  return f"MCH-{part}_{idx}.dirB"
def tip_b_name(part, idx):  return f"MCH-{part}_{idx}.dirB.tip"
def seg_name(part, k):      return f"MCH-{part}.SEG_{k}"
def cmp_name(part, k):      return f"MCH-{part}.SEG_{k}.cmp"
def cmp_tip_name(part, k):  return f"MCH-{part}.SEG_{k}.cmp.tip"
def q_name(part, k, j):     return f"MCH-{part}.SEG_{k}.q{j}"
def up_name(part):          return f"MCH-{part}.Up"
def rad_name(part, s):      return f"MCH-{part}.rad_{s:02d}"
def root_candidates(part):  return (f"CTRL-{part}.Rotation", f"CTRL-{part}.Pivot")
LEN_PROP = "cc_len"


def chain_indices(chain):
    """CTRL indices used by a chain, e.g. PT_3 → [0, 2, 4]."""
    return _ctrl_bone_indices(CONTROL_MODE_COUNT.get(chain.control_mode, 5))


def chain_root(arm, part):
    for n in root_candidates(part):
        if arm.data.bones.get(n):
            return n
    return None


def plane_normal_rest(arm, part):
    """Rest-space plane normal: the root bone's Y axis (Pivot/Rotation bones
    point along the view axis), signed like the old GN normal (-Y)."""
    rn = chain_root(arm, part)
    if rn is None:
        return WORLD_NORMAL_HINT.copy()
    n = arm.data.bones[rn].matrix_local.col[1].to_3d().normalized()
    return n if n.dot(WORLD_NORMAL_HINT) >= 0 else -n


def missing_bones(arm, part, indices):
    need = []
    for n, i in enumerate(indices):
        need += [point_name(part, i), scale_name(part, i)]
        if n > 0:
            need.append(ha_name(part, i))
        if n < len(indices) - 1:
            need.append(hb_name(part, i))
    return [b for b in need if not arm.data.bones.get(b)]


# ── Edit-bone helpers ─────────────────────────────────────────────────────────

def _frame(y, normal):
    y = y.normalized()
    x = normal - y * normal.dot(y)
    if x.length < 1e-6:
        x = y.orthogonal()
    x.normalize()
    return Matrix((x, y, x.cross(y))).transposed()


def _eb(arm, name, head, direction, normal, length, parent):
    ebs = arm.data.edit_bones
    eb = ebs.get(name) or ebs.new(name)
    m = _frame(direction if direction.length > 1e-9 else Vector((0, 0, 1)), normal).to_4x4()
    m.translation = head
    eb.head = head
    eb.tail = head + m.col[1].to_3d() * length
    eb.matrix = m
    eb.length = length
    eb.parent = ebs.get(parent) if parent else None
    eb.use_connect = False
    eb.use_deform = False
    return eb


def _set_mode(arm, mode):
    view_layer = bpy.context.view_layer
    if view_layer.objects.active is not arm:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        view_layer.objects.active = arm
    if arm.mode != mode:
        bpy.ops.object.mode_set(mode=mode)


# ── Constraint / driver helpers ───────────────────────────────────────────────

def _con(pb, ctype, name, arm, sub, **kw):
    c = pb.constraints.new(ctype)
    c.name = name
    if hasattr(c, "target"):
        c.target = arm
        c.subtarget = sub
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _clear_tagged(pb, also_types=()):
    for c in list(pb.constraints):
        if c.name.startswith(TAG) or c.type in also_types:
            pb.constraints.remove(c)


def _driver(arm, path, index=-1):
    try:
        arm.driver_remove(path, index)
    except TypeError:
        pass
    fc = arm.driver_add(path, index)
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)
    drv = fc.driver
    drv.type = 'SCRIPTED'
    for v in list(drv.variables):
        drv.variables.remove(v)
    return fc, drv


def _v_dist(drv, name, arm, b1, b2):
    v = drv.variables.new(); v.name = name; v.type = 'LOC_DIFF'
    for t, b in zip(v.targets, (b1, b2)):
        t.id = arm; t.bone_target = b; t.transform_space = 'WORLD_SPACE'


def _v_prop(drv, name, arm, path):
    v = drv.variables.new(); v.name = name; v.type = 'SINGLE_PROP'
    v.targets[0].id_type = 'OBJECT'; v.targets[0].id = arm; v.targets[0].data_path = path


def _v_scale_y(drv, name, arm, bone):
    v = drv.variables.new(); v.name = name; v.type = 'TRANSFORMS'
    t = v.targets[0]; t.id = arm; t.bone_target = bone
    t.transform_type = 'SCALE_Y'; t.transform_space = 'WORLD_SPACE'


def remove_drivers(arm, prefix):
    ad = arm.animation_data
    if not ad:
        return 0
    dead = [fc for fc in ad.drivers if fc.data_path.startswith(f'pose.bones["{prefix}')]
    for fc in dead:
        ad.drivers.remove(fc)
    return len(dead)


# ── Build the span machinery ──────────────────────────────────────────────────

def build_chain(arm, part, indices, plane='ROOT'):
    """Create (or refresh) MCH dir/tip/SEG/cmp/q/Up bones, their constraints and
    the ease + arc-length drivers for one chain. Leaves the armature in POSE
    mode (or the mode it was in, if not EDIT).

    plane: 'ROOT'      — the sampler up-vector follows the chain root bone, so
                         rotating CTRL-{part}.Rotation tilts the chain plane.
           'ARMATURE'  — fixed armature -Y, exactly what the old GN did."""
    miss = missing_bones(arm, part, indices)
    if miss:
        raise RuntimeError(f"{part}: missing bones {miss}")
    root = chain_root(arm, part)
    bones = arm.data.bones
    normal = plane_normal_rest(arm, part) if plane == 'ROOT' else WORLD_NORMAL_HINT.copy()
    P = {i: bones[point_name(part, i)].head_local.copy() for i in indices}
    HA = {i: bones[ha_name(part, i)].head_local.copy() for i in indices[1:]}
    HB = {i: bones[hb_name(part, i)].head_local.copy() for i in indices[:-1]}
    chain_len = sum((P[b] - P[a]).length for a, b in zip(indices, indices[1:])) or 1.0
    spans = list(zip(indices, indices[1:]))

    prev_mode = arm.mode
    _set_mode(arm, 'EDIT')
    try:
        L0 = {}
        for k, (a, b) in enumerate(spans):
            span = (P[b] - P[a]).length or chain_len
            L0[k] = max(span * 0.25, 1e-3)
            db = (HB[a] - P[a]) if (HB[a] - P[a]).length > 1e-6 else (P[b] - P[a])
            da = (P[b] - HA[b]) if (P[b] - HA[b]).length > 1e-6 else (P[b] - P[a])
            _eb(arm, dir_b_name(part, a), P[a], db, normal, L0[k], root)
            _eb(arm, tip_b_name(part, a), P[a] + db.normalized() * L0[k], db, normal, L0[k] * 0.2, dir_b_name(part, a))
            _eb(arm, dir_a_name(part, b), P[b], da, normal, L0[k], root)
            _eb(arm, cmp_name(part, k), P[a], da, normal, L0[k], root)
            _eb(arm, cmp_tip_name(part, k), P[a] + da.normalized() * L0[k], da, normal, L0[k] * 0.2, cmp_name(part, k))
            eb = _eb(arm, seg_name(part, k), P[a], P[b] - P[a], normal, (P[b] - P[a]).length, root)
            eb.bbone_segments = BBONE_SEGMENTS
            eb.bbone_easein = eb.bbone_easeout = 1.0
            eb.bbone_handle_type_start = 'TANGENT'
            eb.bbone_custom_handle_start = arm.data.edit_bones[dir_b_name(part, a)]
            eb.bbone_handle_type_end = 'TANGENT'
            eb.bbone_custom_handle_end = arm.data.edit_bones[dir_a_name(part, b)]
            eb.bbone_handle_use_ease_start = eb.bbone_handle_use_ease_end = False
            eb.bbone_x = eb.bbone_z = chain_len * 0.005
            for j in (1, 2, 3):
                _eb(arm, q_name(part, k, j), P[a].lerp(P[b], j / 4), P[b] - P[a], normal, chain_len * 0.02, root)
        rh = bones[root].head_local if root else P[indices[0]]
        _eb(arm, up_name(part), rh + normal * chain_len * UP_DISTANCE, normal, normal.orthogonal(), chain_len * 0.05,
            root if plane == 'ROOT' else None)
    finally:
        _set_mode(arm, prev_mode if prev_mode not in ('EDIT', 'OBJECT') else 'POSE')

    coll = arm.data.collections.get(MCH_COLLECTION) or arm.data.collections.new(MCH_COLLECTION)
    coll.is_visible = False
    pbs = arm.pose.bones
    made = []

    def own(name):
        pb = pbs[name]
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        coll.assign(pb.bone)
        made.append(name)
        return pb

    # 'ROOT': build the spans ON the root bone's plane — points are projected
    # onto it and handle directions may only turn about its normal (the MCH
    # bones' local X), so an off-plane control can't tilt the chain.
    flat = plane == 'ROOT' and root is not None

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

    remove_drivers(arm, f"MCH-{part}.SEG_")
    for k, (a, b) in enumerate(spans):
        pb = own(dir_b_name(part, a))
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, point_name(part, a))
        on_plane(pb)
        aim(pb, hb_name(part, a), 'TRACK_Y')
        own(tip_b_name(part, a))
        pb = own(dir_a_name(part, b))
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, point_name(part, b))
        on_plane(pb)
        aim(pb, ha_name(part, b), 'TRACK_NEGATIVE_Y')
        pb = own(cmp_name(part, k))
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, dir_b_name(part, a))
        _con(pb, 'COPY_ROTATION', TAG + "Rot", arm, dir_a_name(part, b))
        own(cmp_tip_name(part, k))

        sn = seg_name(part, k)
        pb = own(sn)
        _con(pb, 'COPY_LOCATION', TAG + "Loc", arm, point_name(part, a))
        on_plane(pb)
        _con(pb, 'STRETCH_TO', TAG + "Span", arm, dir_a_name(part, b) if flat else point_name(part, b),
             volume='NO_VOLUME', keep_axis='PLANE_X', rest_length=pb.bone.length)
        for prop, pt, handle in (("bbone_easein", point_name(part, a), hb_name(part, a)),
                                 ("bbone_easeout", point_name(part, b), ha_name(part, b))):
            _, drv = _driver(arm, f'pose.bones["{sn}"].{prop}')
            _v_dist(drv, "h", arm, pt, handle)
            _v_dist(drv, "c", arm, point_name(part, a), point_name(part, b))
            _v_dist(drv, "d", arm, tip_b_name(part, a), cmp_tip_name(part, k))
            _v_dist(drv, "w", arm, cmp_name(part, k), cmp_tip_name(part, k))
            # cos(θ/2) = sqrt(1 - (d / 2w)^2); rest ease 1.0 is added by Blender
            drv.expression = "h * 1.5 * (1 + sqrt(max(0, 1 - d * d / (4 * w * w)))) / max(c, 1e-9) - 1"
        for j in (1, 2, 3):
            pq = own(q_name(part, k, j))
            _con(pq, 'COPY_LOCATION', TAG + "OnSpan", arm, sn, head_tail=j / 4, use_bbone_shape=True)
        pb[LEN_PROP] = (P[b] - P[a]).length
        _, drv = _driver(arm, f'pose.bones["{sn}"]["{LEN_PROP}"]')
        pts = [point_name(part, a)] + [q_name(part, k, j) for j in (1, 2, 3)] + [point_name(part, b)]
        for n, (x, y) in enumerate(zip(pts, pts[1:])):
            _v_dist(drv, f"s{n}", arm, x, y)
        _v_dist(drv, "h0", arm, pts[0], pts[2])
        _v_dist(drv, "h1", arm, pts[2], pts[4])
        drv.expression = "(4 * (s0 + s1 + s2 + s3) - (h0 + h1)) / 3"
    own(up_name(part))
    return {"part": part, "root": root, "bones": made}


# ── Samplers ──────────────────────────────────────────────────────────────────

def span_rest_lengths(arm, part, indices):
    b = arm.data.bones
    out = []
    for a, c in zip(indices, indices[1:]):
        p0, p1 = b[point_name(part, a)].head_local, b[hb_name(part, a)].head_local
        p2, p3 = b[ha_name(part, c)].head_local, b[point_name(part, c)].head_local
        prev, tot = p0, 0.0
        for i in range(1, 129):
            t = i / 128
            q = ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t * t * p2 + (t ** 3) * p3
            tot += (q - prev).length
            prev = q
        out.append(tot)
    return out


def fixed_slots(arm, part, indices, count):
    """(span, head_tail) per sample, spread by REST arc length."""
    lens = span_rest_lengths(arm, part, indices)
    total = sum(lens)
    out = []
    for s in range(count):
        dist = total * s / (count - 1) if count > 1 else 0.0
        acc = 0.0
        for k, L in enumerate(lens):
            if dist <= acc + L + 1e-9 or k == len(lens) - 1:
                out.append((k, min(max((dist - acc) / L if L > 0 else 0.0, 0.0), 1.0)))
                break
            acc += L
    return out


def bind_samplers(arm, part, indices, samplers, spacing='UNIFORM', facing=None):
    """Rebind sampler bones (index order = position along the chain) to the
    spans. Replaces GEOMETRY_ATTRIBUTE / earlier CC_ constraints in place, so a
    trailing Limit Scale or Stretch To keeps running after them.

    facing: {sampler: 'TRACK_X' | 'TRACK_NEGATIVE_X'} — which side of the plane
    each sampler's X faces. The converter measures it from the old GN result;
    rest frames can NOT tell (LittlePig's right-side chains rest at +Y but the
    GN drove them to -Y). Missing entries keep an existing CC_Up's setting,
    else default to TRACK_X (toward MCH-{part}.Up)."""
    facing = dict(facing or {})
    for name in samplers:
        old = arm.pose.bones[name].constraints.get(TAG + "Up")
        if name not in facing and old is not None:
            facing[name] = old.track_axis
    nspan = len(indices) - 1
    count = len(samplers)
    root = chain_root(arm, part)
    _set_mode(arm, 'EDIT')
    try:
        ebs = arm.data.edit_bones
        for s, name in enumerate(samplers):
            src = ebs[name]
            r = ebs.get(rad_name(part, s)) or ebs.new(rad_name(part, s))
            r.head = src.head; r.tail = src.head + Vector((0, 0, max(src.length * 0.2, 1e-3)))
            r.parent = None; r.use_deform = False
    finally:
        _set_mode(arm, 'POSE')
    coll = arm.data.collections.get(MCH_COLLECTION) or arm.data.collections.new(MCH_COLLECTION)
    remove_drivers(arm, f"MCH-{part}.rad_")
    for name in samplers:
        remove_drivers(arm, name + '"]')

    lens = [f"L{k}" for k in range(nspan)]
    slots = fixed_slots(arm, part, indices, count)
    pbs = arm.pose.bones
    report = []
    # 'ROOT' plane (Up parented to the chain root): also PROJECT every sampler
    # onto the root bone's plane, so the deform chain lies flat on it even when
    # a control drifts off-plane. 'ARMATURE' keeps the old GN behaviour (no
    # projection) for converted rigs.
    up_b = arm.data.bones.get(up_name(part))
    project = root is not None and up_b is not None and up_b.parent is not None and up_b.parent.name == root
    for s, name in enumerate(samplers):
        pb = pbs[name]
        slot = next((i for i, c in enumerate(pb.constraints)
                     if c.type == 'GEOMETRY_ATTRIBUTE' or c.name.startswith(TAG)), 0)
        _clear_tagged(pb, also_types=('GEOMETRY_ATTRIBUTE',))
        u = s / (count - 1) if count > 1 else 0.0
        new = []
        if spacing == 'UNIFORM':
            X = f"{u:.9g} * ({' + '.join(lens)})"
            for k in range(nspan):
                c = _con(pb, 'COPY_TRANSFORMS', f"{TAG}Sample_{k}", arm, seg_name(part, k),
                         head_tail=0.0, use_bbone_shape=True)
                new.append(c)
                C = " + ".join(lens[:k]) or "0"
                path = f'pose.bones["{name}"].constraints["{c.name}"]'
                _, drv = _driver(arm, path + ".head_tail")
                for kk in range(nspan):
                    _v_prop(drv, f"L{kk}", arm, f'pose.bones["{seg_name(part, kk)}"]["{LEN_PROP}"]')
                drv.expression = f"min(max(({X} - ({C})) / max(L{k}, 1e-9), 0), 1)"
                if k > 0:
                    _, drv = _driver(arm, path + ".influence")
                    for kk in range(nspan):
                        _v_prop(drv, f"L{kk}", arm, f'pose.bones["{seg_name(part, kk)}"]["{LEN_PROP}"]')
                    drv.expression = f"min(max(({X} - ({C})) * 1e9, 0), 1)"
        else:
            k, ht = slots[s]
            new.append(_con(pb, 'COPY_TRANSFORMS', f"{TAG}Sample_{k}", arm, seg_name(part, k),
                            head_tail=ht, use_bbone_shape=True))
        if project:
            # root bones point along the plane normal: their local Y is it
            new.append(_con(pb, 'LIMIT_LOCATION', TAG + "Plane", None, "",
                            owner_space='CUSTOM', space_object=arm, space_subtarget=root,
                            use_min_y=True, use_max_y=True, min_y=0.0, max_y=0.0,
                            use_transform_limit=False))
        new.append(_con(pb, 'LOCKED_TRACK', TAG + "Up", arm, up_name(part),
                        lock_axis='LOCK_Y', track_axis=facing.get(name, 'TRACK_X')))
        c = _con(pb, 'TRANSFORM', TAG + "Radius", arm, rad_name(part, s),
                 target_space='POSE', owner_space='POSE', map_from='SCALE', map_to='SCALE',
                 map_to_x_from='Y', map_to_y_from='Y', map_to_z_from='Y',
                 from_min_y_scale=0.0, from_max_y_scale=1.0,
                 to_min_x_scale=0.0, to_min_y_scale=0.0, to_min_z_scale=0.0,
                 to_max_x_scale=1.0, to_max_y_scale=1.0, to_max_z_scale=1.0,
                 mix_mode_scale='REPLACE', use_motion_extrapolate=True)
        new.append(c)
        for off, c in enumerate(new):
            pb.constraints.move(list(pb.constraints).index(c), slot + off)
        if project:
            # the rig's own trailing Stretch To (end caps aim at their End
            # handle, which may sit off the plane) is left as is; after it,
            # put X back on the plane normal and turn Y only about that normal
            # toward the target — the end cap still aims at its handle, flat.
            stretch = next((c for c in pb.constraints if c.type == 'STRETCH_TO' and not c.name.startswith(TAG)), None)
            if stretch is not None and stretch.subtarget:
                _con(pb, 'LOCKED_TRACK', TAG + "EndUp", arm, up_name(part),
                     lock_axis='LOCK_Y', track_axis=facing.get(name, 'TRACK_X'))
                _con(pb, 'LOCKED_TRACK', TAG + "EndAim", arm, stretch.subtarget,
                     lock_axis='LOCK_X', track_axis='TRACK_Y')

        # radius carrier: r = r0 + Σ (r_k+1 - r_k) * t_k   (t_k clamped span param)
        rp = pbs[rad_name(part, s)]
        for cc in list(rp.constraints):
            rp.constraints.remove(cc)
        coll.assign(rp.bone)
        _, drv = _driver(arm, f'pose.bones["{rad_name(part, s)}"].scale', 1)
        for n, i in enumerate(indices):
            _v_scale_y(drv, f"r{n}", arm, scale_name(part, i))
        if spacing == 'UNIFORM':
            # t_k is already computed by the sample constraints' own head_tail
            # drivers — read it back instead of repeating it (driver expressions
            # are capped at 255 characters)
            for kk in range(nspan):
                _v_prop(drv, f"t{kk}", arm, f'pose.bones["{name}"].constraints["{TAG}Sample_{kk}"].head_tail')
            terms = [f"(r{k + 1} - r{k}) * t{k}" for k in range(nspan)]
        else:
            k0, ht = slots[s]
            terms = [f"(r{k + 1} - r{k}) * {1.0 if k < k0 else (ht if k == k0 else 0.0)!r}" for k in range(nspan)]
        drv.expression = "r0 + " + " + ".join(terms)
        report.append(name)
    return report


def non_simple_drivers(arm):
    """Driver paths whose expression Blender could not run as a simple
    expression (would need Python / auto-exec)."""
    ad = arm.animation_data
    return [fc.data_path for fc in (ad.drivers if ad else [])
            if fc.data_path.startswith('pose.bones["MCH-') or '"CC_' in fc.data_path
            if fc.driver.type == 'SCRIPTED' and not fc.driver.is_simple_expression]


def samplers_of(arm, part):
    """Sampler bones of a chain, in chain order (from their radius carrier index)."""
    found = {}
    prefix = f"MCH-{part}.rad_"
    for pb in arm.pose.bones:
        c = pb.constraints.get(TAG + "Radius")
        if c is not None and c.subtarget.startswith(prefix):
            found[int(c.subtarget[len(prefix):])] = pb.name
    return [found[k] for k in sorted(found)]


def spacing_of(arm, part):
    for name in samplers_of(arm, part)[:1]:
        n = sum(1 for c in arm.pose.bones[name].constraints if c.name.startswith(TAG + "Sample_"))
        return 'UNIFORM' if n > 1 else 'FIXED'
    return 'UNIFORM'
