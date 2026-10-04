"""
export/gamerig.py — "Game Engine Compatible": a temporary plain-bone rig.

Game engines can't evaluate B-Bones, constraints or drivers. Instead of
changing the character rig (impossible on a library override in an ANIM
file), export builds LOCAL temporary objects in whatever file it runs in:

    EXPORT-{rig}            armature, every bone parented to "root"
      root
      BDEF-{part}.001 …     N plain bones per B-Bone span, numbered along the
                            chain; Copy Transforms + Stretch To on the span's
                            B-Bone shape → they follow the span exactly
      BDEF-{part}.EndL/R    end caps, copied 1:1
      <other deform bones>  (SKEL-, MESHSHEET- …) copied 1:1
    EXPORT-{mesh}           local copies of every mesh the rig deforms,
                            Armature → EXPORT rig; a chain mesh's weight node
                            is pointed at the segment bones and left LIVE

Preview = build and show the copies (originals hidden). Changing
"Segments per Span" and updating rebuilds, and the weight node re-weights the
copies live — tune its Strength/Radius/Blur on the copy, then export.
Export = bake the EXPORT rig's animation, freeze the copies' weights, write
FBX (Unity) or GLB (Godot), delete the temporary objects.
"""
import os
import bpy
from mathutils import Vector

from ..curvechain import builder as bd
from ..shared.utils_gn import _find_socket_id, _get_gn_input, _set_gn_input
from . import weights as W, weight_nodes as WN, optimize as O

COLL = "GB_EXPORT"
TAG = "gb_export"          # custom prop on temporary objects → rig name
ORIG_HIDDEN = "gb_export_hidden"


def rig_name(arm):          return f"EXPORT-{arm.name}"
def seg_bone(part, n):      return f"BDEF-{part}.{n:03d}"


def _collection(scene):
    coll = bpy.data.collections.get(COLL)
    if coll is None:
        coll = bpy.data.collections.new(COLL)
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def temp_objects(arm):
    return [ob for ob in bpy.data.objects if ob.get(TAG) == arm.name]


def is_previewing(arm):
    return bool(temp_objects(arm))


def deformed_meshes(arm, view_layer=None):
    """Meshes the rig deforms that are part of the shot (in the view layer and
    not disabled for render): those are what an export should contain."""
    view_layer = view_layer or bpy.context.view_layer
    return [ob for ob in view_layer.objects
            if ob is not None and ob.type == 'MESH' and not ob.get(TAG) and not ob.hide_render
            and any(m.type == 'ARMATURE' and m.object == arm for m in ob.modifiers)]


def _bezier_points(p0, p1, p2, p3, n=256):
    pts = [((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t * t * p2 + (t ** 3) * p3
           for t in (i / n for i in range(n + 1))]
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + (b - a).length)
    return pts, cum


def _at(pts, cum, f):
    s = f * cum[-1]
    for i in range(1, len(cum)):
        if cum[i] >= s:
            u = (s - cum[i - 1]) / max(cum[i] - cum[i - 1], 1e-12)
            return pts[i - 1].lerp(pts[i], u)
    return pts[-1]


def _rest_joints(arm, name):
    """The B-Bone's own REST segment joints (armature space) + cumulative
    lengths — exactly what Blender binds the mesh to."""
    pb = arm.pose.bones[name]
    m = pb.bone.matrix_local
    pts = [(m @ pb.bbone_segment_matrix(i, rest=True)).translation.copy()
           for i in range(pb.bone.bbone_segments + 1)]
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + (b - a).length)
    return pts, cum


def _span_curves(arm, chains):
    """Rest curve (points, cumulative lengths) per BDEF span, armature space."""
    out = {}
    for part, idx in chains:
        for k in range(len(idx) - 1):
            src = O.bdef_name(part, k)
            if arm.pose.bones.get(src) is None:
                continue
            out[src] = (part, k, _rest_joints(arm, src))
    return out


def _closest_u(pts, cum, p):
    best, bu = None, 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        ab = b - a
        L = ab.length_squared
        t = 0.0 if L == 0 else max(0.0, min(1.0, (p - a).dot(ab) / L))
        d = (a + ab * t - p).length_squared
        if best is None or d < best:
            best, bu = d, (cum[i] + (cum[i + 1] - cum[i]) * t) / cum[-1]
    return bu


def _transfer_to_segments(cp, arm, curves, segments):
    """Split each BDEF span weight on `cp` between the two segment bones whose
    centres bracket the vertex's position along the span's rest curve - the
    same blend Blender's B-Bone deformation does."""
    to_arm = arm.matrix_world.inverted() @ cp.matrix_world
    names = {vg.index: vg.name for vg in cp.vertex_groups}
    spans = {name: curves[name] for name in names.values() if name in curves}
    if not spans:
        return 0
    adds = {}
    for v in cp.data.vertices:
        p = None
        for ge in v.groups:
            name = names.get(ge.group)
            if name not in spans or ge.weight <= 0:
                continue
            part, k, (pts, cum) = spans[name]
            p = p if p is not None else to_arm @ v.co
            u = _closest_u(pts, cum, p)
            f = min(max(u * segments - 0.5, 0.0), segments - 1.0)
            s0 = int(f)
            t = f - s0
            base = k * segments + 1
            for s, w in ((s0, ge.weight * (1 - t)), (min(s0 + 1, segments - 1), ge.weight * t)):
                if w > 1e-6:
                    key = (seg_bone(part, base + s), v.index)
                    adds[key] = adds.get(key, 0.0) + w
    for name in spans:
        cp.vertex_groups.remove(cp.vertex_groups[name])
    by_group = {}
    for (gname, vi), w in adds.items():
        by_group.setdefault(gname, []).append((vi, w))
    for gname, pairs in by_group.items():
        vg = cp.vertex_groups.get(gname) or cp.vertex_groups.new(name=gname)
        for vi, w in pairs:
            vg.add([vi], w, 'REPLACE')
    return len(by_group)


def _weighted_bone_names(arm):
    """Deform bones some mesh actually has a vertex group for."""
    names = set()
    for ob in deformed_meshes(arm):
        names |= {vg.name for vg in ob.vertex_groups}
    return names


def build(context, arm, segments=None):
    """(Re)build the temporary export rig + mesh copies. Returns a report."""
    clear(arm)
    segments = segments or arm.gesturebone_props.export_segments
    scene = context.scene
    coll = _collection(scene)
    bbone = O.deform_mode(arm) == O.MODE_BBONE
    data = bpy.data.armatures.new(rig_name(arm))
    rig = bpy.data.objects.new(rig_name(arm), data)
    rig[TAG] = arm.name
    rig.matrix_world = arm.matrix_world.copy()
    coll.objects.link(rig)

    chains = [(c.part_name, bd.chain_indices(c)) for c in arm.gesturebone_props.chains]
    joints = _span_curves(arm, chains) if bbone else {}
    chain_bones = set()
    spans = {}       # export bone → (source span, ht0, ht1)
    copies = {}      # export bone → source bone (1:1)
    rest = arm.data.bones
    vg_names = _weighted_bone_names(arm)

    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    for ob in view_layer.objects:
        ob.select_set(False)
    view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        ebs = data.edit_bones
        root = ebs.new("root")
        root.head, root.tail = (0, 0, 0), (0, 0.1, 0)
        root.use_deform = False
        if bbone:
            for part, idx in chains:
                n = 0
                for k, (a, b) in enumerate(zip(idx, idx[1:])):
                    src = O.bdef_name(part, k)
                    if rest.get(src) is None:
                        continue
                    chain_bones.add(src)
                    pts, cum = joints[src][2]
                    roll_src = rest[src]
                    for s in range(segments):
                        n += 1
                        nm = seg_bone(part, n)
                        eb = ebs.new(nm)
                        eb.head = _at(pts, cum, s / segments)
                        eb.tail = _at(pts, cum, (s + 1) / segments)
                        if (eb.tail - eb.head).length < 1e-5:
                            eb.tail = eb.head + Vector((0, 0, 1e-3))
                        eb.align_roll(roll_src.matrix_local.col[2].to_3d())   # align_roll sets Z: match the span
                        eb.parent = root
                        eb.use_deform = True
                        spans[nm] = (src, s / segments, (s + 1) / segments)
                for side in ("EndL", "EndR"):
                    chain_bones.add(O.bdef_end(part, side))
        for b in rest:
            if not b.use_deform or b.name in chain_bones or b.name in data.edit_bones:
                continue
            if b.name not in vg_names:
                continue
            eb = ebs.new(b.name)
            eb.head, eb.tail = b.head_local, b.tail_local
            eb.align_roll(b.matrix_local.col[2].to_3d())
            eb.parent = root
            eb.use_deform = True
            copies[b.name] = b.name
        for part, idx in chains if bbone else []:
            for side in ("EndL", "EndR"):
                src = rest.get(O.bdef_end(part, side))
                if src is not None and src.name not in data.edit_bones:
                    eb = ebs.new(src.name)
                    eb.head, eb.tail = src.head_local, src.tail_local
                    eb.align_roll(src.matrix_local.col[2].to_3d())
                    eb.parent = root
                    eb.use_deform = True
                    copies[src.name] = src.name
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    for nm, (src, h0, h1) in spans.items():
        pb = rig.pose.bones[nm]
        c = pb.constraints.new('COPY_TRANSFORMS'); c.target = arm; c.subtarget = src
        c.head_tail = h0; c.use_bbone_shape = True
        c = pb.constraints.new('STRETCH_TO'); c.target = arm; c.subtarget = src
        c.head_tail = h1; c.use_bbone_shape = True
        c.volume = 'NO_VOLUME'; c.keep_axis = 'PLANE_X'; c.rest_length = pb.bone.length
    for nm, src in copies.items():
        c = rig.pose.bones[nm].constraints.new('COPY_TRANSFORMS')
        c.target = arm; c.subtarget = src

    # mesh copies
    curves = joints
    seg_count = {part: sum(1 for nm in spans if nm.startswith(f"BDEF-{part}.")) for part, _ in chains}
    made = []
    for ob in deformed_meshes(arm):
        cp = ob.copy()
        cp.data = ob.data.copy()
        cp.name = f"EXPORT-{ob.name}"
        cp[TAG] = arm.name
        for key in (W.BAKED_PROP, W.SOURCE_PROP):
            if key in cp:
                del cp[key]
        cp.parent = rig
        cp.matrix_world = ob.matrix_world.copy()
        coll.objects.link(cp)
        for m in cp.modifiers:
            if m.type == 'ARMATURE' and m.object == arm:
                m.object = rig
        md = W.weight_modifier(cp, arm)
        exact = bbone and md is not None and arm.gesturebone_props.export_weights == 'BBONE'
        if exact:
            # freeze the original's span weights (and any sprite geometry the node
            # adds) onto the copy, then split them onto the segment bones
            omd = W.weight_modifier(ob, arm)
            if W.is_baked(ob):
                frozen = ob.data.copy()
            else:
                ev, saved = W._evaluate_up_to(ob, omd)
                try:
                    frozen = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True,
                                                             depsgraph=bpy.context.evaluated_depsgraph_get())
                finally:
                    for m, vis in saved:
                        m.show_viewport = vis
            old = cp.data
            cp.data = frozen
            if old.users == 0:
                bpy.data.meshes.remove(old)
            ad = cp.animation_data
            if ad:
                for fc in [f for f in ad.drivers if f.data_path.startswith(f'modifiers["{md.name}"]')]:
                    ad.drivers.remove(fc)
            cp.modifiers.remove(md)
            _transfer_to_segments(cp, arm, curves, segments)
            md = None
        if md is not None:
            part = _get_gn_input(md, _find_socket_id(md, "Module_name"))
            _set_gn_input(md, _find_socket_id(md, "Deform Armature"), rig)
            if bbone and part in seg_count:
                if not WN.has_bdef(md.node_group):
                    if md.node_group.library is not None:
                        raise RuntimeError("the weight node group is linked and has no BDEF- option — "
                                           "convert the CHR file to Blender Optimized first")
                    WN.ensure_bdef_branch(md.node_group)
                _set_gn_input(md, _find_socket_id(md, "Bone_prefix"), WN.PREFIX)
                _set_gn_input(md, _find_socket_id(md, "Bone Count"), seg_count[part])
                for i in range(1, seg_count[part] + 1):
                    if cp.vertex_groups.get(seg_bone(part, i)) is None:
                        cp.vertex_groups.new(name=seg_bone(part, i))
            md.show_viewport = md.show_render = True        # live, adaptive
        if not ob.hide_get():
            ob.hide_set(True)
            ob[ORIG_HIDDEN] = True
        made.append(cp.name)
    if prev_active is not None and prev_active.name in view_layer.objects:
        view_layer.objects.active = prev_active
    return {"rig": rig.name, "bones": len(data.bones) - 1,
            "segment_bones": len(spans), "copied_bones": len(copies), "meshes": made}


def clear(arm):
    for ob in bpy.data.objects:
        if ob.get(ORIG_HIDDEN) and ob.get(TAG) is None:
            ob.hide_set(False)
            del ob[ORIG_HIDDEN]
    removed = 0
    for ob in temp_objects(arm):
        data = ob.data
        ad = ob.animation_data
        act = ad.action if ad else None
        bpy.data.objects.remove(ob)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Armature):
                bpy.data.armatures.remove(data)
            elif isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
        if act is not None and act.users == 0:
            bpy.data.actions.remove(act)
        removed += 1
    coll = bpy.data.collections.get(COLL)
    if coll is not None and not coll.all_objects:
        bpy.data.collections.remove(coll)
    bpy.context.view_layer.update()
    return removed


def export(context, arm, fmt, filepath=None, keep=False):
    """fmt: 'FBX' (Unity) or 'GLB' (Godot). Returns the written path."""
    if not is_previewing(arm):
        build(context, arm)
    rig = bpy.data.objects[rig_name(arm)]
    scene = context.scene
    copies = [ob for ob in temp_objects(arm) if ob.type == 'MESH']
    # freeze weights on the copies (they are throwaway: drivers/sprites freeze too)
    for cp in copies:
        md = W.weight_modifier(cp, rig)
        if md is not None:
            ad = cp.animation_data
            if ad:
                for fc in [f for f in ad.drivers if f.data_path.startswith(f'modifiers["{md.name}"]')]:
                    ad.drivers.remove(fc)
            ok, msg = W.bake(cp, rig)
            if ok:
                cp.modifiers.remove(cp.modifiers[md.name])
    # bake the export rig's motion onto plain keys
    for ob in context.view_layer.objects:
        ob.select_set(False)
    rig.select_set(True)
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='POSE')
    for pb in rig.pose.bones:
        if hasattr(pb, "select"):
            pb.select = True
        else:
            pb.bone.select = True
    bpy.ops.nla.bake(frame_start=scene.frame_start, frame_end=scene.frame_end, only_selected=True,
                     visual_keying=True, clear_constraints=True, use_current_action=False,
                     bake_types={'POSE'})
    bpy.ops.object.mode_set(mode='OBJECT')
    if rig.animation_data and rig.animation_data.action:
        rig.animation_data.action.name = f"{arm.name}_{scene.name}"
    for ob in [rig] + copies:
        ob.select_set(True)
    folder = bpy.path.abspath(arm.gesturebone_props.export_path or "//export/")
    os.makedirs(folder, exist_ok=True)
    base = bpy.path.clean_name(f"{arm.name}_{os.path.splitext(os.path.basename(bpy.data.filepath))[0] or 'untitled'}")
    if fmt == 'FBX':
        path = filepath or os.path.join(folder, base + ".fbx")
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={'ARMATURE', 'MESH'},
                                 use_armature_deform_only=True, add_leaf_bones=False,
                                 apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y',
                                 bake_anim=True, bake_anim_use_all_actions=False,
                                 bake_anim_use_nla_strips=False, use_mesh_modifiers=True,
                                 mesh_smooth_type='FACE')
    else:
        path = filepath or os.path.join(folder, base + ".glb")
        bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True,
                                  export_apply=True, export_animations=True, export_skins=True,
                                  export_def_bones=True, export_yup=True,
                                  export_animation_mode='ACTIVE_ACTIONS')
    if not keep:
        clear(arm)
    return path
