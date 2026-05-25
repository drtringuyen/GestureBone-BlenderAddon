import bpy
from .utils import _p
from .scene_props import _get_bone_settings


def _step(col, props, idname, icon, step_num, label, always_enabled=False):
    row = col.row()
    if not always_enabled:
        row.enabled = (props.completed_step == step_num - 1)
    row.operator(idname, text=label, icon=icon, depress=props.last_step == idname)


def _collapsible_header(layout, props, toggle_prop, text, icon):
    """Draw a collapsible section header. Returns True when expanded."""
    row = layout.row(align=True)
    row.prop(
        props, toggle_prop,
        icon='TRIA_DOWN' if getattr(props, toggle_prop) else 'TRIA_RIGHT',
        icon_only=True, emboss=False,
    )
    row.label(text=text, icon=icon)
    return getattr(props, toggle_prop)


class GESTUREBONE_PT_RigGeneration(bpy.types.Panel):
    bl_label       = "Rig Generation"
    bl_idname      = "GESTUREBONE_PT_rig_generation"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_parent_id   = "GESTUREBONE_PT_main"
    bl_order       = 1

    def draw(self, context):
        layout = self.layout
        props  = _p(context)

        # ── Registration ──────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Registration", icon='PROPERTIES')
        col = box.column(align=True)
        col.prop(props, "atomic_chain")
        col.prop(props, "meta_rig")
        col.prop(props, "meta_collection")
        col.separator()

        # MetaBone + Control Mode quick-access row (above Auto Rig)
        bone_name     = props.active_meta_bone
        bone_selected = bool(bone_name and bone_name != 'NONE')
        entry         = props.bone_settings.get(bone_name) if bone_selected else None
        mode_ready    = entry is not None

        row = col.row(align=True)
        row.prop(props, "active_meta_bone", text="")
        if mode_ready:
            row.prop(entry, "control_mode", text="")
        else:
            # Red button when bone is selected but mode not yet initialised
            sub         = row.row(align=True)
            sub.enabled = bone_selected
            sub.alert   = bone_selected
            sub.operator("gesturebone.init_bone_control_mode", text="", icon='SETTINGS')

        col.separator()

        # Grey out everything below while a bone is selected without a Control Mode
        ops_col         = col.column(align=True)
        ops_col.enabled = not bone_selected or mode_ready

        # Determine current state of CONNECT bones for icon toggle
        gesture_arm_obj = bpy.data.objects.get(f"{props.meta_rig}.Gesture")
        connect_selectable = True
        pivot_active = False
        if gesture_arm_obj:
            cb = [b for b in gesture_arm_obj.data.bones if b.name.startswith('CONNECT')]
            if cb:
                sel_count = sum(1 for b in cb if not b.hide_select)
                connect_selectable = sel_count > len(cb) // 2
            pivot_bc = gesture_arm_obj.data.collections.get('PIVOT-ROTATION')
            if pivot_bc:
                pivot_active = pivot_bc.is_visible
        connect_icon = 'RESTRICT_SELECT_OFF' if connect_selectable else 'RESTRICT_SELECT_ON'
        pivot_icon   = 'PIVOT_CURSOR' if pivot_active else 'NONE'

        # Determine META toggle state
        meta_solo = props.meta_solo_mode
        meta_icon = 'BONE_DATA' if meta_solo else 'GROUP_BONE'

        # Main action row: Auto Rig | Delete Sample Folder | META
        main_row = ops_col.row(align=True)
        sub = main_row.row(align=True)
        sub.scale_x = 3.0
        sub.operator("gesturebone.auto_rig", icon='PLAY')
        main_row.operator("gesturebone.clear_rig", text="", icon='GHOST_DISABLED')
        main_row.operator("gesturebone.delete_sample_folder", text="", icon='ORPHAN_DATA')
        main_row.operator("gesturebone.toggle_meta_collection",
                          text="", icon=meta_icon, depress=meta_solo)

        ops_col.separator()

        # Utility row: CONNECT (toggle) | Reset Stretch | PIVOT
        row = ops_col.row(align=True)
        row.operator("gesturebone.toggle_connect_selectable",
                     text="CONNECT", icon=connect_icon, depress=connect_selectable)
        row.operator("gesturebone.reset_all_bones_stretch",
                     text="Reset Stretch", icon='SNAP_MIDPOINT')
        row.operator("gesturebone.toggle_pivot_rotation",
                     text="PIVOT", icon=pivot_icon, depress=pivot_active)

        # ── Debug-only sections ───────────────────────────────────────────────
        global_props = getattr(context.scene, 'gesturebone_props', None)
        debug_mode   = getattr(global_props, 'debug_mode', False) if global_props else False

        if debug_mode:
            layout.separator()

            # ── Generate Part by Part (collapsible) ───────────────────────────
            expanded = _collapsible_header(layout, props, "show_generate_part",
                                           "Generate Part by Part", 'ARMATURE_DATA')
            if expanded:
                box = layout.box()
                col = box.column(align=True)
                col.prop(props, "active_meta_bone", text="MetaBone")

                # Control MODE for the active bone
                bone_name = props.active_meta_bone
                if bone_name and bone_name != 'NONE':
                    entry = props.bone_settings.get(bone_name)
                    if entry:
                        col.prop(entry, "control_mode", text="Control Mode")
                    else:
                        col.operator("gesturebone.init_bone_control_mode",
                                     text="Set Control Mode", icon='SETTINGS')

                col.separator()
                col.operator("gesturebone.rig_part", icon='PLAY')

            layout.separator()

            # ── Debug Step by Step (collapsible) ─────────────────────────────
            expanded = _collapsible_header(layout, props, "show_debug_steps",
                                           "Debug Step by Step", 'TOOL_SETTINGS')
            if expanded:
                box = layout.box()
                col = box.column(align=False)
                col.prop(props, "active_meta_bone", text="MetaBone")
                col.separator()

                _step(col, props, "gesturebone.duplicate_atomic_chain",
                      'MOD_THICKNESS', 1, "1.  Duplicate and Rename", always_enabled=True)
                _step(col, props, "gesturebone.rebind_constraints_geonodes",
                      'CON_SPLINEIK',  2, "2.  Rebind Constraints & Geonodes")

                col.separator()
                col.label(text="  Align Chain to Bone:", icon='EMPTY_AXIS')

                _step(col, props, "gesturebone.scale_empty_to_rest_pose",
                      'FULLSCREEN_ENTER', 3, "3.  Scale Empty to Rest Pose")
                _step(col, props, "gesturebone.add_align_constraints",
                      'CON_LOCLIKE',     4, "4.  Add Copy Loc & Rot")
                _step(col, props, "gesturebone.edit_alignment_in_metarig",
                      'POSE_HLT',        5, "5.  Edit Alignment in Meta Rig")

                if props.is_aligning:
                    hint = col.row()
                    hint.enabled = False
                    hint.label(text="     Adjust pose -> then Step 6", icon='INFO')

                _step(col, props, "gesturebone.accept_and_bind",
                      'CHECKMARK',       6, "6.  Accept & Bind")

                col.separator()

                _step(col, props, "gesturebone.refresh_rigs",
                      'CON_ROTLIKE',            7,  "7.  Refresh Gesture & Plot Rigs")
                _step(col, props, "gesturebone.rebind_final_armatures",
                      'OUTLINER_OB_ARMATURE',   8,  "8.  Rebind Final Armatures")
                _step(col, props, "gesturebone.finish_merging",
                      'OUTLINER_DATA_ARMATURE', 9,  "9.  Merge & Clean")
                _step(col, props, "gesturebone.merge_rig_into_metarig",
                      'ARMATURE_DATA',          10, "10. Merge .Rig into MetaRig")

                col.separator()

                _step(col, props, "gesturebone.rebind_armature_deform",
                      'MOD_ARMATURE',           11, "11. Rebind Armature Deform")


def register():
    bpy.utils.register_class(GESTUREBONE_PT_RigGeneration)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_RigGeneration)
