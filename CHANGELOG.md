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

### Fixed (Aug 2026)
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
