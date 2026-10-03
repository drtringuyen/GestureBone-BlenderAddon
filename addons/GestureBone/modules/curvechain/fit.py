"""
curvechain/fit.py — Annotation stroke → control points + handles → keyed pose.

Pipeline (pure Python, runs once per Apply — nothing stays live):
  1. latest stroke of the chain's annotation layer on the current frame
  2. lift onto the chain plane (view-ray intersection when a 3D view is known,
     otherwise orthogonal projection)
  3. light smoothing, arc-length parameterisation, auto-orient so the stroke
     starts at the chain's first point
  4. N points at equal arc length, central-difference tangents
  5. per span, least-squares handle lengths for a cubic with those tangents
  6. write: point = location + rotation that turns its handles onto the
     tangent; hA / hB = exact fitted positions; key on the current frame
     (locked channels are left untouched)
"""
import bpy
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_plane

from . import builder as bd
from ..shared.utils_bake import _key_unlocked

LAYER_PREFIX = "GB:"


def layer_name(part):
    return LAYER_PREFIX + part


def scene_annotation(scene, create=False):
    ann = getattr(scene, "annotation", None)
    if ann is None and create:
        ann = bpy.data.annotations.new("GestureBone")
        scene.annotation = ann
    return ann


def chain_layer(scene, part, create=False):
    ann = scene_annotation(scene, create)
    if ann is None:
        return None
    lay = ann.layers.get(layer_name(part))
    if lay is None and create:
        lay = ann.layers.new(layer_name(part), set_active=True)
        lay.color = (0.95, 0.45, 0.1)
        lay.thickness = 4
    return lay


def frame_for(layer, frame):
    """Annotation frames hold until the next keyed frame."""
    best = None
    for fr in layer.frames:
        if fr.frame_number <= frame and (best is None or fr.frame_number > best.frame_number):
            best = fr
    return best


def clear_frame(scene, part, fr):
    """Drop this chain's strokes on one annotation frame. Removes the whole
    frame: the layer belongs to the chain, and Blender 5.1's stroke collection
    has no remove() (5.2 added it)."""
    lay = chain_layer(scene, part)
    if lay is not None and fr is not None:
        lay.frames.remove(fr)


def latest_stroke(scene, part, frame):
    lay = chain_layer(scene, part)
    if lay is None:
        return None, None
    fr = frame_for(lay, frame)
    if fr is None or not fr.strokes:
        return fr, None
    return fr, fr.strokes[-1]


# ── Geometry ──────────────────────────────────────────────────────────────────

def chain_plane(arm, part, plane_space='ROOT'):
    """(origin, normal) of the chain plane in world space, from the root bone's
    CURRENT pose (or the armature's -Y for plane_space='ARMATURE')."""
    mw = arm.matrix_world
    root = bd.chain_root(arm, part)
    if root:
        m = mw @ arm.pose.bones[root].matrix
        origin = m.translation.copy()
        if plane_space == 'ROOT':
            n = m.to_3x3().col[1].normalized()
            hint = (mw.to_3x3() @ bd.WORLD_NORMAL_HINT).normalized()
            return origin, (n if n.dot(hint) >= 0 else -n)
    else:
        origin = mw.translation.copy()
    return origin, (mw.to_3x3() @ bd.WORLD_NORMAL_HINT).normalized()


def lift_to_plane(points, origin, normal, view=None):
    """view: (is_perspective, view_origin, view_dir) or None."""
    out = []
    for p in points:
        q = None
        if view is not None:
            persp, vo, vd = view
            ray_from = vo if persp else p - vd * 1000.0
            ray_dir = (p - vo).normalized() if persp else vd
            if abs(ray_dir.dot(normal)) > 1e-4:
                q = intersect_line_plane(ray_from, ray_from + ray_dir, origin, normal)
        if q is None:
            q = p - normal * (p - origin).dot(normal)
        out.append(q)
    return out


def _smooth(pts, passes=2):
    for _ in range(passes):
        if len(pts) < 3:
            break
        pts = [pts[0]] + [(pts[i - 1] + pts[i] * 2 + pts[i + 1]) / 4 for i in range(1, len(pts) - 1)] + [pts[-1]]
    return pts


class Polyline:
    def __init__(self, pts):
        clean = [pts[0]]
        for p in pts[1:]:
            if (p - clean[-1]).length > 1e-7:
                clean.append(p)
        self.pts = clean
        self.cum = [0.0]
        for a, b in zip(clean, clean[1:]):
            self.cum.append(self.cum[-1] + (b - a).length)
        self.length = self.cum[-1]

    def at(self, s):
        s = min(max(s, 0.0), self.length)
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] < s:
                lo = mid
            else:
                hi = mid
        seg = self.cum[hi] - self.cum[lo]
        u = (s - self.cum[lo]) / seg if seg > 0 else 0.0
        return self.pts[lo].lerp(self.pts[hi], u)

    def tangent(self, s, win):
        a, b = self.at(s - win), self.at(s + win)
        d = b - a
        return d.normalized() if d.length > 1e-9 else Vector((0, 0, 1))


def fit_stroke(points, count):
    """Return (points[count], tangents[count], handles[(out, in)] per span)."""
    poly = Polyline(_smooth(points))
    L = poly.length
    if L <= 1e-6 or len(poly.pts) < 2:
        raise ValueError("stroke is too short")
    ss = [L * i / (count - 1) for i in range(count)]
    cp = [poly.at(s) for s in ss]
    win = L * 0.03
    tan = [poly.tangent(s, win) for s in ss]
    handles = []
    for k in range(count - 1):
        A, B, ta, tb = cp[k], cp[k + 1], tan[k], tan[k + 1]
        n = 40
        m00 = m01 = m11 = r0 = r1 = 0.0
        for j in range(n + 1):
            t = j / n
            q = poly.at(ss[k] + (ss[k + 1] - ss[k]) * t)
            b0, b1, b2, b3 = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            r = q - (A * (b0 + b1) + B * (b2 + b3))
            u, v = ta * b1, -tb * b2
            m00 += u.dot(u); m01 += u.dot(v); m11 += v.dot(v); r0 += u.dot(r); r1 += v.dot(r)
        det = m00 * m11 - m01 * m01
        chord = (B - A).length
        if abs(det) < 1e-12:
            h0 = h1 = chord / 3
        else:
            h0 = (r0 * m11 - r1 * m01) / det
            h1 = (m00 * r1 - m01 * r0) / det
        lo, hi = chord * 0.05, chord * 1.5
        handles.append((min(max(h0, lo), hi), min(max(h1, lo), hi)))
    return cp, tan, handles


# ── Pose writing ──────────────────────────────────────────────────────────────

def _set_world(arm, pb, world):
    """Set a pose bone's world matrix, keeping locked channels as they were."""
    keep = {
        "loc": (tuple(pb.location), tuple(pb.lock_location)),
        "scale": (tuple(pb.scale), tuple(pb.lock_scale)),
    }
    rot_attr = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(pb.rotation_mode, "rotation_euler")
    old_rot = tuple(getattr(pb, rot_attr))
    pb.matrix = arm.matrix_world.inverted() @ world
    for attr, (vals, locks) in (("location", keep["loc"]), ("scale", keep["scale"])):
        cur = list(getattr(pb, attr))
        for i, lk in enumerate(locks):
            if lk:
                cur[i] = vals[i]
        setattr(pb, attr, cur)
    if rot_attr == "rotation_euler":
        cur = list(pb.rotation_euler)
        for i, lk in enumerate(pb.lock_rotation):
            if lk:
                cur[i] = old_rot[i]
        pb.rotation_euler = cur


def _key(pb, frame, rotation=True):
    _key_unlocked(pb, "location", frame)
    if rotation:
        attr = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(pb.rotation_mode, "rotation_euler")
        _key_unlocked(pb, attr, frame)


def apply_fit(context, arm, chain, points_world, frame=None, view=None, auto_direction=True, key=True):
    """Fit a world-space stroke onto `chain` of the single rig `arm` and key it.
    Returns a report dict."""
    part = chain.part_name
    indices = bd.chain_indices(chain)
    plane_space = getattr(chain, "plane_space", 'ROOT')
    frame = context.scene.frame_current if frame is None else frame
    origin, normal = chain_plane(arm, part, plane_space)
    pts = lift_to_plane(points_world, origin, normal, view)
    mw = arm.matrix_world
    p0 = (mw @ arm.pose.bones[bd.point_name(part, indices[0])].matrix).translation
    reversed_ = False
    if auto_direction and (pts[-1] - p0).length < (pts[0] - p0).length:
        pts = list(reversed(pts))
        reversed_ = True
    cp, tan, handles = fit_stroke(pts, len(indices))

    pbs = arm.pose.bones
    # 1. points: position + spin about the plane normal so the handles follow the tangent
    for n, i in enumerate(indices):
        pb = pbs[bd.point_name(part, i)]
        cur = mw @ pb.matrix
        hb = pbs.get(bd.hb_name(part, i)) if n < len(indices) - 1 else None
        ha = pbs.get(bd.ha_name(part, i)) if n > 0 else None
        if hb is not None:
            d = (mw @ hb.matrix).translation - cur.translation
        elif ha is not None:
            d = cur.translation - (mw @ ha.matrix).translation
        else:
            d = Vector()
        rot = d.normalized().rotation_difference(tan[n]) if d.length > 1e-9 else Matrix.Identity(3).to_quaternion()
        new = Matrix.Translation(cp[n]) @ rot.to_matrix().to_4x4() @ Matrix.Translation(-cur.translation) @ cur
        _set_world(arm, pb, new)
    context.view_layer.update()
    # 2. handles at the fitted lengths
    for k in range(len(indices) - 1):
        a, b = indices[k], indices[k + 1]
        for pb, pos in ((pbs[bd.hb_name(part, a)], cp[k] + tan[k] * handles[k][0]),
                        (pbs[bd.ha_name(part, b)], cp[k + 1] - tan[k + 1] * handles[k][1])):
            m = (mw @ pb.matrix).copy()
            m.translation = pos
            _set_world(arm, pb, m)
    context.view_layer.update()
    if key:
        for n, i in enumerate(indices):
            _key(pbs[bd.point_name(part, i)], frame, rotation=True)
            if n < len(indices) - 1:
                _key(pbs[bd.hb_name(part, i)], frame, rotation=False)
            if n > 0:
                _key(pbs[bd.ha_name(part, i)], frame, rotation=False)
    return {"part": part, "frame": frame, "points": len(cp), "reversed": reversed_,
            "handles": [tuple(round(h, 4) for h in hh) for hh in handles]}


def view_from_context(context):
    rv3d = getattr(context, "region_data", None)
    if rv3d is None or not hasattr(rv3d, "view_matrix"):
        return None
    vinv = rv3d.view_matrix.inverted()
    vdir = (vinv.to_3x3() @ Vector((0, 0, -1))).normalized()
    return (rv3d.is_perspective, vinv.translation.copy(), vdir)


def chain_bones(arm, chain):
    """Keyable animator bones of a chain (points + handles)."""
    part = chain.part_name
    idx = bd.chain_indices(chain)
    out = []
    for n, i in enumerate(idx):
        out.append(bd.point_name(part, i))
        if n > 0:
            out.append(bd.ha_name(part, i))
        if n < len(idx) - 1:
            out.append(bd.hb_name(part, i))
    return [b for b in out if arm.pose.bones.get(b)]
