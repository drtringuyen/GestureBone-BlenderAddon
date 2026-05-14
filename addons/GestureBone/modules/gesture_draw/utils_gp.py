import re
import bpy
from collections import defaultdict


# ── GP2 / GP3 stroke compatibility ────────────────────────────────────────────

def _frame_strokes(gp_frame):
    """Return the strokes collection for a GP frame (GP2: frame.strokes, GP3: frame.drawing.strokes)."""
    if hasattr(gp_frame, 'strokes'):
        return gp_frame.strokes
    drawing = getattr(gp_frame, 'drawing', None)
    if drawing is not None:
        return getattr(drawing, 'strokes', None)
    return None


def _remove_matching_strokes(gp_frame, gp_obj, mat):
    """Remove strokes matching mat from a GP frame. Handles GP2 and GP3.

    GP3 (Blender 4.3+): drawing.remove_strokes(indices=[...])
    GP2            : strokes.remove(stroke) iterated in reverse
    """
    drawing = getattr(gp_frame, 'drawing', None)
    if drawing is not None and hasattr(drawing, 'remove_strokes'):
        indices = [
            i for i, s in enumerate(drawing.strokes)
            if mat is None or (
                s.material_index < len(gp_obj.material_slots) and
                gp_obj.material_slots[s.material_index].material == mat
            )
        ]
        if indices:
            drawing.remove_strokes(indices=indices)
        return
    # GP2 path
    strokes = _frame_strokes(gp_frame)
    if strokes is None:
        return
    to_remove = [
        s for s in strokes
        if mat is None or (
            s.material_index < len(gp_obj.material_slots) and
            gp_obj.material_slots[s.material_index].material == mat
        )
    ]
    for stroke in reversed(to_remove):
        strokes.remove(stroke)


def _copy_last_frame_strokes(chain, gp_obj, frame_num):
    """Copy strokes matching part_material from the nearest previous GP frame to frame_num.

    Only copies if the target frame has no matching strokes yet.
    Supports both GP2 (Blender < 4.3, frame.strokes) and GP3 (Blender 4.3+, frame.drawing).
    """
    mat = chain.part_material
    if not gp_obj:
        return

    def _stroke_matches(stroke):
        return (mat is None or (
            stroke.material_index < len(gp_obj.material_slots) and
            gp_obj.material_slots[stroke.material_index].material == mat
        ))

    for layer in gp_obj.data.layers:
        target_frame = next((f for f in layer.frames if f.frame_number == frame_num), None)
        if target_frame is not None:
            existing = _frame_strokes(target_frame)
            if existing and any(_stroke_matches(s) for s in existing):
                continue

        src_frame = None
        for f in sorted(layer.frames, key=lambda f: f.frame_number, reverse=True):
            if f.frame_number >= frame_num:
                continue
            strokes = _frame_strokes(f)
            if strokes and any(_stroke_matches(s) for s in strokes):
                src_frame = f
                break

        if src_frame is None:
            continue

        if target_frame is None:
            try:
                target_frame = layer.frames.new(frame_num)
            except Exception:
                continue

        # ── GP3 path ──────────────────────────────────────────────────────────
        src_drawing = getattr(src_frame, 'drawing', None)
        dst_drawing = getattr(target_frame, 'drawing', None)
        if src_drawing is not None and dst_drawing is not None and hasattr(dst_drawing, 'add_strokes'):
            for src in src_drawing.strokes:
                if not _stroke_matches(src):
                    continue
                try:
                    dst_drawing.add_strokes([len(src.points)])
                    dst = dst_drawing.strokes[-1]
                    for attr in ('material_index', 'cyclic', 'softness',
                                 'start_cap', 'end_cap', 'fill_opacity', 'fill_color', 'hide_stroke'):
                        try:
                            setattr(dst, attr, getattr(src, attr))
                        except Exception:
                            pass
                    for src_pt, dst_pt in zip(src.points, dst.points):
                        for pattr in ('position', 'radius', 'opacity', 'vertex_color', 'rotation'):
                            try:
                                setattr(dst_pt, pattr, getattr(src_pt, pattr))
                            except Exception:
                                pass
                except Exception:
                    pass
            continue

        # ── GP2 path ──────────────────────────────────────────────────────────
        if hasattr(target_frame, 'strokes') and hasattr(target_frame.strokes, 'new'):
            src_strokes = _frame_strokes(src_frame)
            if src_strokes is None:
                continue
            for src in src_strokes:
                if not _stroke_matches(src):
                    continue
                try:
                    dst = target_frame.strokes.new()
                    dst.material_index = src.material_index
                    for attr in ('line_width', 'use_cyclic'):
                        try:
                            setattr(dst, attr, getattr(src, attr))
                        except Exception:
                            pass
                    dst.points.add(len(src.points))
                    for i, pt in enumerate(src.points):
                        dst.points[i].co = pt.co
                        for pattr in ('pressure', 'strength'):
                            try:
                                setattr(dst.points[i], pattr, getattr(pt, pattr))
                            except Exception:
                                pass
                except Exception:
                    pass


def _copy_all_strokes_to_frame(src_gp_obj, dst_gp_obj, dst_layer_name, dst_frame_num):
    """Copy all GP3 strokes from every layer/frame of src_gp_obj into dst_layer at dst_frame_num."""
    dst_data = dst_gp_obj.data
    if not hasattr(dst_data, 'layers'):
        return
    target_layer = next((l for l in dst_data.layers if l.name == dst_layer_name), None)
    if target_layer is None:
        return
    target_frame = next((f for f in target_layer.frames if f.frame_number == dst_frame_num), None)
    if target_frame is None:
        target_frame = target_layer.frames.new(dst_frame_num)
    dst_drawing = getattr(target_frame, 'drawing', None)
    if dst_drawing is None:
        return
    src_data = src_gp_obj.data
    if not hasattr(src_data, 'layers'):
        return
    for src_layer in src_data.layers:
        for src_frame in src_layer.frames:
            src_drawing = getattr(src_frame, 'drawing', None)
            if src_drawing is None:
                continue
            for src in src_drawing.strokes:
                try:
                    dst_drawing.add_strokes([len(src.points)])
                    dst = dst_drawing.strokes[-1]
                    for attr in ('material_index', 'cyclic', 'softness',
                                 'start_cap', 'end_cap', 'fill_opacity', 'fill_color', 'hide_stroke'):
                        try:
                            setattr(dst, attr, getattr(src, attr))
                        except Exception:
                            pass
                    for src_pt, dst_pt in zip(src.points, dst.points):
                        for pattr in ('position', 'radius', 'opacity', 'vertex_color', 'rotation'):
                            try:
                                setattr(dst_pt, pattr, getattr(src_pt, pattr))
                            except Exception:
                                pass
                except Exception:
                    pass


def _count_strokes_at_frame(chain, gp_obj, frame_num):
    """Count strokes matching part_material at a specific GP frame number."""
    mat = chain.part_material
    if not gp_obj:
        return 0
    count = 0
    try:
        for layer in gp_obj.data.layers:
            for gp_frame in layer.frames:
                if gp_frame.frame_number != frame_num:
                    continue
                strokes = _frame_strokes(gp_frame)
                if strokes is None:
                    continue
                for stroke in strokes:
                    if mat is None or (
                        stroke.material_index < len(gp_obj.material_slots) and
                        gp_obj.material_slots[stroke.material_index].material == mat
                    ):
                        count += 1
    except Exception:
        pass
    return count


# ── GP layer join helpers (from join_curve_to_GreasePencil pipeline) ──────────

def _gp_base_name(name: str) -> str:
    """Strip trailing .001 / .002 ... suffix from a GP layer name."""
    return re.sub(r'\.\d+$', '', name)


def _consolidate_gp_layers(gp_data, target_layer_name: str):
    """Merge ALL layers in gp_data into one, rename it to target_layer_name.

    First layer wins on frame conflicts. Safe to call on GP objects with 1 layer.
    """
    layers = list(gp_data.layers)
    if not layers:
        return
    if len(layers) == 1:
        layers[0].name = target_layer_name
        return

    canonical = layers[0]
    canonical_frames = {f.frame_number for f in canonical.frames}

    for dup in layers[1:]:
        for fn in [f.frame_number for f in dup.frames]:
            if fn not in canonical_frames:
                src = dup.get_frame_at(fn)
                if src is None:
                    continue
                try:
                    nf = canonical.frames.new(fn)
                    nf.drawing = src.drawing
                    canonical_frames.add(fn)
                except Exception:
                    pass
        try:
            gp_data.layers.remove(dup)
        except Exception:
            pass

    canonical.name = target_layer_name


def _merge_duplicate_gp_layers(gp_data):
    """Move frames from layers whose names differ only by a numeric suffix (.001, .002 ...)
    into the canonical (un-suffixed) layer, then remove the duplicates.

    Canonical layer wins on frame conflicts.
    """
    groups: dict[str, list] = {}
    for layer in gp_data.layers:
        groups.setdefault(_gp_base_name(layer.name), []).append(layer)

    for base, layers in groups.items():
        if len(layers) < 2:
            continue

        canonical = next((l for l in layers if l.name == base), layers[0])
        canonical_frames = {f.frame_number for f in canonical.frames}

        for dup in [l for l in layers if l is not canonical]:
            for fn in [f.frame_number for f in dup.frames]:
                if fn not in canonical_frames:
                    src = dup.get_frame_at(fn)
                    if src is None:
                        continue
                    try:
                        nf = canonical.frames.new(fn)
                        nf.drawing = src.drawing
                        canonical_frames.add(fn)
                    except Exception:
                        pass
            try:
                gp_data.layers.remove(dup)
            except Exception:
                pass

        canonical.name = base


# ── Mesh-to-GP stroke extraction ──────────────────────────────────────────────

def _mesh_edge_chains(mesh):
    """Extract ordered vertex position lists from a mesh's edge graph.

    Each connected edge chain becomes one list[Vector].
    Open chains (degree-1 endpoints) are walked first; closed loops follow.
    Returns list of list[Vector] in local mesh space.
    """
    adj = defaultdict(list)
    for e in mesh.edges:
        v0, v1 = e.vertices[0], e.vertices[1]
        adj[v0].append(v1)
        adj[v1].append(v0)

    if not adj:
        return []

    visited = set()
    chains = []

    # Open chains start at degree-1 vertices; closed loops start anywhere
    endpoints = [v for v in adj if len(adj[v]) == 1]
    starts = endpoints if endpoints else list(adj.keys())

    for start in starts:
        if start in visited:
            continue
        chain, prev, cur = [], None, start
        while True:
            visited.add(cur)
            chain.append(mesh.vertices[cur].co.copy())
            nexts = [n for n in adj[cur] if n != prev and n not in visited]
            if not nexts:
                break
            prev, cur = cur, nexts[0]
        if len(chain) >= 2:
            chains.append(chain)

    return chains
