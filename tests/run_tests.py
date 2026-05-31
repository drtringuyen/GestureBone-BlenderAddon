"""
tests/run_tests.py — Blender-aware test runner.
Run from Blender's Script Editor or via: blender --background --python tests/run_tests.py
"""
import unittest
import sys
import os


def run():
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    tests_dir = os.path.dirname(__file__)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)

    from test_plotting       import TestPlotting
    from test_gesture        import TestGesture
    from test_multi_character import TestMultiCharacter
    from test_persistence    import TestPersistence

    for cls in (TestPlotting, TestGesture, TestMultiCharacter, TestPersistence):
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


# Allow running via: blender --background --python tests/run_tests.py
if __name__ == "__main__":
    import bpy
    # Register addon first if not yet registered
    try:
        bpy.ops.preferences.addon_enable(module="GestureBone")
    except Exception:
        pass
    # Defer run until after Blender is fully loaded
    bpy.app.timers.register(lambda: (run(), None)[1], first_interval=0.5)
