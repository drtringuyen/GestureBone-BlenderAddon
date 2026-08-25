"""
riglinking/operators.py — One-click localize + relink for linked/overridden rigs.

Workflow for using a GestureBone rig linked from another .blend:
    1. Link the rig collection and make a Library Override (standard Blender).
    2. Run this operator: it makes the *gesture* spline curves local & editable
       and repairs the addon's custom pointers (see relink.py).
    3. The load_post handler re-applies the relink on every reopen, so drawing
       keeps working after the file is closed.

The operator is idempotent: if the gesture splines are already local it only
relinks; running it twice does no harm.
"""
import bpy
from bpy.props import StringProperty
from . import relink


def _gesture_override_rigs():
    return [o for o in bpy.data.objects
            if o.type == 'ARMATURE'
            and o.gesturebone_props.rig_type == 'GESTURE'
            and o.override_library is not None]


def _target_rig(context):
    """The armature these action ops act on: the active armature, else the sole
    override gesture rig in the file."""
    obj = context.active_object
    if obj is not None and obj.type == 'ARMATURE':
        return obj
    rigs = _gesture_override_rigs()
    return rigs[0] if len(rigs) == 1 else None


def _linked_gesture_splines():
    """All linked curves referenced as a chain's gesture_spline via an override rig."""
    targets = set()
    for g in _gesture_override_rigs():
        pr = g.gesturebone_props.plotting_rig
        if pr is None:
            continue
        for chain in pr.gesturebone_props.chains:
            gs = chain.gesture_spline
            if gs is not None and gs.library is not None and relink._local_twin(gs) is None:
                targets.add(gs)
    return targets


class GESTUREBONE_OT_LocalizeForDrawing(bpy.types.Operator):
    bl_idname  = "gesturebone.localize_for_drawing"
    bl_label   = "Localize Gesture Splines for Drawing"
    bl_description = ("Make this linked rig's gesture spline curves local & editable, "
                      "then relink the addon so drawing works and survives reopening the file")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_gesture_override_rigs())

    def execute(self, context):
        made_local = 0
        for gs in list(_linked_gesture_splines()):
            # Prefer the ops path — it remaps existing users (bone constraints)
            # to the new local curve. Fall back to a datablock copy if the linked
            # object isn't present in the view layer to be selected.
            try:
                bpy.ops.object.select_all(action='DESELECT')
                gs.select_set(True)
                context.view_layer.objects.active = gs
                bpy.ops.object.make_local(type='SELECT_OBJECT_DATA')
                made_local += 1
            except (RuntimeError, ReferenceError):
                new_obj      = gs.copy()
                new_obj.data = gs.data.copy() if gs.data else None
                coll = gs.users_collection[0] if gs.users_collection else context.scene.collection
                try:
                    coll.objects.link(new_obj)
                except Exception:
                    context.scene.collection.objects.link(new_obj)
                made_local += 1

        changed = relink.relink_override_rigs()

        if made_local or changed:
            self.report({'INFO'},
                        f"Localized {made_local} spline(s), relinked {changed} pointer(s)")
        else:
            self.report({'INFO'}, "Nothing to localize — rig already set up for drawing")
        return {'FINISHED'}


class GESTUREBONE_OT_RelinkOverrides(bpy.types.Operator):
    bl_idname  = "gesturebone.relink_overrides"
    bl_label   = "Relink Override Pointers"
    bl_description = ("Repair addon pointers on overridden rigs (plotting rig / gesture rig / "
                      "spline) without changing which curves are local")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_gesture_override_rigs())

    def execute(self, context):
        changed = relink.relink_override_rigs()
        self.report({'INFO'}, f"Relinked {changed} pointer(s)")
        return {'FINISHED'}


class GESTUREBONE_OT_ClearLinkedAction(bpy.types.Operator):
    bl_idname  = "gesturebone.clear_linked_action"
    bl_label   = "Clear Linked Action"
    bl_description = "Remove the action currently assigned to this rig's animation (e.g. one linked in with the override)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = _target_rig(context)
        return (rig is not None and rig.animation_data is not None
                and rig.animation_data.action is not None)

    def execute(self, context):
        rig = _target_rig(context)
        if rig is None or rig.animation_data is None or rig.animation_data.action is None:
            self.report({'WARNING'}, "No action on the rig")
            return {'CANCELLED'}
        act        = rig.animation_data.action
        name       = act.name
        was_linked = act.library is not None or act.override_library is not None
        try:
            rig.animation_data.action = None
        except Exception as e:
            self.report({'ERROR'}, f"Could not clear action: {e}")
            return {'CANCELLED'}
        self.report({'INFO'},
                    f"Cleared {'linked ' if was_linked else ''}action '{name}' from '{rig.name}'")
        return {'FINISHED'}


class GESTUREBONE_OT_CreateAction(bpy.types.Operator):
    bl_idname  = "gesturebone.create_action"
    bl_label   = "Create Action"
    bl_description = ("Clear any action on the rig, then create a fresh action with a slot "
                      "named after the rig and bind the rig to it")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _target_rig(context) is not None

    def execute(self, context):
        rig = _target_rig(context)
        if rig is None:
            self.report({'ERROR'}, "No target rig — select an armature")
            return {'CANCELLED'}

        name = (context.scene.gesturebone_action_name or "").strip()
        if not name:
            self.report({'ERROR'}, "Enter an Action Name first")
            return {'CANCELLED'}

        # 1. clear any existing action
        rig.animation_data_create()
        try:
            rig.animation_data.action = None
        except Exception as e:
            self.report({'ERROR'}, f"Could not clear existing action: {e}")
            return {'CANCELLED'}

        # 2. new action with a slot named after the rig, bound to the rig
        act  = bpy.data.actions.new(name)
        slot = act.slots.new(id_type='OBJECT', name=rig.name)
        rig.animation_data.action      = act
        rig.animation_data.action_slot = slot

        self.report({'INFO'},
                    f"Created action '{act.name}' (slot '{slot.name_display}') on '{rig.name}'")
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_LocalizeForDrawing,
    GESTUREBONE_OT_RelinkOverrides,
    GESTUREBONE_OT_ClearLinkedAction,
    GESTUREBONE_OT_CreateAction,
]


def register():
    bpy.types.Scene.gesturebone_action_name = StringProperty(
        name="Action Name",
        description="Name for the action created by Create Action",
        default="Gesture",
    )
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.gesturebone_action_name
