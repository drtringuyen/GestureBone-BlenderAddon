import bpy
from bpy.props import (
    BoolProperty, StringProperty, IntProperty,
    EnumProperty, PointerProperty, CollectionProperty, FloatProperty,
)
from .utils import _bones_in_bone_coll

# ── Control Mode constants (shared with ops_actions) ──────────────────────────

CONTROL_MODES = [
    ('PT_5', "5 Points", "5 control points"),
    ('PT_3', "3 Points", "3 control points"),
    ('PT_2', "2 Points", "2 control points"),
]
# Blender GN integer value for "Control MODE" socket (matches screenshot dropdown order)
CONTROL_MODE_GN_INT = {'PT_5': 0, 'PT_3': 1, 'PT_2': 2}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_bone_settings(props, bone_name):
    """Return (or create) the MetaBoneSettings entry for bone_name."""
    entry = props.bone_settings.get(bone_name)
    if entry is None:
        entry = props.bone_settings.add()
        entry.name = bone_name
    return entry


# ── Dynamic enum / search callbacks ──────────────────────────────────────────

def _collection_items(self, context):
    if not context:
        return [('NONE', '(no context)', '')]
    items = [(c.name, c.name, '') for c in bpy.data.collections]
    return items if items else [('NONE', 'No collections found', '')]


def _bone_template_items(self, context):
    """Per-bone template dropdown — first item is a 'use global' sentinel."""
    items = [('NONE', '(Default Template)', 'Fall back to the global Registration template')]
    if context:
        items += [(c.name, c.name, '') for c in bpy.data.collections]
    return items


def _armature_name_search(self, context, edit_text):
    all_arms = [o.name for o in bpy.data.objects if o.type == 'ARMATURE']
    if not edit_text or edit_text == self.meta_rig:
        return all_arms
    lo = edit_text.lower()
    return [n for n in all_arms if lo in n.lower()]


def _bone_coll_name_search(self, context, edit_text):
    arm = bpy.data.objects.get(self.meta_rig)
    if not arm or arm.type != 'ARMATURE':
        return []
    all_colls = [bc.name for bc in arm.data.collections]
    if not edit_text or edit_text == self.meta_collection:
        return all_colls
    lo = edit_text.lower()
    return [n for n in all_colls if lo in n.lower()]


def _metabone_items(self, context):
    if not context:
        return [('NONE', '(no context)', '')]
    props = context.scene.gesturebone_rig_generation_props
    arm = bpy.data.objects.get(props.meta_rig)
    if not arm or arm.type != 'ARMATURE':
        return [('NONE', 'MetaRig not found', '')]
    names = _bones_in_bone_coll(arm.data, props.meta_collection)
    return [(n, n, '') for n in names] if names else [('NONE', f'No bones in "{props.meta_collection}"', '')]


def _on_active_meta_bone_update(self, context):
    """Auto-create a MetaBoneSettings entry when a new bone is selected."""
    bone_name = self.active_meta_bone
    if not bone_name or bone_name == 'NONE':
        return
    if self.bone_settings.get(bone_name) is None:
        entry = self.bone_settings.add()
        entry.name = bone_name


# ── Property groups ───────────────────────────────────────────────────────────

def _on_bone_settings_control_mode_update(self, context):
    """Sync control_mode from rig_generation bone_settings → gesture_draw chain."""
    if context is None:
        return
    gp = getattr(getattr(context, 'scene', None), 'gesturebone_props', None)
    if gp is None:
        return
    arm = gp.current_armature
    if arm is None:
        return
    sdp = getattr(arm, 'gesturebone_gesture_draw_props', None)
    if sdp is None:
        return
    bone_name = self.name  # PropertyGroup name = bone key
    for chain in sdp.chains:
        if chain.part_name == bone_name and chain.part_control_mode != self.control_mode:
            chain.part_control_mode = self.control_mode
            break


class GESTUREBONE_PG_MetaBoneSettings(bpy.types.PropertyGroup):
    """Per-MetaBone settings stored by bone name (accessed via bone_settings.get(bone_name))."""
    # 'name' StringProperty is inherited from PropertyGroup — used as the bone_name key
    atomic_chain: EnumProperty(
        name="Template",
        description="Template collection for this bone. 'use global' falls back to the Registration template",
        items=_bone_template_items,
    )
    control_mode: EnumProperty(
        name="Control Mode",
        items=CONTROL_MODES,
        default='PT_5',
        update=_on_bone_settings_control_mode_update,
    )
    pivot_placement: EnumProperty(
        name="Pivot Placement",
        description="Where to place CTRL-<Bone>.Rotation and CTRL-<Bone>.Pivot after binding",
        items=[
            ('ORIGIN', "At Origin",
             "Keep Rotation/Pivot bones at their template position",
             'OBJECT_ORIGIN', 0),
            ('CENTER', "At Center",
             "Slide Rotation/Pivot bone heads to the MetaBone midpoint (keeps length & roll)",
             'SNAP_MIDPOINT', 1),
        ],
        default='ORIGIN',
    )


class GESTUREBONE_PG_RigGenerationProps(bpy.types.PropertyGroup):
    atomic_chain:     EnumProperty( name="Template",         items=_collection_items)
    meta_rig:         StringProperty(name="Meta Rig",        default="MetaRig",
                                     search=_armature_name_search)
    meta_collection:  StringProperty(name="Meta Collection", default="MetaCollection",
                                     search=_bone_coll_name_search)
    active_meta_bone: EnumProperty( name="Meta Bone",        items=_metabone_items,
                                    update=_on_active_meta_bone_update)
    wip_coll:         StringProperty(options={'HIDDEN'})
    wip_empty:        StringProperty(options={'HIDDEN'})
    wip_token:        StringProperty(options={'HIDDEN'})  # resolved template token for current pipeline run
    last_step:        StringProperty(options={'HIDDEN'})
    is_aligning:      BoolProperty( options={'HIDDEN'})
    completed_step:   IntProperty(  default=0, options={'HIDDEN'})
    # UI section toggles
    show_generate_part: BoolProperty(name="Generate Part by Part", default=True)
    show_debug_steps:   BoolProperty(name="Debug Step by Step",    default=False)
    # Per-bone settings keyed by bone name
    bone_settings: CollectionProperty(type=GESTUREBONE_PG_MetaBoneSettings)
    # META toggle state: True = META is soloed (only META visible), False = all visible
    meta_solo_mode: BoolProperty(name="META Solo", default=False)


def register():
    bpy.utils.register_class(GESTUREBONE_PG_MetaBoneSettings)
    bpy.utils.register_class(GESTUREBONE_PG_RigGenerationProps)
    bpy.types.Scene.gesturebone_rig_generation_props = PointerProperty(type=GESTUREBONE_PG_RigGenerationProps)


def unregister():
    del bpy.types.Scene.gesturebone_rig_generation_props
    bpy.utils.unregister_class(GESTUREBONE_PG_RigGenerationProps)
    bpy.utils.unregister_class(GESTUREBONE_PG_MetaBoneSettings)
