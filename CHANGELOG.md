# Changelog

## [Unreleased]

See [ARCHITECTURE.md](ARCHITECTURE.md) for the current design.

### Architecture (unified rig model)
- **Two-rig model**: every armature is tagged `rig_type`
  (`PLOTTING` / `GESTURE` / `PRESET` / `NONE`). The PLOTTING rig (MetaRig) owns
  the chain definitions and runs rig generation; the GESTURE rig holds the
  CTRL bones for drawing/binding and back-points to its PLOTTING rig.
- **Unified data model**: a single `GESTUREBONE_PG_ChainDefinition`
  (`modules/shared/chain.py`) replaces the former `CurveBoneChain` and
  `MetaBoneSettings`. Per-armature `GESTUREBONE_PG_ArmatureProps` is registered
  as `Object.gesturebone_props` (replacing `gesturebone_gesture_draw_props` and
  the rig-generation scene props).
- **Module split**: former `gesture_draw` + `rig_generation` modules replaced
  by `modules/{shared,plotting,gesture}`. Module UI is drawn inline from
  `panels.py` (`draw_plotting_ui` / `draw_gesture_ui`) dispatched on
  `rig_type`; the panel stays on the GESTURE UI during a spline draw session.
- **Auto Rig** runs the full 11-step (+12a/b/c bind-mesh) pipeline end-to-end
  via a depsgraph handler; debug mode still exposes it step-by-step.

### UI (Aug 2026)
- Restored the compact "fine tune" panel look on the new backend: gesture
  cards use a double-height activate/toggle button with inline
  switch-direction/apply/delete icons and a slim smoothness + live-preview
  row; plotting shows a "Registration" box and a wide Auto Rig + icon cluster.
  Presentation-only; verified to draw on both Blender 5.1 and 5.2.

### Changed (Sep 2026)
- **Expression Sheet: picking a cell now keys the current frame only.** Both
  pickers (the Pose-mode `E` grid and the per-bone panel picker) used to write
  a second "backfill" key at `frame - 1` holding the previous value whenever
  the bone already had `exp_index` keys. On a CONSTANT channel that key bought
  nothing — the preceding key already holds its value up to the new one — and
  when the playhead sat on an existing key it silently overwrote the key one
  frame back. One pick is now one key, on `frame_current`.
- **Expression Sheet: removed the picker guards that blocked or mutated.** The
  `keying_blocked_reason()` pre-check refused to even open the grid on a
  linked/read-only action (so `E` looked dead), and `_force_constant()` in
  `_prepare` rewrote the interpolation of every existing key on the channel
  just for opening the picker — including when it was then cancelled with Esc.
  Both are gone; `_force_constant` still runs on commit so the new key stays a
  hard step. `keying_blocked_reason()` remains defined as a diagnostic helper.
  Trade-off: a read-only action now fails silently (Blender's console warning
  only) instead of raising an operator error.

### Added (Sep 2026)
- **Expression Sheet: per-bone sprite sheets ("Expression Bones").** The single
  scene-wide `Sheet` + `Cell N` pair is replaced by an explicit registry on the
  armature — `Object.gesturebone_props.expression_bones` — where each entry
  binds one pose bone to its own sheet image, grid count and (optional) picker
  cell size. The panel draws them as a foldout list with the bone's live
  `exp_index` beside each one. Scene settings remain as the fallback for
  unregistered bones and as the default cell size, which is a monitor-dependent
  viewing preference and so deliberately stays out of the rig.
  - The registry lives in `modules/shared/arm_props.py`, not in the module, so
    a downstream file that links the rig keeps the data even with the
    Expression Sheet module toggled off. Entries are keyed by bone NAME within
    the same Object that owns the pose bones, so nothing crosses a datablock
    boundary and library overrides need no pointer repair.
  - `exp_index` itself is unchanged — still a raw pose-bone custom property at
    `pose.bones["X"]["exp_index"]`, so every existing shader-node driver, action
    and keyframe keeps working. Verified by a real link + override + save +
    reload: keyed values persist and drive other datablocks correctly.
  - **Known limitation:** an *unkeyed* `exp_index` edit on a library override
    reverts to the library's value on reload, and the addon cannot prevent it —
    Blender exposes no scriptable way to mark a nested custom property
    library-overridable (`property_overridable_library_set` takes only
    ID-level paths; `wm.properties_edit` is invoke-only). The per-bone picker
    therefore always keys, and the panel warns when the armature is an
    override. The manual fix is one tick of "Library Overridable" in the Edit
    Property popup, per bone, in the source rig.
  - New `Sync Expression Bones` operator migrates rigs built before the
    registry: it registers every bone already carrying `exp_index`, normalises
    the property's UI range to the bone's own grid, and reports entries whose
    bone no longer exists rather than silently dropping them. Manual by design —
    the earlier load-time auto-heal (`0a0f369`) shipped two regressions.
  - Verified on `CHR_BongBong` in Blender 5.2: Sync registers and is idempotent,
    per-bone `grid_count` drives the `exp_index` UI clamp (max 15 at 4×4, 63 at
    8×8), removing an entry leaves the custom property intact for its f-curves,
    a bone renamed out from under an entry is reported and not dropped, and the
    panel keys through the header field (Blender shows it animated).
  - Note `grid_count` is picker-only — the material's own UV grid math is
    independent and must be kept in step by hand.
  - See [docs/expression-bones-design.md](docs/expression-bones-design.md).

### Removed (Sep 2026)
- **Expression Sheet: the per-object sprite-cell selector** (`ops_cell.py`,
  `gesturebone.spritesheet_select`, the `ob["spritesheet_index"]` property and
  the scene-level `chosen_index` fallback). A leftover from the standalone
  SpriteSheet script merged in `9bd8a1c`, it was never wired into the
  bone/`exp_index` design: the value was written and read only by itself, with
  no driver, node, bake or export consuming it. It also sat directly above the
  bone's `exp_index` in the panel showing an unrelated number, which read as if
  the two were the same thing.

### Changed (Aug 2026)
- **Expression Sheet: Pose-mode expression-grid hotkey is now user-rebindable.**
  The grid still defaults to `E` in Pose Mode, but the Expression Sheet panel
  now shows a live, clickable hotkey field next to "Pose Expression" backed by
  `wm.keyconfigs.user` (`ops_pose_expr.get_keymap_item()`), instead of a static
  "Press E" label. Needed because plain `E` is unusable on macOS, and
  Alt/Ctrl/Shift+E are already Blender's built-in keyframe-interpolation
  hotkeys, so no single alternate default works for everyone. Rebinding
  persists across restarts via Blender's normal preferences save, per Blender
  version/profile — it does not ship with the addon zip, so each install still
  starts at the `E` default.
- **Expression Sheet: UV From Bone (Shared) node graph packed into a float4.**
  Each instance used to need six satellite nodes (five `ShaderNodeAttribute`
  feeds, one per driven socket, plus a UV Map node) and 12 driver fcurves on
  every mesh using the material. Everything the bone contributes now travels
  as ONE float4 object custom property — `(loc.x, loc.y, rot.z, uniform
  scale)`, read back off a single Attribute node's `Vector` + `Alpha` outputs
  — plus a scalar exp index. `Location` / `Rotation` / `Scale` / `Mask
  Location` are reconstructed *inside* the shared group, where extra nodes
  cost nothing visually; `Mask Location` needs no transport at all, since it
  is the same bone's raw local XY recovered via a static (never driven)
  `Mask Sign` socket. The two Attribute feeds are collapsed, so they draw as
  pills rather than boxes.
  - Per instance: 6 satellite nodes → 3 (two collapsed); node face loses 3
    socket rows (`Amount` is gone — it was pinned to 1.0 and hidden, making
    its `Mix` an identity pass-through).
  - `CHR_LittlePig`: **780 → 325** object drivers, 30 → 15 feed nodes, 25 →
    10 custom properties, 5 → 2 attribute lookups per shading sample.
  - The float4 layout is deliberate: it maps 1:1 onto an engine-side `float4`
    if this rig is ever exported. (Drivers and object custom properties do not
    themselves survive FBX/glTF — this only makes the data model the right
    shape.)
  - **Behaviour change**: rotation X/Y, location Z and non-uniform scale are
    no longer driven. Only rotation Z, location XY and a uniform scale (the
    mean of the bone's local X and Y scale) affect a 2D UV. Verified
    pixel-identical to the old graph for everything inside that domain.
  - **Verified** on Blender 5.1 and 5.2: a synthetic probe renders the node's
    UV and Mask outputs across a fixed pose sweep, and old-vs-new EXRs match
    to 1e-6 (5.1-on-new vs 5.2-on-old included). On a copy of the real
    character file the migration preserves every authored socket value, every
    UV Map layer choice and all downstream wiring, and is idempotent. Fresh
    link + `make_override_library()` completes in 0.02s (27 overrides, no
    hang) with every driver retargeted to the local override armature, and
    posing the override bone moves the driven value.

- **Shared group is versioned** (`gb_uvfb_version` custom property).
  `upgrade_shared_tree()` rebuilds an old group **in place on the same
  datablock**, so no instance has to be re-pointed and no old tree has to be
  deleted (a custom-group node's user count is not a reliable basis for
  deletion). Because rebuilding the interface destroys every instance's socket
  values *and links*, the upgrade snapshots and restores authored values,
  incoming links and downstream links first — keyed by name, with endpoints on
  other nodes recorded by socket index since names there are not unique.
  A **linked** group is never touched: it belongs to a library that may still
  be running the old addon, so instances referencing it keep being driven in
  the v1 five-property shape by `_build_drivers_v1`. Verified by linking the
  untouched v1 production file into a fresh file under the new addon: it stays
  on v1 (780 drivers, legacy property names) and still animates correctly.

### Added (Aug 2026)
- **"Tidy Expression Node & Driver" operator** (`gesturebone.tidy_expression_node_driver`),
  a button in the Shader Editor's GestureBone tab, enabled only when the
  active node is a `UV From Bone (Shared)` node. One click:
  - Renames the driven custom-property keys on every mesh, and the UV
    Map/Attribute feed nodes' labels, from the generic Blender counter name
    (`UV From Bone.009`) to the bone the instance is wired to (`EXP-Iris.L`).
    **`node.name` itself is left untouched** — it's the stable lookup
    identity `_ensure_attr_feed`/`_remove_attr_feeds`/the orphan-sweep timer
    already key off; renaming it would orphan-and-duplicate feed nodes on
    the next unrelated refresh (armature/bone repick, invert-flag toggle,
    load-time self-heal). A hidden per-node marker
    (`node["_gb_key_ident"]`, see `_instance_key_ident()`) tracks which
    identity is currently baked into the mesh's property keys, defaulting to
    `node.name` so untouched instances behave exactly as before.
  - Property key order is `{bone}::{tree name}::{socket}` — bone first, not
    last — because Blender's N-panel property list truncates long names in
    the *middle*, so front and back survive and the middle gets eaten. Bone
    name up front means it survives truncation instead of the tree-name
    boilerplate. The cleanup sweep matches both this and the pre-reorder
    ordering, so a file with properties from either format never ends up
    with duplicates after a rebuild.
  - Groups the node + its own feed nodes into a dedicated `NodeFrame`
    labeled with the bone name — identified by a fixed name
    (`node.name + "__Frame"`), never by "whatever frame the node happens to
    already be parented to," so it can't hijack/relabel an unrelated shared
    frame a material author built for their own layout.
  - Attribute feeds collapse to pills (every unlinked socket hidden, then
    the node itself collapsed); the UV Map feed is left open since its
    UV-layer picker is worth reaching without expanding it. The satellite
    column is vertically centered on the main node's actual drawn height
    (`node.dimensions.y`), re-derived from the main node's now-frame-relative
    location every run (a node's `.location` is relative to its parent
    frame, not tree-absolute — the reason an earlier pass at this piled
    every satellite on top of each other the instant they were parented).
  - Re-running is idempotent: same frame reused, same 1:1 satellite count,
    no drift, whether or not the naming needed any work that pass.
  - Verified against the real `CHR_LittlePig.blend` production file on all
    5 existing node instances.

- ⚠️ **Known-fixed-but-re-verify: file restart used to auto-scatter every UV
  From Bone (Shared) instance's satellite nodes out of their Tidy frame.**
  Root cause: `refresh_uv_from_bone_shared()` runs automatically on every
  file load (the existing legacy-driver self-heal pass) and used to
  unconditionally delete-then-recreate every Attribute feed node on every
  call — including ones that needed no change at all. A freshly recreated
  node has no `.parent`, so a satellite that had been grouped into its
  owner's Tidy frame lost that grouping the moment the file was reopened;
  worse, its position (computed from the owner's now-frame-relative
  `.location`, but applied with no frame of its own to be relative *to*)
  landed it in a completely different part of the canvas. `_ensure_attr_feed`
  also reset `.location` unconditionally on every call, even when reusing an
  existing node, so simply stopping the deletion alone wasn't sufficient.
  - Fix: `_remove_attr_feeds()` now takes `keep_suffixes` and leaves the
    CURRENT schema's own feed nodes completely untouched (only a genuinely
    different schema's leftovers get swept); `_ensure_attr_feed()` only
    re-parents/labels on every call but only sets `.location` at actual
    creation time, never on reuse.
  - **Verified this session** via repeated simulated reloads
    (`migrate_legacy_drivers()` called 3× in a row against the live
    `CHR_LittlePig.blend` file) — parent/position/hide state came back
    byte-identical every time, driver targets and property values confirmed
    correct, and a Shader Editor screenshot confirmed the visual result.
  - **Not yet verified via an actual Blender close-and-reopen of a saved
    file** — only via live in-memory simulation of the load-time self-heal
    pass. A mid-session discovery this same day found that this addon's
    hot-reload path can silently leave STALE BYTECODE running despite the
    `.py` files on disk being current (see
    [[blender-api-pitfalls]] item 8) — which invalidated some of this same
    session's earlier "verified" claims until caught and corrected. Treat
    this fix as strong-but-not-final until someone actually closes and
    reopens a real `.blend` file with tidied nodes and confirms the layout
    survives.

### Fixed (Aug 2026)
- **Auto Rig broke on Blender 5.2 (GN modifier inputs moved off ID-properties)**:
  5.2 stopped exposing Geometry Nodes modifier inputs as plain ID-properties on
  the modifier (`mod["Socket_6"]`) and moved them to
  `mod.properties.inputs.Socket_6.value`. The old form now raises
  `TypeError: id properties not supported for this type`. This surfaced three
  ways, only the first of which was visible:
  - **Hard crash**: `_sync_gesture_spline_gn` wrote sockets unguarded, so
    `load_chains` — and therefore Auto Rig's final step — aborted outright.
  - **Silent no-op rebinding**: the four socket-walking loops in
    `plotting/ops_steps.py` (steps 2, 8, 10, 11) *read* via
    `mod[item.identifier]` inside `except (KeyError, TypeError): continue`.
    Every socket therefore raised and was skipped, so template references were
    never rewritten. The generated rig kept `Module_name = "<12_Handles>"` and
    `Deform Armature = <12_Handles>.Rig`, which also pinned the hidden template
    armature into the character's modifier stack — that is why the plotting
    bones stayed visible at the origin.
  - **Silent no-op smoothness**: `_on_handle_smoothness_update` wrote inside a
    bare `except Exception: pass`, so `bone_handle_smoothness` never reached
    the modifier.

  Added `_gn_socket` / `_get_gn_input` / `_set_gn_input` in
  `shared/utils_gn.py` (5.2 path first, ID-property fallback for 5.1;
  `_set_gn_input` returns a bool instead of failing silently) and routed every
  call site through them. Panel entries in `interface.items_tree` carry an
  **int** identifier — previously swallowed by the `try/except` by accident —
  so the helpers reject non-`str` ids explicitly.

  Also fixed a third 5.2 change this exposed: **menu sockets take the item name,
  not its index**, so `Control MODE` failed with `expected a string enum, not
  int`. Added `CONTROL_MODE_GN_NAME` beside `CONTROL_MODE_GN_INT` and try
  name → int. Verified on `CHR_BongBong.blend`: Auto Rig runs clean and
  idempotently, `Module_name` → `Body`, `Deform Armature` → `CHR_BongBong`,
  `Control MODE` → `3 Points`, zero remaining template references. 5.1 goes
  through the legacy fallbacks (untested).
- **Expression Sheet (shared) hung Blender on Library Override**: a material
  node-tree driver targeting the gesture armature (the per-instance UV shift
  values) triggers a pathological loop in Blender 5.2's override resolver on
  this rig's dependency web (bisected: any single driver of this shape is
  enough, independent of node count). Fixed by moving the driven values off
  the material entirely — they now live as custom properties driven on every
  mesh object that uses the material (object-level drivers are
  override-safe), read back into the shader via a passive
  `ShaderNodeAttribute` (`OBJECT` type) wired into each node's own input
  sockets. Verified against a throwaway copy of the real character file:
  material node-tree drivers 60 → 0, `make_override_library()` completes
  (27 overrides) instead of hanging indefinitely.
- **`gesturebone.reload` crashed Blender 5.1**: it disabled the addon
  synchronously inside its own `execute()`, so Blender built the operator's
  report string against a freed RNA type (`WM_operator_pystring` null-deref).
  Now deferred to a `bpy.app.timers` callback and marked `INTERNAL`.
- **Chain/armature properties couldn't be edited on a library-overridden
  armature**: `GESTUREBONE_PG_ChainDefinition`, `GESTUREBONE_PG_BoneName`, and
  `GESTUREBONE_PG_ArmatureProps` only tagged their `PointerProperty` fields
  `override={'LIBRARY_OVERRIDABLE'}`; every other field (`ui_expanded`,
  `part_name`, `control_mode`, `is_bound`, `show_debug_steps`, `rig_type`,
  etc.) was locked read-only once the owning armature was an override
  data-block (e.g. the chain-list foldout couldn't expand). Added the tag to
  every user-editable property in all three classes, plus `USE_INSERTION` on
  `control_bones` to match `chains`. This is declared on the class definition
  itself, so it applies to every armature — old or new — without any
  per-file migration.
- **Expression Sheet hang reappeared on the real production file**: the
  object-level-driver fix above was deployed in code but only ever *run* on a
  throwaway test copy, never on the actual `CHR_LittlePig.blend` — so linking
  it still carried the original 60 material node-tree drivers and hung
  `make_override_library()` again. Migrated and saved the real file (60 → 0
  material drivers, → 780 object drivers; override then completes in ~0.04s,
  27 overrides). More importantly, added a `persistent` `load_post` handler
  (`migrate_legacy_drivers` / `_migrate_on_load` in
  `modules/expression_sheet/nodes.py`, mirroring the existing pattern in
  `modules/riglinking/__init__.py`) that force-refreshes every
  `UVFromBoneShared` node on **every file open**, not just when a node
  property changes. Closes the gap where a file could be opened and
  overridden before ever triggering the old lazy self-heal.

### Tooling (Aug 2026)
- **`install.py`** deploys to a list of Blender versions (`["5.1", "5.2"]`;
  `None` auto-detects every version that already has the addon) instead of a
  single hardcoded folder, then hot-reloads the running Blender over the MCP
  socket. Fixes edits landing in a version Blender wasn't running.
