"""
curvechain/ui.py — Panel content for UNIFIED (single-armature) rigs.
draw_unified_ui() is called inline from panels.py, like the gesture/plotting UIs.

Same compact card as the gesture UI: one double-height row per chain
(Draw / Apply | flip | delete keys), details folded away.
"""
from . import fit, builder as bd


def draw_unified_ui(layout, context, arm):
    props = arm.gesturebone_props
    chains = list(props.chains)
    if not chains:
        hint = layout.row()
        hint.enabled = False
        hint.label(text="No chains on this rig", icon='INFO')
        return

    frame = context.scene.frame_current
    for chain in chains:
        part = chain.part_name
        _, stroke = fit.latest_stroke(context.scene, part, frame)
        has_stroke = stroke is not None and len(stroke.points) > 1
        built = arm.pose.bones.get(bd.seg_name(part, 0)) is not None

        box = layout.box()
        stack = box.column(align=True)
        header = stack.row(align=True)
        header.prop(chain, "ui_expanded", icon='TRIA_DOWN' if chain.ui_expanded else 'TRIA_RIGHT',
                    text="", emboss=False)
        header.label(text=part)
        st = header.row(align=True)
        if not built:
            st.alert = True
            st.label(text="", icon='ERROR')
        elif has_stroke:
            st.alert = True
            st.label(text="", icon='GREASEPENCIL')
        else:
            st.label(text="", icon='CHECKMARK')

        row = stack.row(align=True)
        row.scale_y = 2.0
        main = row.row(align=True)
        main.scale_x = 4.0
        if has_stroke:
            main.alert = True
            op = main.operator("gesturebone.cc_apply", text=f"Apply {part}", icon='SORT_ASC')
        else:
            op = main.operator("gesturebone.cc_draw", text=part, icon='GREASEPENCIL',
                               depress=chain.is_drawing)
        op.part_name = part
        sub = row.row(align=True)
        sub.enabled = has_stroke
        sub.operator("gesturebone.cc_flip", text="", icon='ARROW_LEFTRIGHT').part_name = part
        sub.operator("gesturebone.cc_clear", text="", icon='X').part_name = part
        row.operator("gesturebone.cc_delete_keys", text="", icon='KEY_DEHLT').part_name = part

        if not chain.ui_expanded:
            continue
        body = stack.column(align=True)
        r = body.row(align=True)
        r.prop(chain, "plane_space", text="")
        r.operator("gesturebone.cc_rebuild", text="", icon='FILE_REFRESH').part_name = part
        if chain.plane_space == 'ROOT':
            body.prop(chain, "layer_depth", text="Layer Depth")
        info = body.row()
        info.enabled = False
        info.label(text=f"{len(bd.chain_indices(chain))} points · layer {fit.layer_name(part)}")


def draw_convert_box(layout, arm):
    """Offer the conversion on a classic GESTURE rig."""
    layout.operator("gesturebone.cc_convert", text="Convert to Single Rig", icon='AUTOMERGE_ON')
