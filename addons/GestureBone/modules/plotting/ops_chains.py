"""
plotting/ops_chains.py — Chain list management operators.
Chains are fully driven by the META bone collection — no manual add/remove.
"""
import bpy
from bpy.props import IntProperty, EnumProperty
from .utils import _active_plotting_arm, _default_template
from ..shared.utils import _bones_in_bone_coll
from ..shared.chain import CONTROL_MODE_COUNT, _ctrl_bone_indices


class GESTUREBONE_OT_SyncChainsFromMetaBones(bpy.types.Operator):
    """Reconcile the chain list with the META bone collection.

    - Adds ChainDefinition for any META bone not yet in chains (preserves settings).
    - Removes ChainDefinition for any chain whose part_name has no matching META bone.
    - Reorders chains to match META bone order.
    """
    bl_idname      = "gesturebone.sync_chains_from_meta_bones"
    bl_label       = "Sync from META"
    bl_description = "Sync the chain list to match bones in the META collection (add missing, remove orphaned)"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            self.report({'ERROR'}, "Active object is not a PLOTTING rig")
            return {'CANCELLED'}

        props     = arm.gesturebone_props
        coll_name = props.meta_collection
        if not coll_name:
            self.report({'ERROR'}, "Meta Collection not set on this rig")
            return {'CANCELLED'}

        bone_names = _bones_in_bone_coll(arm.data, coll_name)
        if not bone_names:
            self.report({'WARNING'}, f"No bones found in '{coll_name}'")
            return {'FINISHED'}

        bone_set = set(bone_names)

        # Snapshot existing chain settings keyed by part_name
        existing = {}
        for chain in props.chains:
            existing[chain.part_name] = {
                'atomic_chain':     chain.atomic_chain,
                'control_mode':     chain.control_mode,
                'pivot_placement':  chain.pivot_placement,
                'bind_mesh':        chain.bind_mesh,
                'sample_mesh':      chain.sample_mesh,
                'gesture_spline':   chain.gesture_spline,
                'plotting_spline':  chain.plotting_spline,
                'gesture_rig':      chain.gesture_rig,
                'rig_completed_step': chain.rig_completed_step,
                'is_bound':         chain.is_bound,
                'control_bones':    [e.bone for e in chain.control_bones],
            }

        props.chains.clear()

        fallback_template = props.atomic_chain or _default_template()
        added = removed = 0

        for bone_name in bone_names:
            chain = props.chains.add()
            chain.part_name = bone_name
            chain.name      = bone_name  # CollectionProperty key

            if bone_name in existing:
                s = existing[bone_name]
                chain.atomic_chain       = s['atomic_chain'] or fallback_template
                chain.control_mode       = s['control_mode']
                chain.pivot_placement    = s['pivot_placement']
                if s['bind_mesh']:
                    chain.bind_mesh      = s['bind_mesh']
                if s['sample_mesh']:
                    chain.sample_mesh    = s['sample_mesh']
                if s['gesture_spline']:
                    chain.gesture_spline = s['gesture_spline']
                if s['plotting_spline']:
                    chain.plotting_spline = s['plotting_spline']
                if s['gesture_rig']:
                    chain.gesture_rig    = s['gesture_rig']
                chain.rig_completed_step = s['rig_completed_step']
                chain.is_bound           = s['is_bound']
                # Restore control bones
                count = CONTROL_MODE_COUNT.get(chain.control_mode, 5)
                chain.control_point_count = count
                while len(chain.control_bones) < count:
                    chain.control_bones.add()
                while len(chain.control_bones) > count:
                    chain.control_bones.remove(len(chain.control_bones) - 1)
                for i, bname in enumerate(s['control_bones']):
                    if i < len(chain.control_bones):
                        chain.control_bones[i].bone = bname
            else:
                chain.atomic_chain        = fallback_template
                chain.control_point_count = CONTROL_MODE_COUNT.get(chain.control_mode, 5)
                added += 1

        removed = len(existing) - len([n for n in existing if n in bone_set])
        props.active_chain_index = 0

        self.report(
            {'INFO'},
            f"Synced chains: {len(bone_names)} total, {added} added, {removed} removed"
        )
        return {'FINISHED'}


class GESTUREBONE_OT_MoveChain(bpy.types.Operator):
    """Move a chain up or down (display order only — does not affect META bones)."""
    bl_idname  = "gesturebone.move_chain"
    bl_label   = "Move Chain"
    bl_options = {'REGISTER', 'UNDO'}

    chain_index: IntProperty()
    direction: EnumProperty(items=[('UP', 'Up', ''), ('DOWN', 'Down', '')])

    def execute(self, context):
        arm = _active_plotting_arm(context)
        if arm is None:
            return {'CANCELLED'}
        props  = arm.gesturebone_props
        chains = props.chains
        idx    = self.chain_index

        if self.direction == 'UP' and idx > 0:
            chains.move(idx, idx - 1)
            props.active_chain_index = idx - 1
        elif self.direction == 'DOWN' and idx < len(chains) - 1:
            chains.move(idx, idx + 1)
            props.active_chain_index = idx + 1
        else:
            return {'CANCELLED'}
        return {'FINISHED'}


_classes = [
    GESTUREBONE_OT_SyncChainsFromMetaBones,
    GESTUREBONE_OT_MoveChain,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
