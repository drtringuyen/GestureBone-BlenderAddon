# Expression Bones — design

Per-bone sprite sheets for the Expression Sheet module. Replaces the single
scene-wide `Sheet` + `Cell N` pair with an explicit, per-armature registry of
expression bones, each owning its own sheet image and grid.

Status: **design agreed, not yet implemented.** Verified against Blender 5.2.0
LTS and `CHR_BongBong.blend` on 2026-09-02.

---

## 1. What exists today

| Thing | Where it lives |
|---|---|
| `sheet_image`, `grid_count`, `grid_size` | `scene.gesturebone_spritesheet` — one sheet for the whole scene |
| object cell pick | `ob["spritesheet_index"]` (raw IDProperty) |
| `exp_index` | `arm.pose.bones[n]["exp_index"]` (raw IDProperty), keyed CONSTANT by the E-key grid |
| which bones are expression bones | nothing — implicit, "whatever happens to carry the key" |

The shader node (`nodes.py`, `ShaderNodeCustomUVFromBoneShared`) reads
`exp_index` through an **object-property driver** at data path
`pose.bones["X"]["exp_index"]` and passes the scalar straight through. The
cell→UV division happens downstream in the material, not in the node.

### `ob["spritesheet_index"]` is dead — retire it

Swept `CHR_BongBong.blend` across objects, meshes, materials, node trees,
armatures, actions, scenes, shape keys and worlds, checking every driver's
`data_path`, every driver-variable target path, and every driver expression:

- Exists on exactly one datablock: `CHR_BongBong.Gesture`, value `7`.
- **Zero drivers reference it.** Written in one place and read in one place,
  both inside `ops_cell.py`, plus the button label in `ui.py`.

It is a closed loop with no downstream effect. The `Cell 7` and
`Active bone exp_index: 7` shown together in the panel are unrelated values
that coincidentally match — a UX trap, and a second reason to remove it.

### Accidental `exp_index` spill

9 bones carry `exp_index`; only 5 have shader nodes.

| has node | no node (spill) |
|---|---|
| EXP-Eye.L (7), EXP-Eye.R (7), EXP-Iris.L (6), EXP-Iris.R (5), EXP-Mouth (1) | DEF-Eye.L (6), DEF-Eye.R (5), DEF-Mouth (1), DEF-Head (1) |

The DEF values mirror their EXP counterparts exactly — the E-key grid keys
*every selected bone*, so DEF bones selected alongside their EXP counterparts
picked up the property. An explicit registry is the fix for this class of
problem.

---

## 2. Data model

```
Object (armature)
└── gesturebone_props                                  # shared/arm_props.py
    ├── chains                              (existing)
    ├── expression_bones : Collection[ExpressionBone]  # NEW
    │     ├── name         StringProperty   # = bone name, enables ["key"] lookup
    │     ├── bone         StringProperty   # pose-bone name
    │     ├── sheet_image  Pointer(Image)   # the per-bone "Sheet" field
    │     ├── grid_count   Int  (2..8)      # sheet layout, per bone
    │     ├── grid_size    Int  (0 = inherit scene)   # display px override
    │     └── ui_expanded  Bool
    └── active_expression_index : Int
└── pose.bones["EXP-Eye.L"]["exp_index"]               # UNCHANGED, raw IDProperty
```

```python
class GESTUREBONE_PG_ExpressionBone(PropertyGroup):
    name:        StringProperty(override={'LIBRARY_OVERRIDABLE'})
    bone:        StringProperty(override={'LIBRARY_OVERRIDABLE'})
    sheet_image: PointerProperty(type=bpy.types.Image,
                                 override={'LIBRARY_OVERRIDABLE'})
    grid_count:  IntProperty(default=4, min=2, max=8,
                             override={'LIBRARY_OVERRIDABLE'})
    grid_size:   IntProperty(default=0, min=0, max=200,   # 0 = use scene default
                             override={'LIBRARY_OVERRIDABLE'})
    ui_expanded: BoolProperty(default=False,
                              override={'LIBRARY_OVERRIDABLE'})
```

```python
expression_bones: CollectionProperty(
    type=GESTUREBONE_PG_ExpressionBone,
    override={'LIBRARY_OVERRIDABLE', 'USE_INSERTION'},  # INSERTION: add entries downstream
)
active_expression_index: IntProperty(default=0, min=0,
                                     override={'LIBRARY_OVERRIDABLE'})
```

Per-property `override={'LIBRARY_OVERRIDABLE'}` at class level is what commit
`0a0f369` established — permanent for all rigs, no per-file migration.

### `exp_index` is NOT duplicated into the PropertyGroup

It stays a raw pose-bone IDProperty. Three reasons:

1. It is already the driver data path every existing node and material depends
   on (5 live node instances in `CHR_BongBong`).
2. A raw IDProperty is the form that is both freely keyable *and* drivable from
   arbitrary other datablocks.
3. Two copies would desync, and the copy in the PropertyGroup would not be at
   the path the node reads.

The UI draws it live instead:

```python
row.prop(pb, '["exp_index"]', text="")   # keyable via right-click, one source of truth
```

### Why on the Object, not on `bpy.types.Armature`

Pose bones live on the Object. Keeping the list on the same datablock as the
values means an entry and the `exp_index` it points at are always in the **same
override** — no cross-boundary pointers to repair, unlike the problem
`riglinking/relink.py` exists to solve. It also stays correct when two armature
objects share one armature datablock (they would otherwise share one list while
holding divergent `exp_index` values).

### Why in `shared/arm_props.py`, not `expression_sheet/props.py`

`shared` is always registered; a module's `props.register()` does
`del bpy.types.Scene...` on toggle-off. Rig **data** must not disappear when the
module is toggled off in a downstream file. Same precedent as `chains`, which is
plotting-specific but lives in shared.

### Resolver

```python
def resolve_grid(arm_obj, bone_name):
    """(cell_px, grid_count, image) for this bone — entry first, scene fallback."""
    scn = bpy.context.scene.gesturebone_spritesheet
    e = find_entry(arm_obj, bone_name)
    if e is None:
        return scn.grid_size, scn.grid_count, scn.sheet_image
    return (e.grid_size or scn.grid_size,
            e.grid_count,
            e.sheet_image or scn.sheet_image)
```

The scene PropertyGroup survives as defaults for unregistered bones.

---

## 3. Linking and library overrides — verified behaviour

Tested by linking `CHR_BongBong.Gesture` from the real rig into an empty file,
running `override_hierarchy_create`, saving, and reopening.

| Test | Result |
|---|---|
| Override inherits the **linked, read-only action** | ✗ `keyframe_insert` → `False`, "not editable" |
| `keying_blocked_reason()` catches that case | ✓ detects it correctly — but no longer called by the pickers (it used to refuse to open the grid, making `E` look dead); kept as a diagnostic helper |
| After assigning a local action, key `exp_index` | ✓ |
| Keyed values survive save + reload | ✓ f1 → 2, f10 → 6 |
| Fcurve present on the override's local action | ✓ `pose.bones["EXP-Eye.L"]["exp_index"]` |
| Driver on a separate local object reading it | ✓ evaluates 2 @ f1, 6 @ f10 after reload |
| Static **unkeyed** value change | ✗ set 5 → reloaded as 1 (library value) |
| Same with `do_fully_editable=True` | ✗ still reverts |
| `relink_override_rigs()` on load | ✓ "relinked 2 override pointer(s)" |

**Requirement met:** `exp_index` can be keyed on an override and can drive other
things in the linked file, with no change to the current design.

### The unkeyed gap, and why the addon cannot close it

On Blender 5.2 there is **no scriptable way** to set the library-overridable
flag on a pose-bone custom property:

```
ob.property_overridable_library_set('["obj_level_prop"]', True)    → True   ✓
ob.is_property_overridable_library('pose.bones["X"]["exp_index"]') → "not found"
ob.is_property_overridable_library('pose.bones["X"].location')     → "not found"  ← valid path
ob.path_resolve('pose.bones["X"].location')                        → Vector(...)  ← resolves fine
bpy.ops.wm.properties_edit(...)        → RuntimeError: Direct execution not supported
[a for a in dir(pose_bone) if "overrid" in a]                      → []
pb.id_properties_ui("exp_index").as_dict()                         → no override key
```

`property_overridable_library_set` / `is_property_overridable_library` accept
only properties **directly on the ID**; nested paths are rejected even when
`path_resolve` handles them. `wm.properties_edit` — the operator behind the UI's
"Library Overridable" checkbox — is invoke-only.

So: a one-time manual tick per expression bone in the **source** rig
(right-click the property → Edit Property → Library Overridable), or accept that
only keyed values persist.

**Design consequence — do not skip this.** In the new per-bone panel, typing an
index is a static edit. On an override it will appear to work and then revert on
reload. The index field must **key on change** when
`arm_obj.override_library is not None`, or show an inline warning. Otherwise the
feature ships a silent data-loss trap.

### The image pointer

`sheet_image` is the only ID pointer in the feature. IDProperty-held ID pointers
are walked by Blender's dependency query, so linking the rig should pull the
image in as an indirect dependency. In `CHR_BongBong` the sheet
(`EXP_BongBong.png`, 8193×8193, `users=2`) is also referenced by the material,
which is a second guarantee. **Verify on the branch**; if it does not hold, add a
name fallback resolved through `bpy.data.images.get()`.

Note none of the images in the rig are packed — all are `//..\..\02.Texture\`
relative paths. Linking across drives will rely on those resolving.

---

## 4. Code changes

| File | Change |
|---|---|
| `shared/arm_props.py` | `GESTUREBONE_PG_ExpressionBone` + `expression_bones` / `active_expression_index` |
| `expression_sheet/props.py` | Keep scene PG as fallback; add `resolve_grid()` and `find_entry()` |
| `expression_sheet/grid.py` | Replace the `_grid_props(context)` hook with `_grid_settings(context)` returning the resolved triple — 3 call sites, all in `invoke()` |
| `expression_sheet/ops_pose_expr.py` | Per-bone settings; `_ensure_exp_index` also writes `id_properties_ui` (min 0, max `grid_count**2 - 1`, default 0, description) |
| `expression_sheet/ops_expr_bones.py` **(new)** | `expression_bone_add` (Pose mode, selected bones), `_remove`, `_move`, `_sync`, and `expression_cell_pick(bone=...)` opening the grid for one named bone with `key: BoolProperty(default=True)` |
| `expression_sheet/ui.py` | Foldout list; drop the object-level `Cell N` row |
| `expression_sheet/ops_cell.py` | **Retire.** Keep `spritesheet_index` as a read-only fallback for old files, or delete outright |
| `expression_sheet/__init__.py` | Register the new module file |
| `CHANGELOG.md` | Entry |

### Panel

```
Sprite Grid                Cell Size [96]
Expression Bones                        [+] [⟳ Sync]
  ▼ EXP-Eye.L                                [ 7 ]  [x]
      [🖼 EXP_BongBong.png     ][x]   Grid [4]
      [         Cell 7          ]
  ▶ EXP-Mouth                               [ 1 ]  [x]
```

Header carries the live `pb["exp_index"]` so it can be keyed without expanding.
Body row is the Image pointer with `exp_index` beside it.

---

## 5. Migration

`Sync` is the migration path: scan `pose.bones` for `exp_index`, create missing
entries, seed `sheet_image` from the scene fallback.

**Explicitly not a `load_post` auto-heal** — commit `0a0f369`'s auto-heal shipped
two regressions (crash on open; drivers aimed at the linked rather than the
override armature). Manual operator plus lazy ensure-on-write only.

For `CHR_BongBong`: Sync produces 9 entries, of which the 4 DEF bones are spill.
Offer removal of an entry **without** deleting the IDProperty by default —
fcurves and drivers reference it; deleting a keyed IDProperty orphans its
fcurves. Purge should be a separate, explicit action.

---

## 6. Risks

- **Bone rename orphans an entry.** Same failure class as the node-lookup rename
  issue. Handle visibly — `row.alert = entry.bone not in ob.pose.bones`, fixed by
  Sync. No silent auto-repair.
- **`grid_count` is picker-only.** The shader divides the UV using the
  material's own grid math; the node just passes the scalar through. Setting a
  bone to 8 here does **not** change the shader, and per-bone counts create a new
  chance to desync. Short term: a hint row. Later: drive the material's divisor
  from the same entry — separate work, out of scope here.
- **Unkeyed edits on an override revert.** See §3; the index field must key on
  change or warn.
- Keep clamps consistent: `grid_count` max 8 → 64 cells → the `exp_index`
  `id_properties_ui` max is `grid_count**2 - 1` per bone.
