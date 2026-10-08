"""
export/weight_nodes.py — add a "BDEF-" option to the Bone-weight-Linear group.

The group already has two branches picked by its Bone_prefix menu:
  DEF-  chain of <DEF><Module>.<ddd>.UP/.DOWN bones + EndL/EndR
  STR-  chain of <STR><Module>.<ddd>  bones (no UP/DOWN) + EndL/EndR
B-Bone spans (and exported segment bones) are a plain chain like STR-, so the
BDEF- branch is a copy of the STR- branch with the prefix set to "BDEF-":
  * parse_Bone_name's prefix menu gets a "BDEF-" item (value "BDEF-")
  * the STR- branch nodes (chain + EndL/EndR singles + their name parser) are
    duplicated with Bone_prefix = BDEF-
  * the top-level prefix menu switch gets a "BDEF-" item fed by the copy
Nothing in the DEF-/STR- branches changes. Idempotent.

Nodes are always re-fetched by NAME: creating nodes reallocates the node
array and invalidates held pointers (blender-api-pitfalls #1).
"""
import bpy

PREFIX = "BDEF-"
PARSE_GROUP = "parse_Bone_name"
TAG = "GB_BDEF"          # node name prefix for the copied branch


def _menu_item_names(node):
    return [i.name for i in node.enum_items]


def _ensure_parse_item(group_name=PARSE_GROUP):
    pg = bpy.data.node_groups.get(group_name)
    if pg is None:
        raise RuntimeError(f"node group '{group_name}' not found")
    name = next(n.name for n in pg.nodes if n.bl_idname == 'GeometryNodeMenuSwitch'
                and any("DEF-" in i for i in _menu_item_names(n)))
    node = pg.nodes[name]
    if PREFIX not in _menu_item_names(node):
        node.enum_items.new(PREFIX)
        pg.nodes[name].inputs[PREFIX].default_value = PREFIX
    return pg


def _str_branch(tree):
    """Names of the STR- branch nodes: chain group, name parser, EndL/EndR singles."""
    menu = next(n.name for n in tree.nodes if n.bl_idname == 'GeometryNodeMenuSwitch'
                and _menu_item_names(n)[:2] == ['STR-', 'DEF-'])
    chain = next(n.name for n in tree.nodes if n.bl_idname == 'GeometryNodeGroup' and n.node_tree
                 and n.node_tree.name == "Chain_bone_weight"
                 and "STR" in str(n.inputs["Bone_prefix"].default_value))
    parser = next(n.name for n in tree.nodes if n.bl_idname == 'GeometryNodeGroup' and n.node_tree
                  and n.node_tree.name == PARSE_GROUP and "STR" in str(n.inputs["Bone_prefix"].default_value)
                  and not n.inputs["Bone_Index"].is_linked)
    singles = []
    for link in tree.links:
        if link.from_node.name == parser and link.from_socket.name in ("EndL_Bone", "EndR_Bone"):
            for dst in _downstream(tree, link.to_node.name):
                if dst not in singles:
                    singles.append(dst)
    return menu, [chain, parser] + singles


def _downstream(tree, name):
    """Real (non-reroute) nodes reached from `name`, looking through reroutes."""
    node = tree.nodes[name]
    if node.bl_idname != 'NodeReroute':
        return [name]
    out = []
    for l in tree.links:
        if l.from_node.name == name:
            out += _downstream(tree, l.to_node.name)
    return out


def _upstream(tree, node_name, socket_id):
    """(real source node name, output identifier) feeding an input, through reroutes."""
    for l in tree.links:
        if l.to_node.name == node_name and l.to_socket.identifier == socket_id:
            if l.from_node.bl_idname == 'NodeReroute':
                return _upstream(tree, l.from_node.name, l.from_node.inputs[0].identifier)
            return l.from_node.name, l.from_socket.identifier
    return None


def has_bdef(tree):
    return any(n.name.startswith(TAG) for n in tree.nodes)


def ensure_bdef_branch(tree):
    """Add the BDEF- branch to a Bone-weight-Linear tree. Returns True if added."""
    _ensure_parse_item()
    if has_bdef(tree):
        return False
    menu_name, branch = _str_branch(tree)
    # 1. copy nodes (by name), remember old→new
    mapping = {}
    for old_name in branch:
        old = tree.nodes[old_name]
        new = tree.nodes.new(old.bl_idname)
        new_name = f"{TAG}_{old_name}"
        new.name = new_name
        new.label = f"BDEF {old.label or old_name}"
        mapping[old_name] = new_name
        old = tree.nodes[old_name]                 # re-fetch after nodes.new
        new = tree.nodes[new_name]
        if old.bl_idname == 'GeometryNodeGroup':
            new.node_tree = old.node_tree
        new.location = (old.location.x, old.location.y - 1400)
        for i, sock in enumerate(old.inputs):
            if hasattr(sock, "default_value") and i < len(new.inputs):
                try:
                    new.inputs[i].default_value = sock.default_value
                except (TypeError, AttributeError, ValueError):
                    pass
    for old_name, new_name in mapping.items():
        new = tree.nodes[new_name]
        if "Bone_prefix" in new.inputs:
            new.inputs["Bone_prefix"].default_value = PREFIX
        if "Bone_postfix_U/D" in new.inputs:
            new.inputs["Bone_postfix_U/D"].default_value = 'None'
    # 2. replicate every link that ENTERS a copied node
    links = []
    for name in mapping:
        for sock in tree.nodes[name].inputs:
            src = _upstream(tree, name, sock.identifier)
            if src:
                links.append((src[0], src[1], name, sock.identifier))
    for fn, fs, tn, ts in links:
        src_node = tree.nodes[mapping.get(fn, fn)]
        dst_node = tree.nodes[mapping[tn]]
        src = next(s for s in src_node.outputs if s.identifier == fs)
        dst = next(s for s in dst_node.inputs if s.identifier == ts)
        tree.links.new(src, dst)
    # 3. the branch's last geometry node feeds a new BDEF- menu item
    last = None
    for name in branch[2:]:
        n = tree.nodes[mapping[name]]
        if not any(l.from_node.name == n.name and l.to_node.name in mapping.values() for l in tree.links):
            last = n.name
    last = last or mapping[branch[0]]
    menu = tree.nodes[menu_name]
    if PREFIX not in _menu_item_names(menu):
        menu.enum_items.new(PREFIX)
    menu = tree.nodes[menu_name]
    tree.links.new(tree.nodes[last].outputs["Geometry"], menu.inputs[PREFIX])
    return True


def ensure_for_modifier(md):
    if md and md.node_group:
        return ensure_bdef_branch(md.node_group)
    return False
