"""Build the 'Snake Wiggle' Geometry Nodes group (v4, bone-pinned) + a demo scene.

Headless, fresh file (Blender 5.2):
  blender.exe --background --factory-startup --python build_snake_wiggle.py -- <out.blend>
Live upgrade of an open older file (run inside Blender, e.g. over MCP):
  ns = {"__name__": "snake_wiggle_lib"}; exec(open(r"<this file>").read(), ns); ns["upgrade_live"]()

Model (v4)
----------
The input mesh lies straight along its local X axis (head = -X end), body parameter u in [0,1].
Axis = a bone (Bone Info node): pin 1 = bone head, pin 2 = bone tail, the wave swings on bone Z.
Pin 2 sits at u = Pin At, so the body from the head to Pin At is stretched to span the bone exactly;
the tail past Pin At continues the same wave (same phase and fade) beyond the bone tail.
Centerline in axis coords (x along bone Y, y along bone Z), t in [0,1]:
  phi(t) = 2pi * (Waves * cumsum(1/lambda)(t) / cumsum(1/lambda)(Pin At) - Phase)
  x_lin  = t * BoneLength / Pin At
  win(t) = Envelope(min(t / Pin At, 1)) * [Tail Follows Body ? 1 : smoothstep(|t - Pin At| / Pin Softness)]
           Envelope = ONE Float Curve over head..bone tail (node group "SW Envelope Curve");
           past the bone tail the tail holds the curve's end value
  Meander x = x_lin - win*r*c*sin(2phi)*min(1, A/c),  y = win * A * sin(phi)
  Sine    x = x_lin,                                y = win * A * sign(s)|s|^(1/(1+3r))
Pin correction (local): the curve's offset at each pin is subtracted only within Pin Softness of
that pin (smoothstep), and held constant past pin 2. Both pins land exactly, the tail continues the
body wave, and the peaks in the middle keep their true extremes while Phase moves.
The mesh samples the centerline by point index (not arc length), so both pins land exactly.
Every "End" factor fades its parameter as   value(u) = start * lerp(1, End, Fade(u)),
where Fade is ONE shared Float Curve (node group "SW Fade Curve") - edit it to reshape all fades.
Without a valid Armature/Bone the axis falls back to the mesh's own X line, wave on local Z.
"""
import bpy, bmesh, math, sys

GROUP = "Snake Wiggle"
FADE = "SW Fade Curve"
ENVELOPE = "SW Envelope Curve"
START_OLD = "SW Start Curve"   # v3, replaced by the envelope


# ----------------------------------------------------------------------------- tiny node DSL
class Builder:
    def __init__(self, ng):
        self.ng = ng
        self.frame = None

    def node(self, idname, label=None, **props):
        n = self.ng.nodes.new(idname)
        for k, v in props.items():
            setattr(n, k, v)
        if label:
            n.label = label
        if self.frame:
            n.parent = self.frame
        return n

    def section(self, name):
        f = self.ng.nodes.new("NodeFrame")
        f.label = name
        f.label_size = 28
        self.frame = f
        return f

    def feed(self, val, sock):
        if val is None:
            return
        if isinstance(val, bpy.types.NodeSocket):
            self.ng.links.new(val, sock)
        else:
            sock.default_value = val

    def math(self, op, a, b=None, c=None, label=None):
        n = self.node("ShaderNodeMath", label, operation=op)
        for i, v in enumerate((a, b, c)):
            self.feed(v, n.inputs[i])
        return n.outputs[0]

    def vmath(self, op, a, b=None, scale=None, label=None):
        n = self.node("ShaderNodeVectorMath", label, operation=op)
        self.feed(a, n.inputs[0])
        if b is not None:
            self.feed(b, n.inputs[1])
        if scale is not None:
            self.feed(scale, n.inputs["Scale"])
        out = "Value" if op in {"DOT_PRODUCT", "LENGTH", "DISTANCE"} else "Vector"
        return n.outputs[out]

    # shortcuts
    def add(self, a, b): return self.math("ADD", a, b)
    def sub(self, a, b): return self.math("SUBTRACT", a, b)
    def mul(self, a, b): return self.math("MULTIPLY", a, b)
    def div(self, a, b): return self.math("DIVIDE", a, b)

    def lerp1(self, end, f):
        """lerp(1, end, f) = 1 + (end - 1) * f"""
        return self.math("MULTIPLY_ADD", self.sub(end, 1.0), f, 1.0)

    def xyz(self, x=0.0, y=0.0, z=0.0):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.feed(v, n.inputs[i])
        return n.outputs[0]

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.feed(v, n.inputs[0])
        return n.outputs

    def menu_switch(self, data_type, menu, items, label=None):
        """items: list of (name, value). Returns output socket."""
        n = self.node("GeometryNodeMenuSwitch", label, data_type=data_type)
        while len(n.enum_items) < len(items):
            n.enum_items.new("x")
        for i, (name, _) in enumerate(items):
            n.enum_items[i].name = name
        self.feed(menu, n.inputs["Menu"])
        for i, (_, val) in enumerate(items):
            self.feed(val, n.inputs[i + 1])
        return n.outputs[0]


# ----------------------------------------------------------------------------- fade curve group
def build_fade_group():
    ng = bpy.data.node_groups.new(FADE, "GeometryNodeTree")
    ng.description = "Shared fade shape for every End factor. 0 = start of body, 1 = tail"
    ng.interface.new_socket("Value", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Fade", in_out="OUTPUT", socket_type="NodeSocketFloat")
    gi = ng.nodes.new("NodeGroupInput"); gi.location = (-300, 0)
    go = ng.nodes.new("NodeGroupOutput"); go.location = (300, 0)
    fc = ng.nodes.new("ShaderNodeFloatCurve"); fc.label = "Fade Shape (edit me)"
    fc.width = 240
    curve = fc.mapping.curves[0]
    # holds the start size, then fades faster toward the tail (ease-in)
    curve.points[0].location = (0.0, 0.0)
    curve.points[1].location = (1.0, 1.0)
    curve.points.new(0.5, 0.22)
    fc.mapping.update()
    ng.links.new(gi.outputs[0], fc.inputs["Value"])
    ng.links.new(fc.outputs[0], go.inputs[0])
    return ng


def build_envelope_group():
    ng = bpy.data.node_groups.new(ENVELOPE, "GeometryNodeTree")
    ng.description = "Amplitude envelope from the head (0) to the bone tail (1). The tail holds the end value"
    ng.interface.new_socket("Value", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Envelope", in_out="OUTPUT", socket_type="NodeSocketFloat")
    gi = ng.nodes.new("NodeGroupInput"); gi.location = (-300, 0)
    go = ng.nodes.new("NodeGroupOutput"); go.location = (300, 0)
    fc = ng.nodes.new("ShaderNodeFloatCurve"); fc.label = "Envelope Shape (edit me)"
    fc.width = 240
    curve = fc.mapping.curves[0]
    # rise from the head, plateau, ease down toward the bone tail (end > 0 keeps the tail moving)
    curve.points[0].location = (0.0, 0.0)
    curve.points[1].location = (1.0, 0.3)
    for x, y in ((0.3, 0.95), (0.5, 1.0), (0.75, 0.9)):
        curve.points.new(x, y)
    fc.mapping.update()
    ng.links.new(gi.outputs[0], fc.inputs["Value"])
    ng.links.new(fc.outputs[0], go.inputs[0])
    return ng


# ----------------------------------------------------------------------------- main group
def build_group(fade_ng=None, env_ng=None):
    fade_ng = fade_ng or bpy.data.node_groups.get(FADE) or build_fade_group()
    env_ng = env_ng or bpy.data.node_groups.get(ENVELOPE) or build_envelope_group()
    ng = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
    ng.is_modifier = True
    ng.description = ("Bend a straight mesh lying along local X into a snake wave pinned to a bone: "
                      "head at the bone head, Pin At at the bone tail. Head = -X end")
    itf = ng.interface

    def sock(name, stype, default=None, lo=None, hi=None, sub=None, parent=None, desc=""):
        s = itf.new_socket(name, in_out="INPUT", socket_type=stype, parent=parent)
        if sub:
            s.subtype = sub
        if default is not None:
            s.default_value = default
        if lo is not None:
            s.min_value = lo
        if hi is not None:
            s.max_value = hi
        s.description = desc
        return s

    itf.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    itf.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    p_bone = itf.new_panel("Bone")
    sock("Armature", "NodeSocketObject", parent=p_bone, desc="Armature holding the axis bone")
    sock("Bone", "NodeSocketString", "", parent=p_bone,
         desc="Axis bone: snake head pinned at its head, Pin At pinned at its tail, wave on its Z")

    p_wave = itf.new_panel("Wave")
    sock("Waves", "NodeSocketInt", 4, 0, 64, parent=p_wave,
         desc="Full waves between the two pins (bone head to bone tail)")
    sock("Phase", "NodeSocketFloat", 0.0, parent=p_wave,
         desc="Slides the waves along the body (1 = one full wave); the pins stay put. Keyframe it")
    sock("Amplitude", "NodeSocketFloat", 1.0, 0.0, sub="DISTANCE", parent=p_wave,
         desc="Full size of the waves along bone Z (shaped by node group 'SW Envelope Curve')")

    p_shape = itf.new_panel("Shape")
    shape_s = sock("Shape", "NodeSocketMenu", parent=p_shape,
                   desc="Meander: poles bulge and necks overhang. Sine: plain wave with rounded poles")
    sock("Roundness", "NodeSocketFloat", 0.8, 0.0, 1.0, sub="FACTOR", parent=p_shape,
         desc="How round / bulb-shaped the poles are. Meander overhangs above ~0.5")

    p_pin = itf.new_panel("Pins")
    sock("Pin At", "NodeSocketFloat", 0.85, 0.5, 1.0, sub="FACTOR", parent=p_pin,
         desc="Fraction of the body from the head to pin 2 (bone tail). The rest is tail past the bone")
    sock("Tail Follows Body", "NodeSocketBool", True, parent=p_pin,
         desc="On: the wave passes through the bone tail at its natural slope and the tail continues it. "
              "Off: the wave is squeezed flat onto the axis at the bone tail")
    sock("Pin Softness", "NodeSocketFloat", 0.08, 0.005, 0.5, sub="FACTOR", parent=p_pin,
         desc="How much of the body next to each pin bends to meet it "
              "(and, with Tail Follows Body off, how wide the squeeze at the bone tail is)")

    p_fade = itf.new_panel("Fade to Tail")
    sock("Amplitude End", "NodeSocketFloat", 0.4, 0.0, 1.0, sub="FACTOR", parent=p_fade,
         desc="Amplitude at the tail, as a factor of the start")
    sock("Wavelength End", "NodeSocketFloat", 0.55, 0.0, 1.0, sub="FACTOR", parent=p_fade,
         desc="Wave length at the tail, as a factor of the start (smaller = tighter waves)")
    sock("Roundness End", "NodeSocketFloat", 0.6, 0.0, 1.0, sub="FACTOR", parent=p_fade,
         desc="Roundness at the tail, as a factor of the start")
    sock("Thickness End", "NodeSocketFloat", 0.25, 0.0, 1.0, sub="FACTOR", parent=p_fade,
         desc="Body thickness at the tail, as a factor of the start")

    p_body = itf.new_panel("Body")
    sock("Thickness", "NodeSocketFloat", 1.0, 0.0, 10.0, parent=p_body,
         desc="Cross-section scale at the head")

    p_set = itf.new_panel("Settings", default_closed=True)
    sock("Resolution", "NodeSocketInt", 512, 16, 8192, parent=p_set,
         desc="Centerline points. Raise for many waves")

    B = Builder(ng)
    gi = ng.nodes.new("NodeGroupInput")
    go = ng.nodes.new("NodeGroupOutput")
    I = gi.outputs

    def fade(v):
        n = B.node("GeometryNodeGroup", "Fade")
        n.node_tree = fade_ng
        B.feed(v, n.inputs[0])
        return n.outputs[0]

    def switch(kind, cond, false, true):
        n = B.node("GeometryNodeSwitch", input_type=kind)
        B.feed(cond, n.inputs[0]); B.feed(false, n.inputs[1]); B.feed(true, n.inputs[2])
        return n.outputs[0]

    def sample(geo, value, index, kind="FLOAT"):
        n = B.node("GeometryNodeSampleIndex", data_type=kind, domain="POINT", clamp=True)
        B.feed(geo, n.inputs["Geometry"]); B.feed(value, n.inputs["Value"]); B.feed(index, n.inputs["Index"])
        return n.outputs[0]

    def smooth01(v, width):
        n = B.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP", clamp=True)
        B.feed(v, n.inputs["Value"]); B.feed(0.0, n.inputs["From Min"]); B.feed(width, n.inputs["From Max"])
        return n.outputs["Result"]

    def xform(kind, vec, matrix):
        n = B.node("FunctionNodeTransform" + kind)
        B.feed(vec, n.inputs[0]); B.feed(matrix, n.inputs[1])
        return n.outputs[0]

    def position():
        return B.node("GeometryNodeInputPosition").outputs[0]

    # ---- measure the straight mesh along X
    B.section("Measure mesh along X")
    px = B.sep(position())[0]
    st = B.node("GeometryNodeAttributeStatistic", data_type="FLOAT", domain="POINT")
    B.feed(I["Geometry"], st.inputs["Geometry"]); B.feed(px, st.inputs["Attribute"])
    xmin = st.outputs["Min"]
    L = B.math("MAXIMUM", st.outputs["Range"], 1e-4, label="Mesh Length")

    # ---- axis from the bone, in this mesh's object space
    B.section("Bone axis: head, tail, Z")
    bi = B.node("GeometryNodeBoneInfo", transform_space="RELATIVE")
    B.feed(I["Armature"], bi.inputs["Armature"]); B.feed(I["Bone"], bi.inputs["Bone Name"])
    bh = xform("Point", (0.0, 0.0, 0.0), bi.outputs["Pose"])
    bt = xform("Point", B.xyz(0.0, bi.outputs["Rest Length"], 0.0), bi.outputs["Pose"])
    bz = xform("Direction", (0.0, 0.0, 1.0), bi.outputs["Pose"])
    ok = B.node("FunctionNodeBooleanMath", operation="AND")
    B.feed(bi.outputs["Exists"], ok.inputs[0])
    B.feed(B.math("GREATER_THAN", B.vmath("DISTANCE", bh, bt), 1e-6), ok.inputs[1])
    ok = ok.outputs[0]
    H = switch("VECTOR", ok, B.xyz(xmin), bh)
    T = switch("VECTOR", ok, B.xyz(B.math("MULTIPLY_ADD", L, I["Pin At"], xmin)), bt)
    Z0 = switch("VECTOR", ok, (0.0, 0.0, 1.0), bz)
    Lb = B.vmath("DISTANCE", H, T)
    Yb = B.vmath("NORMALIZE", B.vmath("SUBTRACT", T, H))
    Zb = B.vmath("NORMALIZE", B.vmath("SUBTRACT", Z0,
                                      B.vmath("SCALE", Yb, scale=B.vmath("DOT_PRODUCT", Z0, Yb))))
    Xb = B.vmath("CROSS_PRODUCT", Yb, Zb)

    # ---- centerline wave in axis coords (x along bone, y along bone Z)
    B.section("Centerline wave (t = 0 head .. 1 tail)")
    line = B.node("GeometryNodeCurvePrimitiveLine")
    line.inputs["End"].default_value = (1, 0, 0)
    res = B.node("GeometryNodeResampleCurve")
    B.feed(line.outputs[0], res.inputs["Curve"]); B.feed(I["Resolution"], res.inputs["Count"])
    idx = B.node("GeometryNodeInputIndex").outputs[0]
    nm1 = B.sub(I["Resolution"], 1.0)
    t = B.div(idx, nm1)
    f = fade(t)
    rho = B.div(1.0, B.math("MAXIMUM", B.lerp1(I["Wavelength End"], f), 0.02))
    rho_v = B.mul(rho, B.math("LESS_THAN", idx, nm1))           # last point contributes 0
    acc = B.node("GeometryNodeAccumulateField", data_type="FLOAT", domain="POINT")
    B.feed(rho_v, acc.inputs["Value"])
    ip = B.math("ROUND", B.mul(I["Pin At"], nm1), label="Pin Index")
    p_eff = B.div(ip, nm1)
    acc_pin = B.math("MAXIMUM", sample(res.outputs[0], acc.outputs["Trailing"], ip), 1e-6)
    waves = B.math("MAXIMUM", I["Waves"], 0.0)
    phi = B.mul(2 * math.pi, B.sub(B.mul(waves, B.div(acc.outputs["Trailing"], acc_pin)), I["Phase"]))
    A = B.mul(I["Amplitude"], B.lerp1(I["Amplitude End"], f))
    r = B.mul(I["Roundness"], B.lerp1(I["Roundness End"], f))
    span = B.div(Lb, p_eff)                                      # axis length of the whole body
    # radians-to-length scale c = dx/dphi of the plain wave
    c = B.div(B.mul(span, acc_pin),
              B.math("MAXIMUM", B.mul(B.mul(2 * math.pi, waves), B.mul(rho, nm1)), 1e-4))
    env = B.node("GeometryNodeGroup", "Envelope")
    env.node_tree = env_ng
    B.feed(B.math("MINIMUM", B.div(t, B.math("MAXIMUM", p_eff, 1e-6)), 1.0), env.inputs[0])
    ramp = env.outputs[0]
    squeeze = smooth01(B.math("ABSOLUTE", B.sub(t, p_eff)), I["Pin Softness"])
    win = B.mul(ramp, switch("FLOAT", I["Tail Follows Body"], squeeze, 1.0))
    s = B.math("SINE", phi)
    x_lin = B.mul(t, span)
    Aw = B.mul(A, win)
    # Meander
    shift = B.mul(B.mul(B.mul(r, c), win),
                  B.mul(B.math("SINE", B.mul(phi, 2.0)),
                        B.math("MINIMUM", 1.0, B.div(A, B.math("MAXIMUM", c, 1e-6)))))
    p_meander = B.xyz(B.sub(x_lin, shift), B.mul(Aw, s))
    # Sine with rounded poles
    rounded = B.mul(B.math("SIGN", s), B.math("POWER", B.math("ABSOLUTE", s),
                                               B.div(1.0, B.math("MULTIPLY_ADD", r, 3.0, 1.0))))
    p_sine = B.xyz(x_lin, B.mul(Aw, rounded))
    p_raw = B.menu_switch("VECTOR", I["Shape"], [("Meander", p_meander), ("Sine", p_sine)], "Shape")
    sp1 = B.node("GeometryNodeSetPosition")
    B.feed(res.outputs[0], sp1.inputs["Geometry"]); B.feed(p_raw, sp1.inputs["Position"])

    # ---- pin correction: subtract each pin's offset only within Pin Softness of that pin (past pin 2
    # the pin-2 offset is held), so both pins land exactly, the tail continues the wave as one piece,
    # and the middle of the body is untouched - its peaks keep their extremes while Phase moves.
    B.section("Pin correction")
    raw = sp1.outputs[0]
    d0 = sample(raw, position(), 0, "FLOAT_VECTOR")
    dp = B.vmath("SUBTRACT", sample(raw, position(), ip, "FLOAT_VECTOR"), B.xyz(Lb))
    w0 = B.sub(1.0, smooth01(t, I["Pin Softness"]))
    w2 = smooth01(B.sub(t, B.sub(p_eff, I["Pin Softness"])), I["Pin Softness"])
    corr = B.vmath("ADD", B.vmath("SCALE", d0, scale=w0), B.vmath("SCALE", dp, scale=w2))
    sp2 = B.node("GeometryNodeSetPosition")
    B.feed(raw, sp2.inputs["Geometry"])
    B.feed(B.vmath("SUBTRACT", position(), corr), sp2.inputs["Position"])
    centerline = sp2.outputs[0]

    # ---- deform the mesh: body u -> centerline point index (not arc length), so the pins are exact
    B.section("Bend mesh along centerline, place on bone")
    lp = B.sep(position())
    u = B.math("MINIMUM", B.math("MAXIMUM", B.div(B.sub(lp[0], xmin), L), 0.0), 1.0)
    fi = B.mul(u, nm1)
    i0 = B.math("FLOOR", fi)
    fr = B.sub(fi, i0)
    i1 = B.math("MINIMUM", B.add(i0, 1.0), nm1)
    tan_field = B.node("GeometryNodeInputTangent").outputs[0]

    def lerp_sample(field):
        a = sample(centerline, field, i0, "FLOAT_VECTOR")
        b = sample(centerline, field, i1, "FLOAT_VECTOR")
        return B.vmath("ADD", a, B.vmath("SCALE", B.vmath("SUBTRACT", b, a), scale=fr))

    cP = B.sep(lerp_sample(position()))
    cT = B.sep(B.vmath("NORMALIZE", lerp_sample(tan_field)))
    # in-plane normal of the wave, in object space (bone Y = along, bone Z = wave)
    n_obj = B.vmath("ADD", B.vmath("SCALE", Yb, scale=B.mul(cT[1], -1.0)),
                    B.vmath("SCALE", Zb, scale=cT[0]))
    thick = B.mul(I["Thickness"], B.lerp1(I["Thickness End"], fade(u)))
    # mesh local Z -> wave normal, mesh local Y -> -bone X (keeps handedness)
    off = B.vmath("ADD", B.vmath("SCALE", Xb, scale=B.mul(B.mul(lp[1], thick), -1.0)),
                  B.vmath("SCALE", n_obj, scale=B.mul(lp[2], thick)))
    center = B.vmath("ADD", H, B.vmath("ADD", B.vmath("SCALE", Yb, scale=cP[0]),
                                       B.vmath("SCALE", Zb, scale=cP[1])))
    sp3 = B.node("GeometryNodeSetPosition")
    B.feed(I["Geometry"], sp3.inputs["Geometry"])
    B.feed(B.vmath("ADD", center, off), sp3.inputs["Position"])
    ng.links.new(sp3.outputs[0], go.inputs[0])

    # menu defaults (items exist once the menu sockets are linked)
    shape_s.default_value = "Meander"
    layout(ng, gi, go)
    return ng


def layout(ng, gi, go):
    """Column = longest path from inputs, rows stacked per frame; frames stacked vertically."""
    nodes = [n for n in ng.nodes if n.bl_idname not in {"NodeFrame"}]
    depth = {n: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for l in ng.links:
            a, b = l.from_node, l.to_node
            if a.bl_idname == "NodeGroupInput":
                continue
            if depth[b] < depth[a] + 1:
                depth[b] = depth[a] + 1; changed = True
        if not changed:
            break
    frames = [n for n in ng.nodes if n.bl_idname == "NodeFrame"]
    y0 = 0
    maxd = 0
    for fr in frames:
        members = [n for n in nodes if n.parent == fr]
        if not members:
            continue
        cols = {}
        for n in members:
            cols.setdefault(depth[n], []).append(n)
        rows = max(len(v) for v in cols.values())
        for dd, col in cols.items():
            for i, n in enumerate(col):
                n.location = (dd * 200, y0 - i * 170)
            maxd = max(maxd, dd)
        y0 -= rows * 170 + 160
    gi.location = (-300, 0)
    go.location = ((maxd + 1) * 200, 0)


# ----------------------------------------------------------------------------- demo scene
def demo_tube(name, length=10.0, radius=0.25, rings=300, seg=16):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    loops = []
    for i in range(rings):
        x = -length / 2 + length * i / (rings - 1)
        loops.append([bm.verts.new((x, radius * math.cos(2 * math.pi * j / seg),
                                    radius * math.sin(2 * math.pi * j / seg))) for j in range(seg)])
    for a, b in zip(loops, loops[1:]):
        for j in range(seg):
            bm.faces.new((a[j], a[(j + 1) % seg], b[(j + 1) % seg], b[j]))
    bm.faces.new(list(reversed(loops[0])))
    bm.faces.new(loops[-1])
    bm.normal_update()
    bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def demo_rig(name="SnakeRig", bone="Spine", head=(-5.0, 0.0, 0.0), tail=(3.5, 0.0, 0.0)):
    """One-bone armature; bone along +X, roll 0 -> bone Z = world Z (the wave stands upright)."""
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(ob)
    ob.show_in_front = True
    prev = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones.new(bone)
    eb.head, eb.tail, eb.roll = head, tail, 0.0
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = prev
    return ob


def input_ids(ng):
    return {i.name: i.identifier for i in ng.interface.items_tree
            if getattr(i, "in_out", "") == "INPUT" and i.socket_type != "NodeSocketGeometry"}


def fcurves(ob):
    ad = ob.animation_data
    if not (ad and ad.action):
        return []
    return [fc for layer in ad.action.layers for strip in layer.strips
            for bag in strip.channelbags for fc in bag.fcurves]


def input_path(mod, sid):
    """Animation path of a GN modifier input. Blender 5.2 accepts the subscript form
    properties.inputs["Socket_N"]["value"] too, but then the modifier never re-evaluates when the
    value animates - only this attribute form (what the UI's Insert Keyframe uses) does."""
    return f'modifiers["{mod.name}"].properties.inputs.{sid}.value'


def key_phase(ob, mod, ng):
    """Phase 0 -> 1 over frames 1..49, linear, cycled."""
    pid = input_ids(ng)["Phase"]
    path = input_path(mod, pid)
    mod.properties.inputs[pid]["value"] = 0.0
    ob.keyframe_insert(path, frame=1)
    mod.properties.inputs[pid]["value"] = 1.0
    ob.keyframe_insert(path, frame=49)
    for fc in fcurves(ob):
        if fc.data_path == path:
            for k in fc.keyframe_points:
                k.interpolation = "LINEAR"
            if not fc.modifiers:
                fc.modifiers.new("CYCLES")


def upgrade_live(snake="Snake", rig_name="SnakeRig", bone="Spine"):
    """Swap an open file's older group for this version, keeping the user's values, curves and Phase keys."""
    old = bpy.data.node_groups[GROUP]
    ob = bpy.data.objects[snake]
    mod = next(m for m in ob.modifiers if m.type == "NODES" and m.node_group == old)
    old_ids = input_ids(old)
    vals = {n: mod.properties.inputs[i].get("value") for n, i in old_ids.items()}
    old.name = GROUP + " old"
    ng = build_group(bpy.data.node_groups.get(FADE), bpy.data.node_groups.get(ENVELOPE))
    mod.node_group = ng
    new_ids = input_ids(ng)
    # sockets are stored by identifier, so a new socket can inherit an unrelated old value:
    # give every new-only input its default, then restore the user's values by name
    items = {i.name: i for i in ng.interface.items_tree if getattr(i, "in_out", "") == "INPUT"}
    for n, i in new_ids.items():
        if n not in vals and hasattr(items[n], "default_value") and items[n].socket_type != "NodeSocketMenu":
            mod.properties.inputs[i]["value"] = items[n].default_value
    for n, v in vals.items():
        if n in new_ids and v is not None and n != "Phase":
            mod.properties.inputs[new_ids[n]]["value"] = v
    # Phase animation: repoint the old fcurve at the new socket id, in the attribute path form
    old_forms = (f'modifiers["{mod.name}"].properties.inputs["{old_ids["Phase"]}"]["value"]',
                 input_path(mod, old_ids["Phase"]))
    for fc in fcurves(ob):
        if fc.data_path in old_forms:
            fc.data_path = input_path(mod, new_ids["Phase"])
    rig = bpy.data.objects.get(rig_name) or demo_rig(rig_name, bone)
    mod.properties.inputs[new_ids["Armature"]]["value"] = rig
    mod.properties.inputs[new_ids["Bone"]]["value"] = bone
    if not any(m.node_group == old for o in bpy.data.objects for m in o.modifiers if m.type == "NODES"):
        bpy.data.node_groups.remove(old)
    stale = bpy.data.node_groups.get(START_OLD)
    if stale and stale.users == 0:
        bpy.data.node_groups.remove(stale)
    ob.update_tag()
    return ng


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[0] if argv else None
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    ng = build_group()

    mat = bpy.data.materials.new("Snake Orange")
    mat.diffuse_color = (1.0, 0.35, 0.05, 1.0)
    ob = demo_tube("Snake", radius=0.16)
    ob.data.materials.append(mat)
    mod = ob.modifiers.new("Snake Wiggle", "NODES")
    mod.node_group = ng
    rig = demo_rig()
    ids = input_ids(ng)
    mod.properties.inputs[ids["Armature"]]["value"] = rig
    mod.properties.inputs[ids["Bone"]]["value"] = "Spine"

    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 48
    key_phase(ob, mod, ng)
    sc.frame_set(1)

    if out:
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("SAVED", out)


if __name__ == "__main__":
    main()
