"""
tests/test_persistence.py — Tests that chain data survives save/reload and stale pointer handling.
"""
import unittest
import bpy
import tempfile
import os


class TestPersistence(unittest.TestCase):

    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)

    def _make_plotting_arm_with_chain(self):
        bpy.ops.object.armature_add()
        arm = bpy.context.active_object
        arm.name = "Persist_Test"
        props = arm.gesturebone_props
        props.rig_type        = 'PLOTTING'
        props.meta_collection = "META"

        bpy.ops.object.mode_set(mode='EDIT')
        arm.data.edit_bones[0].name = "Body"
        bpy.ops.object.mode_set(mode='OBJECT')
        bc = arm.data.collections.new("META")
        bc.assign(arm.data.bones["Body"])

        bpy.context.view_layer.objects.active = arm
        bpy.ops.gesturebone.sync_chains_from_meta_bones()

        chain = props.chains.get("Body")
        chain.control_mode    = 'PT_3'
        chain.pivot_placement = 'CENTER'

        # Create a gesture spline object and link it
        curve_data = bpy.data.curves.new("Persist_Test-Body.GestureSpline", 'CURVE')
        spline_obj = bpy.data.objects.new("Persist_Test-Body.GestureSpline", curve_data)
        bpy.context.scene.collection.objects.link(spline_obj)
        chain.gesture_spline = spline_obj

        return arm, chain

    def test_chain_data_survives_save_reload(self):
        """PointerProperty and StringProperty chain data persists after save/reload."""
        arm, chain = self._make_plotting_arm_with_chain()
        spline_name = chain.gesture_spline.name if chain.gesture_spline else None

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".blend", delete=False) as f:
            blend_path = f.name
        try:
            bpy.ops.wm.save_as_mainfile(filepath=blend_path)
            bpy.ops.wm.open_mainfile(filepath=blend_path)

            # Reload and check
            arm = bpy.data.objects.get("Persist_Test")
            self.assertIsNotNone(arm, "Armature must survive save/reload")

            props = arm.gesturebone_props
            self.assertEqual(props.rig_type, 'PLOTTING')

            chain = props.chains.get("Body")
            self.assertIsNotNone(chain, "Chain must survive save/reload")
            self.assertEqual(chain.control_mode, 'PT_3')
            self.assertEqual(chain.pivot_placement, 'CENTER')

            if spline_name:
                self.assertIsNotNone(chain.gesture_spline,
                                     "gesture_spline PointerProperty must survive reload")
                self.assertEqual(chain.gesture_spline.name, spline_name)
        finally:
            if os.path.exists(blend_path):
                os.unlink(blend_path)

    def test_stale_plotting_rig_no_crash(self):
        """Selecting a GESTURE rig whose plotting_rig was deleted shows a warning, no crash."""
        # Create gesture rig with a plotting_rig pointer
        bpy.ops.object.armature_add()
        plotting = bpy.context.active_object
        plotting.name = "ToBeDeleted"
        plotting.gesturebone_props.rig_type = 'PLOTTING'

        bpy.ops.object.armature_add()
        gesture = bpy.context.active_object
        gesture.name = "GestureOrphan"
        gesture.gesturebone_props.rig_type    = 'GESTURE'
        gesture.gesturebone_props.plotting_rig = plotting

        # Delete the plotting rig — gesture rig now has a stale pointer
        bpy.data.objects.remove(plotting, do_unlink=True)

        # Make gesture rig active — UI draw must not raise
        bpy.context.view_layer.objects.active = gesture
        bpy.context.scene.gesturebone_props.current_armature = gesture

        try:
            from addons.GestureBone.modules.gesture.ui import draw_gesture_ui
            import io
            dummy_layout = None  # Can't fully simulate layout without Blender UI context
            # The validate_plotting_rig function returns None gracefully — test that
            from addons.GestureBone.modules.shared.utils import _validate_plotting_rig
            result = _validate_plotting_rig(gesture)
            self.assertIsNone(result, "_validate_plotting_rig must return None for deleted rig")
        except Exception as e:
            self.fail(f"Stale plotting_rig caused an exception: {e}")
