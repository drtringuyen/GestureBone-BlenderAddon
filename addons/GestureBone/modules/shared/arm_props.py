"""
shared/arm_props.py — ArmatureProps PropertyGroup registered on every Object.
Replaces both gesturebone_gesture_draw_props and gesturebone_rig_generation_props.
"""
import bpy
from bpy.props import (
    BoolProperty, StringProperty, IntProperty,
    EnumProperty, PointerProperty, CollectionProperty,
)
from .chain import GESTUREBONE_PG_ChainDefinition


# ── Search callbacks ───────────────────────────────────────────────────────────

def _collection_search(self, context, edit_text):
    tagged = [c.name for c in bpy.data.collections if "gesturebone_template" in c]
    pool   = tagged if tagged else [c.name for c in bpy.data.collections]
    if not edit_text:
        return pool
    lo = edit_text.lower()
    return [n for n in pool if lo in n.lower()]


def _bone_coll_search(self, context, edit_text):
    """Search bone collections in THIS armature."""
    obj = context.active_object if context else None
    if not obj or obj.type != 'ARMATURE':
        return []
    return [bc.name for bc in obj.data.collections if edit_text.lower() in bc.name.lower()]


# ── Property group ─────────────────────────────────────────────────────────────

class GESTUREBONE_PG_ArmatureProps(bpy.types.PropertyGroup):
    """Per-armature properties. rig_type drives which UI and operators apply."""

    rig_type: EnumProperty(
        name="Rig Type",
        items=[
            ('PLOTTING', "Plotting Rig",
             "MetaRig — contains META bones, runs rig generation, owns chain definitions"),
            ('GESTURE',  "Gesture Rig",
             "Control rig — contains CTRL bones, used for gesture drawing and binding"),
            ('PRESET',   "Rig Preset",
             "Template armature — appears in Create Rig dropdown"),
            ('NONE',     "Untagged", ""),
        ],
        default='NONE',
    )

    # ── PLOTTING: chain list ───────────────────────────────────────────────────
    # LIBRARY_OVERRIDABLE + USE_INSERTION so chain pointers persist on overrides
    # (see modules/riglinking). The load_post relink handler is the safety net.
    chains: CollectionProperty(
        type=GESTUREBONE_PG_ChainDefinition,
        override={'LIBRARY_OVERRIDABLE', 'USE_INSERTION'},
    )
    active_chain_index: IntProperty(default=0, min=0)

    # ── PLOTTING: global rig-gen settings ─────────────────────────────────────
    meta_collection: StringProperty(
        name="Meta Collection",
        default="META",
        description="Bone collection on this armature that contains the MetaBones",
        search=_bone_coll_search,
    )
    atomic_chain: StringProperty(
        name="Global Template",
        description="Fallback atomic chain template used when a chain has no per-bone override",
        search=_collection_search,
    )
    meta_rig_preset: StringProperty(
        name="Rig Preset",
        description="PRESET armature to duplicate when creating this rig (shown in Create Rig dialog)",
    )

    # ── PLOTTING: workflow state ───────────────────────────────────────────────
    wip_coll:            StringProperty(options={'HIDDEN'})
    wip_empty:           StringProperty(options={'HIDDEN'})
    wip_token:           StringProperty(options={'HIDDEN'})
    last_step:           StringProperty(options={'HIDDEN'})
    completed_step:      IntProperty(default=0, options={'HIDDEN'})
    is_aligning:         BoolProperty(default=False, options={'HIDDEN'})
    active_bone_name:    StringProperty(options={'HIDDEN'},
                         description="Current MetaBone being processed — set by RigPart/AutoRig")

    # ── PLOTTING: UI toggles ───────────────────────────────────────────────────
    meta_solo_mode:     BoolProperty(name="META Solo",          default=False)
    gesture_active:     BoolProperty(name="Gesture Active",     default=False)
    show_both_armatures: BoolProperty(name="Show Both",         default=True)
    show_generate_part: BoolProperty(name="Generate Part by Part", default=True)
    show_debug_steps:   BoolProperty(name="Debug Steps",        default=False)

    # ── GESTURE: back-pointer to the PLOTTING rig ─────────────────────────────
    plotting_rig: PointerProperty(
        name="Plotting Rig",
        type=bpy.types.Object,
        description="The PLOTTING (MetaRig) armature this GESTURE rig was generated from",
        override={'LIBRARY_OVERRIDABLE'},
    )


def register():
    bpy.utils.register_class(GESTUREBONE_PG_ArmatureProps)
    bpy.types.Object.gesturebone_props = PointerProperty(type=GESTUREBONE_PG_ArmatureProps)


def unregister():
    del bpy.types.Object.gesturebone_props
    bpy.utils.unregister_class(GESTUREBONE_PG_ArmatureProps)
