# GestureBone — Architecture

This document describes the addon as it exists after the **unified-rig
rearchitecture** (commit `25d470a`, "unified ChainDefinition, ArmatureProps")
and the follow-up UI/tooling work in August 2026. It supersedes the older
`module_*_operators.py` layout still referenced in some historical notes.

---

## 1. Mental model: two armature roles

GestureBone works with **two cooperating armatures** per character:

| Role | Example object | Holds | Purpose |
|------|----------------|-------|---------|
| **PLOTTING** rig (the "MetaRig") | `CHR_LittlePig` | META bones + the **chain definitions** | Rig generation — turns META bones into curve-driven control chains |
| **GESTURE** rig | `CHR_LittlePig.Gesture` | CTRL bones | Gesture drawing & binding — draw a spline, bake it onto the control bones |

Each armature is tagged by `arm.gesturebone_props.rig_type`, one of
`PLOTTING`, `GESTURE`, `PRESET` (a template shown in the *Create Rig*
dropdown), or `NONE` (untagged). A GESTURE rig stores a back-pointer to its
PLOTTING rig in `plotting_rig`; the chain definitions live **only** on the
PLOTTING rig, and each chain records which GESTURE rig owns its CTRL bones via
`chain.gesture_rig`.

The single source of truth for a body part is therefore one
`ChainDefinition` on the PLOTTING rig; the GESTURE UI reads those same chains
back through `_chains_for_gesture_rig()`.

---

## 2. Data model (`modules/shared/`)

The rearchitecture collapsed the two former property groups
(`CurveBoneChain` from gesture_draw and `MetaBoneSettings` from
rig_generation) into one.

### `shared/chain.py`
- **`GESTUREBONE_PG_ChainDefinition`** — one body part. Groups:
  - *Identity:* `part_name`, `active_tool` (DRAW/EDIT)
  - *Rig-gen config:* `atomic_chain` (template collection), `control_mode`
    (`PT_5`/`PT_3`/`PT_2`), `pivot_placement`, `bind_mesh`, `sample_mesh`
  - *Gesture/draw config:* `gesture_spline`, `control_bones`
    (collection of bone-name entries), `bone_handle_smoothness`,
    `plotting_spline`, `plotting_mode`
  - *Workflow state:* `gesture_rig` (pointer), `rig_completed_step`
    (0 = none … 11 = rigged, 12–14 = bind-mesh sub-steps), `is_bound`,
    `is_drawing`
  - *UI:* `ui_expanded`, `control_bones_expanded`
- **`GESTUREBONE_PG_BoneName`** — a single `bone: StringProperty` (with a
  CTRL-bone search callback); `control_bones` is a collection of these.
- Control-point counts map to CTRL bone indices via `_ctrl_bone_indices()`
  (`PT_5 → [0,1,2,3,4]`, `PT_3 → [0,2,4]`, `PT_2 → [0,2,4]`).

### `shared/arm_props.py`
- **`GESTUREBONE_PG_ArmatureProps`**, registered as
  `bpy.types.Object.gesturebone_props`. Holds `rig_type`, the `chains`
  collection + `active_chain_index`, global rig-gen settings
  (`meta_collection`, `atomic_chain`, `meta_rig_preset`), transient workflow
  state (`wip_*`, `last_step`, `completed_step`, `is_aligning`,
  `active_bone_name`), UI toggles (`meta_solo_mode`, `gesture_active`,
  `show_both_armatures`, …), and the GESTURE→PLOTTING `plotting_rig` pointer.

> Scene-level global props (`current_armature`, `debug_mode`,
> `extra_infos_mode`, `addon_version`) still live on
> `context.scene.gesturebone_props` (see `properties.py`).

### `shared/utils*.py`
- `utils.py` — context resolution (`_arm`, `_plotting_props`,
  `_chains_for_gesture_rig`, `_validate_plotting_rig`), collection
  management, and spline-object management. `_ensure_chain_objects()` creates
  and sorts per-chain curves into `{MetaRig}.GestureSplines` and
  `{MetaRig}.PlottingSplines` collections; `_cleanup_orphan_splines()` prunes
  unreferenced ones.
- `utils_gn.py` — Geometry-Nodes modifier helpers (`TOB-Gesture_drawing`
  sockets). **Note:** writes sockets via raw `mod["Socket_x"]` subscript —
  native on 4.x/5.1; on 5.2 this path may silently no-op (see §8).
- `utils_constraints.py`, `utils_bake.py` — constraint mute/exist checks and
  keyframe bake helpers shared by both modules.

---

## 3. Module layout

```
addons/GestureBone/
├── __init__.py            # bl_info, registration, depsgraph handler
├── properties.py          # scene-level global props
├── panels.py              # Infos panel + MainPanel (rig_type dispatch)
├── infos.py               # build / reload / debug / console operators
├── module_manager.py      # loads modules per modules_config.json
├── modules_config.json    # { "plotting": true, "gesture": true }
└── modules/
    ├── shared/            # ChainDefinition, ArmatureProps, shared utils
    ├── plotting/          # PLOTTING rig: rig generation
    └── gesture/           # GESTURE rig: drawing & binding
```

### `modules/plotting/` — rig generation
- `ui.py` → `draw_plotting_ui()` (drawn inline, no panel class)
- `ops_create.py` — `create_rig`, `append_essentials`,
  `sync_chains_from_meta_bones`
- `ops_chains.py` — `move_chain`, `rerig_part`
- `ops_autorig.py` — `auto_rig` (runs the whole pipeline end-to-end via a
  depsgraph handler)
- `ops_steps.py` — the 11 numbered rig-generation steps
- `ops_alignment.py` — the align-chain-to-bone steps (scale empty, copy
  loc/rot, edit-in-metarig, accept & bind)
- `ops_bind_mesh.py` — `bind_to_mesh` + the `12a/12b/12c` bind sub-steps
- plus the operations-bar toggles: `toggle_armature_visibility`,
  `switch_armature`, `clear_rig`, `delete_sample_folder`,
  `toggle_meta_collection`, `toggle_connect_selectable`,
  `reset_all_bones_stretch`, `toggle_pivot_rotation`

### `modules/gesture/` — drawing & binding
- `ui.py` → `draw_gesture_ui()` (drawn inline)
- `ops_bind.py` — `create_bone_constraints`, `delete_bone_constraints`,
  `load_chains`, `switch_armature`
- `ops_draw.py` — `activate_chain`, `toggle_spline_tool`,
  `switch_curve_direction`, `toggle_constraint_active`
- `ops_bake.py` — `apply_to_bone`, `delete_baked_frames`

Each module's `register()` registers its **operators**; the **UI draw
functions are called inline from `panels.py`**, so `ui.py` `register()` is a
no-op. `module_manager.py` loads/unloads modules according to
`modules_config.json`; `shared` is always loaded via `modules/__init__.py`.

---

## 4. UI dispatch (`panels.py`)

- `GESTUREBONE_PT_Infos` — build time, reload, debug/console toggles,
  extra-infos toggle; module list + version shown only in debug mode.
- `GESTUREBONE_PT_MainPanel` — resolves the "current" armature, then
  dispatches on `rig_type`:
  - `PLOTTING` → `draw_plotting_ui(layout, context, arm)`
  - `GESTURE`  → `draw_gesture_ui(layout, context, arm)`
  - `PRESET` / `NONE` → informational box
- The panel intentionally **stays on the GESTURE UI during a draw session**:
  when the active object is a CURVE that is some chain's `gesture_spline`, it
  resolves back to that chain's GESTURE rig instead of falling through to
  "select an armature" (`_gesture_arm_for_spline`).

Because dispatch is inline (not registered subpanels), the panel appearance
is defined entirely by the two `draw_*_ui` functions.

---

## 5. Rig-generation pipeline

Driven by `props.completed_step` / `props.last_step`; each step is gated so it
only enables once the previous one has run. **Auto Rig** runs the whole thing;
**debug mode** exposes it step-by-step:

1. Duplicate & rename atomic chain
2. Rebind constraints & geonodes
3. Scale empty to rest pose
4. Add copy-loc & copy-rot
5. Edit alignment in MetaRig (user poses, then continue)
6. Accept & bind
7. Refresh gesture & plot rigs
8. Rebind final armatures
9. Merge & clean
10. Merge `.Rig` into MetaRig
11. Rebind armature deform
12. Bind mesh: `12a` move to collection · `12b` sync materials · `12c` copy
    geometry to Sample Mesh

---

## 6. Gesture drawing & binding

1. **Load Chains** pulls the PLOTTING rig's chains into the GESTURE UI and
   resolves each chain's CTRL bones.
2. **Bind** (`create_bone_constraints`) wires the control bones to the
   chain's gesture spline; **Unbind** removes them.
3. **Activate Draw** enters the draw session on the gesture spline;
   **toggle_spline_tool** flips between drawing strokes and editing handles.
4. **Apply to Bone** bakes the spline onto the control bones;
   **Live Preview** mutes/unmutes the constraints; `bone_handle_smoothness`
   drives the spline's GN modifier.

---

## 7. Build, deploy & reload

- **`install.py`** copies `addons/GestureBone/` into each Blender version's
  `scripts/addons/` folder. `BLENDER_VERSIONS` is a list (pinned to
  `["5.1", "5.2"]`; `None` auto-detects every version that already has the
  addon). After copying it hot-reloads **the running Blender** over the MCP
  socket (`localhost:9876`); other versions pick up the files on next start.
- **In-Blender reload** (`gesturebone.reload`, Infos panel) defers the
  disable/enable to a `bpy.app.timers` callback and is marked `INTERNAL` — it
  must not unregister itself while still mid-invoke (that crashed Blender 5.1;
  see CHANGELOG and `infos.py`).
- `zip_addon.py` / `build_extension.py` produce distributable builds;
  `manifest.toml` carries the extension metadata.

---

## 8. Compatibility notes

- `bl_info["blender"] = (4, 0, 0)`; the addon runs on **Blender 5.1 and 5.2**
  (both are deployed to on this project).
- **Geometry-Nodes sockets:** 5.2 removed id-property subscript access to GN
  modifier inputs. GestureBone currently still uses raw `mod["Socket_x"]`
  writes (`utils_gn.py`, `chain.py`), which are correct on 4.x/5.1 but may
  silently fail on 5.2 — a known follow-up to route through a version-safe
  helper.
- The panel-category (N-panel tab) cannot be set from script on 5.1
  (read-only), which only affects tooling, not the addon.

---

## 9. History

See `CHANGELOG.md` for dated changes. The major milestones:
`25d470a` unified data model → inline `rig_type` dispatch →
compact "fine tune" UI restored on the new backend (Aug 2026) →
5.1 reload-crash fix + dual-version deploy.
