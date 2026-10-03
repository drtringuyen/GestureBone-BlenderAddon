"""
curvechain/convert.py — Fold a two-rig character (PLOTTING MetaPlot + GESTURE
rig + per-chain Gesture/Plotting splines) into ONE armature.

Direction of the merge is deliberate: the MetaPlot's deform stack goes INTO the
GESTURE rig, because the Gesture rig is what the animation (its action), the
Expression Sheet drivers and every other rig's constraints already point at.
Nothing animator-facing has to be re-targeted.

Order:
  1. collect: chains, sampler (STR) bones per chain from their GEOMETRY_ATTRIBUTE
     sample_index, splines to delete
  2. copy chain definitions PLOTTING → GESTURE
  3. re-point meshes (Armature modifiers, parenting) MetaPlot → Gesture
  4. join MetaPlot into Gesture (no bone-name collisions allowed)
  5. rename .hL/.hR → .hA/.hB and .End.L/.End.R → .End.A/.End.B on the gesture
     side (Blender fixes fcurve paths, constraint subtargets and drivers)
  6. per chain: build_chain(), rebind samplers, drop the old spline constraints
  7. delete the chain splines (GN node groups are left for Purge — templates
     still use them)
"""
import re
import bpy

from . import builder

UNIFIED = 'UNIFIED'
_RENAMES = ((re.compile(r"\.hL$"), ".hA"), (re.compile(r"\.hR$"), ".hB"),
            (re.compile(r"\.End\.L$"), ".End.A"), (re.compile(r"\.End\.R$"), ".End.B"))
_RENAME_PREFIXES = ("CTRL-", "CONNECT-", "LIMIT-")


def _copy_pg(src, dst):
    for prop in src.bl_rna.properties:
        pid = prop.identifier
        if pid == "rna_type":
            continue
        if prop.type == 'COLLECTION':
            sc, dc = getattr(src, pid), getattr(dst, pid)
            dc.clear()
            for item in sc:
                _copy_pg(item, dc.add())
        elif prop.is_readonly:
            continue
        else:
            try:
                setattr(dst, pid, getattr(src, pid))
            except (AttributeError, TypeError):
                pass


def collect(gesture):
    """Read-only plan of the conversion. Returns a dict; 'errors' non-empty
    means convert() will refuse."""
    props = gesture.gesturebone_props
    plotting = props.plotting_rig
    plan = {"gesture": gesture.name, "plotting": plotting.name if plotting else None,
            "chains": [], "errors": [], "meshes": [], "splines": []}
    if props.rig_type != 'GESTURE':
        plan["errors"].append(f"'{gesture.name}' is not a GESTURE rig")
        return plan
    if plotting is None or plotting.gesturebone_props.rig_type != 'PLOTTING':
        plan["errors"].append("plotting_rig is not set to a PLOTTING rig")
        return plan
    clash = sorted(set(gesture.data.bones.keys()) & set(plotting.data.bones.keys()))
    if clash:
        plan["errors"].append(f"bone names exist on both rigs: {clash[:8]}")
    if gesture.matrix_world != plotting.matrix_world:
        plan["errors"].append("the two rigs have different object transforms")

    for chain in plotting.gesturebone_props.chains:
        part = chain.part_name
        indices = builder.chain_indices(chain)
        # spline objects are named after the character, not the MetaPlot
        # ("CHR_X-Arm.L.PlottingSpline"), so trust the chain pointers first
        base = plotting.name.rsplit(".", 1)[0]
        plot_spline = (chain.plotting_spline
                       or bpy.data.objects.get(f"{base}-{part}.PlottingSpline")
                       or bpy.data.objects.get(f"{plotting.name}-{part}.PlottingSpline"))
        gest_spline = (chain.gesture_spline
                       or bpy.data.objects.get(f"{base}-{part}.GestureSpline")
                       or bpy.data.objects.get(f"{plotting.name}-{part}.GestureSpline"))
        samplers = {}
        for pb in plotting.pose.bones:
            for c in pb.constraints:
                if c.type == 'GEOMETRY_ATTRIBUTE' and plot_spline is not None and c.target == plot_spline:
                    samplers[c.sample_index] = pb.name
        order = [samplers[i] for i in sorted(samplers)]
        plan["chains"].append({"part": part, "indices": indices, "samplers": order,
                               "sample_count": (max(samplers) + 1) if samplers else 0})
        if not samplers:
            plan["errors"].append(f"{part}: no sampler bones read from a PlottingSpline")
        elif sorted(samplers) != list(range(max(samplers) + 1)):
            plan["errors"].append(f"{part}: sampler indices have gaps {sorted(samplers)}")
        for ob in (gest_spline, plot_spline):
            if ob is not None and ob.type == 'CURVE' and ob.name not in plan["splines"]:
                plan["splines"].append(ob.name)

    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        uses = any(m.type == 'ARMATURE' and m.object == plotting for m in ob.modifiers) or ob.parent == plotting
        if uses:
            plan["meshes"].append(ob.name)
    return plan


def _rename_handles(arm):
    renamed = {}
    for b in list(arm.data.bones):
        if not b.name.startswith(_RENAME_PREFIXES):
            continue
        new = b.name
        for rx, rep in _RENAMES:
            new = rx.sub(rep, new)
        if new != b.name and not arm.data.bones.get(new):
            old = b.name
            b.name = new
            renamed[old] = new
    return renamed


def _anim_state(ob):
    ad = ob.animation_data
    if ad is None:
        return None
    slot = getattr(ad, "action_slot", None)
    return {"action": ad.action,
            "slot": slot.identifier if slot else None,
            "nla": [(t.name, len(t.strips), t.mute) for t in ad.nla_tracks]}


def _restore_anim(ob, state):
    """object.join() drops the active action's slot assignment (Blender 5.x),
    which silently stops the animation from playing — put it back."""
    if not state or state["action"] is None:
        return True
    ad = ob.animation_data or ob.animation_data_create()
    if ad.action != state["action"]:
        ad.action = state["action"]
    if state["slot"] and hasattr(ad, "action_slot"):
        slot = next((s for s in state["action"].slots if s.identifier == state["slot"]), None)
        if slot is not None and ad.action_slot != slot:
            ad.action_slot = slot
    now = [(t.name, len(t.strips), t.mute) for t in ad.nla_tracks]
    return now == state["nla"] and (not state["slot"] or (ad.action_slot and ad.action_slot.identifier == state["slot"]))


def _join(gesture, plotting):
    ctx = bpy.context
    if ctx.object and ctx.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in ctx.view_layer.objects:
        ob.select_set(False)
    for ob in (gesture, plotting):
        ob.hide_set(False)
        ob.hide_viewport = False
        ob.select_set(True)
    ctx.view_layer.objects.active = gesture
    with ctx.temp_override(active_object=gesture, object=gesture,
                           selected_objects=[gesture, plotting],
                           selected_editable_objects=[gesture, plotting]):
        bpy.ops.object.join()


def convert(gesture, delete_splines=True, spacing='UNIFORM', plane='ROOT'):
    """Run the conversion in place. Returns the report dict."""
    plan = collect(gesture)
    if plan["errors"]:
        return plan
    plotting = gesture.gesturebone_props.plotting_rig
    plotting_name = plotting.name
    gprops = gesture.gesturebone_props

    # 2. chain definitions move to the surviving armature
    gprops.chains.clear()
    for src in plotting.gesturebone_props.chains:
        _copy_pg(src, gprops.chains.add())
    for attr in ("meta_collection", "atomic_chain", "meta_rig_preset"):
        setattr(gprops, attr, getattr(plotting.gesturebone_props, attr))

    # 3. meshes follow the deform bones
    for name in plan["meshes"]:
        ob = bpy.data.objects[name]
        for m in ob.modifiers:
            if m.type == 'ARMATURE' and m.object == plotting:
                m.object = gesture
        if ob.parent == plotting:
            mw = ob.matrix_world.copy()
            ob.parent = gesture
            ob.matrix_world = mw

    # 4. one armature (join drops the action slot — restore it)
    anim = _anim_state(gesture)
    _join(gesture, plotting)
    if not _restore_anim(gesture, anim):
        plan["errors"].append("animation (action slot / NLA) could not be restored after join")

    # 5. A/B handles
    plan["renamed"] = len(_rename_handles(gesture))

    # 6. curve machinery + samplers
    bpy.context.view_layer.objects.active = gesture
    built = []
    for ch in plan["chains"]:
        part, indices = ch["part"], ch["indices"]
        miss = builder.missing_bones(gesture, part, indices)
        if miss:
            plan["errors"].append(f"{part}: missing after join {miss}")
            continue
        builder.build_chain(gesture, part, indices, plane)
        builder.bind_samplers(gesture, part, indices, ch["samplers"], spacing)
        built.append(part)
    for pb in gesture.pose.bones:
        for c in list(pb.constraints):
            if c.type == 'GEOMETRY_ATTRIBUTE':
                pb.constraints.remove(c)
    plan["built"] = built
    plan["non_simple_drivers"] = builder.non_simple_drivers(gesture)

    # 7. curves are dead weight now
    if delete_splines:
        for n in plan["splines"]:
            ob = bpy.data.objects.get(n)
            if ob:
                data = ob.data
                bpy.data.objects.remove(ob)
                if data and data.users == 0:
                    bpy.data.curves.remove(data)
        for coll in list(bpy.data.collections):
            if coll.name.endswith((".GestureSplines", ".PlottingSplines")) and not coll.all_objects and not coll.children:
                bpy.data.collections.remove(coll)

    gprops.rig_type = UNIFIED
    gprops.plotting_rig = None
    # join leaves the source object datablock behind (still referenced by the
    # pointers cleared above) — drop it so nothing can resolve to it again
    leftover = bpy.data.objects.get(plotting_name)
    if leftover is not None and leftover is not gesture and not leftover.users_scene:
        data = leftover.data
        bpy.data.objects.remove(leftover)
        if data is not None and data.users == 0:
            bpy.data.armatures.remove(data)
    for chain in gprops.chains:
        chain.gesture_rig = gesture
        chain.gesture_spline = None
        chain.plotting_spline = None
        chain.is_bound = True
        chain.is_drawing = False
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    if not _restore_anim(gesture, anim):
        plan["errors"].append("animation (action slot / NLA) changed during conversion")
    plan["action_slot"] = anim and anim["slot"]
    return plan
