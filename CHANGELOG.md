# Changelog

## [Unreleased]

### Added
- `.gitignore` with whitelist approach — only tracks `.py .md .json .txt .toml .skill`
- `infos.py`: `GESTUREBONE_OT_Reload` — in-place reload without running install.py
- `__init__.py`: persistent depsgraph handler `_track_active_armature` — saves last active armature to `current_armature`; only updates when `current_armature` is None so GP drawing never loses the armature reference
- `operators.py`: `GESTUREBONE_OT_ToggleGPVisibility` — toggles `hide_viewport` on the chain's GP object

### Changed
- **Per-armature data**: `local_props.py` now attaches `gesturebone_gesture_draw_props` to `bpy.types.Object` instead of `bpy.types.Scene` — each armature stores its own chains in the .blend file
- **Armature fallback**: `_arm()` and `_active_arm()` fall back to `props.current_armature` when the active object is not an armature — operators and UI work during GP draw mode
- **MainPanel**: reads `props.current_armature` as source of truth; shows armature name + lists unbound chains as red warnings; only shows "Select an Armature" when `current_armature` is None
- **Infos panel**: all buttons in one row (`build | reload | debug | console | clear`); modules row and version label gated behind `debug_mode`
- **Binding panel**: each chain is a collapsible box; header contains collapse arrow + status icon + name + bind button; body (expanded) shows "Bindings" label + GP picker + material picker + 5 bone search rows (`Bone 1` … `Bone 5`)
- **Gesture Draw panel**: one `align=True` row per chain — visibility dot (`●`) + wide draw toggle with chain name (`scale_x=4`) + key + bind + pose buttons; always fills edge-to-edge
- `properties.py`: renamed `main_armature` → `current_armature`, `main_gp` → `current_gp`

### Removed
- `blender_reload.py` — replaced by `GESTUREBONE_OT_Reload` inside `infos.py`
- `module_example_operators.py`, `module_example_ui.py`, `module_example_utils.py` — no longer generated
- `modules/gesture_draw/utils.py` — unused
