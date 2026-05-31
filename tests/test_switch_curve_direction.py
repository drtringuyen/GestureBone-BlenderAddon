"""
test_switch_curve_direction.py
==============================
Tests for gesturebone.switch_curve_direction operator and the
_switch_spline_direction() helper it uses internally.

Run from Blender's Text Editor or:
    blender --background <file.blend> --python tests/test_switch_curve_direction.py
"""

import bpy
import sys
import math

# ── helpers ────────────────────────────────────────────────────────────────────

_PASS = "\033[92mPASS\033[0m"
_FAIL = "\033[91mFAIL\033[0m"
_results = []


def _assert(condition, test_name, detail=""):
    tag = _PASS if condition else _FAIL
    msg = f"  [{tag}]  {test_name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    _results.append(condition)
    return condition


def _import_helper():
    from GestureBone.modules.gesture_draw.operators_common import _switch_spline_direction
    return _switch_spline_direction


def _make_bezier_curve(name, coords):
    """Create a BEZIER curve object with one spline from a list of (x,y,z) coords."""
    curve_data = bpy.data.curves.new(name, type='CURVE')
    curve_data.dimensions = '3D'
    spline = curve_data.splines.new('BEZIER')
    spline.bezier_points.add(len(coords) - 1)
    for i, (x, y, z) in enumerate(coords):
        p = spline.bezier_points[i]
        p.co            = (x, y, z)
        p.handle_left   = (x - 0.5, y, z)
        p.handle_right  = (x + 0.5, y, z)
        p.handle_left_type  = 'FREE'
        p.handle_right_type = 'FREE'
    obj = bpy.data.objects.new(name, curve_data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _make_poly_curve(name, coords):
    """Create a POLY curve object with one spline."""
    curve_data = bpy.data.curves.new(name, type='CURVE')
    curve_data.dimensions = '3D'
    spline = curve_data.splines.new('POLY')
    spline.points.add(len(coords) - 1)
    for i, (x, y, z) in enumerate(coords):
        spline.points[i].co = (x, y, z, 1.0)
    obj = bpy.data.objects.new(name, curve_data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _cleanup(*objects):
    for obj in objects:
        if obj and obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)


def _get_mod_props(arm):
    return getattr(arm, 'gesturebone_gesture_draw_props', None)


# ── TC-01: bezier points are reversed ─────────────────────────────────────────

def test_01_bezier_points_reversed():
    fn    = _import_helper()
    coords = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)]
    obj   = _make_bezier_curve("_test_bezier_rev", coords)
    try:
        fn(obj)
        pts = obj.data.splines[0].bezier_points
        xs  = [round(p.co.x, 4) for p in pts]
        expected = [3.0, 2.0, 1.0, 0.0]
        _assert(xs == expected, "TC-01  Bezier points reversed in order",
                f"got {xs}")
    finally:
        _cleanup(obj)


# ── TC-02: bezier handles are swapped left↔right ──────────────────────────────

def test_02_bezier_handles_swapped():
    fn = _import_helper()
    curve_data = bpy.data.curves.new("_test_bezier_hdl", type='CURVE')
    spline     = curve_data.splines.new('BEZIER')
    spline.bezier_points.add(1)

    p0 = spline.bezier_points[0]
    p0.co             = (0, 0, 0)
    p0.handle_left    = (-1, 0, 0)   # distinct values
    p0.handle_right   = (1,  0, 0)
    p0.handle_left_type  = 'VECTOR'
    p0.handle_right_type = 'FREE'

    p1 = spline.bezier_points[1]
    p1.co             = (4, 0, 0)
    p1.handle_left    = (3, 0, 0)
    p1.handle_right   = (5, 0, 0)
    p1.handle_left_type  = 'AUTO'
    p1.handle_right_type = 'ALIGNED'

    obj = bpy.data.objects.new("_test_bezier_hdl", curve_data)
    bpy.context.scene.collection.objects.link(obj)
    try:
        fn(obj)
        pts = obj.data.splines[0].bezier_points
        # After reversal: old p1 is now index 0, old p0 is now index 1
        # And left/right handles are swapped per point
        new_p0 = pts[0]
        _assert(
            round(new_p0.co.x, 4) == 4.0,
            "TC-02a  After reverse: first point is old last point",
            f"co.x={new_p0.co.x}",
        )
        _assert(
            round(new_p0.handle_left.x,  4) == 5.0 and
            round(new_p0.handle_right.x, 4) == 3.0,
            "TC-02b  Handles swapped left↔right after reverse",
            f"hl={new_p0.handle_left.x} hr={new_p0.handle_right.x}",
        )
        _assert(
            new_p0.handle_left_type  == 'ALIGNED' and
            new_p0.handle_right_type == 'AUTO',
            "TC-02c  Handle types swapped after reverse",
            f"ht_l={new_p0.handle_left_type} ht_r={new_p0.handle_right_type}",
        )
    finally:
        _cleanup(obj)


# ── TC-03: double-reverse restores original order ─────────────────────────────

def test_03_double_reverse_identity():
    fn     = _import_helper()
    coords = [(0, 0, 0), (1, 1, 0), (2, 0, 0)]
    obj    = _make_bezier_curve("_test_bezier_dbl", coords)
    try:
        before = [obj.data.splines[0].bezier_points[i].co.copy() for i in range(3)]
        fn(obj)
        fn(obj)
        after  = [obj.data.splines[0].bezier_points[i].co.copy() for i in range(3)]
        match  = all((b - a).length < 1e-5 for b, a in zip(before, after))
        _assert(match, "TC-03  Double-reverse restores original point order")
    finally:
        _cleanup(obj)


# ── TC-04: poly curve reversed ────────────────────────────────────────────────

def test_04_poly_curve_reversed():
    fn     = _import_helper()
    coords = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
    obj    = _make_poly_curve("_test_poly_rev", coords)
    try:
        fn(obj)
        xs = [round(obj.data.splines[0].points[i].co.x, 4) for i in range(3)]
        _assert(xs == [2.0, 1.0, 0.0], "TC-04  POLY spline points reversed", f"got {xs}")
    finally:
        _cleanup(obj)


# ── TC-05: object not in view layer — no crash ────────────────────────────────

def test_05_works_outside_view_layer():
    """Helper must not crash on objects excluded from the view layer."""
    fn          = _import_helper()
    hidden_coll = bpy.data.collections.new("_test_hidden_coll")
    # Do NOT link to scene — so it is outside the view layer
    curve_data  = bpy.data.curves.new("_test_hidden_curve", type='CURVE')
    spline      = curve_data.splines.new('BEZIER')
    spline.bezier_points.add(1)
    spline.bezier_points[0].co = (0, 0, 0)
    spline.bezier_points[1].co = (1, 0, 0)
    obj = bpy.data.objects.new("_test_hidden_obj", curve_data)
    hidden_coll.objects.link(obj)   # NOT in scene.collection → not in view layer
    try:
        raised = False
        try:
            fn(obj)
        except Exception as e:
            raised = True
            print(f"    exception: {e}")
        _assert(not raised, "TC-05  No crash when object is outside the view layer")
        xs = [round(p.co.x, 4) for p in obj.data.splines[0].bezier_points]
        _assert(xs == [1.0, 0.0], "TC-05b  Points still reversed correctly", f"got {xs}")
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(hidden_coll)


# ── TC-06: operator cancel when no spline assigned ────────────────────────────

def test_06_operator_cancel_no_spline():
    """Operator must return CANCELLED and report a warning when the chain has no spline."""
    arm = bpy.context.scene.gesturebone_props.current_armature
    mod = _get_mod_props(arm)
    if not mod or not mod.chains:
        print("  [SKIP] No chains available — run Load Chain first")
        return

    # Find a chain without a gesture spline, or temporarily clear one
    chain_idx = None
    original_spline = None
    for i, chain in enumerate(mod.chains):
        if chain.part_gesture_spline is None:
            chain_idx = i
            break

    if chain_idx is None:
        # Temporarily clear first chain's spline
        chain_idx      = 0
        original_spline = mod.chains[0].part_gesture_spline
        mod.chains[0].part_gesture_spline = None

    try:
        result = bpy.ops.gesturebone.switch_curve_direction(chain_index=chain_idx)
        _assert('CANCELLED' in result,
                "TC-06  Operator returns CANCELLED when no spline assigned",
                f"result={result}")
    finally:
        if original_spline is not None:
            mod.chains[0].part_gesture_spline = original_spline


# ── TC-07: operator cancel on out-of-range index ─────────────────────────────

def test_07_operator_cancel_bad_index():
    result = bpy.ops.gesturebone.switch_curve_direction(chain_index=9999)
    _assert('CANCELLED' in result,
            "TC-07  Operator returns CANCELLED for out-of-range chain_index",
            f"result={result}")


# ── TC-08: operator succeeds on a live chain ──────────────────────────────────

def test_08_operator_live_chain():
    """End-to-end: operator on a chain with a real gesture spline must return FINISHED."""
    arm = bpy.context.scene.gesturebone_props.current_armature
    mod = _get_mod_props(arm)
    if not mod:
        print("  [SKIP] No armature / mod_props")
        return

    chain_idx = next(
        (i for i, c in enumerate(mod.chains) if c.part_gesture_spline is not None),
        None,
    )
    if chain_idx is None:
        print("  [SKIP] No chain has a gesture spline assigned")
        return

    spline = mod.chains[chain_idx].part_gesture_spline
    before = [p.co.copy() for p in spline.data.splines[0].bezier_points] \
             if spline.data.splines and spline.data.splines[0].type == 'BEZIER' else None

    result = bpy.ops.gesturebone.switch_curve_direction(chain_index=chain_idx)
    _assert('FINISHED' in result,
            "TC-08  Operator returns FINISHED on a live chain",
            f"result={result}")

    if before and len(before) >= 2:
        after_x0 = spline.data.splines[0].bezier_points[0].co.x
        _assert(
            abs(after_x0 - before[-1].x) < 1e-4,
            "TC-08b  First point after switch matches last point before switch",
            f"after[0].x={after_x0:.4f}  before[-1].x={before[-1].x:.4f}",
        )

    # Undo and verify restoration
    bpy.ops.ed.undo()
    if before:
        restored_x0 = spline.data.splines[0].bezier_points[0].co.x
        _assert(
            abs(restored_x0 - before[0].x) < 1e-4,
            "TC-08c  Undo restores original first point",
            f"restored[0].x={restored_x0:.4f}  original[0].x={before[0].x:.4f}",
        )


# ── runner ─────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 60)
    print("  GestureBone: Switch Curve Direction — Test Suite")
    print("=" * 60)

    test_01_bezier_points_reversed()
    test_02_bezier_handles_swapped()
    test_03_double_reverse_identity()
    test_04_poly_curve_reversed()
    test_05_works_outside_view_layer()
    test_06_operator_cancel_no_spline()
    test_07_operator_cancel_bad_index()
    test_08_operator_live_chain()

    passed = sum(_results)
    total  = len(_results)
    print("=" * 60)
    print(f"  Result: {passed}/{total} passed")
    print("=" * 60 + "\n")

    if passed < total:
        sys.exit(1)


run()
