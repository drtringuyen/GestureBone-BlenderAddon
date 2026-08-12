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
- **`gesturebone.reload` crashed Blender 5.1**: it disabled the addon
  synchronously inside its own `execute()`, so Blender built the operator's
  report string against a freed RNA type (`WM_operator_pystring` null-deref).
  Now deferred to a `bpy.app.timers` callback and marked `INTERNAL`.

### Tooling (Aug 2026)
- **`install.py`** deploys to a list of Blender versions (`["5.1", "5.2"]`;
  `None` auto-detects every version that already has the addon) instead of a
  single hardcoded folder, then hot-reloads the running Blender over the MCP
  socket. Fixes edits landing in a version Blender wasn't running.
