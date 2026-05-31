"""
tests/test_plotting.py — Tests for the plotting module (rig creation, chain sync, AutoRig).
"""
import unittest
import bpy


def _make_preset_arm(name="TestPreset"):
    """Create a minimal armature tagged as PRESET."""
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.object.armature_add()
    arm = bpy.context.active_object
    arm.name = name
    arm.gesturebone_props.rig_type = 'PRESET'
    # Add META bone collection with one bone
    bc = arm.data.collections.new("META")
    for b in arm.data.bones:
        bc.assign(b)
    return arm


def _make_plotting_arm(name="TestPlotting"):
    """Create a minimal armature tagged as PLOTTING with a META bone."""
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.object.armature_add()
    arm = bpy.context.active_object
    arm.name = name
    props = arm.gesturebone_props
    props.rig_type        = 'PLOTTING'
    props.meta_collection = "META"
    # Add META bone collection with one bone
    bpy.ops.object.mode_set(mode='EDIT')
    # rename default bone
    eb = arm.data.edit_bones[0]
    eb.name = "Body"
    bpy.ops.object.mode_set(mode='OBJECT')
    bc = arm.data.collections.new("META")
    bc.assign(arm.data.bones["Body"])
    return arm


def _cleanup(*names):
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)


class TestPlotting(unittest.TestCase):

    def setUp(self):
        # Start with a clean scene
        bpy.ops.wm.read_homefile(use_empty=True)

    # ── Create Rig ────────────────────────────────────────────────────────────

    def test_create_rig_sets_plotting_type(self):
        """CreateRig tags the duplicated armature as PLOTTING."""
        preset = _make_preset_arm("Preset_A")
        bpy.context.view_layer.objects.active = preset

        result = bpy.ops.gesturebone.create_rig(new_rig_name="CHR_Test", rig_preset="Preset_A")
        self.assertIn('FINISHED', result)

        new_arm = bpy.data.objects.get("CHR_Test")
        self.assertIsNotNone(new_arm, "CreateRig should produce 'CHR_Test' armature")
        self.assertEqual(new_arm.gesturebone_props.rig_type, 'PLOTTING')

    # ── Sync Chains ───────────────────────────────────────────────────────────

    def test_sync_chains_matches_meta_bones(self):
        """SyncChainsFromMetaBones creates one chain per META bone."""
        arm = _make_plotting_arm("Rig_Sync")
        bpy.context.view_layer.objects.active = arm

        # Add two more bones to META
        bpy.ops.object.mode_set(mode='EDIT')
        for bname in ("Arm.L", "Leg.L"):
            eb = arm.data.edit_bones.new(bname)
            eb.head = (0, 0, 0)
            eb.tail = (0, 1, 0)
        bpy.ops.object.mode_set(mode='OBJECT')
        bc = arm.data.collections.get("META")
        for bname in ("Arm.L", "Leg.L"):
            bc.assign(arm.data.bones[bname])

        result = bpy.ops.gesturebone.sync_chains_from_meta_bones()
        self.assertIn('FINISHED', result)

        props = arm.gesturebone_props
        self.assertEqual(len(props.chains), 3)
        chain_names = [c.part_name for c in props.chains]
        self.assertIn("Body",  chain_names)
        self.assertIn("Arm.L", chain_names)
        self.assertIn("Leg.L", chain_names)

    def test_sync_removes_orphaned_chain(self):
        """Re-syncing after removing a META bone removes the orphaned chain."""
        arm = _make_plotting_arm("Rig_Orphan")
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.data.edit_bones.new("Arm.L")
        eb.head = (0, 0, 0)
        eb.tail = (0, 1, 0)
        bpy.ops.object.mode_set(mode='OBJECT')
        arm.data.collections.get("META").assign(arm.data.bones["Arm.L"])

        bpy.context.view_layer.objects.active = arm
        bpy.ops.gesturebone.sync_chains_from_meta_bones()
        self.assertEqual(len(arm.gesturebone_props.chains), 2)

        # Remove Arm.L from META
        bpy.ops.object.mode_set(mode='EDIT')
        arm.data.edit_bones.remove(arm.data.edit_bones["Arm.L"])
        bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.gesturebone.sync_chains_from_meta_bones()
        self.assertEqual(len(arm.gesturebone_props.chains), 1)
        self.assertEqual(arm.gesturebone_props.chains[0].part_name, "Body")

    def test_sync_preserves_existing_settings(self):
        """Re-syncing preserves existing chain settings for matching bones."""
        arm = _make_plotting_arm("Rig_Preserve")
        bpy.context.view_layer.objects.active = arm
        bpy.ops.gesturebone.sync_chains_from_meta_bones()

        # Change control mode on the chain
        arm.gesturebone_props.chains[0].control_mode = 'PT_3'

        bpy.ops.gesturebone.sync_chains_from_meta_bones()
        self.assertEqual(arm.gesturebone_props.chains[0].control_mode, 'PT_3',
                         "Existing chain settings must be preserved after re-sync")

    def test_rerig_resets_step_counter(self):
        """ReRigPart resets chain.rig_completed_step to 0."""
        arm = _make_plotting_arm("Rig_Rerig")
        bpy.context.view_layer.objects.active = arm
        bpy.ops.gesturebone.sync_chains_from_meta_bones()

        chain = arm.gesturebone_props.chains.get("Body")
        self.assertIsNotNone(chain)
        chain.rig_completed_step = 11  # simulate partially done

        bpy.ops.gesturebone.rerig_part(bone_name="Body")
        # After reset, step should be 0 (reset happens before re-run)
        # Note: RigPart may fail without a full scene — just check the reset
        self.assertEqual(chain.rig_completed_step, 0,
                         "ReRigPart must reset rig_completed_step to 0")

    def test_clear_rig_resets_chain_pointers(self):
        """ClearRig resets gesture_rig pointer and rig_completed_step on all chains."""
        arm = _make_plotting_arm("Rig_Clear")
        bpy.context.view_layer.objects.active = arm
        bpy.ops.gesturebone.sync_chains_from_meta_bones()

        # Simulate a completed rig
        chain = arm.gesturebone_props.chains.get("Body")
        chain.rig_completed_step = 14

        # Create a dummy gesture arm
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.armature_add()
        gesture_arm = bpy.context.active_object
        gesture_arm.name = "Rig_Clear.Gesture"
        gesture_arm.gesturebone_props.rig_type    = 'GESTURE'
        gesture_arm.gesturebone_props.plotting_rig = arm
        chain.gesture_rig = gesture_arm

        bpy.context.view_layer.objects.active = arm
        bpy.ops.gesturebone.clear_rig()

        self.assertIsNone(chain.gesture_rig)
        self.assertEqual(chain.rig_completed_step, 0)
