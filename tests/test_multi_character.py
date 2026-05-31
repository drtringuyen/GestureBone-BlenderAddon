"""
tests/test_multi_character.py — Tests that multiple characters are fully isolated.
"""
import unittest
import bpy


def _make_char(name, bone_names):
    """Create a PLOTTING rig + matching GESTURE rig for a character."""
    bpy.ops.object.armature_add()
    plotting = bpy.context.active_object
    plotting.name = name
    props = plotting.gesturebone_props
    props.rig_type        = 'PLOTTING'
    props.meta_collection = "META"

    bpy.ops.object.mode_set(mode='EDIT')
    for i, bname in enumerate(bone_names):
        if i == 0:
            plotting.data.edit_bones[0].name = bname
        else:
            eb = plotting.data.edit_bones.new(bname)
            eb.head = (0, i, 0)
            eb.tail = (0, i + 1, 0)
    bpy.ops.object.mode_set(mode='OBJECT')

    bc = plotting.data.collections.new("META")
    for bname in bone_names:
        bc.assign(plotting.data.bones[bname])

    bpy.context.view_layer.objects.active = plotting
    bpy.ops.gesturebone.sync_chains_from_meta_bones()

    # Make gesture rig
    bpy.ops.object.armature_add()
    gesture = bpy.context.active_object
    gesture.name = f"{name}.Gesture"
    gesture.gesturebone_props.rig_type    = 'GESTURE'
    gesture.gesturebone_props.plotting_rig = plotting

    for chain in plotting.gesturebone_props.chains:
        chain.gesture_rig = gesture

    return plotting, gesture


class TestMultiCharacter(unittest.TestCase):

    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)

    def test_three_characters_isolated(self):
        """CHR_LittlePig, CHR_Fox, CHR_Tiger have fully independent chains."""
        pig_p,  pig_g  = _make_char("CHR_LittlePig", ["Body", "Arm.L", "Tail"])
        fox_p,  fox_g  = _make_char("CHR_Fox",        ["Spine", "Ear.L"])
        tiger_p, tiger_g = _make_char("CHR_Tiger",    ["Hip", "Shoulder", "Neck"])

        self.assertEqual(len(pig_p.gesturebone_props.chains),   3)
        self.assertEqual(len(fox_p.gesturebone_props.chains),   2)
        self.assertEqual(len(tiger_p.gesturebone_props.chains), 3)

        pig_names   = [c.part_name for c in pig_p.gesturebone_props.chains]
        fox_names   = [c.part_name for c in fox_p.gesturebone_props.chains]
        tiger_names = [c.part_name for c in tiger_p.gesturebone_props.chains]

        self.assertIn("Body",  pig_names)
        self.assertIn("Spine", fox_names)
        self.assertIn("Hip",   tiger_names)

        # No bleed: fox has no Pig chains
        self.assertNotIn("Body",  fox_names)
        self.assertNotIn("Spine", pig_names)

    def test_gesture_rig_reads_correct_chains(self):
        """Selecting CHR_Fox.Gesture only shows Fox chains, not Pig chains."""
        from addons.GestureBone.modules.shared.utils import _chains_for_gesture_rig

        pig_p,  pig_g  = _make_char("CHR_LittlePig", ["Body", "Arm.L"])
        fox_p,  fox_g  = _make_char("CHR_Fox",        ["Spine", "Ear.L"])

        fox_chains = _chains_for_gesture_rig(fox_g)
        fox_names  = [c.part_name for c in fox_chains]

        self.assertIn("Spine", fox_names)
        self.assertIn("Ear.L", fox_names)
        self.assertNotIn("Body",  fox_names)
        self.assertNotIn("Arm.L", fox_names)

    def test_switch_armature_from_gesture_context(self):
        """SwitchArmature with a PLOTTING arm present does not crash."""
        pig_p, pig_g = _make_char("CHR_LittlePig", ["Body"])
        pig_p.gesturebone_props.gesture_active = True

        bpy.context.view_layer.objects.active = pig_p
        # Should finish (may report error if gesture arm not found — that's OK for this test)
        result = bpy.ops.gesturebone.switch_armature()
        self.assertIn(result.pop(), {'FINISHED', 'CANCELLED'})
