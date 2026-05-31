"""
tests/test_gesture.py — Tests for the gesture module (bind, draw, bake).
"""
import unittest
import bpy


def _make_scene():
    """Return (plotting_arm, gesture_arm, chain) for a minimal two-arm setup."""
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.object.armature_add()
    plotting_arm = bpy.context.active_object
    plotting_arm.name = "CHR_Test"
    props = plotting_arm.gesturebone_props
    props.rig_type        = 'PLOTTING'
    props.meta_collection = "META"

    # Add Body META bone
    bpy.ops.object.mode_set(mode='EDIT')
    eb = plotting_arm.data.edit_bones[0]
    eb.name = "Body"
    bpy.ops.object.mode_set(mode='OBJECT')
    bc = plotting_arm.data.collections.new("META")
    bc.assign(plotting_arm.data.bones["Body"])
    bpy.ops.gesturebone.sync_chains_from_meta_bones()

    # Create a minimal GESTURE rig with CTRL bones
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.object.armature_add()
    gesture_arm = bpy.context.active_object
    gesture_arm.name = "CHR_Test.Gesture"
    gesture_arm.gesturebone_props.rig_type    = 'GESTURE'
    gesture_arm.gesturebone_props.plotting_rig = plotting_arm

    bpy.ops.object.mode_set(mode='EDIT')
    for i in range(5):
        eb = gesture_arm.data.edit_bones.new(f"CTRL-Body_{i}")
        eb.head = (0, i * 0.2, 0)
        eb.tail = (0, i * 0.2 + 0.1, 0)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Link chain to gesture rig
    chain = plotting_arm.gesturebone_props.chains.get("Body")
    chain.gesture_rig = gesture_arm

    return plotting_arm, gesture_arm, chain


class TestGesture(unittest.TestCase):

    def setUp(self):
        self.plotting_arm, self.gesture_arm, self.chain = _make_scene()

    # ── Load Chains ───────────────────────────────────────────────────────────

    def test_load_chains_links_splines(self):
        """LoadChains creates and links the GestureSpline by canonical name."""
        bpy.context.view_layer.objects.active = self.gesture_arm
        result = bpy.ops.gesturebone.load_chains()
        self.assertIn('FINISHED', result)
        chain = self.chain
        self.assertIsNotNone(chain.gesture_spline,
                             "LoadChains must link or create gesture_spline")
        expected_name = "CHR_Test-Body.GestureSpline"
        self.assertEqual(chain.gesture_spline.name, expected_name)

    def test_load_chains_populates_control_bones(self):
        """LoadChains fills control_bones list with CTRL bone names."""
        bpy.context.view_layer.objects.active = self.gesture_arm
        bpy.ops.gesturebone.load_chains()
        chain = self.chain
        filled = [e.bone for e in chain.control_bones if e.bone]
        self.assertEqual(len(filled), 5,
                         "PT_5 mode must populate 5 control bone entries")
        for name in filled:
            self.assertTrue(name.startswith("CTRL-Body_"))

    # ── Bind constraints ──────────────────────────────────────────────────────

    def test_bind_creates_constraints(self):
        """Bind creates a Gesture_copy constraint on each CTRL bone."""
        bpy.context.view_layer.objects.active = self.gesture_arm
        bpy.ops.gesturebone.load_chains()

        # Fill gesture_spline first
        chain = self.chain
        if not chain.gesture_spline:
            curve_data = bpy.data.curves.new("CHR_Test-Body.GestureSpline", 'CURVE')
            chain.gesture_spline = bpy.data.objects.new("CHR_Test-Body.GestureSpline", curve_data)
            bpy.context.scene.collection.objects.link(chain.gesture_spline)

        result = bpy.ops.gesturebone.create_bone_constraints(part_name="Body")
        self.assertIn('FINISHED', result)
        self.assertTrue(chain.is_bound)

        # Check each CTRL bone has the constraint
        for entry in chain.control_bones:
            if not entry.bone:
                continue
            pb = self.gesture_arm.pose.bones.get(entry.bone)
            self.assertIsNotNone(pb, f"Pose bone '{entry.bone}' must exist")
            has_con = any(c.name == "Gesture_copy" for c in pb.constraints)
            self.assertTrue(has_con, f"'{entry.bone}' must have Gesture_copy constraint")

    def test_bind_constraint_count_pt5(self):
        """PT_5 mode creates exactly 5 constraints."""
        bpy.context.view_layer.objects.active = self.gesture_arm
        bpy.ops.gesturebone.load_chains()
        chain = self.chain
        if not chain.gesture_spline:
            curve_data = bpy.data.curves.new("CHR_Test-Body.GestureSpline", 'CURVE')
            chain.gesture_spline = bpy.data.objects.new("CHR_Test-Body.GestureSpline", curve_data)
            bpy.context.scene.collection.objects.link(chain.gesture_spline)
        bpy.ops.gesturebone.create_bone_constraints(part_name="Body")
        count = sum(
            1 for e in chain.control_bones if e.bone and
            any(c.name == "Gesture_copy"
                for c in self.gesture_arm.pose.bones.get(e.bone, bpy.types.PoseBone()).constraints)
        )
        self.assertEqual(count, 5)

    def test_unbind_removes_constraints(self):
        """Unbind removes all Gesture_copy constraints."""
        bpy.context.view_layer.objects.active = self.gesture_arm
        bpy.ops.gesturebone.load_chains()
        chain = self.chain
        if not chain.gesture_spline:
            curve_data = bpy.data.curves.new("CHR_Test-Body.GestureSpline", 'CURVE')
            chain.gesture_spline = bpy.data.objects.new("CHR_Test-Body.GestureSpline", curve_data)
            bpy.context.scene.collection.objects.link(chain.gesture_spline)
        bpy.ops.gesturebone.create_bone_constraints(part_name="Body")
        bpy.ops.gesturebone.delete_bone_constraints(part_name="Body")
        self.assertFalse(chain.is_bound)
        for entry in chain.control_bones:
            if not entry.bone:
                continue
            pb = self.gesture_arm.pose.bones.get(entry.bone)
            if pb:
                has_con = any(c.name == "Gesture_copy" for c in pb.constraints)
                self.assertFalse(has_con, f"'{entry.bone}' must have no Gesture_copy after unbind")
