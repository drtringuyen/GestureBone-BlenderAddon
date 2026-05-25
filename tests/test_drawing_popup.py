"""
test_drawing_popup.py
=====================
Test cases for GESTUREBONE_OT_ConfirmExitDrawing popup behaviour.

Paste into Blender's Text Editor and press "Run Script", or run via:
    blender --background <file.blend> --python tests/test_drawing_popup.py

Each test prints PASS / FAIL and a short description.
The suite returns non-zero exit code if any test fails (useful in CI).
"""

import bpy
import sys

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


def _get_ops_bake():
    from GestureBone.modules.gesture_draw import operators_bake
    return operators_bake


def _current_arm():
    return bpy.context.scene.gesturebone_props.current_armature


def _mod_props(arm):
    return getattr(arm, 'gesturebone_gesture_draw_props', None) if arm else None


def _drawing_chains_on(arm):
    sdp = _mod_props(arm)
    if sdp is None:
        return []
    return [c for c in sdp.chains if c.is_drawing]


def _stale_drawing_anywhere():
    """Return list of (armature_name, chain_name) tuples where is_drawing=True
    but the armature is NOT the current_armature."""
    current = _current_arm()
    stale = []
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE' or obj is current:
            continue
        sdp = _mod_props(obj)
        if sdp is None:
            continue
        for c in sdp.chains:
            if c.is_drawing:
                stale.append((obj.name, c.part_name))
    return stale


def _force_object_mode():
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

# ── setup ──────────────────────────────────────────────────────────────────────

def _setup():
    """Ensure chains are loaded on CHR_LittlePig.Gesture before any test."""
    obs = bpy.data.objects
    gesture_arm = obs.get("CHR_LittlePig.Gesture")
    if gesture_arm is None:
        print("  [SKIP] CHR_LittlePig.Gesture not found — run 'Load Chain From Meta Rig' first")
        return False

    _force_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    gesture_arm.hide_set(False)
    gesture_arm.select_set(True)
    bpy.context.view_layer.objects.active = gesture_arm

    # Run Load Chain to set current_armature and clear stale flags
    bpy.ops.gesturebone.load_chains_from_meta_rig()

    # Ensure all chains are bound
    sdp = _mod_props(gesture_arm)
    for i in range(len(sdp.chains)):
        bpy.ops.gesturebone.create_bone_constraints(chain_index=i)

    _force_object_mode()
    return True


# ── TC-01: After load, no stale is_drawing on non-current armatures ────────────

def test_01_no_stale_drawing_after_load():
    stale = _stale_drawing_anywhere()
    _assert(
        len(stale) == 0,
        "TC-01  No stale is_drawing on non-current armatures after Load Chain",
        f"stale={stale}" if stale else "",
    )


# ── TC-02: Handler only watches current_armature ───────────────────────────────

def test_02_handler_ignores_non_current_armature():
    """Manually set is_drawing on a non-current armature and verify the handler
    does NOT set _exit_confirm_pending."""
    ob = _get_ops_bake()
    ob.reset_exit_confirm_pending()

    non_current = bpy.data.objects.get("CHR_LittlePig")  # MetaRig, not .Gesture
    if non_current is None:
        print("  [SKIP] CHR_LittlePig not found")
        return

    sdp = _mod_props(non_current)
    if sdp and len(sdp.chains) > 0:
        sdp.chains[0].is_drawing = True
        try:
            # Simulate one handler call
            ob._check_drawing_state(bpy.context.scene, None)
            _assert(
                not ob._exit_confirm_pending,
                "TC-02  Handler ignores is_drawing on non-current armature",
            )
        finally:
            sdp.chains[0].is_drawing = False
    else:
        print("  [SKIP] CHR_LittlePig has no chains")


# ── TC-03: Handler triggers when current armature's spline exits edit ──────────

def test_03_handler_fires_for_current_armature():
    """Set is_drawing=True on a chain of current_armature; active object is NOT
    the spline → handler should set _exit_confirm_pending=True."""
    ob = _get_ops_bake()
    ob.reset_exit_confirm_pending()

    arm = _current_arm()
    sdp = _mod_props(arm)
    if not sdp or not sdp.chains:
        print("  [SKIP] No chains on current armature")
        return

    chain = sdp.chains[0]
    original_drawing = chain.is_drawing
    chain.is_drawing = True

    # Active object is NOT the gesture spline → simulates unexpected mode exit
    _force_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm

    try:
        ob._check_drawing_state(bpy.context.scene, None)
        _assert(
            ob._exit_confirm_pending,
            "TC-03  Handler fires when current armature chain exits edit mode",
        )
    finally:
        chain.is_drawing = original_drawing
        ob.reset_exit_confirm_pending()


# ── TC-04: Handler does NOT fire when spline IS in edit mode ───────────────────

def test_04_handler_silent_when_in_edit():
    """If the gesture spline IS the active object in EDIT_CURVE, handler stays silent.

    Note: is_drawing must be set AFTER entering edit mode (mirroring _enter_spline_edit_mode).
    Setting it before a mode_set would let the handler fire during the mode transition
    when the spline is not yet in edit — that's expected behaviour, not a bug.
    """
    ob = _get_ops_bake()

    arm = _current_arm()
    sdp = _mod_props(arm)
    if not sdp or not sdp.chains:
        print("  [SKIP] No chains on current armature")
        return

    chain = sdp.chains[0]
    spline = chain.part_gesture_spline
    if spline is None:
        print("  [SKIP] Chain has no gesture spline")
        return

    # Enter edit mode FIRST, then set is_drawing (mirrors real operator order)
    _force_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    spline.hide_set(False)
    spline.select_set(True)
    bpy.context.view_layer.objects.active = spline
    bpy.ops.object.mode_set(mode='EDIT')

    original_drawing = chain.is_drawing
    chain.is_drawing = True
    ob.reset_exit_confirm_pending()  # clear any trigger from the mode_set above

    try:
        ob._check_drawing_state(bpy.context.scene, None)
        _assert(
            not ob._exit_confirm_pending,
            "TC-04  Handler stays silent when gesture spline is in edit mode",
        )
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        chain.is_drawing = original_drawing
        ob.reset_exit_confirm_pending()


# ── TC-05: clear_all_drawing_state() wipes everything ─────────────────────────

def test_05_clear_all_drawing_state():
    """clear_all_drawing_state() should reset is_drawing on every armature."""
    ob = _get_ops_bake()

    # Artificially set is_drawing on multiple armatures
    dirtied = []
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE':
            continue
        sdp = _mod_props(obj)
        if sdp and len(sdp.chains) > 0:
            sdp.chains[0].is_drawing = True
            dirtied.append(obj.name)

    ob.clear_all_drawing_state()

    still_drawing = []
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE':
            continue
        sdp = _mod_props(obj)
        if sdp:
            for c in sdp.chains:
                if c.is_drawing:
                    still_drawing.append(obj.name)

    _assert(
        len(still_drawing) == 0,
        "TC-05  clear_all_drawing_state() clears is_drawing on all armatures",
        f"still_drawing={still_drawing}" if still_drawing else f"cleared {len(dirtied)} armature(s)",
    )
    _assert(
        not ob._exit_confirm_pending,
        "TC-05b clear_all_drawing_state() also resets _exit_confirm_pending",
    )


# ── TC-06: popup does not loop after Stop Drawing ─────────────────────────────

def test_06_no_popup_loop_after_stop_drawing():
    """After ConfirmExitDrawing runs with action=STOP, is_drawing should be False
    and _exit_confirm_pending should remain False after another handler call."""
    ob = _get_ops_bake()
    ob.reset_exit_confirm_pending()

    arm = _current_arm()
    sdp = _mod_props(arm)
    if not sdp or not sdp.chains:
        print("  [SKIP] No chains on current armature")
        return

    chain = sdp.chains[0]
    chain.is_drawing    = True
    chain.drawing_frame = 1

    # Simulate Stop Drawing (set is_drawing=False as the operator does)
    chain.is_drawing    = False
    chain.drawing_frame = -1
    ob.reset_exit_confirm_pending()

    # Handler fires — should NOT trigger popup since is_drawing=False
    _force_object_mode()
    ob._check_drawing_state(bpy.context.scene, None)
    _assert(
        not ob._exit_confirm_pending,
        "TC-06  Handler stays silent after Stop Drawing resolves the chain",
    )


# ── TC-07: LoadChainsFromMetaRig clears stale is_drawing ──────────────────────

def test_07_load_chains_clears_stale():
    """After LoadChainsFromMetaRig, no armature should have is_drawing=True."""
    # Dirty a non-current armature
    non_current = bpy.data.objects.get("CHR_LittlePig")
    if non_current:
        sdp = _mod_props(non_current)
        if sdp and len(sdp.chains) > 0:
            sdp.chains[0].is_drawing = True

    # Run load (this calls clear_all_drawing_state internally)
    _force_object_mode()
    arm = bpy.data.objects.get("CHR_LittlePig.Gesture")
    if arm:
        bpy.ops.object.select_all(action='DESELECT')
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm

    bpy.ops.gesturebone.load_chains_from_meta_rig()

    stale = _stale_drawing_anywhere()
    _assert(
        len(stale) == 0,
        "TC-07  LoadChainsFromMetaRig wipes stale is_drawing on all armatures",
        f"stale={stale}" if stale else "",
    )


# ── runner ─────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 60)
    print("  GestureBone: Drawing Mode Interrupted — Test Suite")
    print("=" * 60)

    if not _setup():
        print("  Setup failed — aborting tests.")
        sys.exit(1)

    test_01_no_stale_drawing_after_load()
    test_02_handler_ignores_non_current_armature()
    test_03_handler_fires_for_current_armature()
    test_04_handler_silent_when_in_edit()
    test_05_clear_all_drawing_state()
    test_06_no_popup_loop_after_stop_drawing()
    test_07_load_chains_clears_stale()

    passed = sum(_results)
    total  = len(_results)
    print("=" * 60)
    print(f"  Result: {passed}/{total} passed")
    print("=" * 60 + "\n")

    if passed < total:
        sys.exit(1)


run()
