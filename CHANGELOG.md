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

### Changed (Aug 2026)
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
