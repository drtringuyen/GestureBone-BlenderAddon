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


# ── Expression bones ───────────────────────────────────────────────────────────
# Lives here rather than in modules/expression_sheet/props.py on purpose: this
# is rig DATA, and `shared` is always registered while a module's own
# props.register() does `del bpy.types.Scene...` on toggle-off. A downstream
# file that links the rig with the Expression Sheet module disabled must not
# lose the registry.
#
# The exp_index VALUE deliberately does not live here — it stays a raw
# IDProperty on the pose bone (`pb["exp_index"]`), which is the data path every
# existing shader-node driver already reads, and the only form that is both
# freely keyable and drivable from other datablocks. This group holds only what
# the picker needs. See docs/expression-bones-design.md.

class GESTUREBONE_PG_ExpressionBone(bpy.types.PropertyGroup):
    """One registered expression bone: which sheet it picks from, and how that
    sheet is sliced for the picker."""

    # `name` is what makes expression_bones["EXP-Eye.L"] resolve; kept equal to
    # `bone` by the operators. `bone` is the one the code reads.
    name: StringProperty(override={'LIBRARY_OVERRIDABLE'})
    bone: StringProperty(
        name="Bone",
        description="Pose bone this entry drives (keyed by name — renaming the "
                    "bone orphans the entry until you re-sync)",
        override={'LIBRARY_OVERRIDABLE'},
    )
    sheet_image: PointerProperty(
        name="Sheet",
        description="Sprite sheet shown in this bone's picker grid",
        type=bpy.types.Image,
        override={'LIBRARY_OVERRIDABLE'},
    )
    grid_count: IntProperty(
        name="Grid Count",
        description="Cells per row/column on this bone's sheet. Picker only — "
                    "the material's own UV grid math must match it",
        default=4, min=2, max=8,
        override={'LIBRARY_OVERRIDABLE'},
    )
    grid_size: IntProperty(
        name="Cell Size",
        description="Pixel size of each picker cell. 0 = use the scene default",
        default=0, min=0, max=200,
        override={'LIBRARY_OVERRIDABLE'},
    )
    ui_expanded: BoolProperty(name="Expanded", default=False,
                              override={'LIBRARY_OVERRIDABLE'})


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
        override={'LIBRARY_OVERRIDABLE'},
    )

    # ── PLOTTING: chain list ───────────────────────────────────────────────────
    # LIBRARY_OVERRIDABLE + USE_INSERTION so chain pointers persist on overrides
    # (see modules/riglinking). The load_post relink handler is the safety net.
    chains: CollectionProperty(
        type=GESTUREBONE_PG_ChainDefinition,
        override={'LIBRARY_OVERRIDABLE', 'USE_INSERTION'},
    )
    active_chain_index: IntProperty(default=0, min=0, override={'LIBRARY_OVERRIDABLE'})

    # ── PLOTTING: global rig-gen settings ─────────────────────────────────────
    meta_collection: StringProperty(
        name="Meta Collection",
        default="META",
        description="Bone collection on this armature that contains the MetaBones",
        search=_bone_coll_search,
        override={'LIBRARY_OVERRIDABLE'},
    )
    atomic_chain: StringProperty(
        name="Global Template",
        description="Fallback atomic chain template used when a chain has no per-bone override",
        search=_collection_search,
        override={'LIBRARY_OVERRIDABLE'},
    )
    meta_rig_preset: StringProperty(
        name="Rig Preset",
        description="PRESET armature to duplicate when creating this rig (shown in Create Rig dialog)",
        override={'LIBRARY_OVERRIDABLE'},
    )

    # ── PLOTTING: workflow state ───────────────────────────────────────────────
    wip_coll:            StringProperty(options={'HIDDEN'}, override={'LIBRARY_OVERRIDABLE'})
    wip_empty:           StringProperty(options={'HIDDEN'}, override={'LIBRARY_OVERRIDABLE'})
    wip_token:           StringProperty(options={'HIDDEN'}, override={'LIBRARY_OVERRIDABLE'})
    last_step:           StringProperty(options={'HIDDEN'}, override={'LIBRARY_OVERRIDABLE'})
    completed_step:      IntProperty(default=0, options={'HIDDEN'}, override={'LIBRARY_OVERRIDABLE'})
    is_aligning:         BoolProperty(default=False, options={'HIDDEN'}, override={'LIBRARY_OVERRIDABLE'})
    active_bone_name:    StringProperty(options={'HIDDEN'},
                         description="Current MetaBone being processed — set by RigPart/AutoRig",
                         override={'LIBRARY_OVERRIDABLE'})

    # ── PLOTTING: UI toggles ───────────────────────────────────────────────────
    meta_solo_mode:     BoolProperty(name="META Solo",          default=False, override={'LIBRARY_OVERRIDABLE'})
    gesture_active:     BoolProperty(name="Gesture Active",     default=False, override={'LIBRARY_OVERRIDABLE'})
    show_both_armatures: BoolProperty(name="Show Both",         default=True, override={'LIBRARY_OVERRIDABLE'})
    show_generate_part: BoolProperty(name="Generate Part by Part", default=True, override={'LIBRARY_OVERRIDABLE'})
    show_debug_steps:   BoolProperty(name="Debug Steps",        default=False, override={'LIBRARY_OVERRIDABLE'})

    # ── EXPRESSION SHEET: per-bone sprite sheets ──────────────────────────────
    # USE_INSERTION so a downstream file can register NEW expression bones on
    # an override, not just edit the ones the library shipped.
    expression_bones: CollectionProperty(
        type=GESTUREBONE_PG_ExpressionBone,
        override={'LIBRARY_OVERRIDABLE', 'USE_INSERTION'},
    )
    active_expression_index: IntProperty(default=0, min=0,
                                         override={'LIBRARY_OVERRIDABLE'})

    # ── GESTURE: back-pointer to the PLOTTING rig ─────────────────────────────
    plotting_rig: PointerProperty(
        name="Plotting Rig",
        type=bpy.types.Object,
        description="The PLOTTING (MetaRig) armature this GESTURE rig was generated from",
        override={'LIBRARY_OVERRIDABLE'},
    )


def register():
    bpy.utils.register_class(GESTUREBONE_PG_ExpressionBone)
    bpy.utils.register_class(GESTUREBONE_PG_ArmatureProps)
    bpy.types.Object.gesturebone_props = PointerProperty(type=GESTUREBONE_PG_ArmatureProps)


def unregister():
    del bpy.types.Object.gesturebone_props
    bpy.utils.unregister_class(GESTUREBONE_PG_ArmatureProps)
    bpy.utils.unregister_class(GESTUREBONE_PG_ExpressionBone)
