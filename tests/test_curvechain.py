"""
tests/test_curvechain.py — single-armature rig math on a synthetic chain.

Needs no production file: builds CTRL/handle/scale/STR bones for one 3-point
chain, runs builder.build_chain + bind_samplers, then checks the samplers
against an analytic bezier resampled by arc length (what the old GN did).

Run standalone against the repo copy:
    blender --background --factory-startup --python tests/test_curvechain.py
"""
import math
import os
import sys
import unittest

import bpy
from mathutils import Vector

REPO_ADDONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "addons")


def _ensure_addon():
    if hasattr(bpy.types.Object, "gesturebone_props"):
        return
    if REPO_ADDONS not in sys.path:
        sys.path.insert(0, REPO_ADDONS)
    import GestureBone
    GestureBone.register()


PART = "Limb"
IDX = [0, 2, 4]
N_SAMPLES = 13


def _bezier(p0, p1, p2, p3, t):
    return ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t * t * p2 + (t ** 3) * p3


def _uniform_reference(ob, count):
    """Old GN behaviour: the bezier through the CTRL heads, resampled by length."""
    W = lambda n: (ob.matrix_world @ ob.pose.bones[n].matrix).translation
    pts = []
    for a, b in zip(IDX, IDX[1:]):
        P0, H0 = W(f"CTRL-{PART}_{a}"), W(f"CTRL-{PART}_{a}.hB")
        H1, P1 = W(f"CTRL-{PART}_{b}.hA"), W(f"CTRL-{PART}_{b}")
        pts += [_bezier(P0, H0, H1, P1, i / 600) for i in range(600)]
    pts.append(W(f"CTRL-{PART}_{IDX[-1]}"))
    cum = [0.0]
    for p, q in zip(pts, pts[1:]):
        cum.append(cum[-1] + (q - p).length)
    out, j = [], 1
    for s in range(count):
        d = cum[-1] * s / (count - 1)
        while j < len(cum) - 1 and cum[j] < d:
            j += 1
        u = (d - cum[j - 1]) / max(cum[j] - cum[j - 1], 1e-12)
        out.append(pts[j - 1].lerp(pts[j], u))
    return out


class TestCurveChain(unittest.TestCase):

    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        _ensure_addon()
        from GestureBone.modules.curvechain import builder
        self.bd = builder
        arm = bpy.data.armatures.new("Rig")
        ob = bpy.data.objects.new("Rig", arm)
        bpy.context.scene.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.edit_bones
        root = eb.new(f"CTRL-{PART}.Rotation")
        root.head, root.tail = (0, 0, 0), (0, -0.2, 0)       # points along the view axis, like the pig
        for n, i in enumerate(IDX):
            x = n * 0.5
            p = eb.new(f"CTRL-{PART}_{i}"); p.head, p.tail = (x, 0, 1), (x, -0.1, 1); p.parent = root
            s = eb.new(f"CTRL-{PART}_{i}.scale"); s.head, s.tail = (x, 0, 1), (x, 0, 0.9); s.parent = p
            if n > 0:
                h = eb.new(f"CTRL-{PART}_{i}.hA"); h.head, h.tail = (x - 0.15, 0, 1), (x - 0.15, -0.05, 1); h.parent = p
            if n < len(IDX) - 1:
                h = eb.new(f"CTRL-{PART}_{i}.hB"); h.head, h.tail = (x + 0.15, 0, 1), (x + 0.15, -0.05, 1); h.parent = p
        for k in range(N_SAMPLES):
            b = eb.new(f"STR-{PART}.{k:03d}"); b.head = (k / 12, 0, 1); b.tail = (k / 12, 0, 0.95)
        bpy.ops.object.mode_set(mode='POSE')
        self.ob = ob
        builder.build_chain(ob, PART, IDX, plane='ROOT')
        builder.bind_samplers(ob, PART, IDX, [f"STR-{PART}.{k:03d}" for k in range(N_SAMPLES)], 'UNIFORM')

    def _pose(self):
        P = self.ob.pose.bones
        P[f"CTRL-{PART}_2"].location = (0.0, 0.0, 0.0)
        P[f"CTRL-{PART}_2"].matrix = self.ob.matrix_world.inverted() @ (
            self.ob.matrix_world @ P[f"CTRL-{PART}_2"].matrix).copy()
        P[f"CTRL-{PART}_4"].location = Vector((0.3, 0, -0.25))      # local axes: see root roll
        P[f"CTRL-{PART}_0.hB"].location = Vector((0.0, 0.0, 0.25))
        P[f"CTRL-{PART}_2.hA"].location = Vector((-0.1, 0.0, 0.0))
        P[f"CTRL-{PART}_4.hA"].location = Vector((0.0, 0.0, 0.2))
        bpy.context.view_layer.update()

    def test_drivers_are_simple_expressions(self):
        self.assertEqual(self.bd.non_simple_drivers(self.ob), [])

    def test_rest_matches_reference(self):
        bpy.context.view_layer.update()
        ref = _uniform_reference(self.ob, N_SAMPLES)
        for k, r in enumerate(ref):
            got = (self.ob.matrix_world @ self.ob.pose.bones[f"STR-{PART}.{k:03d}"].matrix).translation
            self.assertLess((got - r).length, 1e-4, f"sample {k}")

    def test_posed_matches_reference_and_stays_planar(self):
        self._pose()
        ref = _uniform_reference(self.ob, N_SAMPLES)
        length = sum((a - b).length for a, b in zip(ref, ref[1:]))
        n = Vector((0, -1, 0))
        for k, r in enumerate(ref):
            m = self.ob.matrix_world @ self.ob.pose.bones[f"STR-{PART}.{k:03d}"].matrix
            self.assertLess((m.translation - r).length / length, 0.005, f"sample {k} position")
            self.assertAlmostEqual(abs(m.to_3x3().normalized().col[0].dot(n)), 1.0, places=4,
                                   msg=f"sample {k} X must stay on the plane normal (no twist)")

    def test_radius_follows_scale_bones(self):
        P = self.ob.pose.bones
        P[f"CTRL-{PART}_0.scale"].scale = (1, 2.0, 1)
        P[f"CTRL-{PART}_4.scale"].scale = (1, 1.0, 1)
        bpy.context.view_layer.update()
        first = (self.ob.matrix_world @ P[f"STR-{PART}.000"].matrix).to_scale()
        last = (self.ob.matrix_world @ P[f"STR-{PART}.{N_SAMPLES - 1:03d}"].matrix).to_scale()
        self.assertAlmostEqual(first.x, 2.0, places=3)
        self.assertAlmostEqual(first.y, 2.0, places=3)
        self.assertAlmostEqual(last.x, 1.0, places=3)

    def test_stroke_fit_keys_chain(self):
        from GestureBone.modules.curvechain import fit
        self.ob.gesturebone_props.rig_type = 'UNIFIED'
        chain = self.ob.gesturebone_props.chains.add()
        chain.part_name, chain.control_mode = PART, 'PT_3'
        stroke = [Vector((t * 1.0, 0.05 * math.sin(t * 7), 1.0 + 0.2 * math.sin(t * 3.1))) for t in
                  (i / 80 for i in range(81))]
        rep = fit.apply_fit(bpy.context, self.ob, chain, stroke, frame=1)
        self.assertFalse(rep["reversed"])
        bpy.context.scene.frame_set(1)
        origin, normal = fit.chain_plane(self.ob, PART, 'ROOT')
        flat = fit.Polyline(fit.lift_to_plane(stroke, origin, normal))
        dense = [flat.at(flat.length * i / 1000) for i in range(1001)]
        worst = max(min(((self.ob.matrix_world @ self.ob.pose.bones[f"STR-{PART}.{k:03d}"].matrix).translation - d).length
                        for d in dense) for k in range(N_SAMPLES))
        self.assertLess(worst / flat.length, 0.01)
        self.assertTrue(self.ob.animation_data and self.ob.animation_data.action)

    def test_root_plane_projects_and_follows_root(self):
        P = self.ob.pose.bones
        mw = self.ob.matrix_world
        # push a control off the plane, then tilt the chain root
        m = (mw @ P[f"CTRL-{PART}_2"].matrix).copy(); m.translation.y += 0.15
        P[f"CTRL-{PART}_2"].matrix = mw.inverted() @ m
        P[f"CTRL-{PART}.Rotation"].rotation_mode = 'XYZ'
        P[f"CTRL-{PART}.Rotation"].rotation_euler = (0.0, 0.0, 0.5)
        bpy.context.view_layer.update()
        root = mw @ P[f"CTRL-{PART}.Rotation"].matrix
        n = root.to_3x3().col[1].normalized()
        for k in range(N_SAMPLES):
            m = mw @ P[f"STR-{PART}.{k:03d}"].matrix
            self.assertLess(abs((m.translation - root.translation).dot(n)), 1e-4, f"sample {k} off the root plane")
            self.assertAlmostEqual(abs(m.to_3x3().normalized().col[0].dot(n)), 1.0, places=3)

    def test_layer_depth_ramps_toward_camera(self):
        chain = self.ob.gesturebone_props.chains.add()
        chain.part_name, chain.control_mode, chain.plane_space = PART, 'PT_3', 'ROOT'
        chain.layer_depth = 0.05                       # live: update callback writes the constraints
        bpy.context.view_layer.update()
        P = self.ob.pose.bones; mw = self.ob.matrix_world
        root = mw @ P[f"CTRL-{PART}.Rotation"].matrix
        n = root.to_3x3().col[1].normalized()
        depth = lambda k: ((mw @ P[f"STR-{PART}.{k:03d}"].matrix).translation - root.translation).dot(n)
        self.assertAlmostEqual(depth(0), 0.0, places=5)
        self.assertAlmostEqual(depth(N_SAMPLES - 1), 0.05, places=5)
        self.assertAlmostEqual(depth(6), 0.025, places=5)
        chain.layer_depth = 0.0
        bpy.context.view_layer.update()
        self.assertAlmostEqual(depth(N_SAMPLES - 1), 0.0, places=5)

    def test_rig_type_enum_keeps_saved_indices(self):
        items = [i.identifier for i in bpy.types.Object.bl_rna.properties["gesturebone_props"]
                 .fixed_type.properties["rig_type"].enum_items]
        self.assertEqual(items[:4], ['PLOTTING', 'GESTURE', 'PRESET', 'NONE'])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(TestCurveChain))
    sys.exit(0 if result.wasSuccessful() else 1)
