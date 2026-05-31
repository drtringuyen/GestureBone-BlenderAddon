import bpy

TAG_SAMPLE_RIG     = "gesturebone_rig_preset"
TAG_TEMPLATE       = "gesturebone_template"
TAG_GESTURE_RIGGED = "gesturebone_gesture_rigged"


def _active_collection(context):
    vlc = getattr(context.view_layer, 'active_layer_collection', None)
    return vlc.collection if vlc else None


def _extra_infos_on(context):
    gp = getattr(getattr(context, 'scene', None), 'gesturebone_props', None)
    return getattr(gp, 'extra_infos_mode', False)


# ── Operators ─────────────────────────────────────────────────────────────────

class GESTUREBONE_OT_TagSampleRig(bpy.types.Operator):
    bl_idname  = "gesturebone.tag_sample_rig"
    bl_label   = "Tag Rig Preset"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}
        if TAG_SAMPLE_RIG in obj:
            del obj[TAG_SAMPLE_RIG]
        else:
            obj[TAG_SAMPLE_RIG] = True
        return {'FINISHED'}


class GESTUREBONE_OT_TagTemplate(bpy.types.Operator):
    bl_idname  = "gesturebone.tag_template"
    bl_label   = "Tag BoneChain Template"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        coll = _active_collection(context)
        if not coll:
            self.report({'ERROR'}, "No active collection")
            return {'CANCELLED'}
        if TAG_TEMPLATE in coll:
            del coll[TAG_TEMPLATE]
        else:
            coll[TAG_TEMPLATE] = True
        return {'FINISHED'}


class GESTUREBONE_OT_TagGestureRigged(bpy.types.Operator):
    bl_idname  = "gesturebone.tag_gesture_rigged"
    bl_label   = "Tag Gesture Rigged"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}
        if TAG_GESTURE_RIGGED in obj:
            del obj[TAG_GESTURE_RIGGED]
        else:
            obj[TAG_GESTURE_RIGGED] = True
        return {'FINISHED'}


# ── Panel ─────────────────────────────────────────────────────────────────────

class GESTUREBONE_PT_ExtraInfos(bpy.types.Panel):
    bl_label       = "Tagging Atomic Chain & Rig Template"
    bl_idname      = "GESTUREBONE_PT_extra_infos"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "GestureBone"
    bl_order       = 99

    @classmethod
    def poll(cls, context):
        return _extra_infos_on(context)

    def draw(self, context):
        layout = self.layout
        obj    = context.active_object
        coll   = _active_collection(context)

        # ── Active Armature ───────────────────────────────────────────────────
        col = layout.column(align=True)
        col.label(text="Active Object", icon='OBJECT_DATA')
        box = col.box()
        if obj and obj.type == 'ARMATURE':
            # Sample Rig tag
            tagged_sample = TAG_SAMPLE_RIG in obj
            row = box.row(align=True)
            row.label(text=obj.name, icon='ARMATURE_DATA')
            sr = row.row(align=True)
            sr.active_default = tagged_sample
            sr.operator(
                "gesturebone.tag_sample_rig",
                text="Rig Preset" + (" ✓" if tagged_sample else ""),
                icon='CHECKMARK' if tagged_sample else 'RADIOBUT_OFF',
                depress=tagged_sample,
            )
            # GestureRigged tag
            tagged_rigged = TAG_GESTURE_RIGGED in obj
            row2 = box.row(align=True)
            row2.label(text="", icon='BLANK1')
            gr = row2.row(align=True)
            gr.active_default = tagged_rigged
            gr.operator(
                "gesturebone.tag_gesture_rigged",
                text="GestureRigged" + (" ✓" if tagged_rigged else ""),
                icon='CHECKMARK' if tagged_rigged else 'RADIOBUT_OFF',
                depress=tagged_rigged,
            )
        else:
            row = box.row()
            row.enabled = False
            row.label(text="Select an Armature", icon='INFO')

        layout.separator(factor=0.5)

        # ── Active Collection ─────────────────────────────────────────────────
        col = layout.column(align=True)
        col.label(text="Active Collection", icon='OUTLINER_COLLECTION')
        box = col.box()
        if coll:
            tagged = TAG_TEMPLATE in coll
            row = box.row(align=True)
            row.label(text=coll.name, icon='COLLECTION_COLOR_01' if tagged else 'OUTLINER_COLLECTION')
            op_row = row.row(align=True)
            op_row.active_default = tagged
            op_row.operator(
                "gesturebone.tag_template",
                text="Template" + (" ✓" if tagged else ""),
                icon='CHECKMARK' if tagged else 'RADIOBUT_OFF',
                depress=tagged,
            )
        else:
            row = box.row()
            row.enabled = False
            row.label(text="No active collection", icon='INFO')


_classes = [
    GESTUREBONE_OT_TagSampleRig,
    GESTUREBONE_OT_TagTemplate,
    GESTUREBONE_OT_TagGestureRigged,
    GESTUREBONE_PT_ExtraInfos,
]


def register():
    for cls in _classes:
        # Wipe every stale registration of this bl_idname before re-registering
        if hasattr(cls, 'bl_idname'):
            for stale in [c for c in bpy.types.Panel.__subclasses__()
                          if getattr(c, 'bl_idname', '') == cls.bl_idname]:
                try:
                    bpy.utils.unregister_class(stale)
                except Exception:
                    pass
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass


def unregister():
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
