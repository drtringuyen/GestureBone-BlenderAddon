import bpy


class GESTUREBONE_PT_GestureDraw(bpy.types.Panel):
    bl_label = "GestureDraw"
    bl_idname = "GESTUREBONE_PT_gesture_draw"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_main"
    bl_order = 0

    def draw(self, context):
        pass


class GESTUREBONE_PT_GestureDrawBinding(bpy.types.Panel):
    """List and bind CurveBoneChain entries"""
    bl_label = "Binding"
    bl_idname = "GESTUREBONE_PT_gesture_draw_binding"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_gesture_draw"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        mod_props = context.scene.gesturebone_gesture_draw_props

        # Add / Remove row
        row = layout.row(align=True)
        row.operator("gesturebone.add_chain", icon='ADD', text="Add Chain")
        if mod_props.chains:
            row.operator("gesturebone.remove_chain", icon='REMOVE', text="").chain_index = len(mod_props.chains) - 1

        for i, chain in enumerate(mod_props.chains):
            box = layout.box()

            # Row 1: name | GP | material | armature | bind toggle
            row = box.row(align=True)
            row.prop(chain, "part_name", text="")
            row.prop(chain, "part_gp", text="", icon='GREASEPENCIL')
            row.prop(chain, "part_material", text="", icon='MATERIAL')
            row.prop(chain, "part_armature", text="", icon='ARMATURE_DATA')

            sub = row.row(align=True)
            sub.active_default = chain.is_bound
            if chain.is_bound:
                op = sub.operator("gesturebone.delete_bone_constraints", text="", icon='LINKED')
            else:
                op = sub.operator("gesturebone.create_bone_constraints", text="", icon='UNLINKED')
            op.chain_index = i

            # Row 2: collapsible bones
            row2 = box.row()
            row2.prop(
                chain, "bones_expanded",
                text="Bones",
                icon='TRIA_DOWN' if chain.bones_expanded else 'TRIA_RIGHT',
                emboss=False,
            )
            if chain.bones_expanded:
                col = box.column(align=True)
                col.prop(chain, "bone_0")
                col.prop(chain, "bone_1")
                col.prop(chain, "bone_2")
                col.prop(chain, "bone_3")
                col.prop(chain, "bone_4")


class GESTUREBONE_PT_GestureDrawGestures(bpy.types.Panel):
    """Perform gesture operations on the chain list"""
    bl_label = "Gesture Draw"
    bl_idname = "GESTUREBONE_PT_gesture_draw_gestures"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GestureBone"
    bl_parent_id = "GESTUREBONE_PT_gesture_draw"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        mod_props = context.scene.gesturebone_gesture_draw_props

        if not mod_props.chains:
            layout.label(text="No chains — add in Binding", icon='INFO')
            return

        for i, chain in enumerate(mod_props.chains):
            row = layout.row(align=True)
            row.label(text=chain.part_name or f"Chain {i + 1}", icon='STROKE')

            # Draw toggle (GP draw mode + material)
            draw_sub = row.row(align=True)
            draw_sub.active_default = chain.is_drawing
            op = draw_sub.operator("gesturebone.toggle_drawing", text="", icon='GREASEPENCIL')
            op.chain_index = i

            # Key (apply visual + insert keyframe)
            op = row.operator("gesturebone.apply_and_key_bone_constraints", text="", icon='KEY_HLT')
            op.chain_index = i

            # Bind toggle
            bind_sub = row.row(align=True)
            bind_sub.active_default = chain.is_bound
            if chain.is_bound:
                op = bind_sub.operator("gesturebone.delete_bone_constraints", text="", icon='LINKED')
            else:
                op = bind_sub.operator("gesturebone.create_bone_constraints", text="", icon='UNLINKED')
            op.chain_index = i

            # Edit Pose
            op = row.operator("gesturebone.edit_pose", text="", icon='BONE_DATA')
            op.chain_index = i


def register():
    bpy.utils.register_class(GESTUREBONE_PT_GestureDraw)
    bpy.utils.register_class(GESTUREBONE_PT_GestureDrawBinding)
    bpy.utils.register_class(GESTUREBONE_PT_GestureDrawGestures)


def unregister():
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDrawGestures)
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDrawBinding)
    bpy.utils.unregister_class(GESTUREBONE_PT_GestureDraw)
